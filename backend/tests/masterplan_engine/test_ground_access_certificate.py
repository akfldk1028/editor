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


def test_a_drive_exactly_as_wide_as_the_rule_is_full_width():
    """The generator draws the aisle at aisle_width_m. Eroding by a hair under half the width used to
    leave a 2e-5 m core that floating-point noise emptied: every standard layout stayed unknown."""
    drive = box(0, 0, 30, 6)
    stalls = [box(x, 6, x + 2.5, 11) for x in range(2, 26, 5)]
    result = certify_ground_access(drive, stalls, LineString([(0, 0), (30, 0)]), 6)
    assert result['status'] == 'passed' and result['certified_stalls'] == len(stalls)
    def through_strip(strip_width):
        strip = box(15 - strip_width/2, 0, 15 + strip_width/2, 4)       # entry strip into a full-depth drive
        drive = unary_union([strip, box(0, 4, 30, 10)])
        return certify_ground_access(drive, [box(14, 10, 16.5, 15)], LineString([(0, 0), (30, 0)]), 6)['status']
    assert through_strip(6.0) == 'passed' and through_strip(5.995) == 'passed'
    assert through_strip(5.98) == 'unknown', 'the slack is 1 cm in total, not a width relaxation'


@pytest.mark.parametrize('neck', [1.0, 2.0])
def test_a_drive_reached_only_through_a_narrow_neck_from_a_shallow_ledge_is_not_served(neck):
    """A width-long road contact on a 0.5 m ledge, a neck up to the real drive: no full-width body can
    cross the road into the drive. The reversed sweep used to start inside the drive and never meet the
    road; a core within the slack of the start made the body empty. Both certified 3/3."""
    road = LineString([(0, 0), (30, 0)])
    for depth in (2.0, 3.0):      # 3.0 puts the core exactly a body length from the portal
        drive = unary_union([box(0, 0, 30, 0.5), box(15 - neck/2, 0.5, 15 + neck/2, depth), box(0, depth, 30, depth + 6)])
        stalls = [box(x, depth + 6, x + 2.5, depth + 11) for x in (5, 14, 23)]
        result = certify_ground_access(drive, stalls, road, 6)
        assert result['status'] == 'unknown' and result['certified_stalls'] == 0, (neck, depth, result)


def test_an_entry_strip_skewed_to_the_road_is_a_valid_approach():
    """고산: the rows follow the parcel, the road runs 28 degrees off them. The entry strip meets the
    road at that angle; a car drives straight along the strip, not normal to the road."""
    from shapely.geometry import Polygon
    import math
    skew = 12 * math.tan(math.radians(28))
    opening = 6 / math.cos(math.radians(28))                 # 6 m measured across the strip
    strip = Polygon([(0, 0), (opening, 0), (opening + skew, 12), (skew, 12)])
    drive = unary_union([box(0, 10, 40, 16), strip]).buffer(0)
    road = LineString([(-20, 0), (60, 0)])
    stalls = [box(x, 16, x + 2.5, 21) for x in range(10, 36, 5)]
    result = certify_ground_access(drive, stalls, road, 6)
    assert result['status'] == 'passed', result
