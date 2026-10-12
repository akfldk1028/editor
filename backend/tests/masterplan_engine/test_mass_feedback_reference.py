import pytest

from backend.app.modules.design.generation.maas.masterplan.feedback import build_mass_feedback


@pytest.mark.parametrize('mode,provided,shortfall', [('reference', 45, 0),
                                                  ('required', 45, 5),
                                                  ('reference', 35, 4)])
def test_mass_revision_demand_does_not_promote_reference_count(mode, provided, shortfall):
    request = {'law': {'required_spaces': 39, 'status': 'needs_evidence'},
               'rules': {'source_snapshot': {'source': 'owner-test'}},
               'options': {'planning_stage': 'placement', 'parking_target_mode': mode,
                           'target_parking_stalls': 50, 'max_basement_levels': 1}}
    result = {'metrics': {'provided_parking_stalls': provided, 'planned_parking_stalls': 50},
              'levels': [{'level': 0, 'provided_spaces': 27}, {'level': -1, 'provided_spaces': provided - 27}],
              'validation': {'geometry_status': 'passed'}}
    feedback = build_mass_feedback(request, result)
    assert feedback['demand']['shortfall_stalls'] == shortfall
    assert feedback['demand']['parking_target_mode'] == mode
    assert feedback['demand']['reference_shortfall_stalls'] == (50 - provided if mode == 'reference' else None)
    assert any(a['id'] == 'review_massing_for_shortfall' for a in feedback['actions']) is bool(shortfall)
    if mode == 'reference' and provided >= 39:
        assert [v['proposed_required_stalls'] for v in feedback['levels']] == [27, provided - 27]


def test_reference_surplus_does_not_request_deep_floor_removal():
    feedback = build_mass_feedback({
        'law': {'required_spaces': 10, 'status': 'needs_evidence'},
        'rules': {'source_snapshot': {'source': 'owner-test'}},
        'options': {'planning_stage': 'placement', 'target_parking_stalls': 50}}, {
        'metrics': {'provided_parking_stalls': 60, 'planned_parking_stalls': 50},
        'levels': [{'level': 0, 'provided_spaces': 10}, {'level': -1, 'provided_spaces': 50}]})
    assert not any(a['id'] == 'review_eliminating_deep_level' for a in feedback['actions'])


def test_law_demand_above_reference_keeps_each_shortfall_separate():
    feedback = build_mass_feedback({
        'law': {'required_spaces': 60, 'status': 'needs_evidence'},
        'rules': {'source_snapshot': {'source': 'owner-test'}},
        'options': {'planning_stage': 'placement', 'target_parking_stalls': 50}}, {
        'metrics': {'provided_parking_stalls': 55, 'planned_parking_stalls': 60},
        'levels': [{'level': 0, 'provided_spaces': 27}, {'level': -1, 'provided_spaces': 28}]})
    assert feedback['demand']['reference_stalls'] == 50
    assert feedback['demand']['reference_shortfall_stalls'] == 0
    assert feedback['demand']['legal_shortfall_stalls'] == 5
