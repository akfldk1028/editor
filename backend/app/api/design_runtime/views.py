"""
Design Optimization API

8 endpoints for building mass optimization with GA + SSE streaming.
SSE pattern mirrors land/views.py agent_analyze_stream.
"""

import json
import logging
import math
import queue
import threading
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404
from django.http import JsonResponse, StreamingHttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from backend.app.modules.design.generation.engine.runner import JobRunner, MultiAlgoRunner
from backend.app.modules.design.generation.formatters import format_job_response, format_design_response, format_pareto_front
from backend.app.adapters.design_storage.models import OptimizationJob, DesignResult, MaasRevisionEvent
from backend.app.adapters.design_storage.persistence import save_job, save_results
from backend.app.adapters.design_storage import lifecycle
from backend.app.modules.design.generation.paths import workspace_root, backend_root
from .job_validation import validate_request, validate_spec
from .result_identity import (canonicalize_result_event,
                              requested_design_uid, resolve_design_result, ResultIdentityError)
from backend.app.modules.design.generation.services.constraint_bridge import regulations_to_constraints, build_default_job_spec, compute_setback_geometry, build_floor_plan_spec
from backend.app.modules.design.generation.services.mass_evaluator import evaluate_designs
from backend.app.modules.design.generation.services.mass_renderer import design_to_geojson
from backend.app.modules.design.generation.services.regulation_validator import validate_design, validate_best_designs, auto_correct_constraints
from backend.app.modules.design.generation.services.site_geometry import fetch_parcel_boundary, geojson_to_polygon, validate_site
from backend.app.modules.design.generation.services.interactive_patch import build_interactive_patch_plan
from backend.app.modules.design.generation.services.interactive_apply import build_interactive_preview
from backend.app.modules.design.generation.services.mass_operations import apply_mass_operation
from backend.app.modules.design.generation.maas import build_maas_evidence_bundle, export_mass_geojson_to_scad, generate_legal_mass_variants
from backend.app.modules.design.generation.maas.interactive import apply_conversational_graph_revision, build_revision_learning_profile
from backend.app.modules.design.generation.maas.mass_brain import record_proposal_feedback
from backend.app.modules.design.generation.maas.language_system import build_language_system_manifest
from backend.app.modules.design.generation.maas.outcome_graph_slice import build_outcome_graph_slice
from backend.app.modules.design.generation.maas.book_language.registry import build_book_language_registry
from backend.app.modules.design.generation.maas.aesthetic import build_aesthetic_pipeline_result
from backend.app.modules.design.generation.maas.aesthetic.adapters import NanoBananaAdapter, OpenAIImageAdapter
from backend.app.modules.design.generation.maas.aesthetic.renderers import MultiViewReferencePackRenderer
from backend.app.modules.design.generation.maas.preference.reference_corpus import default_reference_root
from backend.app.modules.design.generation.maas.geometry_language import architectural_shape_programs, build_mass_execution_passport, compile_geometry_program, materialize_isometric_thumbnail, passport_path_for_preview, render_compilation_preview, write_mass_execution_passport
from backend.app.modules.design.generation.maas.geometry_language.executed_archive import compile_executed_mass, executed_mass_manifest, materialize_executed_mass_passport, materialize_executed_mass_preview
from backend.app.modules.design.generation.maas.single_execution import execute_single_mass, is_single_execution_run, single_execution_archive_manifest, single_execution_passport, single_execution_preview, single_execution_run_id, single_execution_runs, review_single_mass_with_vlm
from backend.app.modules.design.generation.maas.single_execution.replay import downstream_evidence_from_passport
from backend.app.modules.design.generation.maas.single_execution.pipeline import resolve_single_execution_replay
from backend.app.modules.design.generation.maas.creative_portfolio_catalog import creative_portfolio_manifest, creative_portfolio_render
from backend.app.modules.design.generation.maas.portfolio_evaluation_catalog import portfolio_evaluation_manifest, portfolio_evaluation_render

logger = logging.getLogger(__name__)

# Active runners keyed by job_id for cancellation
_active_runners: dict[str, JobRunner] = {}
_geometry_preview_lock = threading.Lock()


def _single_execution_root() -> Path:
    configured = getattr(settings, "MAAS_SINGLE_EXECUTION_ROOT", "")
    if configured:
        return Path(configured).resolve()
    return (
        workspace_root()
        / "docs" / "ai-session-memory" / "maas-service-cache" / "single-executions"
    ).resolve()


def _creative_portfolio_root() -> Path:
    configured = getattr(settings, "MAAS_CREATIVE_PORTFOLIO_ROOT", "")
    if configured:
        return Path(configured).resolve()
    return (
        workspace_root() / "docs" / "mass"
    ).resolve()


def _portfolio_evaluation_root() -> Path:
    configured = getattr(settings, "MAAS_PORTFOLIO_EVALUATION_ROOT", "")
    if configured:
        return Path(configured).resolve()
    return (
        workspace_root()
        / "docs" / "playwright" / "design-route-live-verify"
    ).resolve()


@require_http_methods(["GET"])
def maas_creative_portfolios(request):
    """Return a validated pre-legal creative archive without type coercion."""

    run_id = str(request.GET.get("run_id") or "").strip()
    try:
        return JsonResponse(creative_portfolio_manifest(
            _creative_portfolio_root(),
            run_id or None,
        ))
    except FileNotFoundError as exc:
        raise Http404("creative portfolio not found") from exc
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("Invalid creative portfolio request: %s", exc)
        return JsonResponse({"error": "invalid creative portfolio"}, status=400)


@require_http_methods(["GET"])
def maas_portfolio_evaluations(request):
    run_id = str(request.GET.get("run_id") or "").strip()
    try:
        return JsonResponse(portfolio_evaluation_manifest(
            _portfolio_evaluation_root(),
            run_id or None,
        ))
    except FileNotFoundError as exc:
        raise Http404("portfolio evaluation not found") from exc
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("Invalid portfolio evaluation request: %s", exc)
        return JsonResponse(
            {"error": "invalid portfolio evaluation"},
            status=400,
        )


@require_http_methods(["GET"])
def maas_portfolio_evaluation_render(
    request,
    run_id,
    candidate_id,
):
    try:
        output = portfolio_evaluation_render(
            _portfolio_evaluation_root(),
            str(run_id),
            str(candidate_id),
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise Http404("portfolio evaluation render not found") from exc
    response = FileResponse(output.open("rb"), content_type="image/png")
    response["Cache-Control"] = "public, max-age=31536000, immutable"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_http_methods(["GET"])
def maas_creative_portfolio_render(
    request,
    run_id,
    candidate_id,
):
    """Serve only the validated candidate PNG bound by the catalog."""

    try:
        output = creative_portfolio_render(
            _creative_portfolio_root(),
            str(run_id),
            str(candidate_id),
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise Http404("creative candidate render not found") from exc
    response = FileResponse(output.open("rb"), content_type="image/png")
    response["Cache-Control"] = "public, max-age=31536000, immutable"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_http_methods(["GET"])
def maas_language_system(request):
    """Expose the typed BOOK-to-VLM lattice without running generation."""

    return JsonResponse(build_language_system_manifest())


@require_http_methods(["GET"])
def maas_outcome_graph_slice(request):
    """Return a bounded real lineage slice, never the full multi-hundred-MB graph."""

    pnu = str(request.GET.get("pnu") or "").strip()
    if not pnu:
        return JsonResponse({"error": "pnu is required"}, status=400)
    try:
        depth = int(request.GET.get("depth") or 3)
        max_nodes = int(request.GET.get("max_nodes") or 180)
    except (TypeError, ValueError):
        return JsonResponse({"error": "depth and max_nodes must be integers"}, status=400)
    try:
        run_id = str(request.GET.get("run_id") or "").strip()
        graph_path = None
        if is_single_execution_run(run_id):
            return JsonResponse({
                "schema_version": "arr.maas.outcome_graph_slice.v1",
                "status": "not_found",
                "pnu": pnu,
                "root_node_ids": [],
                "nodes": [],
                "edges": [],
                "counts": {"nodes": 0, "edges": 0},
                "contracts": {
                    "single_execution_uses_passport_graph": True,
                    "parallel_outcome_graph_created": False,
                },
            })
        if run_id:
            archive = executed_mass_manifest(run_id)
            source_archive = Path(str(archive["source_archive"])).resolve()
            graph_path = source_archive.with_name("maas-geometry-mutation-outcome-graph.json")
        payload = build_outcome_graph_slice(
            pnu=pnu,
            graph_path=graph_path,
            node_id=str(request.GET.get("node_id") or "").strip(),
            candidate_id=str(request.GET.get("candidate_id") or "").strip(),
            geometry_hash=str(request.GET.get("geometry_hash") or "").strip(),
            depth=depth,
            max_nodes=max_nodes,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        logger.warning("MAAS outcome graph slice failed: %s", exc)
        return JsonResponse({"error": "outcome graph is unavailable"}, status=503)
    return JsonResponse(payload)


@require_http_methods(["GET"])
def maas_book_asset(request, page):
    """Serve one allow-listed BOOK scan for graph evidence inspection."""

    page_number = int(page)
    if not 1 <= page_number <= 69:
        raise Http404("BOOK page not found")
    page_record = next(
        (item for item in build_book_language_registry()["pages"] if int(item["page"]) == page_number),
        None,
    )
    if not page_record or not page_record.get("source_path"):
        raise Http404("BOOK scan unavailable")
    scan_path = Path(str(page_record["source_path"])).resolve()
    book_root = (workspace_root() / "docs" / "260506" / "BOOK").resolve()
    if not scan_path.is_relative_to(book_root) or not scan_path.is_file():
        raise Http404("BOOK scan unavailable")
    response = FileResponse(scan_path.open("rb"), content_type="image/jpeg")
    response["Cache-Control"] = "public, max-age=86400, immutable"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_http_methods(["GET"])
def maas_geometry_shape_preview(request, index):
    """Compile and serve one deterministic four-view phenotype MASS PNG."""

    shape_index = int(index)
    programs = architectural_shape_programs()
    if not 1 <= shape_index <= len(programs):
        raise Http404("geometry phenotype not found")
    program = programs[shape_index - 1]
    compilation = compile_geometry_program(program)
    if compilation.status != "compiled":
        raise Http404("geometry phenotype did not compile")
    cache_root = (
        workspace_root()
        / "docs" / "ai-session-memory" / "maas-service-cache" / "geometry-language"
    ).resolve()
    filename = f"shape-{shape_index:02d}-{compilation.geometry_hash[:16]}.png"
    output = cache_root / filename
    with _geometry_preview_lock:
        if not output.is_file():
            render_compilation_preview(
                compilation,
                output,
                title=f"{shape_index:02d} {program.metadata.get('family') or program.name}",
            )
        elif not passport_path_for_preview(output).is_file():
            write_mass_execution_passport(compilation, output)
    response = FileResponse(output.open("rb"), content_type="image/png")
    response["Cache-Control"] = "public, max-age=31536000, immutable"
    response["ETag"] = f'"{compilation.geometry_hash}"'
    response["X-Geometry-Hash"] = compilation.geometry_hash
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_http_methods(["GET"])
def maas_geometry_shape_passport(request, index):
    """Return the materialized execution passport for one phenotype MASS."""

    shape_index = int(index)
    programs = architectural_shape_programs()
    if not 1 <= shape_index <= len(programs):
        raise Http404("geometry phenotype not found")
    program = programs[shape_index - 1]
    compilation = compile_geometry_program(program)
    if compilation.status != "compiled":
        return JsonResponse(build_mass_execution_passport(compilation), status=422)
    cache_root = (
        workspace_root()
        / "docs" / "ai-session-memory" / "maas-service-cache" / "geometry-language"
    ).resolve()
    output = cache_root / f"shape-{shape_index:02d}-{compilation.geometry_hash[:16]}.png"
    with _geometry_preview_lock:
        if not output.is_file():
            render_compilation_preview(
                compilation,
                output,
                title=f"{shape_index:02d} {program.metadata.get('family') or program.name}",
            )
        passport_file = write_mass_execution_passport(compilation, output)
        passport = json.loads(passport_file.read_text(encoding="utf-8"))
    return JsonResponse(passport)


@csrf_exempt
@require_http_methods(["POST"])
def maas_single_execution(request):
    """Compile one explicit AST immediately; portfolio/VLM search is optional upstream."""

    if len(request.body) > 1_000_000:
        return JsonResponse({"error": "request body exceeds 1 MB"}, status=413)
    try:
        body = json.loads(request.body or b"{}")
        if not isinstance(body, dict):
            raise ValueError("request body must be an object")
        program = body.get("program")
        downstream_evidence = None
        vlm_result = None
        validated_compilation = None
        source_replay = False
        if not isinstance(program, dict):
            source_replay = True
            source_run_id = str(body.get("source_run_id") or "").strip()
            source_mass_index = int(body.get("source_mass_index") or 0)
            if not source_run_id or source_mass_index < 1:
                raise ValueError("program or source_run_id/source_mass_index is required")
            if is_single_execution_run(source_run_id):
                if source_mass_index != 1:
                    raise ValueError("single execution run contains exactly one MASS")
                (
                    resolved_program,
                    source_passport,
                    validated_compilation,
                ) = resolve_single_execution_replay(
                    root=_single_execution_root(),
                    run_id=source_run_id,
                    compile_archive=compile_executed_mass,
                )
            else:
                compilation, _, _, _ = compile_executed_mass(source_mass_index, source_run_id)
                resolved_program = compilation.program
                validated_compilation = compilation
                source_passport = materialize_executed_mass_passport(source_mass_index, source_run_id)
            program = resolved_program.to_dict()
            downstream_evidence = downstream_evidence_from_passport(source_passport)
            # A previous VLM judgment is bound to its exact rendered PNG and
            # execution. Replays must be reviewed explicitly after rendering.
            vlm_result = None
        requested_execution_mode = str(body.get("execution_mode") or "explicit_program")
        if not source_replay and requested_execution_mode not in {"explicit_program", "fresh_synthesis"}:
            raise ValueError("execution_mode must be explicit_program or fresh_synthesis")
        result = execute_single_mass(
            program,
            output_root=_single_execution_root(),
            execution_id=f"mass-{timezone.now().strftime('%Y%m%dT%H%M%S%fZ')}",
            title=str(body.get("title") or ""),
            downstream_evidence=downstream_evidence,
            vlm_result=vlm_result,
            execution_mode="exact_replay" if source_replay else requested_execution_mode,
            source_run_id=source_run_id if source_replay else "",
            source_mass_index=source_mass_index if source_replay else 0,
            validated_compilation=validated_compilation,
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    payload = result.to_dict()
    payload.pop("artifacts", None)
    base = f"/design/maas/single-executions/{result.execution_id}"
    payload.update({
        "archive_run_id": single_execution_run_id(result.execution_id),
        "preview_url": f"{base}/preview/" if result.preview_path.is_file() else "",
        "manifest_url": f"{base}/manifest/",
        "passport_url": f"{base}/passport/",
    })
    return JsonResponse(payload, status=201 if result.geometry_ready else 422)


@csrf_exempt
@require_http_methods(["POST"])
def maas_single_execution_vlm_review(request, execution_id):
    """Run one cache-first, bounded paid VLM review for an immutable MASS."""

    try:
        body = json.loads(request.body or b"{}")
        if not isinstance(body, dict):
            raise ValueError("request body must be an object")
        reference_limit = int(body.get("reference_limit", 3))
        if reference_limit < 0 or reference_limit > 3:
            raise ValueError("reference_limit must be between 0 and 3")
        payload = review_single_mass_with_vlm(
            _single_execution_root(),
            str(execution_id),
            reference_limit=reference_limit,
            building_type=str(body.get("building_type") or ""),
            model=str(body.get("model") or "") or None,
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except Exception as exc:
        logger.exception("single MASS VLM review failed")
        return JsonResponse({"error": f"{type(exc).__name__}: {exc}"}, status=502)
    return JsonResponse(payload)


@require_http_methods(["GET"])
def maas_single_execution_preview(request, execution_id):
    output = _single_execution_artifact(execution_id, "mass.png")
    if not output.is_file():
        raise Http404("single MASS preview not found")
    response = FileResponse(output.open("rb"), content_type="image/png")
    response["Cache-Control"] = "public, max-age=31536000, immutable"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_http_methods(["GET"])
def maas_single_execution_thumbnail(request, execution_id):
    preview = _single_execution_artifact(execution_id, "mass.png")
    try:
        output = materialize_isometric_thumbnail(preview)
    except (OSError, ValueError) as exc:
        raise Http404("single MASS thumbnail not found") from exc
    response = FileResponse(output.open("rb"), content_type="image/png")
    response["Cache-Control"] = "public, max-age=31536000, immutable"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_http_methods(["GET"])
def maas_single_execution_manifest(request, execution_id):
    return _single_execution_json(execution_id, "execution.json")


@require_http_methods(["GET"])
def maas_single_execution_passport(request, execution_id):
    return _single_execution_json(execution_id, "mass.png.passport.json")


@require_http_methods(["GET"])
def maas_single_execution_elevation(request, execution_id, view):
    if str(view) not in {"front", "right", "back", "left", "top", "axon"}:
        raise Http404("unknown elevation view")
    output = _single_execution_artifact(
        execution_id,
        f"elevation/views/{view}.png",
    )
    if not output.is_file():
        raise Http404("single MASS elevation not found")
    response = FileResponse(output.open("rb"), content_type="image/png")
    response["Cache-Control"] = "public, max-age=31536000, immutable"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_http_methods(["GET"])
def maas_single_execution_elevation_proposal(request, execution_id):
    output = _single_execution_artifact(
        execution_id,
        "elevation/proposals/alt-01/proposal.png",
    )
    if not output.is_file():
        raise Http404("single MASS elevation proposal not found")
    response = FileResponse(output.open("rb"), content_type="image/png")
    response["Cache-Control"] = "public, max-age=31536000, immutable"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_http_methods(["GET"])
def maas_single_execution_multi_view_elevation_artifact(
    request,
    execution_id,
    artifact,
):
    filenames = {
        "front": "front.png",
        "right": "right.png",
        "back": "back.png",
        "left": "left.png",
        "critic-montage": "critic-montage.png",
    }
    filename = filenames.get(str(artifact))
    if not filename:
        raise Http404("unknown multi-view elevation artifact")
    output = _single_execution_artifact(
        execution_id,
        f"elevation/proposals/multi-view-alt-01/{filename}",
    )
    if not output.is_file():
        raise Http404("multi-view elevation artifact not found")
    response = FileResponse(output.open("rb"), content_type="image/png")
    response["Cache-Control"] = "public, max-age=31536000, immutable"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_http_methods(["GET"])
def maas_single_execution_multi_view_elevation_evidence(
    request,
    execution_id,
    document,
):
    filenames = {
        "proposal": "proposal.json",
        "critic": "critic.json",
    }
    filename = filenames.get(str(document))
    if not filename:
        raise Http404("unknown multi-view elevation evidence")
    return _single_execution_json(
        execution_id,
        f"elevation/proposals/multi-view-alt-01/{filename}",
    )


def _single_execution_json(execution_id: str, filename: str) -> JsonResponse:
    output = _single_execution_artifact(execution_id, filename)
    try:
        payload = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise Http404("single MASS execution artifact not found") from exc
    return JsonResponse(payload)


def _single_execution_artifact(execution_id: str, filename: str) -> Path:
    root = _single_execution_root()
    output = (root / str(execution_id) / filename).resolve()
    if not output.is_relative_to(root):
        raise Http404("invalid single MASS execution path")
    return output


@require_http_methods(["GET"])
def maas_executed_masses(request):
    """List one immutable run plus the chronological MAAS run timeline."""

    try:
        run_id = str(request.GET.get("run_id") or "").strip()
        if is_single_execution_run(run_id):
            portfolio = executed_mass_manifest()
            payload = single_execution_archive_manifest(
                _single_execution_root(),
                run_id,
                other_runs=portfolio.get("runs") or (),
            )
        else:
            payload = executed_mass_manifest(run_id or None)
            extra_runs = single_execution_runs(_single_execution_root())
            if extra_runs:
                merged = {
                    str(item.get("run_id") or ""): item
                    for item in (*payload.get("runs", ()), *extra_runs)
                    if isinstance(item, dict) and item.get("run_id")
                }
                payload["runs"] = sorted(
                    merged.values(),
                    key=lambda item: (str(item.get("created_at") or ""), str(item.get("run_id") or "")),
                )
                payload["run_count"] = len(payload["runs"])
                payload["archive_revision"] = f"{payload.get('archive_revision', '')}:{extra_runs[-1]['created_at']}"
        return JsonResponse(payload)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("MAAS executed archive unavailable: %s", exc)
        return JsonResponse({"error": "executed MASS archive is unavailable"}, status=503)


@require_http_methods(["GET"])
def maas_executed_mass_preview(request, index):
    """Serve the exact candidate card rendered during the recorded MAAS run."""

    try:
        run_id = str(request.GET.get("run_id") or "").strip()
        if is_single_execution_run(run_id):
            if int(index) != 1:
                raise IndexError(index)
            output = single_execution_preview(_single_execution_root(), run_id)
        else:
            output = materialize_executed_mass_preview(int(index), run_id or None)
    except (OSError, ValueError, IndexError, json.JSONDecodeError) as exc:
        logger.warning("MAAS executed preview unavailable: %s", exc)
        raise Http404("executed MASS render not found") from exc
    response = FileResponse(output.open("rb"), content_type="image/png")
    response["Cache-Control"] = "public, max-age=86400, immutable"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_http_methods(["GET"])
def maas_executed_mass_passport(request, index):
    """Replay one archived GeometryProgram and expose its real execution passport."""

    try:
        run_id = str(request.GET.get("run_id") or "").strip()
        if is_single_execution_run(run_id):
            if int(index) != 1:
                raise IndexError(index)
            payload = single_execution_passport(_single_execution_root(), run_id)
        else:
            payload = materialize_executed_mass_passport(int(index), run_id or None)
        return JsonResponse(payload)
    except (OSError, ValueError, IndexError, json.JSONDecodeError) as exc:
        logger.warning("MAAS executed passport unavailable: %s", exc)
        return JsonResponse({"error": "executed MASS passport is unavailable"}, status=422)


def _passport_vlm_result(passport: dict):
    stage = next((
        item for item in passport.get("stages") or ()
        if isinstance(item, dict) and item.get("id") == "vlm"
    ), None)
    if not stage or stage.get("status") == "not_evaluated":
        return None
    evidence = dict(stage.get("evidence") or {})
    evidence["cache_hit"] = stage.get("status") == "cache_hit"
    evidence["vlm_image_inputs"] = evidence.pop("image_inputs", {})
    return evidence


@require_http_methods(["GET"])
def maas_reference_asset(request, asset_path):
    """Serve only local VLM precedent images inside the curated reference corpus."""

    reference_root = default_reference_root().resolve()
    target = (reference_root / asset_path).resolve()
    if not target.is_relative_to(reference_root) or not target.is_file():
        raise Http404("reference image not found")
    response = FileResponse(target.open("rb"), content_type=_image_content_type(target))
    response["Cache-Control"] = "public, max-age=86400, immutable"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _all_mode_budget_options(options: dict | None) -> dict[str, int]:
    """Budget used for each algorithm when algorithm='all'."""
    options = options or {}
    return {
        "Number of generations": int(options.get("Number of generations", 80)),
        "num_islands": int(options.get("num_islands", 5)),
        "pop_per_island": int(options.get("pop_per_island", 20)),
    }


def _daylight_diagonal_multiplier(zone_names: list[str], building_type: str) -> float | None:
    """건축법 §61②/시행령 §86③ 채광사선 적용 배수."""
    residential_types = ("공동주택", "아파트", "다세대", "연립", "다가구")
    if not any(t in (building_type or "") for t in residential_types):
        return None
    # 법 §61②: 일반상업지역ㆍ중심상업지역에 건축하는 공동주택은 제외.
    if any(z in ("일반상업지역", "중심상업지역") for z in zone_names):
        return None
    if any(z in ("근린상업지역", "준주거지역") for z in zone_names):
        return 4.0
    return 2.0


def _precompute_sunlight_envelope(job) -> dict | None:
    """
    Phase B (2026-05-08) — job_stream에서 NSGA-II 시작 전에 sunlight envelope 계산.

    Repair operator(`design.services.repair_operator.clip_to_sunlight_envelope`)가
    envelope corners polygon으로 footprint를 clip할 때 사용. PNU에서 zones 받아
    sunlight_applies 여부 판정 후 적용 zone(전용/일반주거)이면 envelope 생성.

    sunlight 미적용 zone(상업/공업 등)이면 None 반환 → Repair clip 단계 skip.

    실패시 None — Repair는 envelope 없이도 BCR/FAR/height 작동.
    """
    if not job.pnu and not job.site_polygon:
        return None
    try:
        from backend.app.modules.land.reference.services import land_api, regulation_calculator, road_frontage, zoning_mapper
        from backend.app.modules.land.reference.services.setback_geometry import compute_setback_lines
        from backend.app.modules.land.reference import config as land_config

        zones = []
        if job.pnu:
            try:
                land_info = land_api.get_land_use_info(job.pnu)
                zones = land_info.get("zones", []) or []
            except Exception as e:
                logger.warning(f"land_api zones lookup failed for {job.pnu}: {e}")

        if not zones:
            return None
        limits = zoning_mapper.resolve_limits(zones)
        zone_names = [z["zone_name"] for z in (limits or {}).get("zones", [])] or zones
        reg = regulation_calculator.calculate_all(
            zone_names,
            use_llm_extraction=False,
        )

        if not reg.get("sunlight_applies"):
            logger.info(f"[sunlight_clip] zone={zone_names} sunlight_applies=False → clip skip")
            return None
        road_frontages = []
        neighbor_parcels = []
        if job.site_polygon:
            try:
                roads_result = road_frontage.fetch_neighbor_roads(job.site_polygon)
                if roads_result.get("success"):
                    road_frontages = roads_result.get("roads") or []
            except Exception as e:
                logger.warning(f"[sunlight_clip] road frontage lookup failed: {e}")
            try:
                neighbors_result = road_frontage.fetch_neighbor_parcels(job.site_polygon)
                if neighbors_result.get("success"):
                    neighbor_parcels = neighbors_result.get("neighbors") or []
            except Exception as e:
                logger.warning(f"[sunlight_clip] neighbor parcel lookup failed: {e}")

        lines = compute_setback_lines(
            job.site_polygon, reg,
            compute_datum=land_config.ENABLE_DATUM_ELEVATION,
            road_frontages=road_frontages,
            neighbor_parcels=neighbor_parcels,
        )
        env = lines.get("sunlight_envelope")
        if env:
            corners = (env.get("slanted_polygons") or [{}])[0].get("corners") or []
            heights = [c[2] for c in corners] if corners else []
            logger.info(
                f"[sunlight_clip] zone={zone_names} envelope: "
                f"corners={len(corners)}, H={min(heights) if heights else 0:.1f}~"
                f"{max(heights) if heights else 0:.1f}m → Repair clip 활성"
            )
        else:
            logger.warning(f"[sunlight_clip] zone={zone_names} envelope=None")
        return env
    except Exception as e:
        logger.warning(f"_precompute_sunlight_envelope failed: {e}")
        return None


@csrf_exempt
@require_http_methods(["POST"])
def create_job(request):
    """POST /design/jobs/ — Create and start an optimization job."""
    try:
        body = json.loads(request.body)
        validate_request(body)
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    site_polygon_geojson = body.get("site_polygon")
    if not site_polygon_geojson:
        return JsonResponse({"error": "site_polygon is required"}, status=400)

    try:
        site_polygon = geojson_to_polygon(site_polygon_geojson)
    except Exception as e:
        return JsonResponse({"error": f"Invalid site_polygon: {e}"}, status=400)

    validation = validate_site(site_polygon)
    if not validation["valid"] or not math.isfinite(validation["area_m2"]):
        return JsonResponse({"error": "Invalid site", "details": validation["errors"]}, status=400)

    job_spec = body.get("job_spec")
    constraints = body.get("constraints", [])
    pnu = body.get("pnu", "")
    address = body.get("address", "")

    # Build default spec if not provided or incomplete (missing inputs/outputs)
    user_options = job_spec.get("options", {}) if job_spec else {}
    building_type = user_options.get("building_type", "공동주택")
    algorithm = user_options.get("algorithm", "additive")
    if not job_spec or "inputs" not in job_spec:
        job_spec = build_default_job_spec(validation["area_m2"], constraints, building_type, algorithm)
        # Override defaults with any user-provided options
        if user_options:
            job_spec["options"].update(user_options)
    else:
        # Full spec provided — inject constraints into outputs if missing
        existing_names = {o["name"] for o in job_spec.get("outputs", [])}
        for c in constraints:
            if c["name"] not in existing_names:
                job_spec.setdefault("outputs", []).append(c)

    try:
        validate_spec(job_spec, complete=True)
    except (ValueError, TypeError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    max_gen = int(job_spec.get("options", {}).get("Number of generations", 50))
    opts = job_spec.get("options", {})
    pop_size = int(opts.get("num_islands", 7)) * int(opts.get("pop_per_island", 30))

    # Create DB record
    job = save_job({
        "pnu": pnu,
        "address": address,
        "site_polygon": site_polygon_geojson,
        "site_area_m2": validation["area_m2"],
        "job_spec": job_spec,
        "constraints": constraints,
        "max_generations": max_gen,
        "population_size": pop_size,
    })

    if not job:
        return JsonResponse({"error": "Failed to create job"}, status=500)

    return JsonResponse(format_job_response(job), status=202)


@require_http_methods(["GET"])
def get_job(request, job_id):
    """GET /design/jobs/<id>/ — Get job status."""
    lifecycle.recover_interrupted(job_id)
    try:
        job = OptimizationJob.objects.get(id=job_id)
    except OptimizationJob.DoesNotExist:
        return JsonResponse({"error": "Job not found"}, status=404)

    return JsonResponse(format_job_response(job))


@csrf_exempt
@require_http_methods(["POST"])
def cancel_job(request, job_id):
    try:
        job = lifecycle.cancel(job_id)
    except OptimizationJob.DoesNotExist:
        return JsonResponse({"error": "Job not found"}, status=404)
    runner = _active_runners.get(str(job_id))
    if runner and job.status == "cancelled":
        runner.cancel()
    return JsonResponse({"id": str(job.id), "status": job.status})


@require_http_methods(["GET"])
def job_stream(request, job_id):
    try:
        after = int(request.META.get("HTTP_LAST_EVENT_ID") or request.GET.get("after") or 0)
        if after < 0:
            raise ValueError("negative cursor")
    except (TypeError, ValueError):
        return JsonResponse({"error": "Last-Event-ID must be a non-negative integer"}, status=400)
    try:
        lifecycle.start(job_id, _produce_job)
    except OptimizationJob.DoesNotExist:
        return JsonResponse({"error": "Job not found"}, status=404)
    response = StreamingHttpResponse(lifecycle.replay(job_id, after), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@csrf_exempt
@require_http_methods(["POST"])
def run_job(request, job_id):
    try:
        job = lifecycle.start(job_id, _produce_job)
    except OptimizationJob.DoesNotExist:
        return JsonResponse({"error": "Job not found"}, status=404)
    return JsonResponse({"id": str(job.id), "status": job.status}, status=202)


def _produce_job(job_id, token):
    job = OptimizationJob.objects.get(id=job_id)
    site_polygon = geojson_to_polygon(job.site_polygon)
    site_area_m2 = job.site_area_m2 or 0

    job_options = job.job_spec.get("options", {})
    building_type = job_options.get("building_type", "공동주택")
    algorithm = job_options.get("algorithm", "additive")

    # Phase B (2026-05-08) — sunlight envelope 즉석 계산. Repair operator가 envelope
    # corners polygon으로 footprint clip할 때 사용. PNU 없거나 정북일조 미적용 zone
    # (상업지역)이면 None — Repair는 envelope=None 시 clip 단계 skip.
    sunlight_envelope = _precompute_sunlight_envelope(job)

    event_queue = queue.Queue()
    ids_by_uid = {}

    maas_mode = algorithm == "maas_legal_envelope"

    if algorithm == "all" or maas_mode:
        # Multi-algorithm mode: run all 10 algorithms in parallel
        from backend.app.modules.design.generation.services.constraint_bridge import ALL_ALGORITHMS, build_default_job_spec as build_spec
        constraints = job.constraints or []
        base_options = job.job_spec.get("options", {})
        budget_options = _all_mode_budget_options(base_options)

        algo_specs = {}
        evaluate_fns = {}
        for algo in ALL_ALGORITHMS:
            spec = build_spec(site_area_m2, constraints, building_type, algo)
            # Respect caller/UI budget in "all" mode. Previously this was hard-coded
            # to 80x5x20 per algorithm, making short test runs unexpectedly heavy.
            spec["options"].update(base_options)
            spec["options"].update(budget_options)
            spec["options"]["algorithm"] = algo
            algo_specs[algo] = spec

            def make_eval(a, outputs_def):
                def fn(designs):
                    return evaluate_designs(
                        designs, site_polygon, site_area_m2,
                        outputs_def, building_type, a,
                        enable_repair=True,
                        sunlight_envelope=sunlight_envelope,
                    )
                return fn
            evaluate_fns[algo] = make_eval(algo, spec.get("outputs"))

        runner = MultiAlgoRunner(algo_specs, evaluate_fns, event_queue)
    else:
        # Single algorithm mode
        def evaluate_fn(designs):
            return evaluate_designs(designs, site_polygon, site_area_m2,
                                    job.job_spec.get("outputs"), building_type,
                                    algorithm,
                                    enable_repair=True,
                                    sunlight_envelope=sunlight_envelope)
        runner = JobRunner(job.job_spec, evaluate_fn, event_queue)

    _active_runners[str(job_id)] = runner
    thread = threading.Thread(target=runner.run, daemon=True)
    try:
        if not lifecycle.owns_job(job_id, token):
            return
        thread.start()
        while lifecycle.owns_job(job_id, token):
            try:
                event = event_queue.get(timeout=1.0)
            except queue.Empty:
                if not thread.is_alive():
                    raise RuntimeError("Optimization ended without a terminal event")
                continue

            event_type = event.get("type", "update")
            if algorithm == "all":
                event = canonicalize_result_event(event, ids_by_uid)

            # Enrich with GeoJSON for 3D mass visualization
            # Throttle: only every 10th generation + complete (geometry pipeline is expensive)
            gen_num = event.get("generation", 0)
            if event_type == "complete" or (event_type == "generation" and gen_num % 10 == 0):
                # In all/MAAS mode, each seed design has its own legacy
                # algorithm tag. MAAS mode then replaces the client-facing
                # final front with legal-envelope variants.
                render_algo = "per_design" if (algorithm == "all" or maas_mode) else algorithm
                render_outputs = job.job_spec.get("outputs")
                if algorithm == "all" or maas_mode:
                    render_outputs = list(algo_specs.values())[0].get("outputs")
                _enrich_event_geojson(
                    event,
                    site_polygon,
                    site_area_m2,
                    building_type,
                    render_algo,
                    outputs_def=render_outputs,
                    enable_repair=True,
                    sunlight_envelope=sunlight_envelope,
                )

            client_event = event
            if event_type == "complete" and maas_mode:
                client_event = _maas_client_event(
                    event,
                    site_polygon_geojson=job.site_polygon,
                    constraints=job.constraints or [],
                    building_type=building_type,
                    sunlight_envelope=sunlight_envelope,
                    pnu=job.pnu or None,
                    job_options=job_options,
                )

            persist = None
            if event_type == "complete":
                save_algo = "per_design" if (algorithm == "all" or maas_mode) else algorithm
                save_outputs = job.job_spec.get("outputs")
                if algorithm == "all" or maas_mode:
                    save_outputs = list(algo_specs.values())[0].get("outputs")

                def persist():
                    _save_final_results(
                        job, client_event, site_polygon, site_area_m2,
                        building_type, save_algo, outputs_def=save_outputs,
                        enable_repair=True, sunlight_envelope=sunlight_envelope,
                    )

            if not lifecycle.publish(job_id, token, client_event, persist=persist):
                break
            if event_type in ("complete", "error", "cancelled"):
                break
    finally:
        runner.cancel()
        _active_runners.pop(str(job_id), None)



def _enrich_event_geojson(event, site_polygon, site_area_m2,
                          building_type="공동주택", algorithm="additive",
                          *,
                          outputs_def=None,
                          enable_repair: bool = False,
                          sunlight_envelope: dict | None = None):
    """Add best_geojson and pareto_geojson to SSE events for 3D visualization.

    When algorithm="per_design", each design dict must have an "algorithm" key.
    """
    def _algo_for(d: dict) -> str:
        if algorithm == "per_design":
            return d.get("algorithm", "additive")
        return algorithm

    best = event.get("best")
    if best and best.get("inputs"):
        try:
            a = _algo_for(best)
            feat = design_to_geojson(best["inputs"], site_polygon, site_area_m2,
                                     building_type, a,
                                     enable_repair=enable_repair,
                                     outputs_def=outputs_def,
                                     sunlight_envelope=sunlight_envelope)
            if feat:
                feat["properties"]["design_id"] = best.get("id")
                feat["properties"]["design_uid"] = best.get("uid")
                feat["properties"]["algorithm"] = a
                event["best_geojson"] = feat
        except Exception:
            pass

    pareto = event.get("pareto_front", [])
    if pareto:
        geojson_list = []
        for d in pareto:
            if not d.get("inputs"):
                continue
            try:
                a = _algo_for(d)
                feat = design_to_geojson(d["inputs"], site_polygon, site_area_m2,
                                         building_type, a,
                                         enable_repair=enable_repair,
                                         outputs_def=outputs_def,
                                         sunlight_envelope=sunlight_envelope)
                if feat:
                    feat["properties"]["design_id"] = d.get("id")
                    feat["properties"]["design_uid"] = d.get("uid")
                    feat["properties"]["objectives"] = d.get("objectives", [])
                    feat["properties"]["algorithm"] = a
                    geojson_list.append(feat)
            except Exception:
                pass
        if geojson_list:
            event["pareto_geojson"] = geojson_list


def _maas_design_from_feature(feature: dict, index: int, generation: int) -> dict:
    props = feature.get("properties", {}) or {}
    floor_area = float(props.get("floor_area") or 0.0)
    open_pct = float(props.get("open_pct") or max(0.0, 100.0 - float(props.get("bcr") or 0.0)))
    maas_score = float(props.get("maas_score") or 0.0)
    variant_id = props.get("variant_id") or f"maas_{index + 1:02d}"
    design_id = 900000 + index
    return {
        "id": design_id,
        "uid": f"maas:{variant_id}",
        "generation": generation,
        "parents": [None, None],
        "feasible": True,
        "inputs": [],
        "objectives": [floor_area, open_pct],
        "penalty": 0.0,
        "rank": maas_score,
        "elite": 1,
        "algorithm": "maas_legal_envelope",
    }


def _maas_client_event(
    event: dict,
    *,
    site_polygon_geojson: dict,
    constraints: list[dict],
    building_type: str,
    sunlight_envelope: dict | None = None,
    pnu: str | None = None,
    job_options: dict | None = None,
) -> dict:
    """Replace the final client Pareto front with legal-envelope MAAS variants.

    The optimization runner still uses the legacy 10 algorithms as a seed
    search. The user-facing MAAS mode must not expose those raw repaired boxes
    as the final answer; it exposes floor-by-floor legal envelope variants.
    """
    seed_features = event.get("pareto_geojson") or []
    seed = event.get("best_geojson") or (seed_features[0] if seed_features else None)
    if not seed:
        raise ValueError("MAAS legal-envelope generation has no usable seed geometry")

    try:
        result = generate_legal_mass_variants(
            mass_geojson=seed,
            site_polygon_geojson=site_polygon_geojson,
            constraints=constraints,
            building_type=building_type,
            max_variants=18,
            sunlight_envelope=sunlight_envelope,
            pnu=pnu,
            parking_options=_parking_options_from_job_options(job_options, site_polygon_geojson=site_polygon_geojson),
        )
        features = result.get("feature_collection", {}).get("features", []) or []
    except Exception as exc:
        raise RuntimeError(f"MAAS legal-envelope generation failed: {exc}") from exc

    if not features:
        status = result.get("generation_status") or "infeasible"
        reason = result.get("infeasible_reason") or "no_accepted_variants"
        raise ValueError(f"MAAS legal-envelope generation {status}: {reason}")

    generation = int(event.get("generations") or event.get("generation") or 0)
    pareto_front = []
    pareto_geojson = []
    for idx, feature in enumerate(features):
        design = _maas_design_from_feature(feature, idx, generation)
        feature.setdefault("properties", {})
        feature["properties"]["design_id"] = design["id"]
        feature["properties"]["design_uid"] = design["uid"]
        feature["properties"]["objectives"] = design["objectives"]
        feature["properties"]["algorithm"] = "maas_legal_envelope"
        pareto_front.append(design)
        pareto_geojson.append(feature)

    def parking_candidate_score(item):
        idx, feature = item
        props = feature.get("properties") if isinstance(feature, dict) else {}
        precheck = props.get("parking_precheck") if isinstance(props, dict) else {}
        layout = precheck.get("layout_candidate") if isinstance(precheck, dict) else {}
        if not isinstance(layout, dict):
            return (0, 0, 0, 0, 0, 0, -idx)
        status = str(layout.get("status") or "")
        adjacency = layout.get("adjacency") if isinstance(layout.get("adjacency"), dict) else {}
        turning = layout.get("turning_clearance") if isinstance(layout.get("turning_clearance"), dict) else {}
        grid = layout.get("grid_solver") if isinstance(layout.get("grid_solver"), dict) else {}
        required = int(layout.get("required_spaces") or 0)
        provided = int(layout.get("provided_spaces") or 0)
        frontage = int(turning.get("frontage_connected_stalls") or 0)
        return (
            1 if required > 0 and provided > 0 else 0,
            1 if status == "pass" else 0,
            1 if provided >= required else 0,
            1 if required <= 1 or adjacency.get("contiguous_ok") else 0,
            1 if grid.get("entrance_verified") else 0,
            frontage,
            -idx,
        )

    best_idx = max(range(len(pareto_geojson)), key=lambda idx: parking_candidate_score((idx, pareto_geojson[idx])))
    client_event = dict(event)
    client_event["pareto_front"] = pareto_front
    client_event["pareto_geojson"] = pareto_geojson
    client_event["best"] = pareto_front[best_idx]
    client_event["best_geojson"] = pareto_geojson[best_idx]
    client_event["pareto_count"] = len(pareto_front)
    client_event["maas_result"] = {
        "mode": result.get("mode"),
        "algorithm": result.get("algorithm"),
        "constraints": result.get("constraints"),
        "rejected_count": len(result.get("rejected") or []),
        "notes": result.get("notes") or [],
    }
    return client_event


def _parking_options_from_job_options(job_options: dict | None, *, site_polygon_geojson: dict | None = None) -> dict:
    options = job_options or {}
    result = {}
    for key in ("parking_rule_id", "parking_metric", "parking_metric_value"):
        if options.get(key) is not None:
            result[key] = options.get(key)
    road_context = options.get("parking_road_context")
    if isinstance(road_context, dict):
        result["road_context"] = road_context
    elif isinstance(site_polygon_geojson, dict):
        inferred = _infer_parking_road_context(site_polygon_geojson)
        if inferred:
            result["road_context"] = inferred
    return result


def _infer_parking_road_context(site_polygon_geojson: dict) -> dict | None:
    try:
        from backend.app.modules.land.reference.services import road_frontage
        roads_result = road_frontage.fetch_neighbor_roads(site_polygon_geojson)
        road_frontages = roads_result.get("roads") if isinstance(roads_result, dict) else None
    except Exception:
        return None
    if not isinstance(road_frontages, list) or not road_frontages:
        return None
    widths = []
    for road in road_frontages:
        if not isinstance(road, dict):
            continue
        try:
            width = float(road.get("roadWidthM") or road.get("road_width_m") or 0.0)
        except (TypeError, ValueError):
            width = 0.0
        if width > 0:
            widths.append(width)
    return {
        "road_width_m": max(widths) if widths else None,
        "road_frontages": [
            {
                "geometry": road.get("geometry"),
                "roadWidthM": road.get("roadWidthM") or road.get("road_width_m"),
                "sharedEdge": road.get("sharedEdge") or road.get("shared_edge"),
                "roadCenterline": road.get("roadCenterline") or road.get("road_centerline"),
                "landCategory": road.get("landCategory") or road.get("land_category"),
            }
            for road in road_frontages
            if isinstance(road, dict)
        ][:5],
    }


def _save_final_results(job, event, site_polygon, site_area_m2,
                        building_type="공동주택", algorithm="additive",
                        *,
                        outputs_def=None,
                        enable_repair: bool = False,
                        sunlight_envelope: dict | None = None):
    """Save Pareto-optimal designs to database."""
    pareto = event.get("pareto_front", [])
    geojson_by_uid = {}
    geojson_by_id = {}
    for feature in event.get("pareto_geojson", []) or []:
        props = feature.get("properties", {}) or {}
        if props.get("design_uid") is not None:
            geojson_by_uid[str(props.get("design_uid"))] = feature
        if props.get("design_id") is not None:
            geojson_by_id[str(props.get("design_id"))] = feature
    designs_to_save = []
    for d in pareto:
        a = d.get("algorithm", algorithm) if algorithm == "per_design" else algorithm
        mass_geojson = (
            geojson_by_uid.get(str(d.get("uid")))
            or geojson_by_id.get(str(d.get("id")))
        )
        if mass_geojson is None and d.get("inputs"):
            mass_geojson = design_to_geojson(d.get("inputs", []), site_polygon, site_area_m2,
                                             building_type, a,
                                             enable_repair=enable_repair,
                                             outputs_def=outputs_def,
                                             sunlight_envelope=sunlight_envelope)
        if not isinstance(mass_geojson, dict) or not mass_geojson.get("geometry"):
            raise ValueError("Final design has no generated mass geometry")
        designs_to_save.append({
            "generation": d.get("generation", 0),
            "design_id": d.get("id", 0),
            "inputs": d.get("inputs", []),
            "outputs": {
                "objectives": d.get("objectives", []),
                "penalty": d.get("penalty", 0),
                "result_identity": {
                    "algorithm": a,
                    "uid": d.get("uid"),
                    "source_design_id": d.get("source_design_id", d.get("id", 0)),
                },
            },
            "ranking": 1.0,
            "crowding_distance": 0.0,
            "is_feasible": d.get("feasible", True),
            "is_pareto_optimal": True,
            "mass_geojson": mass_geojson,
        })
    save_results(job, designs_to_save)


@require_http_methods(["GET"])
def job_results(request, job_id):
    """GET /design/jobs/<id>/results/ — Get all results for a job."""
    lifecycle.recover_interrupted(job_id)
    try:
        job = OptimizationJob.objects.get(id=job_id)
    except OptimizationJob.DoesNotExist:
        return JsonResponse({"error": "Job not found"}, status=404)

    designs = job.results.all()
    pareto = job.results.filter(is_pareto_optimal=True)

    return JsonResponse({
        "job": format_job_response(job),
        "total_designs": designs.count(),
        "pareto_front": format_pareto_front(pareto),
        "designs": [format_design_response(d) for d in designs],
    })


def _requested_design_result(request, job_id, design_id, body=None):
    try:
        uid = requested_design_uid(request.GET.getlist("design_uid"), body)
        design = resolve_design_result(job_id, design_id, uid)
        return design, uid, None
    except ResultIdentityError as exc:
        return None, None, JsonResponse({"error": str(exc), "code": exc.code}, status=exc.status)


def _requested_design_evidence(design, uid):
    bundle = build_maas_evidence_bundle(job=design.job, design=design)
    if uid is not None:
        from urllib.parse import quote
        bundle["candidate"]["design_uid"] = uid
        bundle["bundle_id"] += ":uid:" + quote(uid, safe="")
    return bundle


@require_http_methods(["GET"])
def design_detail(request, job_id, design_id):
    """GET /design/jobs/<id>/results/<design_id>/ — Get single design."""
    design, uid, error = _requested_design_result(request, job_id, design_id)
    if error is not None:
        return error

    payload = format_design_response(design)
    if uid is not None:
        payload["design_uid"] = uid
    return JsonResponse(payload)


@require_http_methods(["GET"])
def design_evidence(request, job_id, design_id):
    """GET /design/jobs/<id>/results/<design_id>/evidence/ — canonical MAAS evidence bundle."""
    design, uid, error = _requested_design_result(request, job_id, design_id)
    if error is not None:
        return error

    return JsonResponse(_requested_design_evidence(design, uid))


@csrf_exempt
@require_http_methods(["POST"])
def design_aesthetic(request, job_id, design_id):
    """POST /design/jobs/<id>/results/<design_id>/aesthetic/ — render locked mass then call image provider."""
    try:
        body = json.loads(request.body or b"{}")
        if not isinstance(body, dict):
            raise ValueError("body must be an object")
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    design, uid, error = _requested_design_result(request, job_id, design_id, body)
    if error is not None:
        return error

    provider = body.get("provider") if isinstance(body.get("provider"), str) else "placeholder"
    if provider not in {"placeholder", "gpt-image", "nano-banana"}:
        return JsonResponse({"error": "provider must be one of: placeholder, gpt-image, nano-banana"}, status=400)

    style = body.get("style") if isinstance(body.get("style"), str) else None
    evidence = _requested_design_evidence(design, uid)
    media_root = backend_root() / "media" / "maas" / "aesthetic"
    renderer = MultiViewReferencePackRenderer(media_root / "references")
    adapter = None
    if provider == "gpt-image":
        adapter = OpenAIImageAdapter(output_dir=media_root / "generated")
    elif provider == "nano-banana":
        adapter = NanoBananaAdapter(output_dir=media_root / "generated")

    try:
        result = build_aesthetic_pipeline_result(
            evidence,
            provider=provider,
            style=style,
            renderer=renderer,
            adapter=adapter,
            attach_to_evidence=bool(body.get("attach_to_evidence", True)),
        )
    except Exception as e:
        return JsonResponse({"error": f"MAAS aesthetic generation failed: {e}"}, status=400)
    return JsonResponse(_with_aesthetic_asset_urls(result))


@require_http_methods(["GET"])
def maas_aesthetic_asset(request, asset_path):
    """Serve local MAAS aesthetic reference/generated assets in development."""
    media_root = (backend_root() / "media" / "maas" / "aesthetic").resolve()
    target = (media_root / asset_path).resolve()
    if media_root not in target.parents and target != media_root:
        raise Http404("Asset not found")
    if not target.exists() or not target.is_file():
        raise Http404("Asset not found")
    return FileResponse(target.open("rb"), content_type=_image_content_type(target))


def _image_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".gltf":
        return "model/gltf+json"
    if suffix == ".json":
        return "application/json"
    return "image/png"


def _with_aesthetic_asset_urls(result: dict) -> dict:
    media_root = (backend_root() / "media" / "maas" / "aesthetic").resolve()

    def public_url(uri):
        if not isinstance(uri, str):
            return None
        if uri.startswith("http://") or uri.startswith("https://"):
            return uri
        try:
            path = Path(uri).resolve()
        except Exception:
            return None
        if media_root in path.parents or path == media_root:
            rel = path.relative_to(media_root).as_posix()
            return f"/design/maas/aesthetic-assets/{rel}"
        return None

    reference = result.get("reference")
    if isinstance(reference, dict):
        url = public_url(reference.get("uri"))
        if url:
            reference["url"] = url
        _add_nested_aesthetic_urls(reference.get("metadata"), public_url)

    provider_result = result.get("provider_result")
    if isinstance(provider_result, dict):
        for asset in provider_result.get("assets") or []:
            if isinstance(asset, dict):
                url = public_url(asset.get("uri"))
                if url:
                    asset["url"] = url

    evidence = result.get("evidence")
    aesthetic_assets = ((evidence or {}).get("assets") or {}).get("aesthetic") if isinstance(evidence, dict) else None
    if isinstance(aesthetic_assets, list):
        for item in aesthetic_assets:
            if not isinstance(item, dict):
                continue
            ref = item.get("reference")
            if isinstance(ref, dict):
                url = public_url(ref.get("uri"))
                if url:
                    ref["url"] = url
            provider = item.get("provider_result")
            if isinstance(provider, dict):
                for asset in provider.get("assets") or []:
                    if isinstance(asset, dict):
                        url = public_url(asset.get("uri"))
                        if url:
                            asset["url"] = url
    return result


def _add_nested_aesthetic_urls(value, public_url):
    if isinstance(value, dict):
        url = public_url(value.get("uri"))
        if url:
            value["url"] = url
        for child in value.values():
            _add_nested_aesthetic_urls(child, public_url)
    elif isinstance(value, list):
        for child in value:
            _add_nested_aesthetic_urls(child, public_url)


@csrf_exempt
@require_http_methods(["POST"])
def interactive_patch(request):
    """POST /design/interactive/patch/ — Dry-run natural language mass edit plan."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    user_text = body.get("message", "")
    selected_design = body.get("selected_design")
    mass_geojson = body.get("mass_geojson")
    constraints = body.get("constraints", [])

    if not isinstance(user_text, str) or not user_text.strip():
        return JsonResponse({"error": "message is required"}, status=400)

    plan = build_interactive_patch_plan(
        user_text=user_text,
        selected_design=selected_design if isinstance(selected_design, dict) else None,
        mass_geojson=mass_geojson if isinstance(mass_geojson, dict) else None,
        constraints=constraints if isinstance(constraints, list) else [],
    )
    return JsonResponse(plan)


@csrf_exempt
@require_http_methods(["POST"])
def interactive_preview(request):
    """POST /design/interactive/preview/ — Apply dry-run patch candidates to geometry."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    patch_plan = body.get("patch_plan")
    selected_design = body.get("selected_design")
    site_polygon = body.get("site_polygon")
    site_area_m2 = body.get("site_area_m2")
    constraints = body.get("constraints", [])
    building_type = body.get("building_type", "공동주택")
    algorithm = body.get("algorithm")

    if not isinstance(patch_plan, dict):
        return JsonResponse({"error": "patch_plan is required"}, status=400)
    if not isinstance(selected_design, dict):
        return JsonResponse({"error": "selected_design is required"}, status=400)
    if not isinstance(site_polygon, dict):
        return JsonResponse({"error": "site_polygon is required"}, status=400)
    try:
        site_area_m2 = float(site_area_m2)
    except (TypeError, ValueError):
        return JsonResponse({"error": "site_area_m2 is required"}, status=400)

    result = build_interactive_preview(
        patch_plan=patch_plan,
        selected_design=selected_design,
        site_polygon_geojson=site_polygon,
        site_area_m2=site_area_m2,
        constraints=constraints if isinstance(constraints, list) else [],
        building_type=building_type if isinstance(building_type, str) else "공동주택",
        algorithm=algorithm if isinstance(algorithm, str) else None,
    )
    if "error" in result:
        return JsonResponse(result, status=400)
    return JsonResponse(result)


@csrf_exempt
@require_http_methods(["POST"])
def interactive_operation(request):
    """POST /design/interactive/operation/ — Apply push/pull-style mass operation."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    mass_geojson = body.get("mass_geojson")
    site_polygon = body.get("site_polygon")
    operation = body.get("operation")
    if not isinstance(mass_geojson, dict):
        return JsonResponse({"error": "mass_geojson is required"}, status=400)
    if not isinstance(site_polygon, dict):
        return JsonResponse({"error": "site_polygon is required"}, status=400)
    if not isinstance(operation, dict):
        return JsonResponse({"error": "operation is required"}, status=400)

    try:
        result = apply_mass_operation(
            mass_geojson=mass_geojson,
            site_polygon_geojson=site_polygon,
            operation=operation,
            constraints=body.get("constraints") if isinstance(body.get("constraints"), list) else [],
            building_type=body.get("building_type") if isinstance(body.get("building_type"), str) else "공동주택",
            sunlight_envelope=body.get("sunlight_envelope") if isinstance(body.get("sunlight_envelope"), dict) else None,
            setback_geometries=body.get("setback_geometries") if isinstance(body.get("setback_geometries"), dict) else None,
        )
    except Exception as e:
        return JsonResponse({"error": f"Interactive operation failed: {e}"}, status=400)
    return JsonResponse(result)


@csrf_exempt
@require_http_methods(["POST"])
def maas_conversational_revision(request):
    """Bounded edit of one accepted MAAS component graph; never regenerates a population."""
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON body"}, status=400)
    job = None
    job_id = body.get("job_id")
    if job_id:
        try:
            job = OptimizationJob.objects.get(id=job_id)
        except (OptimizationJob.DoesNotExist, ValueError):
            return JsonResponse({"error": "unknown job_id"}, status=404)
    accepted_feature = body.get("accepted_feature")
    design_id = body.get("design_id")
    if job is not None and isinstance(design_id, int):
        try:
            stored_design = DesignResult.objects.get(job=job, design_id=design_id)
        except DesignResult.DoesNotExist:
            return JsonResponse({"error": "unknown design_id for job"}, status=404)
        if isinstance(stored_design.mass_geojson, dict):
            accepted_feature = stored_design.mass_geojson
    site_polygon = job.site_polygon if job is not None else body.get("site_polygon")
    graph_operations = body.get("graph_operations")
    references = body.get("references") if isinstance(body.get("references"), list) else []
    if not isinstance(accepted_feature, dict):
        return JsonResponse({"error": "accepted_feature is required"}, status=400)
    if not isinstance(site_polygon, dict):
        return JsonResponse({"error": "site_polygon is required"}, status=400)
    instruction = body.get("instruction") if isinstance(body.get("instruction"), str) else ""
    if graph_operations is not None and not isinstance(graph_operations, list):
        return JsonResponse({"error": "graph_operations must be a list"}, status=400)
    if not graph_operations and not instruction.strip() and not references:
        return JsonResponse({"error": "instruction, references, or graph_operations is required"}, status=400)
    try:
        project_key = str((job.pnu if job is not None else body.get("project_key")) or "")
        learning_profile = build_revision_learning_profile(project_key)
        constraints = job.constraints if job is not None and isinstance(job.constraints, list) else (
            body.get("constraints") if isinstance(body.get("constraints"), list) else []
        )
        result = apply_conversational_graph_revision(
            accepted_feature=accepted_feature,
            site_polygon_geojson=site_polygon,
            graph_operations=graph_operations or [],
            constraints=constraints,
            building_type=body.get("building_type") if isinstance(body.get("building_type"), str) else "공동주택",
            instruction=instruction,
            references=references,
            revision_history=body.get("revision_history") if isinstance(body.get("revision_history"), list) else [],
            reference_vlm_model=body.get("reference_vlm_model") if isinstance(body.get("reference_vlm_model"), str) else None,
            learning_profile=learning_profile,
        )
    except Exception as exc:
        logger.exception("MAAS conversational revision failed")
        return JsonResponse({"error": f"MAAS conversational revision failed: {exc}"}, status=400)
    props = accepted_feature.get("properties") if isinstance(accepted_feature.get("properties"), dict) else {}
    reference_evidence = result.get("reference_evidence") if isinstance(result.get("reference_evidence"), dict) else {}
    mass_brain = props.get("mass_brain_shadow") if isinstance(props.get("mass_brain_shadow"), dict) else {}
    if mass_brain.get("proposal_id"):
        reference_evidence = {
            **reference_evidence,
            "mass_brain": {
                "proposal_id": str(mass_brain["proposal_id"]),
                "project_key": project_key,
            },
        }
    event = MaasRevisionEvent.objects.create(
        job=job,
        project_key=project_key,
        variant_id=str(props.get("variant_id") or ""),
        instruction=instruction,
        inference_source=str((result.get("intent_translation") or {}).get("source") or ""),
        accepted_by_gates=bool(result.get("accepted")),
        graph_diff=result.get("graph_diff") if isinstance(result.get("graph_diff"), list) else [],
        validation=result.get("validation") if isinstance(result.get("validation"), dict) else {},
        reference_evidence=reference_evidence,
        revision_evaluation=result.get("revision_evaluation") if isinstance(result.get("revision_evaluation"), dict) else {},
    )
    result["revision_event_id"] = str(event.id)
    result["constraint_source"] = "stored_optimization_job" if job is not None else "request_payload"
    result["learning_profile"] = learning_profile
    return JsonResponse(result)


@csrf_exempt
@require_http_methods(["POST"])
def maas_revision_feedback(request, revision_id):
    """Persist architect/client acceptance, rejection, or undo for later calibration."""
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON body"}, status=400)
    try:
        event = MaasRevisionEvent.objects.get(id=revision_id)
    except MaasRevisionEvent.DoesNotExist:
        return JsonResponse({"error": "revision event not found"}, status=404)
    decision = str(body.get("decision") or "").strip().lower()
    if decision not in {"accepted", "rejected", "undo"}:
        return JsonResponse({"error": "decision must be accepted, rejected, or undo"}, status=400)
    rating = body.get("rating")
    if rating is not None:
        if not isinstance(rating, int | float) or not 1 <= float(rating) <= 5:
            return JsonResponse({"error": "rating must be between 1 and 5"}, status=400)
        event.user_rating = float(rating)
    event.user_decision = decision
    event.feedback_note = str(body.get("note") or "")[:4000]
    event.feedback_at = timezone.now()
    event.save(update_fields=["user_decision", "user_rating", "feedback_note", "feedback_at"])
    mass_brain = event.reference_evidence.get("mass_brain") if isinstance(event.reference_evidence, dict) else None
    mass_brain_feedback = {"status": "not_mass_brain_proposal"}
    if isinstance(mass_brain, dict) and mass_brain.get("proposal_id"):
        mass_brain_feedback = record_proposal_feedback(
            project_key=str(mass_brain.get("project_key") or event.project_key),
            proposal_id=str(mass_brain["proposal_id"]),
            feedback_id=str(event.id),
            decision=decision,
            rating=event.user_rating,
            note=event.feedback_note,
        )
    return JsonResponse({
        "schema_version": "arr.maas.revision_feedback.v1",
        "revision_event_id": str(event.id),
        "decision": event.user_decision,
        "rating": event.user_rating,
        "recorded": True,
        "mass_brain_feedback": mass_brain_feedback,
    })


@csrf_exempt
@require_http_methods(["POST"])
def maas_export_scad(request):
    """POST /design/maas/export-scad/ — Export ARR mass GeoJSON to OpenSCAD."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    mass_geojson = body.get("mass_geojson")
    name = body.get("name")
    if not isinstance(mass_geojson, dict):
        return JsonResponse({"error": "mass_geojson is required"}, status=400)

    try:
        result = export_mass_geojson_to_scad(
            mass_geojson,
            name=name if isinstance(name, str) else None,
        )
    except Exception as e:
        return JsonResponse({"error": f"MAAS SCAD export failed: {e}"}, status=400)
    return JsonResponse(result)


@csrf_exempt
@require_http_methods(["POST"])
def maas_legal_variants(request):
    """POST /design/maas/legal-variants/ — Generate legal/diverse MAAS mass variants."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    mass_geojson = body.get("mass_geojson")
    site_polygon = body.get("site_polygon")
    if not isinstance(mass_geojson, dict):
        return JsonResponse({"error": "mass_geojson is required"}, status=400)
    if not isinstance(site_polygon, dict):
        return JsonResponse({"error": "site_polygon is required"}, status=400)

    from backend.app.modules.design.generation.maas.service_cache import load_verified_result, request_cache_key, store_verified_result

    service_mode = str(body.get("service_mode") or "sync").strip().lower()
    cache_key = request_cache_key(body)
    if service_mode == "cached":
        cached = load_verified_result(cache_key)
        if cached is None:
            return JsonResponse({
                "status": "cache_miss",
                "cache_key": cache_key,
                "refresh_required": True,
            }, status=404)
        response = JsonResponse(cached)
        response["X-MAAS-Cache"] = "hit"
        return response

    try:
        result = generate_legal_mass_variants(
            mass_geojson=mass_geojson,
            site_polygon_geojson=site_polygon,
            constraints=body.get("constraints") if isinstance(body.get("constraints"), list) else [],
            building_type=body.get("building_type") if isinstance(body.get("building_type"), str) else "공동주택",
            max_variants=int(body.get("max_variants") or 6),
            sunlight_envelope=body.get("sunlight_envelope") if isinstance(body.get("sunlight_envelope"), dict) else None,
            setback_geometries=body.get("setback_geometries") if isinstance(body.get("setback_geometries"), dict) else None,
            include_interactive_seed=bool(body.get("include_interactive_seed")),
            preferred_operator=body.get("preferred_operator") if isinstance(body.get("preferred_operator"), str) else None,
            pnu=body.get("pnu") if isinstance(body.get("pnu"), str) else None,
            parking_options=body.get("parking_options") if isinstance(body.get("parking_options"), dict) else None,
        )
    except Exception as e:
        logger.exception("MAAS legal variants generation failed")
        return JsonResponse({"error": f"MAAS legal variants failed: {e}"}, status=400)
    if service_mode == "refresh":
        try:
            store_verified_result(cache_key, result)
        except ValueError as exc:
            return JsonResponse({"error": str(exc), "cache_key": cache_key}, status=409)
    return JsonResponse(result)


@csrf_exempt
@require_http_methods(["POST"])
def site_boundary(request):
    """POST /design/site-boundary/ — Get parcel polygon from PNU."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    pnu = (body.get("pnu") or "").strip()
    if not pnu:
        return JsonResponse({"error": "pnu is required"}, status=400)

    # 19자리 숫자 아니면 주소로 간주 → Vworld geocode로 PNU 자동 추출
    # (사용자 편의: ControlPanel placeholder "PNU 코드 (19자리) 또는 주소")
    if not (pnu.isdigit() and len(pnu) == 19):
        try:
            from backend.app.modules.land.reference.services.pnu_resolver import resolve_address
            resolved = resolve_address(pnu)
            if resolved and resolved.get("pnu"):
                pnu = resolved["pnu"]
            else:
                return JsonResponse(
                    {"error": f"주소 '{pnu}' → PNU 변환 실패"}, status=404
                )
        except Exception as e:
            return JsonResponse(
                {"error": f"주소 변환 오류: {e}"}, status=500
            )

    geometry = fetch_parcel_boundary(pnu)
    if not geometry:
        return JsonResponse({"error": f"No boundary found for PNU {pnu}"}, status=404)

    # Validate the polygon
    polygon = geojson_to_polygon(geometry)
    validation = validate_site(polygon)

    return JsonResponse({
        "pnu": pnu,
        "geometry": geometry,
        "area_m2": validation["area_m2"],
        "valid": validation["valid"],
        "errors": validation["errors"],
    })


@csrf_exempt
@require_http_methods(["POST"])
def auto_constraints(request):
    """POST /design/auto-constraints/ — Generate constraints from land regulations."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    pnu = body.get("pnu", "")
    zones = body.get("zones", [])
    address = body.get("address", "")
    building_type = body.get("building_type", "")
    include_law_articles = bool(body.get("include_law_articles", True))

    if not pnu and not zones and not address:
        return JsonResponse({"error": "pnu, zones, or address required"}, status=400)

    # Call land/analyze internally
    try:
        from backend.app.modules.land.reference.services import regulation_calculator
        from backend.app.modules.land.reference.services import zoning_mapper, land_api, road_frontage

        # If PNU given but no zones, look up zones via Vworld Data API
        if not zones and pnu:
            land_info = land_api.get_land_use_info(pnu)
            zones = land_info.get("zones", [])

        # resolve_limits handles exact matching + strictest-zone logic
        limits = zoning_mapper.resolve_limits(zones) if zones else {}
        zone_names = [z["zone_name"] for z in limits.get("zones", [])] if limits else zones

        reg = regulation_calculator.calculate_all(
            zone_names,
            use_llm_extraction=include_law_articles,
        )

        daylight_multiplier = _daylight_diagonal_multiplier(zone_names, building_type)
        if daylight_multiplier is not None:
            reg["daylight_diagonal_multiplier"] = daylight_multiplier

        constraints = regulations_to_constraints(reg)

        # Query law articles for building-type-specific regulations
        law_articles = {}
        if include_law_articles and building_type and zone_names:
            try:
                from backend.app.modules.land.reference.services.law_enricher import search_for_building_type
                law_result = search_for_building_type(building_type, zone_names)
                law_articles = law_result
            except Exception as e:
                logger.warning(f"Law search for building type failed: {e}")
                law_articles = {"articles": [], "total_count": 0,
                                "errors": [str(e)]}

        # Compute setback geometry for map visualization
        setback_geometries = {}
        site_geojson = body.get("site_polygon")
        if site_geojson:
            try:
                from backend.app.modules.land.reference.services.setback_geometry import compute_setback_lines
                from backend.app.modules.land.reference import config as land_config
                road_frontages = []
                neighbor_parcels = []
                try:
                    roads_result = road_frontage.fetch_neighbor_roads(site_geojson)
                    if roads_result.get("success"):
                        road_frontages = roads_result.get("roads") or []
                except Exception as e:
                    logger.warning(f"road frontage lookup failed: {e}")
                try:
                    neighbors_result = road_frontage.fetch_neighbor_parcels(site_geojson)
                    if neighbors_result.get("success"):
                        neighbor_parcels = neighbors_result.get("neighbors") or []
                except Exception as e:
                    logger.warning(f"neighbor parcel lookup failed: {e}")

                lines = compute_setback_lines(
                    site_geojson, reg,
                    compute_datum=land_config.ENABLE_DATUM_ELEVATION,
                    road_frontages=road_frontages,
                    neighbor_parcels=neighbor_parcels,
                )
                adj_m = reg.get("adjacent_setback_m") or 0.5
                sunlight_m = 1.5
                if lines.get("buildable_area"):
                    setback_geometries["buildable_area"] = {
                        "geometry": lines["buildable_area"],
                        "distance_m": float(adj_m),
                        "label": f"건축가능영역 (이격 {adj_m}m)",
                    }
                if lines.get("north_setback"):
                    setback_geometries["north_setback"] = {
                        "geometry": lines["north_setback"],
                        "distance_m": sunlight_m,
                        "label": f"정북 일조사선 {sunlight_m}m",
                    }
                if lines.get("adjacent_setback"):
                    setback_geometries["adjacent_setback"] = {
                        "geometry": lines["adjacent_setback"],
                        "distance_m": float(adj_m),
                        "label": f"인접대지 이격 {adj_m}m",
                    }
                road_m = 0.0
                if lines.get("road_setback"):
                    road_setback_meta = lines.get("road_setback") or {}
                    road_m = road_setback_meta.get("setback_m")
                    if road_m is None:
                        road_m = reg.get("building_line_setback_m") or 1.0
                if lines.get("road_setback"):
                    setback_geometries["road_setback"] = {
                        "geometry": lines["road_setback"],
                        "distance_m": float(road_m),
                        "label": f"건축선 후퇴 {road_m}m",
                    }
                cutoff_val = reg.get("corner_cutoff_m") or 3.0
                if lines.get("corner_cutoff"):
                    setback_geometries["corner_cutoff"] = {
                        "geometry": lines["corner_cutoff"],
                        "distance_m": float(cutoff_val),
                        "label": f"가각전제 {cutoff_val}m",
                    }
                desig_m = reg.get("building_designation_setback_m")
                if lines.get("building_designation_line"):
                    setback_geometries["building_designation_line"] = {
                        "geometry": lines["building_designation_line"],
                        "distance_m": float(desig_m) if desig_m else 2.0,
                        "label": f"건축지정선 {desig_m or 2.0}m",
                    }
                if lines.get("sunlight_envelope"):
                    setback_geometries["sunlight_envelope"] = lines["sunlight_envelope"]
                if lines.get("daylight_diagonal_envelope"):
                    setback_geometries["daylight_diagonal_envelope"] = lines["daylight_diagonal_envelope"]
                # Phase 2D: datum_result는 envelope과 독립적으로 노출
                # (정북일조 미적용 zone(상업 등)에서도 datum 표시 가능)
                if lines.get("datum_result"):
                    setback_geometries["datum_result"] = lines["datum_result"]
                    datum = lines["datum_result"]
                    road_widths = [
                        float(r.get("roadWidthM") or r.get("road_width_m") or 0.0)
                        for r in road_frontages
                        if float(r.get("roadWidthM") or r.get("road_width_m") or 0.0) > 0
                    ]
                    if road_widths:
                        road_width = max(road_widths)
                        road_diag_mult = reg.get("road_diagonal_multiplier")
                        setback_geometries["front_road_diagonal_profile"] = {
                            "road_width_m": road_width,
                            "slope": float(road_diag_mult or 1.5),
                            "applies": road_diag_mult is not None,
                            "law_basis": reg.get("road_diagonal_article") or "건축법 시행령 §82 도로사선 기준 참고",
                            "note": reg.get("road_diagonal_rule") or "현행 도로사선은 삭제/가로구역별 높이제한으로 대체. 1:1.5는 참고 단면.",
                            "road_datum_m": datum.get("road_datum_m"),
                            "parcel_datum_m": datum.get("parcel_datum_m"),
                        }
                    setback_geometries["road_frontages"] = [
                        {
                            "geometry": r.get("geometry"),
                            "roadWidthM": float(r.get("roadWidthM") or r.get("road_width_m") or 0.0),
                            "sharedEdge": r.get("sharedEdge") or r.get("shared_edge"),
                            "roadCenterline": r.get("roadCenterline") or r.get("road_centerline"),
                            "landCategory": r.get("landCategory") or r.get("land_category"),
                        }
                        for r in road_frontages
                    ][:5]
                    setback_geometries["neighbor_parcels"] = [
                        {
                            "geometry": n.get("geometry"),
                            "sharedEdge": n.get("sharedEdge") or n.get("shared_edge"),
                            "landCategory": n.get("landCategory") or n.get("land_category"),
                            "pnu": n.get("pnu"),
                        }
                        for n in neighbor_parcels
                    ][:10]
            except Exception as e:
                logger.warning(f"setback_geometry failed, falling back: {e}")
                # Fallback: simple buffer
                setback_m = reg.get("adjacent_setback_m")
                if setback_m:
                    geom = compute_setback_geometry(site_geojson, float(setback_m))
                    if geom:
                        setback_geometries["adjacent_setback"] = {
                            "geometry": geom,
                            "distance_m": float(setback_m),
                            "label": f"인접대지 이격 {setback_m}m",
                        }

        return JsonResponse({
            "zones": zone_names,
            "regulations": {
                "bcr_pct": reg.get("bcr_pct"),
                "far_pct": reg.get("far_pct"),
                "height_limit_m": reg.get("height_limit_m"),
                "adjacent_setback_m": reg.get("adjacent_setback_m"),
                "sunlight_applies": reg.get("sunlight_applies"),
                "sunlight_rules": reg.get("sunlight_rules"),
                "corner_cutoff_required": reg.get("corner_cutoff_required"),
                "road_diagonal_multiplier": reg.get("road_diagonal_multiplier"),
                "road_diagonal_rule": reg.get("road_diagonal_rule"),
                "road_diagonal_article": reg.get("road_diagonal_article"),
                "daylight_diagonal_multiplier": reg.get("daylight_diagonal_multiplier"),
                "zone_category": reg.get("zone_category"),
            },
            "constraints": constraints,
            "setback_geometries": setback_geometries,
            "law_articles": law_articles,
            "building_type": building_type,
        })

    except ImportError:
        logger.warning("land app not available for constraint generation")
        return JsonResponse({
            "zones": zones,
            "regulations": {},
            "constraints": [],
            "warning": "land app not available",
        })
    except Exception as e:
        logger.error(f"Auto-constraints failed: {e}")
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def validate_job(request, job_id):
    """
    POST /design/jobs/<id>/validate/ — Validate designs against building regulations.

    Body: {
        "regulation_result": {bcr_pct, far_pct, height_limit_m, adjacent_setback_m, ...}
    }

    Returns validation results + tightened constraints if violations found.
    """
    try:
        job = OptimizationJob.objects.get(id=job_id)
    except OptimizationJob.DoesNotExist:
        return JsonResponse({"error": "Job not found"}, status=404)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    regulation_result = body.get("regulation_result", {})
    if not regulation_result:
        return JsonResponse({"error": "regulation_result is required"}, status=400)

    # Get top pareto designs
    pareto_designs = job.results.filter(is_pareto_optimal=True)
    if not pareto_designs.exists():
        return JsonResponse({"error": "No pareto designs found. Run optimization first."}, status=400)

    # Extract metrics from stored design outputs
    designs_metrics = []
    for d in pareto_designs[:5]:
        outputs = d.outputs or {}
        objectives = outputs.get("objectives", [])
        # Map from job_spec output order to named metrics
        output_defs = job.job_spec.get("outputs", [])
        metrics = {}
        for i, obj_def in enumerate(output_defs):
            if i < len(objectives):
                metrics[obj_def["name"]] = objectives[i]
        designs_metrics.append(metrics)

    # Validate
    result = validate_best_designs(designs_metrics, regulation_result)

    # If violations exist, suggest tightened constraints
    tightened = None
    if not result["all_valid"] and result["worst_violations"]:
        current_constraints = list(job.constraints or [])
        tightened = auto_correct_constraints(result["worst_violations"], current_constraints)

    return JsonResponse({
        "job_id": str(job_id),
        "all_valid": result["all_valid"],
        "violations": result["violations"],
        "worst_violations": result["worst_violations"],
        "tightened_constraints": tightened,
    })


from backend.app.adapters.planm_agent import PlanmClient


@csrf_exempt
@require_http_methods(["POST"])
def create_floor_plan(request):
    """
    POST /design/floor-plan/

    Proxy to the Plan Agent (agents/planm): the floor-plan algorithms (ga, subdivision,
    mcts, packing, graph2plan) live there. The body is forwarded unchanged; the reply
    carries the agent's receipt of exactly that body and design_acceptance: not_verified.
    """
    try:
        body = json.loads(request.body)
        if not isinstance(body, dict):
            raise ValueError("Expected a JSON object")
    except (json.JSONDecodeError, ValueError, TypeError):
        return JsonResponse({"error": "Expected a finite JSON object"}, status=400)
    if not body.get("footprint_geojson"):
        return JsonResponse({"error": "footprint_geojson is required"}, status=400)
    if not body.get("rooms"):
        return JsonResponse({"error": "rooms list is required"}, status=400)
    try:
        result = PlanmClient().generate(body)
    except TimeoutError as exc:
        return JsonResponse({"error": str(exc)}, status=504)
    except (RuntimeError, ValueError) as exc:
        logger.warning("Plan Agent unavailable for floor-plan: %s", exc)
        return JsonResponse({"error": f"Plan Agent unavailable: {exc}"}, status=502)
    if "error" in result:
        return JsonResponse(result, status=422)
    return JsonResponse(result)


@csrf_exempt
@require_http_methods(["POST"])
def constraints_visualize(request):
    """POST /design/constraints/visualize/ — site polygon + 법규 한도 → envelope/setback GeoJSON.

    Flexity 광고 스타일: 대지경계선 + 대지 안의 공지(빨간 점선) + 정북 일조 base(녹색 점선) +
    sunlight slope metadata + 법규 한도 라벨.
    """
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    site_polygon_geojson = body.get("site_polygon")
    if not site_polygon_geojson:
        return JsonResponse({"error": "site_polygon is required"}, status=400)

    try:
        site_polygon = geojson_to_polygon(site_polygon_geojson)
    except Exception as e:
        return JsonResponse({"error": f"Invalid site_polygon: {e}"}, status=400)

    from backend.app.modules.design.generation.services.mass_renderer import constraint_envelope_geojson

    kwargs = {
        k: body[k] for k in (
            "bcr_limit_pct", "far_limit_pct", "height_limit_m",
            "adjacent_setback_m", "north_setback_m", "road_setback_m",
            "sunlight_slope", "sunlight_base_height_m",
        ) if k in body
    }

    try:
        result = constraint_envelope_geojson(site_polygon, **kwargs)
    except Exception as e:
        logger.exception("constraint_envelope_geojson failed")
        return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse(result)
