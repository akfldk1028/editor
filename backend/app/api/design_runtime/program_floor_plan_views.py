"""Explicit Program-to-Plan batch boundary; no database or implicit selection."""
import json
from pathlib import Path

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from backend.app.modules.design.generation.services.program_floor_plans import digest, generate


@csrf_exempt
@require_POST
def program_floor_plans(request):
    try:
        body = json.loads(request.body)
        if not isinstance(body, dict):
            raise ValueError('Expected object')
        body_hash = digest(body)
    except (ValueError, TypeError, UnicodeError):
        return JsonResponse({'error': 'Expected finite JSON object'}, status=400)
    receipt = {'received_request_hash': body_hash,
        'input_receipt': {'scope': 'received_body_only', 'request_hash': body_hash}}
    try:
        if 'program_plan' not in body or set(body) - {'program_plan', 'author_context'}:
            raise ValueError('Expected program_plan and optional author_context')
        if 'author_context' in body and not isinstance(body['author_context'], dict):
            raise ValueError('author_context must be an object')
        root = Path(settings.BASE_DIR) / 'tmp_mass_check' / 'program_floor_plans'
        result = generate(body['program_plan'], root)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
        return JsonResponse({'error': str(exc), **receipt}, status=400)
    except OSError as exc:
        return JsonResponse({'error': 'Plan artifact publication failed: ' + type(exc).__name__, **receipt}, status=503)
    return JsonResponse({**result, **receipt})
