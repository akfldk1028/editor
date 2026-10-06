"""Interactive editing and MAAS revision endpoints: patch/preview/operation, conversational revision, feedback, SCAD export, legal variants.

Split out of views.py; views.py re-exports every name defined here.
"""

import json
import logging
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from backend.app.adapters.design_storage.models import OptimizationJob, DesignResult, MaasRevisionEvent
from backend.app.modules.design.generation.services.interactive_patch import build_interactive_patch_plan
from backend.app.modules.design.generation.services.interactive_apply import build_interactive_preview
from backend.app.modules.design.generation.services.mass_operations import apply_mass_operation
from backend.app.modules.design.generation.maas import export_mass_geojson_to_scad, generate_legal_mass_variants
from backend.app.modules.design.generation.maas.interactive import apply_conversational_graph_revision, build_revision_learning_profile
from backend.app.modules.design.generation.maas.mass_brain import record_proposal_feedback

logger = logging.getLogger("backend.app.api.design_runtime.views")


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
