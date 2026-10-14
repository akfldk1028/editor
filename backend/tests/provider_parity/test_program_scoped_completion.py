"""Owner completion distinguishes finite comparisons from legal clearance."""
from copy import deepcopy
import hashlib

import pytest

from backend.app.modules.law.reference.program_review import fingerprint, review_program
from backend.app.modules.law.reference.facility_area_rules import FACILITY_AREA_RULES


def seal(value):
    value['request_hash'] = fingerprint({k: v for k, v in value.items() if k != 'request_hash'})
    return value


def constraint_handoff():
    excerpt = 'Synthetic comparison fixture; not an actual legal requirement.'
    source = {'url': 'https://example.org/fixture', 'article': 'fixture', 'excerpt': excerpt,
              'excerpt_sha256': hashlib.sha256(excerpt.encode()).hexdigest(),
              'effective_from': '2026-01-01', 'edition_checked_on': '2026-10-13'}
    return seal({'contract_version': 'program-law/2', 'project_id': 'fixture', 'program_id': 'main',
                 'program_revision': 1, 'content_revision': 1, 'input_hash': 'fixture',
                 'input_versions': {}, 'assessment_date': '2026-10-13',
                 'requested_checks': ['supplied_constraints'], 'requirements': {
                     'legal_constraints': [{'rule_id': 'fixture', 'scope': 'program',
                         'input_nodes': ['program'], 'source': source, 'applies_when': [],
                         'requirements': [{'fact': 'fixture_count', 'operator': 'gte', 'value': 2}]}],
                     'legal_facts': [{'fact_id': 'fixture_count', 'value': 2,
                         'input_node': 'program', 'input_version': 1, 'source_ref': 'fixture-source'}]}})


def facility_handoff():
    value = constraint_handoff()
    rule = next(r for r in FACILITY_AREA_RULES if r['rule_id'] == 'kr.medical.single_room')
    value['assessment_date'] = rule['source']['verified_as_of']
    value['requested_checks'] = ['facility_area']
    value['requirements'] = {'facility_facts': [{'fact_id': 'room',
        'facility_type': rule['facility_types'][0], 'conditions': deepcopy(rule['required_conditions']),
        'condition_evidence': {k: {'source_ref': 'project-transition-review'} for k in rule['required_conditions']},
        'quantities': {rule['quantity_fact']: 1},
        'areas': {rule['area_fact']: {'value': rule['fixed_minimum_m2'], 'unit': 'm2',
                  'basis': rule['area_basis'], 'source_ref': 'room-measurement'}}}]}
    return seal(value)


def test_supplied_constraints_complete_only_the_explicit_comparison_scope():
    result = review_program(constraint_handoff())
    assert result['status'] == 'reviewed'
    assert result['completion']['completed_checks'] == ['supplied_constraints']
    assert result['completion']['status'] == 'reviewed_scope_only'
    assert result['completion']['legal_interpretation_verified'] is False
    assert result['completion']['full_permit_review'] is False
    assert result['permit_ready'] is False
    raw = next(c['result'] for c in result['checks'] if c['check'] == 'program_constraints')
    assert raw['status'] == 'needs_evidence'
    assert raw['checks'][0]['source_verified'] is False


@pytest.mark.parametrize('requested', [[], ['fire_egress'], ['supplied_constraints', 'unknown_scope'],
    ['legal_use_classification', 'principal_accessory', 'aggregation_scope', 'zoning_use_permission',
     'statutory_area_basis', 'parking', 'fire_egress', 'accessibility']])
def test_empty_unknown_and_broad_requests_cannot_pass(requested):
    value = constraint_handoff()
    value['requested_checks'] = requested
    result = review_program(seal(value))
    assert result['status'] == 'needs_evidence'
    assert result['completion']['status'] == 'needs_evidence'


@pytest.mark.parametrize('requested', ['parking', None, {}, [1], [''], ['parking', 'parking']])
def test_invalid_request_scope_rejected(requested):
    value = constraint_handoff()
    value['requested_checks'] = requested
    with pytest.raises(ValueError, match='requested_checks'):
        review_program(seal(value))


@pytest.mark.parametrize('fault', ['missing_fact', 'stale_fact', 'stale_edition', 'no_constraints', 'no_applicable'])
def test_constraints_need_substantive_current_comparisons(fault):
    value = constraint_handoff()
    requirements = value['requirements']
    if fault == 'missing_fact':
        requirements['legal_facts'] = []
    elif fault == 'stale_fact':
        requirements['legal_facts'][0]['input_version'] = 0
    elif fault == 'stale_edition':
        requirements['legal_constraints'][0]['source']['edition_checked_on'] = '2026-10-12'
    elif fault == 'no_constraints':
        requirements['legal_constraints'] = []
    else:
        requirements['legal_constraints'][0]['applies_when'] = [{'fact': 'fixture_count', 'operator': 'eq', 'value': 0}]
    assert review_program(seal(value))['completion']['status'] == 'needs_evidence'


def test_violation_dominates_even_outside_requested_scope():
    value = constraint_handoff()
    value['requirements']['legal_facts'][0]['value'] = 0
    value['requested_checks'] = ['unknown_scope']
    result = review_program(seal(value))
    assert result['status'] == 'conflict'
    assert result['completion']['status'] == 'needs_revision'
    assert result['violations']


def test_constraints_outside_program_scope_are_not_silently_completed():
    value = constraint_handoff()
    outside = deepcopy(value['requirements']['legal_constraints'][0])
    outside.update(rule_id='unreviewed-mass', scope='mass')
    value['requirements']['legal_constraints'].append(outside)
    result = review_program(seal(value))
    assert result['completion']['unresolved_checks'] == ['supplied_constraints']
    assert result['status'] == 'needs_evidence'


def test_facility_minimum_pass_uses_existing_owner_snapshot():
    result = review_program(facility_handoff())
    assert result['status'] == 'reviewed'
    assert result['completion']['completed_checks'] == ['facility_area']
    assert result['sources']


@pytest.mark.parametrize('fault', ['stale_edition', 'missing_measurement', 'no_applicable', 'unknown_facility'])
def test_facility_gaps_do_not_become_completion(fault):
    value = facility_handoff()
    fact = value['requirements']['facility_facts'][0]
    if fault == 'stale_edition':
        value['assessment_date'] = '2030-01-01'
    elif fault == 'missing_measurement':
        next(iter(fact['areas'].values())).pop('source_ref')
    elif fault == 'no_applicable':
        fact['conditions']['current_standard_applies'] = False
    else:
        fact['facility_type'] = 'arbitrary_unregistered_operation'
    assert review_program(seal(value))['completion']['status'] == 'needs_evidence'


def test_actual_parking_owner_completes_qualified_count_and_retains_source():
    from backend.tests.provider_parity.test_program_parking import handoff
    result = review_program(handoff())
    assert result['status'] == 'reviewed'
    assert result['completion']['completed_checks'] == ['parking']
    assert result['parking']['calculation']['source'] in result['sources']
    assert review_program(handoff(False))['completion']['status'] == 'needs_evidence'
