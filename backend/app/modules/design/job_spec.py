"""Validated, immutable-input preparation for native mass-search specifications.

Creation does not execute a search or establish municipal/legal permission.
"""
from copy import deepcopy
import json
import math
import re

from shapely.geometry import shape

from backend.app.modules.land.projection import wgs84_to_utm
from .job_defaults import ALL_ALGORITHMS, FLOOR_HEIGHTS, build_default_job_spec


class JobSpecError(ValueError):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)


def _fail(code, message):
    raise JobSpecError(code, message)


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _fields(value, allowed, context):
    if not isinstance(value, dict) or set(value) - set(allowed):
        _fail('unsupported_fields', f'Unsupported {context} fields')


def _site(geometry):
    _fields(geometry, ('type', 'coordinates'), 'site geometry')
    if geometry.get('type') != 'Polygon':
        _fail('unsupported_geometry', 'Only WGS84 Polygon sites are supported')
    rings = geometry.get('coordinates')
    if not isinstance(rings, list) or not 1 <= len(rings) <= 100:
        _fail('invalid_geometry', 'Polygon needs an exterior ring and bounded holes')
    if any(not isinstance(ring, list) for ring in rings) or sum(map(len, rings)) > 10000:
        _fail('geometry_budget_exceeded', 'Site exceeds 10000 coordinates')
    for ring in rings:
        if len(ring) < 4 or ring[0] != ring[-1]:
            _fail('invalid_geometry', 'Polygon rings must be closed with at least four coordinates')
        for point in ring:
            if (not isinstance(point, (list, tuple)) or len(point) != 2
                    or not all(_number(v) for v in point)
                    or not -180 <= point[0] <= 180 or not -90 <= point[1] <= 90):
                _fail('invalid_geometry', 'Site coordinates must be finite longitude and latitude pairs')
    polygon = shape(geometry)
    if not polygon.is_valid or polygon.is_empty:
        _fail('invalid_geometry', 'Site polygon is invalid')
    projected = wgs84_to_utm(polygon)
    if (not projected.is_valid or not math.isfinite(projected.area)
            or not all(math.isfinite(v) for v in projected.bounds)):
        _fail('invalid_geometry', 'Site projection is invalid')
    if not 10 <= projected.area <= 100000:
        _fail('site_area_out_of_range', 'Site area must be between 10 and 100000 square metres')
    x0, y0, x1, y1 = projected.bounds
    if min(x1-x0, y1-y0) < 3:
        _fail('site_too_narrow', 'Projected site width and depth must each be at least 3 metres')
    return round(projected.area, 2)


_METRICS = {'floor_area', 'daylight_score', 'bcr', 'far', 'height', 'setback',
            'building_line_setback', 'landscaping_pct', 'compactness', 'stepback_factor'}


def _outputs(records, *, constraints_only=False):
    if not isinstance(records, list) or len(records) > 40:
        _fail('invalid_outputs', 'Outputs must be a list of at most 40 definitions')
    identities, identifiers = set(), set()
    for item in records:
        _fields(item, ('id', 'name', 'type', 'Goal', 'Requirement', 'val', 'unit', 'label'), 'output')
        if not isinstance(item.get('name'), str) or item['name'] not in _METRICS or item.get('type') not in ('Objective', 'Constraint'):
            _fail('invalid_outputs', 'Output metric or type is unsupported')
        identity = (item['name'], item['type'])
        if identity in identities:
            _fail('duplicate_output', 'Output metric and role must be unique')
        identities.add(identity)
        if 'id' in item:
            if not isinstance(item['id'], str) or not item['id'] or len(item['id']) > 100 or item['id'] in identifiers:
                _fail('duplicate_output', 'Output IDs must be nonempty and unique')
            identifiers.add(item['id'])
        for key in ('unit', 'label'):
            if key in item and (not isinstance(item[key], str) or len(item[key]) > 500):
                _fail('invalid_outputs', 'Output labels must be bounded strings')
        if item['type'] == 'Objective':
            if constraints_only or item.get('Goal') not in ('Maximize', 'Minimize') or any(k in item for k in ('Requirement', 'val')):
                _fail('invalid_outputs', 'Objective requires a supported goal')
        elif (item.get('Requirement') not in ('Less than', 'Greater than', 'Equals')
              or not _number(item.get('val')) or abs(item['val']) > 1e9 or 'Goal' in item):
            _fail('invalid_outputs', 'Constraint requires a finite target and supported requirement')


_INTEGER_OPTIONS = {
    'Number of generations': (1, 1000), 'num_islands': (1, 20),
    'pop_per_island': (4, 200), 'migration_interval': (1, 1000),
    'migrants_count': (0, 200), 'tournament_size': (2, 200),
}
_ENUM_OPTIONS = {
    'algorithm': ALL_ALGORITHMS, 'building_type': tuple(FLOOR_HEIGHTS),
    'penalty_mode': ('normalized', 'binary'), 'island_mode': ('homogeneous', 'heterogeneous'),
}


def _options(options):
    _fields(options, (*_INTEGER_OPTIONS, *_ENUM_OPTIONS, 'initial_mutation_rate',
                      'final_mutation_rate', 'island_strategies'), 'options')
    for name, (low, high) in _INTEGER_OPTIONS.items():
        if name in options and (type(options[name]) is not int or not low <= options[name] <= high):
            _fail('invalid_options', f'{name} must be an integer between {low} and {high}')
    for name, choices in _ENUM_OPTIONS.items():
        if name in options and options[name] not in choices:
            _fail('unsupported_algorithm' if name == 'algorithm' else 'invalid_options', f'Unsupported {name}')
    for name in ('initial_mutation_rate', 'final_mutation_rate'):
        if name in options and (not _number(options[name]) or not 0 <= options[name] <= 1):
            _fail('invalid_options', f'{name} must be between zero and one')
    islands, population = options.get('num_islands', 7), options.get('pop_per_island', 30)
    if islands * population > 2000 or islands * (population + options.get('Number of generations', 50)) > 20000:
        _fail('work_budget_exceeded', 'Search population or evaluation budget is too large')
    if options.get('migrants_count', 3) > population or options.get('tournament_size', 8) > population:
        _fail('invalid_options', 'Migration and tournament sizes must fit each island population')
    strategies = options.get('island_strategies')
    if strategies is not None and (not isinstance(strategies, list) or len(strategies) != islands or any(s not in ('blx', 'de') for s in strategies)):
        _fail('invalid_options', 'Island strategies must identify BLX or DE for every island')


def _inputs(inputs, expected):
    if not isinstance(inputs, list) or len(inputs) != len(expected):
        _fail('invalid_inputs', 'Inputs must match the selected algorithm gene layout')
    identifiers = set()
    for item, reference in zip(inputs, expected):
        _fields(item, ('id', 'name', 'type', 'Min', 'Max', 'Set length'), 'gene')
        if item.get('name') != reference['name'] or item.get('type') != 'Continuous' or type(item.get('Set length')) is not int or item['Set length'] != 1:
            _fail('invalid_inputs', 'Gene names, order and scalar continuous types must match the algorithm')
        if any(not _number(item.get(k)) or abs(item[k]) > 1e6 for k in ('Min', 'Max')) or item['Min'] > item['Max']:
            _fail('invalid_gene_range', 'Gene range must be finite, ordered and within one million')
        if 'id' in item:
            identifier = item['id']
            if not isinstance(identifier, str) or not identifier or len(identifier) > 100 or identifier in identifiers:
                _fail('invalid_inputs', 'Gene IDs must be nonempty and unique')
            identifiers.add(identifier)


def prepare_job(payload: dict) -> dict:
    _fields(payload, ('site_polygon', 'pnu', 'address', 'constraints', 'job_spec'), 'job')
    try:
        encoded = json.dumps(payload, allow_nan=False)
    except (ValueError, TypeError, OverflowError):
        _fail('invalid_json', 'Job must contain finite JSON values')
    if len(encoded.encode()) > 2*1024*1024:
        _fail('payload_budget_exceeded', 'Job exceeds two MiB')
    payload = deepcopy(payload)
    area = _site(payload.get('site_polygon'))
    pnu, address = payload.get('pnu', ''), payload.get('address', '')
    if not isinstance(pnu, str) or (pnu and not re.fullmatch(r'[0-9]{19}', pnu)):
        _fail('invalid_pnu', 'PNU must be empty or 19 digits')
    if not isinstance(address, str) or len(address) > 1000:
        _fail('invalid_address', 'Address must be a bounded string')
    constraints = payload.get('constraints', [])
    _outputs(constraints, constraints_only=True)
    spec = payload.get('job_spec', {})
    _fields(spec, ('inputs', 'outputs', 'options'), 'specification')
    options = spec.get('options', {})
    _options(options)
    algorithm, building_type = options.get('algorithm', 'additive'), options.get('building_type', '공동주택')
    defaults = deepcopy(build_default_job_spec(area, constraints, building_type, algorithm))
    if 'inputs' not in spec:
        if 'outputs' in spec:
            _fail('incomplete_specification', 'Custom outputs require a complete input specification')
        spec = defaults
        spec['options'].update(options)
    else:
        _outputs(spec.get('outputs'))
        identities = {(item['name'], item['type']):item for item in spec['outputs']}
        for constraint in constraints:
            identity = (constraint['name'], constraint['type'])
            if identity in identities:
                current = identities[identity]
                if any(current.get(k) != constraint.get(k) for k in ('Requirement', 'val')):
                    _fail('constraint_conflict', 'Requested constraint conflicts with the supplied specification')
            else:
                spec['outputs'].append(constraint)
    _inputs(spec['inputs'], defaults['inputs'])
    _outputs(spec['outputs'])
    if not any(item['type'] == 'Objective' for item in spec['outputs']):
        _fail('missing_objective', 'At least one measured objective is required')
    _options(spec.get('options', {}))
    effective = spec.get('options', {})
    return {'site_polygon':payload['site_polygon'], 'pnu':pnu, 'address':address,
            'constraints':constraints, 'job_spec':spec, 'site_area_m2':area,
            'max_generations':effective.get('Number of generations', 50),
            'population_size':effective.get('num_islands', 7)*effective.get('pop_per_island', 30),
            'algorithm':algorithm, 'building_type':building_type}
