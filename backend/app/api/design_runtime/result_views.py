"""Job result endpoints: results list, design detail/evidence/aesthetic and reference/aesthetic asset serving.

Split out of views.py; views.py re-exports every name defined here.
"""

import json
from pathlib import Path
from django.http import FileResponse, Http404
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from backend.app.modules.design.generation.formatters import format_job_response, format_design_response, format_pareto_front
from backend.app.adapters.design_storage.models import OptimizationJob
from backend.app.adapters.design_storage import lifecycle
from backend.app.modules.design.generation.paths import aesthetic_media_root
from .result_identity import requested_design_uid, resolve_design_result, ResultIdentityError
from backend.app.modules.design.generation.maas import build_maas_evidence_bundle
from backend.app.modules.design.generation.maas.aesthetic import build_aesthetic_pipeline_result
from backend.app.modules.design.generation.maas.aesthetic.adapters import NanoBananaAdapter, OpenAIImageAdapter
from backend.app.modules.design.generation.maas.aesthetic.renderers import MultiViewReferencePackRenderer
from backend.app.modules.design.generation.maas.preference.reference_corpus import default_reference_root


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
    media_root = aesthetic_media_root()
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
    media_root = aesthetic_media_root().resolve()
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
    media_root = aesthetic_media_root().resolve()

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
