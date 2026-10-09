import copy

import pytest
from shapely.geometry import LineString, box, mapping, shape

from backend.app.modules.design.generation.maas.masterplan.placement_moves import apply_placement_moves
from backend.app.modules.design.generation.maas.masterplan.pedestrian import pedestrian_reservation


def request():
    return {'site': mapping(box(0, 0, 40, 40)),
            'footprint': mapping(box(8, 20, 32, 32)),
            'pedestrian_frontage': mapping(LineString([(0, 0), (40, 0)])),
            'options': {}, 'evidence': {'pedestrian_frontage': 'Site/Law reviewed arrival fixture'}}


def moves(approach='front_middle', width=2):
    return {'pedestrian_route': approach, 'pedestrian_width_m': width}


def test_ai_approach_changes_connected_reserved_geometry_without_mutating_sources():
    req = request()
    before = copy.deepcopy(req)
    routes = []
    for approach in ('front_start', 'front_middle', 'front_end'):
        out = apply_placement_moves(req, moves(approach))
        reserved = pedestrian_reservation(out['request'])
        corridor = reserved['route']['corridor']
        assert corridor.area == pytest.approx(40)
        assert corridor.distance(shape(req['pedestrian_frontage'])) < 1e-6
        assert corridor.distance(shape(req['footprint'])) < 1e-6
        assert corridor.intersection(shape(req['footprint'])).area < 1e-6
        routes.append(corridor.centroid.x)
        assert any('door' in s for s in out['unresolved'])
    assert routes == [10, 20, 30]
    assert req == before


@pytest.mark.parametrize('width', [None, True, 0, -1, float('nan'), float('inf'), '2'])
def test_missing_or_invalid_width_never_becomes_a_default(width):
    with pytest.raises(ValueError):
        apply_placement_moves(request(), moves(width=width))


def test_missing_mass_or_frontage_is_not_invented():
    for field in ('footprint', 'pedestrian_frontage'):
        req = request()
        req.pop(field)
        with pytest.raises(ValueError):
            apply_placement_moves(req, moves())


def test_route_does_not_overwrite_authored_reservations_or_enable_crossings():
    req = request()
    req['pedestrian_reserved_area'] = mapping(box(1, 1, 3, 3))
    req['evidence']['pedestrian_reserved_area'] = 'authored'
    out = apply_placement_moves(req, moves())['request']
    assert out['pedestrian_reserved_area'] == req['pedestrian_reserved_area']
    assert out['evidence'] == req['evidence']
    reserve = pedestrian_reservation(out)
    assert reserve['reserved'].area == pytest.approx(44)
    assert reserve['crossing'].is_empty


def test_obstruction_and_boundary_pinching_are_refused():
    req = request()
    req['columns'] = [mapping(box(19, 5, 21, 7))]
    with pytest.raises(ValueError):
        apply_placement_moves(req, moves())
    with pytest.raises(ValueError):
        apply_placement_moves(request(), moves(width=50))


def test_width_without_route_and_existing_route_replacement_are_refused():
    with pytest.raises(ValueError):
        apply_placement_moves(request(), {'pedestrian_width_m': 2})
    req = apply_placement_moves(request(), moves())['request']
    with pytest.raises(ValueError):
        apply_placement_moves(req, moves('front_end'))


def test_vehicle_frontage_never_substitutes_for_site_pedestrian_evidence():
    req = request()
    req['front_frontage'] = req.pop('pedestrian_frontage')
    with pytest.raises(ValueError, match='pedestrian_frontage'):
        apply_placement_moves(req, moves())
    req = request()
    req['evidence'] = {}
    with pytest.raises(ValueError, match='source-attributed'):
        apply_placement_moves(req, moves())


def test_independent_validation_rejects_missing_route_and_vehicle_overlap():
    from backend.app.modules.design.generation.maas.masterplan.geometry import feature
    from backend.app.modules.design.generation.maas.masterplan.pedestrian_routes import route_features
    from backend.app.modules.design.generation.maas.masterplan.validation import validate_plan
    req = apply_placement_moves(request(), moves())['request']
    route = pedestrian_reservation(req)['route']
    features = [feature('building_footprint', shape(req['footprint'])), *route_features(route)]
    valid = validate_plan(req, {'features': features})
    assert valid['geometry_status'] == 'passed'
    assert 'pedestrian_entrance_door_and_internal_connection_review' in valid['pending_reviews']
    missing = validate_plan(req, {'features': features[:1]})
    assert missing['geometry_status'] == 'failed'
    conflict = validate_plan(req, {'features': features + [feature('vehicular_access', box(0, 4, 40, 8))]})
    assert any(c['id'] == 'pedestrian_reservation:vehicular_access' and c['status'] == 'failed'
               for c in conflict['checks'])


def test_source_crossing_does_not_silently_authorize_crossing_new_ai_route():
    req = request()
    req['pedestrian_reserved_area'] = mapping(box(19, 0, 21, 20))
    req['pedestrian_vehicle_crossing_area'] = mapping(box(19, 4, 21, 8))
    req['evidence']['pedestrian_vehicle_crossing_area'] = 'existing crossing'
    result = pedestrian_reservation(apply_placement_moves(req, moves())['request'])
    assert result['vehicle_blocked'].covers(result['route']['corridor'])


def test_real_planner_serializes_route_before_parking_and_validator_passes():
    from backend.app.modules.design.generation.maas.masterplan.planner import plan_site
    req = apply_placement_moves(request(), moves())['request']
    req.update(law={'required_spaces': 4, 'required_accessible_spaces': 0, 'bcr_pct': 60},
               frontage=mapping(LineString([(0, 0), (40, 0)])),
               rules={'stall_width_m': 2.5, 'stall_length_m': 5, 'accessible_width_m': 3.3,
                      'accessible_length_m': 5, 'aisle_width_m': 6})
    req['options'].update(parking_strategy='surface', max_basement_levels=0)
    result = plan_site(req)
    assert result['validation']['geometry_status'] == 'passed', result['validation']
    assert result['metrics']['provided_parking_stalls'] >= 4
    assert any(f['properties']['layer'] == 'pedestrian_entrance_proposal' for f in result['features'])
