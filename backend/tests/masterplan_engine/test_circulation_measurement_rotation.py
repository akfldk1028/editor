import pytest
from shapely.affinity import rotate
from shapely.geometry import LineString, Polygon, box, mapping

from backend.app.modules.design.generation.maas.masterplan.validation_circulation import validate_circulation_geometry


def entry_checks(geometry, angle=0, frontage=None):
    objects = [('site_boundary', box(-30, -30, 30, 30), {}),
               ('road_frontage', frontage if frontage is not None else LineString([(-20, 0), (20, 0)]), {}),
               ('vehicular_access', geometry, {'role': 'surface_entry_connector'})]
    features = [{'properties': {'layer': layer, 'level': 0, **props},
                 'geometry': mapping(rotate(geom, angle, origin=(0, 0)))}
                for layer, geom, props in objects]
    report = validate_circulation_geometry(features, {'aisle_width_m': 6})
    return {check['id']: check for check in report['checks']}


@pytest.mark.parametrize('angle', [0, 15, 45, 90, 137])
def test_rotation_cannot_turn_a_two_metre_corridor_into_a_six_metre_entry(angle):
    check = entry_checks(box(0, 0, 2, 10), angle)['entry_approach_width']
    assert check['measured'] == pytest.approx(2, abs=.01)
    assert check['status'] == 'failed'


@pytest.mark.parametrize('angle', [0, 45, 137])
def test_full_width_straight_corridor_is_rotation_invariant(angle):
    check = entry_checks(box(0, 0, 6, 10), angle)['entry_approach_width']
    assert check['measured'] == pytest.approx(6, abs=.01)
    assert check['status'] == 'passed'


def test_oblique_end_portal_does_not_change_parallel_corridor_width():
    entry = Polygon([(0, 0), (6, 2), (6, 12), (0, 12)])
    frontage = LineString([(-30, -10), (30, 10)])
    assert entry_checks(entry, 45, frontage)['entry_approach_width']['measured'] == pytest.approx(6, abs=.01)


def test_pinched_nonconvex_entry_is_not_certified_from_its_bounding_box():
    entry = box(0, 0, 8, 4).union(box(3, 4, 5, 6)).union(box(0, 6, 8, 10))
    check = entry_checks(entry)['entry_approach_width']
    assert check['status'] == 'unknown'
    assert check['measured'] is None


def test_parallel_end_caps_do_not_certify_a_tapered_entry():
    entry = Polygon([(0, 0), (2, 0), (8, 10), (0, 10)])
    check = entry_checks(entry, 45)['entry_approach_width']
    assert check['status'] == 'unknown'
    assert check['measured'] is None


def test_short_corridor_uses_side_width_not_approach_length():
    check = entry_checks(box(0, 0, 6, 3), 45)['entry_approach_width']
    assert check['status'] == 'passed'
    assert check['measured'] == pytest.approx(6, abs=.01)


def test_vehicle_dimensions_without_a_path_do_not_pass_swept_path_check():
    vehicle = {'length_m': 4.5, 'width_m': 1.8, 'wheelbase_m': 2.7, 'min_turn_radius_m': 5.5}
    checks = validate_circulation_geometry([], {'aisle_width_m': 6}, {'vehicle': vehicle})['checks']
    check = next(c for c in checks if c['id'] == 'swept_path_design_vehicle')
    assert check['status'] == 'unknown'
    assert check['measured'] == vehicle
