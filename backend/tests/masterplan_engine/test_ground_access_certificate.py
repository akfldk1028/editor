from shapely.geometry import LineString, box
from shapely.ops import unary_union
from shapely.affinity import rotate, translate
import pytest

from backend.app.modules.design.generation.maas.masterplan.ground_access import certify_ground_access


def test_separate_ground_lots_can_each_use_their_own_road_opening():
    drive = unary_union([box(0, 0, 20, 6), box(30, 0, 50, 6)])
    stalls = [box(8, 6, 10.5, 11), box(38, 6, 40.5, 11)]
    road = LineString([(0, 0), (60, 0)])
    result = certify_ground_access(drive, stalls, road, 6)
    assert result['status'] == 'passed'
    assert result['certified_stalls'] == 2


def test_a_connected_narrow_neck_does_not_get_a_width_certificate():
    drive = unary_union([box(0, 0, 6, 12), box(6, 5, 16, 6), box(16, 0, 30, 12)])
    result = certify_ground_access(drive, [box(20, 12, 22.5, 17)], LineString([(0, 0), (6, 0)]), 6)
    assert result['status'] == 'unknown'
    assert result['certified_stalls'] == 0


def test_missing_road_and_narrow_opening_cannot_certify():
    for road in [None, LineString([(2, 0), (3, 0)])]:
        assert certify_ground_access(box(0, 0, 20, 6), [box(8, 6, 10.5, 11)], road, 6)['status'] == 'unknown'


def test_bent_road_contact_cannot_add_two_narrow_openings():
    road = LineString([(0, 3), (0, 0), (3, 0)])
    result = certify_ground_access(box(0, 0, 20, 6), [box(8, 6, 10.5, 11)], road, 6)
    assert result['status'] == 'unknown'
    assert result['certified_stalls'] == 0


def test_long_portal_with_shallow_strip_cannot_use_endpoint_as_entry():
    drive = unary_union([box(3, 0, 20, 12), box(0, 0, 3, 1)])
    road = LineString([(0, 0), (6, 0)])
    result = certify_ground_access(drive, [box(10, 12, 12.5, 17)], road, 6)
    assert result['status'] == 'unknown'
    assert result['certified_stalls'] == 0


def test_collinear_road_vertices_preserve_a_full_width_opening():
    road = LineString([(0, 0), (3, 0), (6, 0)])
    result = certify_ground_access(box(0, 0, 20, 6), [box(8, 6, 10.5, 11)], road, 6)
    assert result['status'] == 'passed'


def test_only_stalls_in_road_served_erosion_core_are_certified():
    drive = unary_union([box(0, 0, 12, 12), box(12, 5, 13, 6), box(13, 0, 25, 12)])
    road = LineString([(0, 0), (12, 0)])
    result = certify_ground_access(drive, [box(3, 12, 5.5, 17), box(17, 12, 19.5, 17)], road, 6)
    assert result['status'] == 'unknown'
    assert result['certified_stalls'] == 1


@pytest.mark.parametrize('angle', [0, 17, 37, 89])
@pytest.mark.parametrize('case', ['rectangle', 'bent_portal', 'shallow_portal'])
def test_certificate_is_stable_under_rotation_and_translation(angle, case):
    drive = box(0, 0, 20, 6)
    stall = box(8, 6, 10.5, 11)
    road = LineString([(0, 0), (6, 0)])
    if case == 'bent_portal':
        road = LineString([(0, 3), (0, 0), (3, 0)])
    elif case == 'shallow_portal':
        drive = unary_union([box(3, 0, 20, 12), box(0, 0, 3, 1)])
        stall = box(10, 12, 12.5, 17)
    def transform(geometry):
        return translate(rotate(geometry, angle, origin=(0, 0)), xoff=200000, yoff=450000)
    result = certify_ground_access(transform(drive), [transform(stall)], transform(road), 6)
    assert result['status'] == ('passed' if case == 'rectangle' else 'unknown')
