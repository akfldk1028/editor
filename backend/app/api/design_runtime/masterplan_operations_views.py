"""HTTP adapter; geometry and legal calculations remain in their engine owners."""
import json
import logging
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from backend.app.modules.design.generation.maas.masterplan_operations import SCHEMA, OPERATIONS, invoke

logger = logging.getLogger('arr.masterplan.operations')
# Layout validation carries metric input and owner geometry; one bounded read here,
# independent of Django's form-body limit.
MAX_REQUEST_BYTES = 32 * 1024 * 1024
TRACE_FIELDS = ('run_id', 'request_id', 'project', 'branch', 'round', 'task_id', 'parent_task_id', 'caller', 'hop')


def trace_context(request):
    raw = request.headers.get('X-ACE-Trace', '')
    if not raw or len(raw) > 8192:
        return {}
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    if not isinstance(value, dict):
        return {}
    return {key: str(value[key])[:512] for key in TRACE_FIELDS if key in value}


@csrf_exempt
@require_http_methods(['GET', 'POST'])
def masterplan_operations(request):
    if request.method == 'GET':
        return JsonResponse({'schema_version': SCHEMA, 'provider': 'arr.masterplan-operations',
                             'operations': sorted(OPERATIONS)})
    try:
        # Layout validation carries both metric input and owner geometry. Read this
        # endpoint's bounded stream instead of Django's 2.5 MiB form-body limit.
        # Do not change the global limit for unrelated APIs or disable limits.
        limit = MAX_REQUEST_BYTES
        body = request.read(limit + 1)
        if len(body) > limit:
            return JsonResponse({'status': 'failed', 'code': 'request_too_large',
                                 'max_request_bytes': limit}, status=413)
        payload = json.loads(body, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        result = invoke(payload)
        trace = trace_context(request)
        logger.info('%s', json.dumps({'operation': result.get('operation'),
            'request_hash': result.get('request_hash'), 'status': result.get('status'), 'trace': trace}))
        if trace:
            result['trace'] = trace
        return JsonResponse(result, json_dumps_params={'allow_nan': False})
    except (ValueError, TypeError) as exc:
        return JsonResponse({'status': 'failed', 'code': 'invalid_request', 'reason': str(exc)}, status=400)
    except (ImportError, RuntimeError) as exc:
        return JsonResponse({'status': 'failed', 'code': 'owner_unavailable', 'reason': str(exc)}, status=503)
