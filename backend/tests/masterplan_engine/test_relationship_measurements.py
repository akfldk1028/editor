from collections import defaultdict
import pytest
from shapely.affinity import rotate
from shapely.geometry import box, LineString, mapping
from backend.app.modules.design.generation.maas.masterplan.relationship_measurements import measure_relationships


def fixture(width=6, angle=0):
    transform = lambda g: rotate(g, angle, origin=(0, 0))
    grouped = defaultdict(list)
    props = {'from_level': 0, 'to_level': -1}
    grouped[(-1, 'ramp_centerline')] = [(transform(LineString([(3, -20), (3, 0)])), props)]
    grouped[(-1, 'vehicular_access')] = [(transform(box(0, -6, 6, 0)), dict(props, role='ramp_arrival'))]
    grouped[(-1, 'parking_aisle')] = [(transform(box(3-width/2, 0, 3+width/2, 20)), {})]
    grouped[(0, 'building_footprint')] = [(transform(box(0, 5, 20, 15)), {})]
    request = {'site': mapping(transform(box(-30, -30, 40, 40))),
               'front_frontage': mapping(transform(LineString([(-10, 0), (30, 0)])))}
    return grouped, request


@pytest.mark.parametrize('angle', [0, 45, 133])
def test_outlet_width_distinguishes_contacts_that_both_touch(angle):
    wide = measure_relationships(*fixture(6, angle))['ramp_landings'][0]
    narrow = measure_relationships(*fixture(2, angle))['ramp_landings'][0]
    assert wide['outlet_width_m'] == pytest.approx(6, abs=1e-4)
    assert narrow['outlet_width_m'] == pytest.approx(2, abs=1e-4)
    assert wide['landing_end_width_m'] == pytest.approx(6, abs=1e-4)


def test_disjoint_openings_are_not_summed_and_missing_aisle_is_unknown():
    grouped, request = fixture()
    grouped[(-1, 'parking_aisle')] = [(box(0, 0, 2, 20).union(box(4, 0, 6, 20)), {})]
    assert measure_relationships(grouped, request)['ramp_landings'][0]['outlet_width_m'] == pytest.approx(2, abs=1e-4)
    grouped[(-1, 'parking_aisle')] = []
    assert measure_relationships(grouped, request)['ramp_landings'][0]['outlet_width_m'] is None


def test_frontage_facing_is_distinct_from_physical_contact():
    grouped, request = fixture()
    result = measure_relationships(grouped, request)['building_frontage']
    assert result['boundary_contact_m'] == 0
    assert result['facing_facade_length_m'] == pytest.approx(20)
    assert result['distance_m'] == pytest.approx(5)
    grouped[(0, 'building_footprint')] = [(box(0, 0, 20, 10), {})]
    assert measure_relationships(grouped, request)['building_frontage']['boundary_contact_m'] == pytest.approx(20)
    assert measure_relationships(grouped, request)['building_frontage']['facing_facade_length_m'] == pytest.approx(20)


def test_supported_checks_are_separate_from_unverified_requirements():
    from backend.app.modules.design.generation.maas.masterplan.planning_scores import score_relationships
    features = [{'geometry': mapping(box(0, 0, 6, 20)), 'properties': {
        'layer': 'parking_aisle', 'level': level}} for level in (0, -1)]
    features.append({'properties': {'layer': 'ramp', 'from_level': 0, 'to_level': -1,
                                    'layout_type': 'curved'}})
    names = ['ramp_containment', 'ramp_profile_length', 'ramp_width', 'ramp_grade',
             'ramp_departure_profile_endpoint', 'ramp_arrival_profile_endpoint', 'ramp_curve_radius']
    checks = [{'id': f'{name}:0:-1', 'status': 'passed'} for name in names]
    checks += [{'id': name, 'status': 'passed'} for name in
               ['entry_approach_width', 'placement_full_width_drive:-1']]
    checks.append({'id': 'ramp_grade_kerbs:0:-1', 'status': 'measured'})
    groups = score_relationships(features, checks)['groups']
    assert groups['ramp_geometry']['coverage_pct'] == 100
    assert groups['drive_width']['coverage_pct'] == 100
    assert groups['ramp_kerb_grade']['score'] is None
    assert groups['ground_drive_width']['score'] is None


def test_duplicate_ramp_identity_and_nonpolygon_landing_stay_unknown():
    grouped, request = fixture()
    grouped[(-1, 'ramp_centerline')] *= 2
    assert all(r['outlet_width_m'] is None for r in measure_relationships(grouped, request)['ramp_landings'])
    grouped, request = fixture()
    grouped[(-1, 'vehicular_access')][0] = (LineString([(0, 0), (6, 0)]), grouped[(-1, 'vehicular_access')][0][1])
    assert measure_relationships(grouped, request)['ramp_landings'][0]['outlet_width_m'] is None
