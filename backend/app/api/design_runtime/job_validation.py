"""Validate executable design specifications before allocating a persisted job."""
import json
import math

from backend.app.modules.design.generation.services.constraint_bridge import ALL_ALGORITHMS


def integer(value, name, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'{name} must be an integer between {minimum} and {maximum}')


def number(value, name):
    try:
        finite = math.isfinite(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else False
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError(f'{name} must be a finite number')


def output_spec(value):
    if not isinstance(value, dict) or not isinstance(value.get('name'), str) or not value['name'].strip():
        raise ValueError('Each output/constraint requires a name')
    if value.get('type') == 'Objective':
        if value.get('Goal') not in {'Maximize', 'Minimize'}:
            raise ValueError('Objective Goal must be Maximize or Minimize')
    elif value.get('type') == 'Constraint':
        if value.get('Requirement') not in {'Less than', 'Greater than', 'Equals'}:
            raise ValueError('Invalid constraint Requirement')
        number(value.get('val'), 'constraint val')
    else:
        raise ValueError('Output type must be Objective or Constraint')


def validate_spec(spec, *, complete=False):
    if not isinstance(spec, dict):
        raise ValueError('job_spec must be an object')
    options = spec.get('options', {})
    if not isinstance(options, dict):
        raise ValueError('job_spec.options must be an object')
    if options.get('algorithm', 'additive') not in [*ALL_ALGORITHMS, 'all', 'maas_legal_envelope']:
        raise ValueError('Unsupported optimization algorithm')
    if 'building_type' in options and not isinstance(options['building_type'], str):
        raise ValueError('building_type must be a string')
    limits = {'Number of generations': (1, 500), 'num_islands': (1, 32), 'pop_per_island': (2, 500),
              'migration_interval': (1, 500), 'migrants_count': (1, 500), 'tournament_size': (2, 500)}
    for key, bounds in limits.items():
        if key in options:
            integer(options[key], key, *bounds)
    for key in ('initial_mutation_rate', 'final_mutation_rate'):
        if key in options:
            number(options[key], key)
            if not 0 <= options[key] <= 1:
                raise ValueError(f'{key} must be between zero and one')
    effort = options.get('Number of generations', 120) * options.get('num_islands', 7) * options.get('pop_per_island', 30)
    if options.get('algorithm') in {'all', 'maas_legal_envelope'}:
        effort *= len(ALL_ALGORITHMS)
    if effort > 2_000_000:
        raise ValueError('Optimization budget exceeds 2,000,000 evaluations')
    for key in ('inputs', 'outputs'):
        if key in spec or complete:
            if not isinstance(spec.get(key), list) or not 1 <= len(spec[key]) <= 256:
                raise ValueError(f'{key} must contain between 1 and 256 definitions')
    for value in spec.get('inputs', []):
        if not isinstance(value, dict) or value.get('type') not in {'Continuous', 'Categorical', 'Series', 'Sequence'}:
            raise ValueError('Invalid input definition')
        kind = value['type']
        if kind != 'Sequence':
            integer(value.get('Set length'), 'Set length', 1, 4096)
        if kind == 'Continuous':
            number(value.get('Min'), 'Min')
            number(value.get('Max'), 'Max')
            if value['Min'] > value['Max']:
                raise ValueError('Input Min cannot exceed Max')
        if kind in {'Categorical', 'Sequence'}:
            integer(value.get('Num options'), 'Num options', 1, 4096)
        if kind == 'Series':
            integer(value.get('Depth'), 'Depth', 1, 4096)
    for value in spec.get('outputs', []):
        output_spec(value)
    if 'outputs' in spec and not any(value['type'] == 'Objective' for value in spec['outputs']):
        raise ValueError('At least one objective is required')


def validate_request(body):
    if not isinstance(body, dict):
        raise ValueError('Request must be a JSON object')
    json.dumps(body, allow_nan=False)
    geometry = body.get('site_polygon')
    if not isinstance(geometry, dict) or geometry.get('type') not in {'Polygon', 'MultiPolygon'}:
        raise ValueError('site_polygon must be a Polygon or MultiPolygon geometry')
    if 'job_spec' in body and body['job_spec'] is not None:
        validate_spec(body['job_spec'])
    constraints = body.get('constraints', [])
    if not isinstance(constraints, list) or len(constraints) > 128:
        raise ValueError('constraints must be a list with at most 128 entries')
    for value in constraints:
        output_spec(value)
        if value['type'] != 'Constraint':
            raise ValueError('constraints may only contain Constraint definitions')
    for field, maximum in (('pnu', 19), ('address', 500)):
        if not isinstance(body.get(field, ''), str) or len(body.get(field, '')) > maximum:
            raise ValueError(f'{field} must be a string with at most {maximum} characters')
