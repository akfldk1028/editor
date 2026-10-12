"""JSON transport for existing pure MasterPlan engine operations."""
import hashlib
import json


SCHEMA = 'arr.masterplan.operations.v1'
OPERATIONS = {
    'apply_placement_moves': ({'request', 'moves'}, {'parent_ref'}),
    'bind_delivered_mass': ({'request', 'source_handle'}, set()),
    'bind_delivered_request': ({'request', 'source_handle'}, set()),
    'plan_site': ({'request'}, set()),
    'propose_core_repairs': ({'request', 'result'}, {'limit'}),
    'repack_core': ({'request', 'result'}, set()),
    'review_placement': ({'request', 'result'}, set()),
    'validate_plan': ({'request', 'result'}, set()),
    'evaluate_siting_relations': ({'brief', 'owner_artifacts'}, set()),
    'footprint_inside': ({'parcel', 'target'}, {'direction', 'align_to', 'module_depth_m'}),
    'bind_program': ({'context', 'pnu', 'design'}, set()),
    'check_consumption': ({'binding', 'features'}, set()),
    'frontage_shapes_from_registration': ({'registration'}, set()),
    'ramp_overhead': ({'ramp', 'occupied', 'soffit_z_m', 'required_height_m'}, set()),
}


def _engine_provenance(module):
    """Which engine answered: the module path and the bytes of it and its geometry dependency."""
    from pathlib import Path
    source = Path(module.__file__)
    return {'callable': module.__name__ + '.overhead_clearance',
            'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'geometry_dependency_sha256': hashlib.sha256(source.with_name('geometry.py').read_bytes()).hexdigest()}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def dispatch(operation, arguments):
    if operation not in OPERATIONS:
        raise ValueError('unsupported MasterPlan operation')
    required, optional = OPERATIONS[operation]
    if not isinstance(arguments, dict) or not required <= arguments.keys() or arguments.keys() - required - optional:
        raise ValueError('operation arguments do not match the owner interface')
    if operation == 'apply_placement_moves':
        from backend.app.modules.design.generation.maas.masterplan.placement_moves import apply_placement_moves
        return apply_placement_moves(**arguments)
    if operation == 'bind_delivered_request':
        from backend.app.modules.design.generation.maas.masterplan.delivered_source import bind_delivered_request
        return bind_delivered_request(**arguments)
    if operation == 'bind_delivered_mass':
        from backend.app.modules.design.generation.maas.masterplan.delivered_source import bind_delivered_mass
        return bind_delivered_mass(**arguments)
    if operation == 'plan_site':
        from backend.app.modules.design.generation.maas.masterplan.planner import plan_site
        from backend.app.modules.design.generation.maas.masterplan.placement_state import resolve_request, publish, preservation_checks, change_report, retain_generated_review
        logical_request = arguments['request']
        result = plan_site(resolve_request(logical_request))
        checks = preservation_checks(logical_request, result)
        if any(c['status'] == 'failed' for c in checks):
            result['status'] = 'needs_revision'
            result.setdefault('validation', {})['geometry_status'] = 'failed'
        result.setdefault('validation', {}).setdefault('checks', []).extend(checks)
        result['placement_delta'] = change_report(logical_request, result)
        retain_generated_review(logical_request, result)
        from backend.app.modules.design.generation.maas.masterplan.feedback import build_mass_feedback
        result['mass_feedback'] = build_mass_feedback(logical_request, result)
        if logical_request.get('placement_state') and not any(logical_request.get(k) for k in ('footprint', 'ground_footprint', 'core', 'columns')):
            for feature in result.get('features') or []:
                if feature['properties'].get('layer') == 'building_ground_footprint':
                    feature['properties']['source'] = 'owner generated parent occupancy'
        result['placement_snapshot'] = publish(logical_request, result)
        if 'handoff' in result:
            result['handoff'].update(input_hash=digest(logical_request),
                                     geometry_hash=digest(result.get('features') or []),
                                     metric_geometry_hash=digest(result.get('features') or []))
        return result
    if operation == 'propose_core_repairs':
        from backend.app.modules.design.generation.maas.masterplan.core_repair import propose_core_repairs
        return propose_core_repairs(**arguments)
    if operation == 'repack_core':
        from backend.app.modules.design.generation.maas.masterplan.core_repacking import repack_core
        return repack_core(**arguments)
    if operation == 'review_placement':
        from backend.app.modules.design.generation.maas.masterplan.placement_quality import review_placement
        return review_placement(**arguments)
    if operation == 'evaluate_siting_relations':
        from backend.app.modules.design.generation.maas.masterplan.siting_relations import evaluate_relations
        return {'brief_id': arguments['brief'].get('brief_id'), 'relations': evaluate_relations(**arguments),
                'scope': 'Bound polygon relationships; caller retains owner provenance, doors are not inferred'}
    if operation == 'validate_plan':
        from backend.app.modules.design.generation.maas.masterplan.validation import validate_plan
        from backend.app.modules.design.generation.maas.masterplan.placement_state import resolve_request, preservation_checks, retain_generated_review
        logical_request, result = arguments['request'], arguments['result']
        checked = validate_plan(resolve_request(logical_request), result)
        checks = preservation_checks(logical_request, result)
        checked.setdefault('checks', []).extend(checks)
        if any(c['status'] == 'failed' for c in checks):
            checked['geometry_status'] = 'failed'
        retain_generated_review(logical_request, {'validation': checked})
        return checked
    if operation == 'bind_program':
        from backend.app.modules.design.generation.maas.masterplan.program_source import bind_program
        return bind_program(arguments['context'], pnu=arguments['pnu'], design=arguments['design'])
    if operation == 'check_consumption':
        from backend.app.modules.design.generation.maas.masterplan.program_source import check_consumption
        return check_consumption(arguments['binding'], arguments['features'])
    from shapely.geometry import mapping, shape
    if operation == 'ramp_overhead':
        from shapely.geometry import LineString
        from backend.app.modules.design.generation.maas.masterplan import ramp_overhead
        ramp = arguments['ramp']
        if not isinstance(ramp, dict) or not isinstance(ramp.get('centerline'), list):
            raise ValueError('ramp requires width_m and an XYZ centerline coordinate list')
        result = ramp_overhead.overhead_clearance(
            {'width_m': ramp.get('width_m'), 'centerline': LineString(ramp['centerline'])},
            shape(arguments['occupied']), arguments['soffit_z_m'], arguments['required_height_m'])
        return {**result, 'engine': _engine_provenance(ramp_overhead)}
    if operation == 'footprint_inside':
        from backend.app.modules.design.generation.maas.masterplan.geometry import footprint_inside
        result = footprint_inside(shape(arguments['parcel']), arguments['target'],
            direction=arguments.get('direction'),
            align_to=shape(arguments['align_to']) if arguments.get('align_to') is not None else None,
            module_depth_m=arguments.get('module_depth_m'))
        return mapping(result)
    from backend.app.modules.design.generation.maas.massv2.parcel_policy import frontage_shapes_from_registration
    return [mapping(geometry) for geometry in frontage_shapes_from_registration(arguments['registration'])]


def invoke(request):
    if not isinstance(request, dict) or set(request) != {'operation', 'arguments'}:
        raise ValueError('request requires operation and arguments')
    envelope = {'schema_version': SCHEMA, 'operation': request['operation'], 'request_hash': digest(request)}
    try:
        result = dispatch(request['operation'], request['arguments'])
        return {**envelope, 'status': 'succeeded', 'result': result, 'result_hash': digest(result)}
    except (ValueError, TypeError, KeyError, IndexError, ZeroDivisionError) as exc:
        return {**envelope, 'status': 'failed', 'code': 'owner_operation_refused',
                'error_type': type(exc).__name__, 'reason': str(exc)}


__all__ = ['SCHEMA', 'OPERATIONS', 'invoke']
