from shapely.geometry import box, mapping
from shapely.affinity import rotate

from backend.app.modules.design.generation.maas.masterplan.placement_quality import review_placement


def test_isolated_parallel_bay_is_a_review_issue_not_automatic_rejection():
    features = [{'geometry': mapping(geom), 'properties': {'layer': layer, 'level': 0}}
                for layer, geom in [('building_footprint', box(0, 0, 5, 5)),
                                    ('parking_stall', box(10, 0, 16, 2)),
                                    ('parking_stall', box(20, 0, 26, 2))]]
    result = review_placement({'buildable': mapping(box(0, 0, 30, 30))}, {
        'features': features, 'metrics': {'planned_parking_stalls': 2},
        'validation': {'geometry_status': 'passed', 'checks': []}})
    assert result['eligible']
    assert 'isolated_single_bay' in result['review_findings']


def test_different_module_axis_is_reviewed_without_inventing_a_requirement():
    result = review_placement({'buildable': mapping(box(-10, -10, 30, 30))}, {
        'features': [{'geometry': mapping(geom), 'properties': {'layer': layer, 'level': 0}}
            for layer, geom in [('building_footprint', box(0, 0, 5, 5)),
                                ('parking_stall', rotate(box(10, 0, 12.5, 5), 30))]],
        'metrics': {'planned_parking_stalls': 1},
        'validation': {'geometry_status': 'passed', 'checks': []}})
    assert result['eligible']
    assert 'inconsistent_module_axis' in result['review_findings']
