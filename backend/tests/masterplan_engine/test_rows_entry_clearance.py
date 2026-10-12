from shapely.geometry import LineString, Point, Polygon, box
from shapely.affinity import rotate
import pytest

from backend.app.modules.design.generation.maas.masterplan.rows import row_candidates

RULES = {'stall_width_m': 2.5, 'stall_length_m': 5, 'accessible_width_m': 3.3,
         'accessible_length_m': 5, 'aisle_width_m': 6}


@pytest.mark.parametrize('angle', [0, 37])
def test_corner_clearance_filters_before_best_per_family_is_selected(angle):
    rot = lambda g: rotate(g, angle, origin=(0, 0))
    site = rot(box(0, 0, 60, 30))
    road = rot(LineString([(0, 0), (0, 30)]))
    rows = row_candidates(site, site, Polygon(), None, road, road, RULES, 20, 1,
                          allowed_angles=[angle], entry_clearance_m=4)
    assert rows, 'a feasible inward aisle must survive, not just reject the former winner'
    assert all(min(r['entrance'].distance(Point(c)) for c in road.coords) >= 4 - 1e-6 for r in rows)


def test_tiled_drives_do_not_cross_enclosed_building():
    site = box(0, 0, 60, 60)
    occupied = box(20, 20, 40, 40)
    road = LineString([(0, 0), (60, 0)])
    rows = row_candidates(site, site.difference(occupied), occupied, None, road, road,
                          RULES, 50, 1, allowed_angles=[0], limit=30)
    assert rows
    assert all(r['drive'].intersection(occupied).area <= 1e-6 for r in rows)


def test_ramp_connector_cannot_cross_building_even_when_landing_is_clear():
    from backend.app.modules.design.generation.maas.masterplan.entry_constraints import ramp_ground_clear
    building = box(10, 10, 30, 30)
    ramp = {'upper_landing': box(0, 0, 6, 6), 'ground_connector': box(0, 15, 40, 21)}
    assert not ramp_ground_clear(ramp, building)
    assert ramp_ground_clear(ramp, box(10, 23, 30, 30))


def test_interior_connector_tries_next_route_after_building_rejection():
    from backend.app.modules.design.generation.maas.masterplan.ramp_access import _connector
    site, road = box(0, 0, 60, 60), LineString([(0, 0), (60, 0)])
    ramp, upper, building = box(27, 35, 33, 60), box(27, 35, 33, 41), box(25, 10, 35, 25)
    first = _connector(site, road, Polygon(), ramp, upper, 6, 6)
    assert first.intersection(building).area > 1
    repaired = _connector(site, road, Polygon(), ramp, upper, 6, 6,
                          accept=lambda corridor: corridor.intersection(building).area <= 1e-6)
    assert repaired is not None
    assert repaired.intersection(building).area <= 1e-6
    assert repaired.intersection(upper).area > 0


def test_generic_packer_preserves_clearance_and_entrance_evidence():
    from backend.app.modules.design.generation.maas.masterplan.bounded_packing import pack_level
    site, road = box(0, 0, 60, 30), LineString([(0, 0), (0, 30)])
    result = pack_level(site, [road], RULES, 20, 1, allowed_angles=[0], entry_clearance_m=4)
    assert result['provided'] > 0
    assert min(result['entrance'].distance(Point(c)) for c in road.coords) >= 4 - 1e-6


@pytest.mark.parametrize('ramp_role', ['road_to_ramp_connector', 'ramp_departure'])
def test_validator_checks_ramp_road_connector_even_with_separate_surface_entry(ramp_role):
    from shapely.geometry import mapping
    from backend.app.modules.design.generation.maas.masterplan.validation_circulation import validate_circulation_geometry
    def f(layer, geom, role=None):
        return {'geometry': mapping(geom), 'properties': {'layer': layer, 'level': 0, 'role': role}}
    features = [f('road_frontage', LineString([(0, 0), (60, 0)])),
                f('vehicular_access', box(25, 0, 31, 10), 'surface_entry_connector'),
                f('vehicular_access', box(1, 0, 7, 10), ramp_role)]
    checked = validate_circulation_geometry(features, RULES, {'corner_clearance_m': 4})
    corner = next(c for c in checked['checks'] if c['id'] == 'entry_corner_clearance')
    assert corner['status'] == 'failed'
    assert corner['measured'] == 1


def test_separate_entry_does_not_hide_known_narrow_corridor():
    from shapely.geometry import mapping
    from backend.app.modules.design.generation.maas.masterplan.validation_circulation import validate_circulation_geometry
    features = [{'geometry': mapping(g), 'properties': {'layer': layer, 'role': role, 'level': 0}}
                for g, layer, role in [(LineString([(0, 0), (60, 0)]), 'road_frontage', None),
                    (box(25, 0, 28, 10), 'vehicular_access', 'surface_entry_connector'),
                    (box(40, 0, 46, 10), 'vehicular_access', 'road_to_ramp_connector')]]
    checks = validate_circulation_geometry(features, RULES, {'corner_clearance_m': 4})['checks']
    width = next(c for c in checks if c['id'] == 'entry_approach_width')
    assert width['status'] == 'failed'
    assert width['measured'] == 3
