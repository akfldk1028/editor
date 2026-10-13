"""Owner-issued generated placement states, separate from authored request geometry."""
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import uuid

from shapely.geometry import Polygon, mapping, shape
from shapely.ops import unary_union

TOL = 1e-6
PILOTI_IDS = {'existing', *(f'e{i}_{depth}' for i in range(4)
                           for depth in ('stall', 'row_aisle', 'module'))}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _root():
    root = Path(os.environ.get('EDITOR_PLACEMENT_SNAPSHOT_ROOT',
                str(Path(__file__).resolve().parents[6] / 'runtime/masterplan-placement')))
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _write(state):
    ident = _digest(state)
    target = _root() / (ident + '.json')
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf8', dir=target.parent,
                                     suffix='.tmp', delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(state, stream, ensure_ascii=False, allow_nan=False)
    try:
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return {'sha256': ident, 'run_id': state['run_id']}


def _read(ref):
    if (not isinstance(ref, dict) or set(ref) != {'sha256', 'run_id'}
            or not isinstance(ref['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', ref['sha256'])):
        raise ValueError('invalid placement snapshot reference')
    try:
        state = json.loads((_root() / (ref['sha256'] + '.json')).read_text(encoding='utf8'))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise ValueError('placement snapshot is unavailable') from exc
    if _digest(state) != ref['sha256'] or state['run_id'] != ref['run_id']:
        raise ValueError('placement snapshot identity mismatch')
    return state


def _union(features, layer):
    return unary_union([shape(f['geometry']) for f in features
                       if f.get('geometry') and f['properties'].get('layer') == layer
                       and f['properties'].get('level', 0) == 0])


def _choices(upper, rules):
    length, aisle = rules.get('stall_length_m'), rules.get('aisle_width_m')
    if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in (length, aisle)):
        return []
    rectangle = upper.minimum_rotated_rectangle
    coords = list(rectangle.exterior.coords)
    choices = []
    for index, (a, b) in enumerate(zip(coords, coords[1:])):
        dx, dy = b[0] - a[0], b[1] - a[1]
        edge = math.hypot(dx, dy)
        if edge <= TOL:
            continue
        nx, ny = dy / edge, -dx / edge
        if ((rectangle.centroid.x - (a[0] + b[0]) / 2) * nx
                + (rectangle.centroid.y - (a[1] + b[1]) / 2) * ny) > 0:
            nx, ny = -nx, -ny
        for family, depth in (('stall', length), ('row_aisle', length + aisle), ('module', 2 * length + aisle)):
            cut = Polygon([a, b, (b[0] - nx * depth, b[1] - ny * depth),
                           (a[0] - nx * depth, a[1] - ny * depth)])
            ground = upper.difference(cut)
            if ground.geom_type == 'Polygon' and ground.area > TOL and ground.is_valid:
                choices.append({'id': f'e{index}_{family}', 'depth_m': depth,
                                'edge': [list(a), list(b)], 'ground': mapping(ground)})
    return choices


def describe(state, ref):
    upper, ground = shape(state['upper']), shape(state['ground'])
    choices = _choices(upper, state['origin_request'].get('rules') or {}) if state['generated'] else []
    existing = next((c for c in choices if shape(c['ground']).symmetric_difference(ground).area <= TOL), None)
    return {'ref': ref, 'generated': state['generated'], 'upper': state['upper'], 'ground': state['ground'],
            'upper_area_m2': upper.area, 'ground_area_m2': ground.area,
            'covered_footprint_m2': upper.difference(ground).area,
            'existing_piloti': {k: existing[k] for k in ('id', 'depth_m', 'edge')} if existing else None,
            'requires_mass_acceptance': state['generated'],
            'piloti_choices': [{'id': 'existing', 'depth_m': None, 'ground_area_m2': ground.area},
                *[{k: v for k, v in c.items() if k != 'ground'} | {'ground_area_m2': shape(c['ground']).area}
                  for c in choices]],
            'scope': 'Owner geometry state; choices are not joint parking feasibility or structural approval.'}


def publish(request, result):
    upper = _union(result.get('features') or [], 'building_footprint')
    if upper.is_empty:
        return None
    ground = _union(result['features'], 'building_ground_footprint')
    if ground.is_empty:
        ground = upper
    previous = _read(request['placement_state']) if request.get('placement_state') else None
    origin = deepcopy(previous['origin_request'] if previous else request)
    origin.pop('placement_state', None)
    state = {'run_id': previous['run_id'] if previous else uuid.uuid4().hex,
             'origin_request': origin, 'request': deepcopy(request),
             'generated': not any(origin.get(k) for k in ('footprint', 'ground_footprint', 'core', 'columns')),
             'upper': mapping(upper), 'ground': mapping(ground),
             'effective_moves': previous.get('effective_moves', {}) if previous else {},
             'features': deepcopy(result['features'])}
    return describe(state, _write(state))


def resolve_request(request):
    resolved = deepcopy(request)
    ref = resolved.pop('placement_state', None)
    if ref is None:
        return resolved
    state = _read(ref)
    expected = deepcopy(state['request'])
    expected.pop('placement_state', None)
    if _digest(resolved) != _digest(expected):
        raise ValueError('placement parent source or options mismatch')
    resolved['footprint'] = deepcopy(state['upper'])
    resolved['ground_footprint'] = deepcopy(state['ground'])
    return resolved


def apply_revision(request, moves, parent_ref):
    from .placement_moves import MOVES, _piloti_ground, apply_placement_moves
    parent = _read(parent_ref)
    if _digest(request) != _digest(parent['origin_request']):
        raise ValueError('placement parent input mismatch')
    if not isinstance(moves, dict):
        raise ValueError('placement moves require an object')
    for key, value in moves.items():
        if key != 'pedestrian_width_m' and (key not in MOVES or not isinstance(value, str) or value not in MOVES[key]):
            raise ValueError('unsupported placement move: ' + key)
    if moves.get('piloti_choice', 'keep') != 'keep' and moves.get('piloti') != 'piloti':
        raise ValueError('piloti choice requires an explicit piloti move')
    changing_mass = any(moves.get(k, 'keep') != 'keep' for k in ('building_side', 'building_proportion'))
    changing_piloti = moves.get('piloti') == 'piloti'
    if changing_mass and moves.get('piloti_choice', 'keep') != 'keep':
        raise ValueError('parent face/depth choice cannot be applied to a replacement building; revise its issued state next')
    if (changing_mass or changing_piloti) and not parent['generated']:
        raise ValueError('placement moves cannot modify authored footprint, ground footprint, core or columns')
    effective = {**parent.get('effective_moves', {}), **{k: v for k, v in moves.items() if v != 'keep'}}
    if changing_mass:
        effective.pop('piloti_choice', None)
    engine_moves = {k: v for k, v in effective.items() if k != 'piloti_choice'
                    and (changing_mass or k not in {'building_side', 'building_proportion', 'piloti'})}
    applied = apply_placement_moves(request, engine_moves)
    upper = shape(applied['request']['footprint']) if changing_mass else shape(parent['upper'])
    ground = shape(applied['request'].get('ground_footprint') or applied['request']['footprint']) if changing_mass else shape(parent['ground'])
    if changing_piloti:
        choice_id = moves.get('piloti_choice')
        if choice_id in (None, 'keep'):
            choice_id = 'existing' if not changing_mass and upper.difference(ground).area > TOL else None
        if choice_id == 'existing':
            if changing_mass:
                raise ValueError('existing piloti cannot be mapped to a replacement building')
        elif choice_id:
            choice = next((c for c in _choices(upper, request.get('rules') or {}) if c['id'] == choice_id), None)
            if choice is None:
                raise ValueError('piloti choice is unavailable on this parent')
            ground = shape(choice['ground'])
        else:
            rules = request['rules']
            ground = _piloti_ground(shape(request['site']), upper, 2 * rules['stall_length_m'] + rules['aisle_width_m'])
            if ground is None:
                raise ValueError('no piloti ground on the fixed parent building')
        applied['unresolved'].append('preliminary piloti: structural support and clear height require Mass review')
    if (request.get('building_entrance') is not None
            and (not upper.equals(shape(parent['upper'])) or not ground.equals(shape(parent['ground'])))):
        raise ValueError('building entrance needs a new source-bound declaration after mass or piloti changes; no door transform is authorized')
    logical_request = applied['request']
    for key in ('footprint', 'ground_footprint'):
        if key in request:
            logical_request[key] = deepcopy(request[key])
        else:
            logical_request.pop(key, None)
    state = {'run_id': parent['run_id'], 'origin_request': deepcopy(request),
             'request': deepcopy(logical_request), 'generated': parent['generated'],
             'upper': mapping(upper), 'ground': mapping(ground), 'effective_moves': effective,
             'parent_ref': parent_ref, 'features': deepcopy(parent['features'])}
    ref = _write(state)
    logical_request['placement_state'] = ref
    before_request = deepcopy(parent['request'])
    before_request.pop('placement_state', None)
    comparable = deepcopy(logical_request)
    comparable.pop('placement_state', None)
    applied.update(applied={k: v for k, v in moves.items() if v != 'keep'},
                   noop=(_digest(comparable) == _digest(before_request)
                         and upper.equals(shape(parent['upper'])) and ground.equals(shape(parent['ground']))),
                   realized_state=describe(state, ref))
    return applied


def preservation_checks(request, result):
    if not request.get('placement_state'):
        return []
    state = _read(request['placement_state'])
    features = result.get('features') or []
    checks = []
    for key, layer in (('upper', 'building_footprint'), ('ground', 'building_ground_footprint')):
        expected = shape(state[key])
        drawn = _union(features, layer)
        if key == 'ground' and drawn.is_empty:
            drawn = _union(features, 'building_footprint')
        delta = drawn.symmetric_difference(expected).area
        checks.append({'id': f'placement_{key}_preserved', 'status': 'passed' if delta <= TOL else 'failed',
                       'measured': delta, 'required': f'<= {TOL} m2 symmetric difference',
                       'parent_ref': state.get('parent_ref'), 'feature_ids': [layer]})
    return checks


def change_report(request, result):
    if not request.get('placement_state'):
        return None
    state = _read(request['placement_state'])
    parent = _read(state['parent_ref']) if state.get('parent_ref') else state
    features = result.get('features') or []
    changes = {}
    for layer in ('building_footprint', 'building_ground_footprint', 'ramp', 'parking_aisle', 'vehicular_access', 'parking_stall'):
        before = [f for f in parent['features'] if f['properties'].get('layer') == layer]
        after = [f for f in features if f['properties'].get('layer') == layer]
        geometry = lambda items: [{'geometry': f.get('geometry'), 'level': f['properties'].get('level', 0)} for f in items]
        changes[layer] = {'changed': _digest(geometry(before)) != _digest(geometry(after)),
                          'feature_content_changed': _digest(before) != _digest(after),
                          'before_features': len(before), 'after_features': len(after)}
    old, new = shape(parent['upper']), _union(features, 'building_footprint')
    return {'parent_ref': state.get('parent_ref'), 'upper_centroid_displacement_m': None if new.is_empty else old.centroid.distance(new.centroid),
            'upper_symmetric_difference_m2': old.symmetric_difference(new).area,
            'layers': changes, 'scope': 'Upper/ground preservation is checked; parking and ramp may be regenerated.'}


def retain_generated_review(request, result):
    if not request.get('placement_state') or not _read(request['placement_state'])['generated']:
        return
    validation = result.setdefault('validation', {})
    reviews = validation.setdefault('pending_reviews', [])
    if 'generated_mass_acceptance' not in reviews:
        reviews.append('generated_mass_acceptance')
    note = 'generated building zone awaits downstream Mass development and architect acceptance'
    if note not in result.setdefault('blocking', []):
        result['blocking'].append(note)
    if result.get('status') == 'resolved':
        result['status'] = 'needs_evidence'
    if 'handoff' in result:
        result['handoff'].update(hard_pass=False)
        if result.get('status') != 'needs_revision':
            result['handoff']['status'] = 'needs_evidence'
