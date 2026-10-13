import pytest
from shapely.geometry import Point, mapping, shape
from test_masterplan_pedestrian_moves import request, moves
from backend.app.modules.design.generation.maas.masterplan.placement_moves import apply_placement_moves
from backend.app.modules.design.generation.maas.masterplan.pedestrian_routes import realize_route, route_features
from backend.app.modules.design.generation.maas.masterplan.siting_relations import measure_siting


@pytest.mark.parametrize('corrupt', [False, True])
def test_declared_route_is_remeasured_from_request_and_serialized_geometry(corrupt):
    data = request()
    data['building_entrance'] = mapping(Point(32, 26))
    data['evidence']['building_entrance'] = 'MassAgent ground entrance E1'
    data = apply_placement_moves(data, moves())['request']
    route = realize_route(data)
    features = route_features(route)
    if corrupt:
        features[1]['geometry']['coordinates'] = [[99, 99], [100, 100]]
    measured = measure_siting(data, features, shape(data['footprint']))['pedestrian']
    assert measured['distance_to_declared_entrance_m'] == (None if corrupt else pytest.approx(route['centerline'].length))
    if not corrupt:
        assert measured['entrance_source'] == data['evidence']['building_entrance']
        assert measured['actual_door_status'] == 'declared'


def test_facade_proposal_never_counts_as_declared_door_distance():
    data = apply_placement_moves(request(), moves())['request']
    route = realize_route(data)
    measured = measure_siting(data, route_features(route), shape(data['footprint']))['pedestrian']
    assert measured['distance_to_declared_entrance_m'] is None
