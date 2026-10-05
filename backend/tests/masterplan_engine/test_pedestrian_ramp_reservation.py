"""A below-grade ramp label must not bypass authored surface reservations."""
import pytest
from shapely.geometry import LineString, box, mapping
from backend.app.modules.design.generation.maas.masterplan.geometry import feature
from backend.app.modules.design.generation.maas.masterplan.validation import validate_plan
from test_masterplan_engine import request


@pytest.mark.parametrize('reserved,crossing,expected', [
    (box(1, 8, 5, 12), False, 'failed'),
    (box(1, 8, 5, 12), True, 'failed'),
    (box(1, 21, 5, 24), True, 'failed'),
    (box(1, 1, 5, 3), False, 'failed'),
    (box(1, 1, 5, 3), True, 'passed'),
])
def test_source_reservation_checks_ramp_even_when_no_access_layer_is_drawn(reserved, crossing, expected):
    data = request(0, 'basement')
    data.pop('core', None)
    data['footprint'] = mapping(box(30, 30, 35, 35))
    data['pedestrian_reserved_area'] = mapping(reserved)
    data['evidence']['pedestrian_reserved_area'] = 'authored pedestrian circulation'
    if crossing:
        data['pedestrian_vehicle_crossing_area'] = mapping(reserved)
        data['evidence']['pedestrian_vehicle_crossing_area'] = 'authored flat ground crossing'
    profile = [{'distance_m': d, 'z_m': z} for d,z in [(0,0), (6,0), (20,-3), (26,-3)]]
    features = [feature('ramp', box(0, 0, 6, 26), -1, from_level=0, to_level=-1,
                        width_m=6., length_m=26., profile=profile),
                feature('ramp_centerline', LineString([(3,0,0), (3,6,0), (3,20,-3), (3,26,-3)]),
                        -1, from_level=0, to_level=-1)]
    checks = {c['id']: c['status'] for c in validate_plan(data, {'features': features})['checks']}
    assert checks.get('pedestrian_reservation:ramp') == expected


def test_generator_skips_conflicting_portals_before_candidate_limit():
    from backend.app.modules.design.generation.maas.masterplan.ramps import ramp_candidates
    from backend.app.modules.design.generation.maas.masterplan.pedestrian import ramp_reservation_conflicts
    from shapely.geometry import Polygon
    data = request(0, 'basement')
    reserved = box(0, 0, 9, 48)
    pedestrian = {'reserved': reserved, 'vehicle_blocked': reserved}
    ramps = ramp_candidates(box(0, 0, 60, 48), LineString([(0, 0), (60, 0)]), Polygon(),
        data['rules'], 3.3, limit=2,
        accept=lambda ramp: ramp_reservation_conflicts(ramp, pedestrian)['passed'])
    assert ramps
    assert all(r['polygon'].intersection(reserved).area < 1e-6 for r in ramps)
