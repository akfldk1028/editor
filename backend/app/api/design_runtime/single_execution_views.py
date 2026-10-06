"""MAAS single-execution endpoints: compile, VLM review and immutable artifact serving.

Split out of views.py; views.py re-exports every name defined here.
"""

import json
import logging
from pathlib import Path
from django.conf import settings
from django.http import FileResponse, Http404
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from backend.app.modules.design.generation.paths import workspace_root
from backend.app.modules.design.generation.maas.geometry_language import materialize_isometric_thumbnail
from backend.app.modules.design.generation.maas.geometry_language.executed_archive import compile_executed_mass, materialize_executed_mass_passport
from backend.app.modules.design.generation.maas.single_execution import execute_single_mass, is_single_execution_run, single_execution_run_id, review_single_mass_with_vlm
from backend.app.modules.design.generation.maas.single_execution.replay import downstream_evidence_from_passport
from backend.app.modules.design.generation.maas.single_execution.pipeline import resolve_single_execution_replay

logger = logging.getLogger("backend.app.api.design_runtime.views")


def _single_execution_root() -> Path:
    configured = getattr(settings, "MAAS_SINGLE_EXECUTION_ROOT", "")
    if configured:
        return Path(configured).resolve()
    return (
        workspace_root()
        / "docs" / "ai-session-memory" / "maas-service-cache" / "single-executions"
    ).resolve()


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
