"""HTTP input checks and delivery receipts, without domain-consumption claims."""
from copy import copy
from functools import wraps
from io import BytesIO
import hashlib
import json
import math

from django.http import JsonResponse
from shapely.geometry import mapping, shape
from backend.app.modules.design.generation.services.floor_plan_coordinates import prepare_footprint, restore_coordinates
from backend.app.modules.design.generation.services.floor_packer import grid_dimensions


def _validate(body):
    if body.get('algorithm', 'ga') not in ('ga', 'subdivision', 'mcts', 'packing', 'graph2plan'):
        raise ValueError('Unknown floor-plan algorithm')
    cell_size = body.get('cell_size', 3.0)
    if isinstance(cell_size, bool) or not isinstance(cell_size, (int, float)) or not math.isfinite(cell_size) or cell_size <= 0:
        raise ValueError('cell_size must be a positive finite number')
    footprint = shape(body.get('footprint_geojson') or {})
    if footprint.geom_type not in ('Polygon', 'MultiPolygon') or footprint.is_empty or not footprint.is_valid or footprint.area <= 0:
        raise ValueError('footprint_geojson must be a valid nonempty Polygon or MultiPolygon')
    if footprint.geom_type == 'MultiPolygon' and body.get('algorithm', 'ga') == 'graph2plan':
        raise ValueError('graph2plan requires one connected Polygon')
    footprint, descriptor = prepare_footprint(body, footprint)
    if body.get('algorithm', 'ga') != 'graph2plan':
        grid_dimensions(footprint, cell_size)
    return {**body, 'footprint_geojson': mapping(footprint)}, descriptor


def floor_plan_contract(view):
    """Bind the exact parsed body, including uninterpreted optional context.

    This proves delivery only. No Program allocation, mass-floor derivation,
    parking compatibility, or Law compliance is inferred from this receipt.
    """
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            body = json.loads(request.body)
            if not isinstance(body, dict):
                raise ValueError('Expected a JSON object')
            canonical = json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
        except (ValueError, TypeError, UnicodeError):
            return JsonResponse({'error': 'Expected a finite JSON object'}, status=400)
        request_hash = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
        receipt = {'received_request_hash': request_hash,
                   'input_receipt': {'scope': 'received_body_only', 'request_hash': request_hash}}
        try:
            working_body, descriptor = _validate(body)
        except (ValueError, TypeError, AttributeError, KeyError, OverflowError) as exc:
            return JsonResponse({'error': str(exc), **receipt}, status=400)
        working_request = copy(request)
        working_request._body = json.dumps(working_body).encode('utf-8')
        working_request._stream = BytesIO(working_request._body)
        response = view(working_request, *args, **kwargs)
        payload = json.loads(response.content)
        payload.update(receipt)
        if response.status_code == 200 and not payload.get('error'):
            restore_coordinates(payload, descriptor)
            # Geometry/fitness output is not an architectural acceptance gate.
            # No numerical tolerance or Program interpretation is inferred here.
            payload['design_acceptance'] = {
                'status': 'not_verified',
                'checks': {
                    'room_area_targets': 'not_verified',
                    'program_allocation': 'not_verified',
                    'egress': 'not_verified',
                    'core_coordination': 'not_verified',
                },
            }
        response.content = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        return response
    return wrapped
