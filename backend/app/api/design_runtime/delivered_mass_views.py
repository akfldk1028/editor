"""HTTP boundary for identity-bound legacy Mass delivery."""
import io
import json
import re
import zipfile
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

_REQUEST_HASH = re.compile(r'[0-9a-f]{64}')
_CANDIDATE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]*')


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def delivered_mass_export(request):
    if request.method == 'GET':
        return JsonResponse({'schema_version': 'arr.delivered_mass_export.v1',
                             'provider': 'arr.delivered-mass-export', 'status': 'available',
                             'geometry_ready': False})
    try:
        payload = json.loads(request.body, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        if not isinstance(payload, dict):
            raise ValueError('request must be an object')
    except (ValueError, TypeError):
        return JsonResponse({'status': 'failed', 'code': 'invalid_request'}, status=400)
    from backend.app.modules.design.generation.maas.delivered_mass_export import export_delivered_mass
    return JsonResponse(export_delivered_mass(payload))


@csrf_exempt
@require_POST
def delivered_mass_bundle(request):
    """The same export, for a Mass cycle sent as a zip from another server."""
    from backend.app.modules.design.generation.maas.delivered_mass_bundle import BundleRefused, export_bundle
    try:
        return JsonResponse(export_bundle(request.body))
    except BundleRefused as exc:
        return JsonResponse({'status': 'failed', 'code': 'invalid_bundle', 'reason': str(exc)}, status=400)


def _export_target(request_hash):
    from backend.app.modules.design.generation.maas.delivered_mass_export import export_root
    if not _REQUEST_HASH.fullmatch(request_hash):
        raise Http404('delivered export not found')
    target = (export_root() / request_hash).resolve()
    if not target.is_dir():
        raise Http404('delivered export not found')
    return target


@require_GET
def delivered_mass_file(request, request_hash, member):
    target = _export_target(request_hash)
    path = (target / member.rstrip('/')).resolve()
    if not path.is_relative_to(target) or not path.is_file():
        raise Http404('delivered export file not found')
    return FileResponse(path.open('rb'), content_type='application/octet-stream')


@require_GET
def delivered_mass_package(request, request_hash):
    """Zip of one candidate folder, named relative to the dataset root (candidates/<id>/...)."""
    target = _export_target(request_hash)
    candidate = request.GET.get('candidate') or ''
    dataset = (target / 'dataset').resolve()
    package = (dataset / 'candidates' / candidate).resolve()
    if (not _CANDIDATE.fullmatch(candidate) or not package.is_relative_to(dataset / 'candidates')
            or not package.is_dir()):
        raise Http404('delivered candidate package not found')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(package.rglob('*')):
            resolved = path.resolve()
            if path.is_file() and resolved.is_relative_to(package):
                archive.write(resolved, path.relative_to(dataset).as_posix())
    response = HttpResponse(buffer.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="{candidate}.zip"'
    return response
