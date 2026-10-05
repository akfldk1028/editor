"""HTTP boundary for identity-bound legacy Mass delivery."""
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods


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
