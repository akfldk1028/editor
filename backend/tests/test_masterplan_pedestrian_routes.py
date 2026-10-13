import copy
import pytest
from shapely.geometry import Point, box, mapping, shape
from test_masterplan_pedestrian_moves import request, moves
from backend.app.modules.design.generation.maas.masterplan.placement_moves import apply_placement_moves
from backend.app.modules.design.generation.maas.masterplan.pedestrian_routes import realize_route


def test_declared_side_door_is_destination_instead_of_nearest_facade():
    data = request()
    data['building_entrance'] = mapping(Point(32, 26))
    data['evidence']['building_entrance'] = 'MassAgent ground entrance E1'
    before = copy.deepcopy(data)
    route = realize_route(apply_placement_moves(data, moves())['request'])
    assert route['entrance'].equals(Point(32, 26))
    assert route['door_status'] == 'declared'
    assert route['distance_to_declared_entrance_m'] == pytest.approx(route['centerline'].length)
    assert route['corridor'].intersection(shape(data['footprint'])).area < 1e-6
    assert data == before


def test_full_width_route_detours_around_column():
    data = request()
    data['columns'] = [mapping(box(19, 5, 21, 7))]
    route = realize_route(apply_placement_moves(data, moves())['request'])
    assert route['centerline'].length > 20
    assert route['corridor'].intersection(shape(data['columns'][0])).area < 1e-6
    assert shape(data['site']).buffer(1e-6).covers(route['corridor'])
    assert route['clearance_verified'] is True
    assert route['door_status'] == 'unknown'
    assert route['distance_to_declared_entrance_m'] is None


@pytest.mark.parametrize('entrance,evidence', [(Point(32,26), None), (Point(20,26), 'source'), (Point(39,39), 'source')])
def test_unsourced_or_off_facade_entrance_is_refused(entrance, evidence):
    data = request()
    data['building_entrance'] = mapping(entrance)
    if evidence:
        data['evidence']['building_entrance'] = evidence
    with pytest.raises(ValueError, match='entrance'):
        apply_placement_moves(data, moves())


def test_separating_barrier_refuses_route():
    data = request()
    data['columns'] = [mapping(box(0, 5, 40, 7))]
    with pytest.raises(ValueError):
        apply_placement_moves(data, moves())


def test_rotated_local_frame_preserves_declared_door_and_clearance():
    from shapely.affinity import rotate, translate
    from backend.app.modules.design.generation.maas.masterplan.pedestrian_routes import route_features
    data = request()
    data['building_entrance'] = mapping(Point(32, 26))
    data['evidence']['building_entrance'] = 'MassAgent E1'
    data['columns'] = [mapping(box(19, 5, 21, 7))]
    base = realize_route(apply_placement_moves(data, moves())['request'])
    transform = lambda g: translate(rotate(g, 31, origin=(0,0)), 1000, 2000)
    for key in ('site', 'footprint', 'pedestrian_frontage', 'building_entrance'):
        data[key] = mapping(transform(shape(data[key])))
    data['columns'] = [mapping(transform(shape(g))) for g in data['columns']]
    route = realize_route(apply_placement_moves(data, moves())['request'])
    assert route['entrance'].distance(transform(base['entrance'])) < 1e-6
    assert route['centerline'].length == pytest.approx(base['centerline'].length)
    assert route['corridor'].intersection(shape(data['columns'][0])).area < 1e-6
    assert all(f['properties']['door_status'] == 'declared' for f in route_features(route))


def test_complex_obstacle_search_has_explicit_budget():
    data = request()
    data['columns'] = [mapping(box(19,5,21,7))] + [
        mapping(box(1+x*.5,10+y*.5,1.1+x*.5,10.1+y*.5))
        for x in range(12) for y in range(12)]
    with pytest.raises(ValueError, match='budget'):
        apply_placement_moves(data, moves(width=.2))


def test_generated_mass_move_refuses_source_door_without_transform_binding():
    data = request()
    data.pop('footprint')
    data['building_entrance'] = mapping(Point(32, 26))
    data['evidence']['building_entrance'] = 'MassAgent E1 in previous geometry'
    data['options']['target_footprint_m2'] = 288
    data['rules'] = {'stall_length_m': 5, 'aisle_width_m': 6}
    before = copy.deepcopy(data)
    with pytest.raises(ValueError, match='entrance.*source'):
        apply_placement_moves(data, {'building_side': 'center'})
    assert data == before


def test_parent_piloti_change_cannot_reuse_stale_source_door(tmp_path, monkeypatch):
    from backend.app.modules.design.generation.maas.masterplan.placement_state import publish
    from backend.app.modules.design.generation.maas.masterplan.geometry import feature
    monkeypatch.setenv('EDITOR_PLACEMENT_SNAPSHOT_ROOT', str(tmp_path))
    data = request()
    upper = shape(data.pop('footprint'))
    data['building_entrance'] = mapping(Point(32, 26))
    data['evidence']['building_entrance'] = 'MassAgent E1 on original parent'
    data['rules'] = {'stall_length_m': 5, 'aisle_width_m': 6}
    parent = publish(data, {'features': [feature('building_footprint', upper)]})
    choice = next(c['id'] for c in parent['piloti_choices'] if c['depth_m'] == 5)
    with pytest.raises(ValueError, match='entrance.*source'):
        apply_placement_moves(data, {'piloti': 'piloti', 'piloti_choice': choice}, parent['ref'])
    kept = apply_placement_moves(data, {'ramp': 'straight'}, parent['ref'])
    assert kept['request']['building_entrance'] == data['building_entrance']
