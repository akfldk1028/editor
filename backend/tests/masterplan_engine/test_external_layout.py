import copy

import pytest
from shapely.geometry import Polygon, box, mapping

from backend.app.modules.design.generation.maas.masterplan_operations import invoke


def draft():
    return {'schema_version': 'masterplan.external-layout.v1',
            'coordinate_frame': 'local_xy_m', 'rotation_convention': 'ccw_degrees',
            'site': mapping(box(0, 0, 200, 200)), 'obstacles': [],
            'source': {'provider': 'rspl', 'revision': 'test', 'input_sha256': 'a' * 64},
            'buildings': [{'id': 'b1', 'center_m': [17, 8], 'width_m': 35,
                           'depth_m': 16, 'height_m': 54, 'rotation_deg': 0}]}


def check(value):
    return invoke({'operation': 'validate_external_layout', 'arguments': {'draft': value}})


def test_original_rspl_boundary_protrusion_is_rejected():
    result = check(draft())
    assert result['status'] == 'succeeded', result
    result = result['result']
    assert result['geometry_status'] == 'failed'
    assert result['checks'][0]['outside_area_m2'] == pytest.approx(8)
    assert result['features'][0]['properties']['building_id'] == 'b1'
    assert result['planning_status'] == 'unknown'


def test_valid_rotated_negative_coordinate_layout_and_no_mutation():
    value = draft()
    value['site'] = mapping(box(-100, -100, 100, 100))
    value['buildings'][0].update(center_m=[-30, -20], rotation_deg=45)
    original = copy.deepcopy(value)
    result = check(value)['result']
    assert result['geometry_status'] == 'passed'
    assert result['features'][0]['properties']['height_m'] == 54
    assert value == original


def test_holes_obstacles_and_pairwise_overlap():
    value = draft()
    value['site'] = mapping(Polygon([(0, 0), (200, 0), (200, 200), (0, 200)],
                                    holes=[[(40, 40), (60, 40), (60, 60), (40, 60)]]))
    value['buildings'][0]['center_m'] = [50, 50]
    second = {**value['buildings'][0], 'id': 'b2', 'center_m': [60, 50]}
    value['buildings'].append(second)
    value['obstacles'] = [mapping(box(65, 40, 70, 60))]
    result = check(value)['result']
    failed = {c['kind'] for c in result['checks'] if c['status'] == 'failed'}
    assert failed == {'site_containment', 'obstacle_overlap', 'building_overlap'}
    assert len(result['features']) == 2


@pytest.mark.parametrize('change', [
    lambda d: d.update(coordinate_frame='pixels'),
    lambda d: d.update(rotation_convention='clockwise'),
    lambda d: d.update(buildings=[]),
    lambda d: d['buildings'].append(dict(d['buildings'][0])),
    lambda d: d['buildings'][0].update(width_m=0),
    lambda d: d['buildings'][0].update(center_m=[True, 8]),
    lambda d: d['source'].update(input_sha256='unbound'),
])
def test_bad_contract_is_refused(change):
    value = draft()
    change(value)
    assert check(value)['status'] == 'failed'


def test_touching_edges_are_not_overlap():
    value = draft()
    value['buildings'][0]['center_m'] = [17.5, 8]
    value['buildings'].append({**value['buildings'][0], 'id': 'b2', 'center_m': [52.5, 8]})
    assert check(value)['result']['geometry_status'] == 'passed'
