"""Bind owner Program evidence to explicit first-basement reservations.

This adapter does not assign floors, derive statutory area, expand grouped rooms,
or claim that the remainder of a building programme has been designed.
"""
from copy import deepcopy
import math

from shapely.geometry import shape
from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.masterplan.geometry import digest, EPS


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def bind_program(context, *, pnu, design):
    """Return a prepared design or a source-bound needs_evidence refusal."""
    binding = {'schema_version': 'masterplan.program_binding.v1',
               'context_hash': digest(context), 'status': 'needs_evidence',
               'coverage': 'basement_reservations_only', 'consumed_space_ids': [],
               'unconsumed_space_ids': []}

    def refuse(code):
        return {'code': code, 'binding': {**binding, 'missing_evidence': [code]}}

    if (not isinstance(context, dict)
            or context.get('schema_version') != 'masterplan.program_input.v1'
            or context.get('pnu') != pnu or not _text(context.get('project'))
            or not _text(context.get('branch'))
            or type(context.get('source_revision')) is not int or context['source_revision'] < 1):
        return refuse('program_context_identity_mismatch')
    program = context.get('program')
    if (not isinstance(program, dict) or program.get('project_id') != context['project']
            or not _text(program.get('program_id')) or type(program.get('revision')) is not int
            or program['revision'] < 1 or not _text(program.get('input_hash'))):
        return refuse('program_context_identity_mismatch')
    if program.get('snapshot_hash') != digest({k: v for k, v in program.items() if k != 'snapshot_hash'}):
        return refuse('program_snapshot_mismatch')
    binding.update(project=context['project'], branch=context['branch'], pnu=pnu,
                   source_revision=context['source_revision'], program_id=program['program_id'],
                   program_revision=program['revision'], program_snapshot_hash=program['snapshot_hash'])
    requirements = program.get('requirements')
    allocation = requirements.get('masterplan_allocation') if isinstance(requirements, dict) else None
    if not isinstance(allocation, dict):
        return refuse('program_allocation_required')
    if (allocation.get('schema_version') != 'masterplan.basement_allocation.v1'
            or not _text(allocation.get('source_ref')) or not _text(allocation.get('building_id'))):
        return refuse('program_allocation_invalid')
    if type(allocation.get('level')) is not int or allocation['level'] != -1:
        return refuse('program_allocation_unsupported')
    selected = allocation.get('space_ids')
    if (not isinstance(selected, list) or not selected or not all(_text(s) for s in selected)
            or len(set(selected)) != len(selected)):
        return refuse('program_allocation_invalid')
    ledger_payload = program.get('area_ledger')
    if not isinstance(ledger_payload, dict):
        return refuse('program_ledger_invalid')
    spaces, entries = program.get('spaces'), ledger_payload.get('entries')
    if (not isinstance(spaces, list) or not isinstance(entries, list)
            or not all(isinstance(s, dict) and _text(s.get('space_id')) for s in spaces)
            or not all(isinstance(e, dict) and _text(e.get('source_space_id')) for e in entries)):
        return refuse('program_ledger_invalid')
    by_id = {s['space_id']: s for s in spaces}
    ledger = {e['source_space_id']: e for e in entries}
    if len(by_id) != len(spaces) or len(ledger) != len(entries):
        return refuse('program_ledger_invalid')
    binding['unconsumed_space_ids'] = sorted(e['source_space_id'] for e in entries if e.get('counted') is True)
    rooms, reservations = [], []
    for sid in selected:
        if sid not in by_id or sid not in ledger:
            return refuse('program_allocation_unknown_space')
        space, entry = by_id[sid], ledger[sid]
        if space.get('building_id') != allocation['building_id'] or entry.get('counted') is not True:
            return refuse('program_allocation_unsupported')
        if type(entry.get('quantity')) not in (int, float) or entry['quantity'] != 1:
            return refuse('program_quantity_unsupported')
        if entry.get('basis') != 'net':
            return refuse('program_area_basis_unsupported')
        if not _positive(entry.get('amount_m2')):
            return refuse('program_area_missing')
        area = entry['amount_m2']
        space_area = space.get('area')
        if (space.get('quantity') != 1 or not isinstance(space_area, dict)
                or space_area.get('basis') != 'net' or space_area.get('unit') != 'm2'
                or space_area.get('value') != area or entry.get('unit_area_m2') != area):
            return refuse('program_ledger_space_mismatch')
        # The existing geometry engine keys room coverage by name. Use unique
        # source IDs there, retain client labels and provenance in this binding.
        if not _text(space.get('functional_type')) or not _text(space.get('name')):
            return refuse('program_space_identity_missing')
        rooms.append({'name': sid, 'area_m2': area, 'kind': space['functional_type']})
        reservations.append({'space_id': sid, 'name': space['name'],
            'ledger_entry_id': entry.get('ledger_entry_id'), 'area_m2': area,
            'basis': 'net', 'level': -1, 'building_id': allocation['building_id'],
            'source_refs': deepcopy(space.get('source_refs', [])),
            'area_source': deepcopy(space_area.get('source'))})
    validation = program.get('validation')
    if not isinstance(validation, dict) or validation.get('valid') is not True:
        return refuse('program_validation_not_current')
    prepared = deepcopy(design)
    if 'basement_program' in prepared and prepared['basement_program'] != rooms:
        return refuse('program_design_conflict')
    provenance = prepared.setdefault('provenance', {})
    if not isinstance(provenance, dict) or 'program_binding' in provenance:
        return refuse('program_design_conflict')
    binding.update(status='prepared', allocation_source_ref=allocation['source_ref'],
                   reservations=reservations,
                   unconsumed_space_ids=sorted(set(binding['unconsumed_space_ids']) - set(selected)))
    prepared['basement_program'] = rooms
    provenance['program_binding'] = deepcopy(binding)
    return {'design': prepared, 'binding': binding}


def check_consumption(binding, features):
    """A bound area is consumed only when matching B1 metric polygons exist."""
    result = deepcopy(binding)
    missing, consumed = [], []
    features = features if isinstance(features, list) else []
    for reservation in binding.get('reservations', []):
        sid = reservation['space_id']
        matches = [f for f in features if isinstance(f, dict)
                   and isinstance(f.get('properties'), dict)
                   and f['properties'].get('layer') == 'basement_room'
                   and f['properties'].get('name') == sid]
        try:
            polygons = [shape(f['geometry']) for f in matches]
            valid = (len(matches) == 1 and matches[0]['properties'].get('level') == -1
                     and matches[0]['properties'].get('declared_area_m2') == reservation['area_m2']
                     and all(g.is_valid and not g.is_empty and g.geom_type == 'Polygon'
                             and not g.interiors for g in polygons)
                     and unary_union(polygons).area + EPS >= reservation['area_m2'])
        except (KeyError, TypeError, ValueError):
            valid = False
        (consumed if valid else missing).append(sid)
    result.update(status='consumed' if consumed and not missing else 'needs_evidence',
                  consumed_space_ids=consumed)
    if missing or not consumed:
        result['missing_evidence'] = ['program_reservations_not_realized']
        result['missing_space_ids'] = missing
    return result


__all__ = ['bind_program', 'check_consumption']
