from copy import deepcopy
import importlib

import pytest

from backend.app.modules.law.reference.siting_rules import catalog


def facts(**overrides):
    values = dict(road_width_m=8.0, has_sidewalk_separation=False,
                  centreline_presence=True, unobstructed_connection=True,
                  legal_road_frontage=True, no_obstruction_to_parking_use=True)
    values.update(overrides)
    return {key: {'value': value, 'source_refs': ['site:survey:1']} for key, value in values.items()}


def evaluate(evidence=None, **overrides):
    module = importlib.import_module('backend.app.modules.law.reference.road_aisle')
    args = dict(pnu='1' * 19, total_spaces=5, structure='surface',
                parking_angle='perpendicular', facts=facts() if evidence is None else evidence,
                assessment_date='2026-10-13')
    args.update(overrides)
    return module.evaluate(**args)


def test_sourced_small_road_condition_is_preliminary_and_bound():
    evidence = facts()
    out = evaluate(evidence)
    assert out['status'] == 'applicable_for_preliminary_design'
    assert out['allowed_extent'] == 'centreline'
    assert out['required_combined_aisle_width_m'] == catalog()['small_attached_parking']['road_aisle']['perpendicular_combined_width_m']
    assert out['permit_compliance_verified'] is False
    assert out['input_identity']['facts'] == evidence
    assert len(out['input_hash']) == 64
    changed = facts(centreline_presence=False)
    assert evaluate(changed)['input_hash'] != out['input_hash']
    assert evaluate(changed)['allowed_extent'] == 'opposite_edge'


@pytest.mark.parametrize('name', ['road_width_m', 'has_sidewalk_separation', 'centreline_presence', 'unobstructed_connection', 'legal_road_frontage'])
def test_unsourced_or_missing_facts_are_unknown(name):
    evidence = facts()
    evidence[name]['source_refs'] = []
    out = evaluate(evidence)
    assert out['status'] == 'needs_evidence'
    assert name in out['missing_evidence']
    assert out['allowed_extent'] is None


@pytest.mark.parametrize('value', [True, float('nan'), float('inf'), -1, '8'])
def test_invalid_width_is_not_positive_evidence(value):
    assert evaluate(facts(road_width_m=value))['status'] == 'needs_evidence'


@pytest.mark.parametrize('overrides', [dict(total_spaces=9), dict(structure='basement'), dict(parking_angle='opposed_45')])
def test_known_outside_scope_is_denied(overrides):
    assert evaluate(**overrides)['status'] == 'denied'


@pytest.mark.parametrize('count', [True, None, float('inf'), 2.5, 0])
def test_total_installed_count_must_be_known_integer(count):
    assert evaluate(total_spaces=count)['status'] == 'needs_evidence'


def test_wide_road_scope_count_angle_and_obstruction():
    evidence = facts(road_width_m=12, has_sidewalk_separation=True)
    assert evaluate(evidence)['status'] == 'applicable_for_preliminary_design'
    assert evaluate(evidence, total_spaces=6)['status'] == 'denied'
    assert evaluate(evidence, parking_angle='parallel')['status'] == 'denied'
    assert evaluate(facts(unobstructed_connection=False))['status'] == 'denied'
    assert evaluate(facts(legal_road_frontage=False))['status'] == 'denied'
    evidence['no_obstruction_to_parking_use']['value'] = None
    assert evaluate(evidence)['status'] == 'needs_evidence'


def test_parallel_width_and_edition_are_catalog_owned():
    out = evaluate(parking_angle='parallel')
    assert out['required_combined_aisle_width_m'] == catalog()['small_attached_parking']['road_aisle']['parallel_combined_width_m']
    assert evaluate(assessment_date='2026-07-26')['status'] == 'needs_evidence'
    later = evaluate(assessment_date='2026-10-14')      # the day after verified_on: in force, re-verify
    assert later['status'] == 'applicable_for_preliminary_design' and later['verification_stale'] is True


def test_original_input_is_not_mutated_or_aliased():
    evidence = facts()
    original = deepcopy(evidence)
    out = evaluate(evidence)
    assert evidence == original
    evidence['road_width_m']['value'] = 999
    assert out['input_identity']['facts'] == original


def test_catalog_snapshot_hash_and_limits_follow_owner(monkeypatch):
    from backend.app.modules.law.reference import siting_rules
    data = catalog()
    original = evaluate()
    data['small_attached_parking']['max_total_spaces'] = 4
    data['small_attached_parking']['road_aisle']['perpendicular_combined_width_m'] = 7.25
    monkeypatch.setattr(siting_rules, 'catalog', lambda: deepcopy(data))
    out = evaluate()
    assert out['status'] == 'denied'
    assert out['max_total_spaces'] == 4
    assert out['required_combined_aisle_width_m'] == 7.25
    assert out['source_snapshot_hash'] != original['source_snapshot_hash']


@pytest.mark.parametrize('width,separated', [(12, False), (8, True)])
def test_neither_road_branch_means_denied(width, separated):
    assert evaluate(facts(road_width_m=width, has_sidewalk_separation=separated))['status'] == 'denied'


def test_wide_extent_and_count_are_owned_and_missing_use_evidence_blocks():
    evidence = facts(road_width_m=12, has_sidewalk_separation=True)
    out = evaluate(evidence)
    assert out['allowed_extent'] == 'source_road_polygon'
    assert out['max_total_spaces'] == catalog()['small_attached_parking']['wide_road_aisle']['max_total_spaces']
    del evidence['no_obstruction_to_parking_use']
    assert evaluate(evidence)['allowed_extent'] is None


@pytest.mark.parametrize('value', ['false', 1, 0, None])
def test_boolean_facts_are_not_coerced(value):
    assert evaluate(facts(centreline_presence=value))['status'] == 'needs_evidence'


def test_known_denial_is_retained_even_with_other_missing_evidence():
    out = evaluate(facts(legal_road_frontage=False, centreline_presence=None))
    assert out['status'] == 'denied'
    assert 'centreline_presence' in out['missing_evidence']
    assert 'no_legal_road_frontage' in out['denial_reasons']


def test_an_assessment_after_the_reference_verification_date_is_flagged_not_blocked():
    """The feature used to expire by wall clock: the day after verified_on every road-aisle candidate
    fell to needs_evidence. The edition is in force from effective_from; a stale check is a review flag."""
    later = evaluate(assessment_date='2030-01-01')
    assert later['status'] == 'applicable_for_preliminary_design'
    assert later['verification_stale'] is True
    assert evaluate()['verification_stale'] is False
    before = evaluate(assessment_date='2020-01-01')
    assert before['status'] == 'needs_evidence' and 'applicable_legal_edition' in before['missing_evidence']
