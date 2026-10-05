"""Explicit gross-area hypotheses, isolated from statutory parking conclusions."""
from copy import deepcopy
from datetime import date
from decimal import Decimal
import math
import re

ASSUMPTION = 'gross_reservations_equal_parking_facility_area_for_scenario_only'


def _number(value):
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and value > 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError('planning scenario area must be a finite positive number')
    return Decimal(str(value))


def evaluate(handoff, resolve):
    proposal = handoff.get('requirements', {}).get('parking_planning_scenario')
    if proposal is None:
        return None
    if not isinstance(proposal, dict) or proposal.get('assumption') != ASSUMPTION:
        raise ValueError('explicit gross-area planning hypothesis required')
    pnu = handoff.get('site', {}).get('input')
    units = handoff.get('use_units', [])
    refs = proposal.get('space_refs')
    if (not isinstance(pnu, str) or not re.fullmatch(r'\d{19}', pnu)
            or not isinstance(units, list) or len(units) != 1 or not isinstance(units[0], dict)
            or not isinstance(refs, list) or not refs or any(not isinstance(r, str) or not r for r in refs)
            or len(refs) != len(set(refs))
            or proposal.get('aggregation_scope') != 'single_use_facility'
            or not proposal.get('use_unit_id') or proposal['use_unit_id'] != units[0].get('use_unit_id')
            or set(refs) != set(units[0].get('space_refs', []))):
        raise ValueError('planning scenario requires exact single-use space coverage and PNU')
    spaces = handoff.get('spaces', [])
    if (not isinstance(spaces, list) or any(not isinstance(s, dict) for s in spaces)
            or len(spaces) != len(refs) or {s.get('space_id') for s in spaces} != set(refs)):
        raise ValueError('single-use scenario must cover every Program space exactly once')
    area, classification = proposal.get('area'), proposal.get('classification')
    if (not isinstance(area, dict) or area.get('unit') != 'm2' or area.get('basis') != 'gross'
            or not area.get('source_ref') or not isinstance(classification, dict)
            or classification.get('status') != 'proposed' or not classification.get('source_ref')
            or not isinstance(classification.get('canonical_use'), str) or not classification['canonical_use'].strip()):
        raise ValueError('source-bound proposed classification and gross-area evidence required')
    amount = _number(area.get('value'))
    total = Decimal(0)
    for space in spaces:
        original = space.get('area', {})
        if not isinstance(original, dict) or original.get('basis') != 'gross' or original.get('unit') != 'm2':
            raise ValueError('all scenario spaces require explicit gross-area records')
        quantity = space.get('quantity', 1)
        if type(quantity) is not int or quantity < 1:
            raise ValueError('space quantity must be a positive integer')
        total += _number(original.get('value')) * quantity
    if abs(amount - total) > Decimal('0.000001'):
        raise ValueError('scenario area differs from exact Program gross reservations')
    calculation = resolve(pnu=pnu, building_type=classification['canonical_use'], facility_area_m2=float(amount),
                          options={'building_use_code': classification.get('building_use_code')})
    source = calculation.get('source') or {}
    try:
        current = date.fromisoformat(source.get('effective_date', '')) <= date.fromisoformat(handoff['assessment_date'])
    except (ValueError, TypeError, KeyError):
        current = False
    count = calculation.get('required_spaces')
    usable = (calculation.get('status') in {'computed', 'calculated'} and type(count) is int and count >= 0
              and current and bool(source.get('source_sha256')))
    return {'schema_version':'program-parking-scenario/1', 'status':'conditional' if usable else 'needs_evidence',
        'proposed_spaces':count if usable else None, 'legal_minimum':None, 'client_approved':False,
        'permit_ready':False, 'input_evidence':deepcopy(proposal), 'calculation':calculation,
        'measurement_request':{'schema_version':'parking-measurement-request/1',
            'program_identity':{key:deepcopy(handoff.get(key)) for key in ('project_id','program_id','program_revision','input_hash')},
            'use_unit_id':proposal['use_unit_id'], 'space_refs':deepcopy(refs),
            'required_facts':['confirmed_operator_and_statutory_use', 'independent_vs_accessory_uses',
                'whole_site_facility_aggregation', 'floor_area_measurement_definition_and_geometry',
                'common_floor_area_included_m2', 'parking_facility_floor_area_excluded_m2',
                'unmeasured_basement_and_other_buildings'],
            'target_basis':'parking_facility_area', 'unit':'m2',
            'qualification_status':'needs_evidence', 'planning_gross_is_not_measurement':True}}
