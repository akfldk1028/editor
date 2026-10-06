"""MAAS archive endpoints: creative portfolios, portfolio evaluations, outcome graph, BOOK scans, geometry phenotypes.

Split out of views.py; views.py re-exports every name defined here.
"""

import json
import logging
import threading
from pathlib import Path
from django.conf import settings
from django.http import FileResponse, Http404
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from backend.app.modules.design.generation.paths import book_scan_root, workspace_root
from backend.app.modules.design.generation.maas.outcome_graph_slice import build_outcome_graph_slice
from backend.app.modules.design.generation.maas.book_language.registry import build_book_language_registry
from backend.app.modules.design.generation.maas.geometry_language import architectural_shape_programs, build_mass_execution_passport, compile_geometry_program, passport_path_for_preview, render_compilation_preview, write_mass_execution_passport
from backend.app.modules.design.generation.maas.geometry_language.executed_archive import executed_mass_manifest
from backend.app.modules.design.generation.maas.single_execution import is_single_execution_run
from backend.app.modules.design.generation.maas.creative_portfolio_catalog import creative_portfolio_manifest, creative_portfolio_render
from backend.app.modules.design.generation.maas.portfolio_evaluation_catalog import portfolio_evaluation_manifest, portfolio_evaluation_render

logger = logging.getLogger("backend.app.api.design_runtime.views")


_geometry_preview_lock = threading.Lock()


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
    # The OCR registry records the scan's original absolute path; only its file
    # name is trusted, resolved against the editor's own scan directory.
    book_root = book_scan_root().resolve()
    scan_path = (book_root / Path(str(page_record["source_path"])).name).resolve()
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
