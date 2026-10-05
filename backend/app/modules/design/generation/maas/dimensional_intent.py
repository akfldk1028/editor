"""Opt-in authored dimensional proposals; never project programme authority."""
from copy import deepcopy
from math import isfinite

KEY = 'dimensional_intent'
SCHEMA = 'arr.maas.dimensional_intent.v1'
POLICY = 'preserve_physical_dimensions'


def intent_schema():
    properties = {
        'schema_version': {'enum': [SCHEMA]},
        'storey_count': {'type': 'integer', 'minimum': 1},
        'storey_height_m': {'type': 'number', 'exclusiveMinimum': 0},
        'target_gfa_m2': {'type': 'number', 'exclusiveMinimum': 0},
        'delivery_policy': {'enum': [POLICY]},
        'programme_status': {'enum': ['unknown']},
    }
    return {'type': 'object', 'additionalProperties': False,
            'required': list(properties), 'properties': properties}


def validate_intent(value):
    if not isinstance(value, dict) or set(value) != set(intent_schema()['properties']):
        raise ValueError('dimensional_intent requires exactly the supported dimensional proposal fields')
    for key, expected in [('schema_version', SCHEMA), ('delivery_policy', POLICY), ('programme_status', 'unknown')]:
        if value[key] != expected:
            raise ValueError(f'unsupported dimensional_intent {key}: {value[key]}')
    count = value['storey_count']
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError('dimensional_intent storey_count must be a positive integer')
    for key in ('storey_height_m', 'target_gfa_m2'):
        number = value[key]
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not isfinite(number) or number <= 0:
            raise ValueError(f'dimensional_intent {key} must be positive finite')
    try:
        finite_height = isfinite(count * value['storey_height_m'])
    except OverflowError:
        finite_height = False
    if not finite_height:
        raise ValueError('dimensional_intent total height must be finite')
    return deepcopy(value)


def program_intent(program):
    metadata = program.get('metadata', {}) if isinstance(program, dict) else program.metadata
    return validate_intent(metadata[KEY]) if metadata.get(KEY) is not None else None
