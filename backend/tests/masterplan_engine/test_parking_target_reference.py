import pytest
from shapely.geometry import box, mapping

from backend.app.modules.design.generation.maas.masterplan.placement_quality import review_placement


@pytest.mark.parametrize('mode,eligible', [(None, True), ('reference', True), ('required', False)])
def test_placement_count_is_reference_unless_explicitly_required(mode, eligible):
    options = {'planning_stage': 'placement'}
    if mode:
        options['parking_target_mode'] = mode
    request = {'buildable': mapping(box(0, 0, 30, 30)), 'options': options}
    features = [{'geometry': mapping(g), 'properties': {'layer': layer, 'level': 0}}
                for layer, g in [('building_footprint', box(0, 0, 5, 5)),
                                 ('parking_stall', box(10, 0, 12.5, 5)),
                                 ('parking_stall', box(12.5, 0, 15, 5))]]
    result = review_placement(request, {'features': features,
        'metrics': {'planned_parking_stalls': 50, 'required_parking_stalls': 2},
        'validation': {'geometry_status': 'passed', 'checks': []}})
    assert result['eligible'] is eligible
    assert result['parking_target']['mode'] == (mode or 'reference')


@pytest.mark.parametrize('mode,rejected', [('reference', False), ('required', True)])
def test_reference_below_law_count_does_not_create_input_conflict(monkeypatch, mode, rejected):
    from backend.app.modules.design.generation.maas.masterplan import planner
    monkeypatch.setattr(planner, '_rank_and_record', lambda *a, **k: k)
    result = planner._plan_site_fixed({
        'site': mapping(box(0, 0, 30, 30)), 'buildable': mapping(box(0, 0, 30, 30)),
        'footprint': mapping(box(0, 0, 10, 10)),
        'law': {'status': 'resolved', 'required_spaces': 2},
        'options': {'planning_stage': 'placement', 'parking_strategy': 'surface',
                    'target_parking_stalls': 1, 'parking_target_mode': mode}})
    assert any('below the law' in f for f in result['failures']) is rejected
    assert result['planned'] == 2
