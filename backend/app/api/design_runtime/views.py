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
from backend.app.modules.design.generation.paths import aesthetic_media_root, book_scan_root, workspace_root
from .job_validation import validate_request, validate_spec
from .result_identity import (canonicalize_result_event,
                              requested_design_uid, resolve_design_result, ResultIdentityError)
from backend.app.modules.design.generation.services.constraint_bridge import regulations_to_constraints, build_default_job_spec, compute_setback_geometry, build_floor_plan_spec
from backend.app.modules.design.generation.services.mass_evaluator import evaluate_designs
from backend.app.modules.design.generation.services.mass_renderer import design_to_geojson
from backend.app.modules.design.generation.services.regulation_validator import validate_design, validate_best_designs, auto_correct_constraints
from backend.app.modules.design.generation.services.site_geometry import geojson_to_polygon, validate_site
from backend.app.modules.design.generation.services.interactive_patch import build_interactive_patch_plan
from backend.app.modules.design.generation.services.interactive_apply import build_interactive_preview
from backend.app.modules.design.generation.services.mass_operations import apply_mass_operation
from backend.app.modules.design.generation.maas import build_maas_evidence_bundle, export_mass_geojson_to_scad, generate_legal_mass_variants
from backend.app.modules.design.generation.maas.interactive import apply_conversational_graph_revision, build_revision_learning_profile
from backend.app.modules.design.generation.maas.mass_brain import record_proposal_feedback
from backend.app.modules.design.generation.maas.outcome_graph_slice import build_outcome_graph_slice
from backend.app.modules.design.generation.maas.book_language.registry import build_book_language_registry
from backend.app.modules.design.generation.maas.aesthetic import build_aesthetic_pipeline_result
from backend.app.modules.design.generation.maas.aesthetic.adapters import NanoBananaAdapter, OpenAIImageAdapter
from backend.app.modules.design.generation.maas.aesthetic.renderers import MultiViewReferencePackRenderer
from backend.app.modules.design.generation.maas.preference.reference_corpus import default_reference_root
from backend.app.modules.design.generation.maas.geometry_language import architectural_shape_programs, build_mass_execution_passport, compile_geometry_program, materialize_isometric_thumbnail, passport_path_for_preview, render_compilation_preview, write_mass_execution_passport
from backend.app.modules.design.generation.maas.geometry_language.executed_archive import compile_executed_mass, executed_mass_manifest, materialize_executed_mass_passport
from backend.app.modules.design.generation.maas.single_execution import execute_single_mass, is_single_execution_run, single_execution_run_id, review_single_mass_with_vlm
from backend.app.modules.design.generation.maas.single_execution.replay import downstream_evidence_from_passport
from backend.app.modules.design.generation.maas.single_execution.pipeline import resolve_single_execution_replay
from backend.app.modules.design.generation.maas.creative_portfolio_catalog import creative_portfolio_manifest, creative_portfolio_render
from backend.app.modules.design.generation.maas.portfolio_evaluation_catalog import portfolio_evaluation_manifest, portfolio_evaluation_render

logger = logging.getLogger(__name__)

# Active runners keyed by job_id for cancellation
_active_runners: dict[str, JobRunner] = {}

from .maas_archive_views import (  # noqa: F401  re-exported
    _geometry_preview_lock,
    _creative_portfolio_root,
    _portfolio_evaluation_root,
    maas_creative_portfolios,
    maas_portfolio_evaluations,
    maas_portfolio_evaluation_render,
    maas_creative_portfolio_render,
    maas_outcome_graph_slice,
    maas_book_asset,
    maas_geometry_shape_preview,
    maas_geometry_shape_passport,
)
from .single_execution_views import (  # noqa: F401  re-exported
    _single_execution_root,
    maas_single_execution,
    maas_single_execution_vlm_review,
    maas_single_execution_preview,
    maas_single_execution_thumbnail,
    maas_single_execution_manifest,
    maas_single_execution_passport,
    maas_single_execution_elevation,
    maas_single_execution_elevation_proposal,
    maas_single_execution_multi_view_elevation_artifact,
    maas_single_execution_multi_view_elevation_evidence,
    _single_execution_json,
    _single_execution_artifact,
    _passport_vlm_result,
)
from .job_support import (  # noqa: F401  re-exported
    _all_mode_budget_options,
    _precompute_sunlight_envelope,
    _enrich_event_geojson,
    _maas_design_from_feature,
    _parking_options_from_job_options,
    _infer_parking_road_context,
    _save_final_results,
)
from .result_views import (  # noqa: F401  re-exported
    maas_reference_asset,
    job_results,
    _requested_design_result,
    _requested_design_evidence,
    design_detail,
    design_evidence,
    design_aesthetic,
    maas_aesthetic_asset,
    _image_content_type,
    _with_aesthetic_asset_urls,
    _add_nested_aesthetic_urls,
)
from .interactive_views import (  # noqa: F401  re-exported
    interactive_patch,
    interactive_preview,
    interactive_operation,
    maas_conversational_revision,
    maas_revision_feedback,
    maas_export_scad,
    maas_legal_variants,
)
from .constraint_views import (  # noqa: F401  re-exported
    _daylight_diagonal_multiplier,
    auto_constraints,
    validate_job,
    create_floor_plan,
    constraints_visualize,
    PlanmClient,
)


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

