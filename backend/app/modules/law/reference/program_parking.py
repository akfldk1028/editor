"""Source-qualified Program parking dispatch to the existing numerical owner.

Single-use scope only. Unknown area/use qualification may yield a clearly
conditional calculation, never a published legal minimum or permit verdict.
"""
from copy import deepcopy
from datetime import date
import math
import re


def _resolve(**kwargs):
    from backend.app.modules.design.generation.maas.parking.requirements import resolve_candidate_parking_requirement
    return resolve_candidate_parking_requirement(**kwargs)


def review_parking(handoff):
    assessment = (handoff.get('requirements') or {}).get('parking_assessment') or {}
    if not isinstance(assessment, dict):
        raise ValueError('requirements.parking_assessment must be an object')
    missing = []
    result = {'status': 'needs_evidence', 'required_spaces': None, 'missing_inputs': missing,
              'scope': 'single_use_facility_count_for_declared_sources_not_permit_approval',
              'permit_ready': False, 'input_evidence': deepcopy(assessment)}
    from backend.app.modules.law.reference.program_parking_scenario import evaluate
    scenario = evaluate(handoff, _resolve)
    if scenario is not None:
        result['planning_scenario'] = scenario
    pnu = (handoff.get('site') or {}).get('input')
    if not isinstance(pnu, str) or not re.fullmatch(r'\d{19}', pnu):
        missing.append('pnu')
    units = handoff.get('use_units') or []
    if not isinstance(units, list) or any(not isinstance(unit, dict) for unit in units):
        raise ValueError('use_units must contain objects')
    unit_id = assessment.get('use_unit_id')
    if (not isinstance(unit_id, str) or not unit_id.strip()
            or assessment.get('aggregation_scope') != 'single_use_facility' or len(units) != 1
            or units[0].get('use_unit_id') != assessment.get('use_unit_id')):
        missing.append('single_use_facility_aggregation')
    area = assessment.get('facility_area') or {}
    classification = assessment.get('classification') or {}
    if not isinstance(area, dict) or not isinstance(classification, dict):
        raise ValueError('parking facility_area and classification must be objects')
    amount = area.get('value')
    if (type(amount) not in (float, int) or not math.isfinite(amount) or amount < 0
            or area.get('unit') != 'm2' or area.get('basis') != 'parking_facility_area' or not area.get('source_ref')):
        missing.append('parking_facility_area')
    building_type = classification.get('canonical_use')
    if not isinstance(building_type, str) or not building_type.strip() or not classification.get('source_ref'):
        missing.append('source_bound_use_classification')
    if missing:
        return result
    calculation = _resolve(pnu=pnu, building_type=building_type, facility_area_m2=amount,
                           options={'building_use_code': classification.get('building_use_code')})
    result['scenario_calculation'] = calculation
    if area.get('qualification_status') != 'qualified':
        missing.append('parking_facility_area_qualification')
    if classification.get('status') != 'classified':
        missing.append('legal_use_classification')
    source = calculation.get('source') or {}
    try:
        effective = date.fromisoformat(source.get('effective_date', ''))
        if effective > date.fromisoformat(handoff['assessment_date']):
            missing.append('rule_effective_on_assessment_date')
    except (ValueError, TypeError):
        missing.append('rule_effective_on_assessment_date')
    if not source.get('source_sha256'):
        missing.append('rule_source_hash')
    count = calculation.get('required_spaces')
    if calculation.get('status') not in {'computed', 'calculated'} or type(count) is not int or count < 0:
        missing.append('supported_parking_rule_calculation')
    if not missing:
        result.update(status='calculated', required_spaces=calculation['required_spaces'],
                      calculation=deepcopy(calculation))
    return result
