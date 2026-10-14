from shapely.geometry import box, mapping, LineString
from backend.app.modules.design.generation.maas.masterplan.siting_relations import measure_siting, evaluate_relations


def feature(layer, geom, **props):
    return {'geometry': mapping(geom), 'properties': {'layer': layer, 'level': 0, **props}}


def test_separate_route_pieces_cannot_fake_frontage_to_building_connection():
    request = {'site': mapping(box(0, 0, 30, 30)), 'pedestrian_frontage': mapping(LineString([(0, 0), (30, 0)]))}
    building = box(10, 20, 20, 30)
    features = [feature('building_footprint', building),
                feature('pedestrian_route', box(12, 0, 14, 5)), feature('pedestrian_route', box(12, 18, 14, 20))]
    result = measure_siting(request, features, building)
    assert result['pedestrian']['facade_connected'] is False
    assert result['pedestrian']['actual_door_status'] == 'unknown'
    features[-1] = feature('pedestrian_route', box(12, 5, 14, 20))
    assert measure_siting(request, features, building)['pedestrian']['facade_connected'] is True


def test_covered_open_land_is_not_counted_as_outdoor_space():
    request = {'site': mapping(box(0, 0, 20, 20)), 'buildable': mapping(box(0, 0, 20, 20))}
    upper, ground = box(0, 0, 10, 10), box(0, 0, 10, 5)
    result = measure_siting(request, [feature('building_footprint', upper)], ground)
    assert result['outdoor']['unoccupied_m2'] == 300
    assert result['building']['upper_m2'] == 100
    assert result['building']['ground_m2'] == 50
    assert result['outdoor']['usable_public_space_status'] == 'unknown'


def test_ramp_arriving_at_ground_is_in_outdoor_occupancy():
    building = box(0, 0, 5, 5)
    result = measure_siting({'site': mapping(box(0, 0, 20, 20))}, [
        feature('building_footprint', building),
        feature('ramp', box(10, 0, 15, 5), level=1, from_level=1, to_level=0)], building)
    assert result['outdoor']['unoccupied_m2'] == 350


def bound():
    brief = {'source_versions': {'programme': {'snapshot_hash': 'programme'}},
             'relations': [{'id': 'r1', 'requirement': {'from': 'a', 'to': 'b', 'kind': 'shares_wall'}}]}
    from backend.app.modules.design.generation.maas.masterplan.siting_relations import brief_digest
    brief['brief_id'] = brief_digest(brief)
    artifacts = {'brief_id': brief['brief_id'], 'programme_snapshot_hash': 'programme', 'geometry_hash': 'geometry',
                 'coordinate_frame': 'metric_local_m', 'features': [
        feature('functional_zone', box(0, 0, 5, 5), space_id='a'),
        feature('functional_zone', box(5, 0, 10, 5), space_id='b')]}
    from backend.app.modules.design.generation.maas.masterplan.geometry import digest
    artifacts['geometry_hash'] = digest(artifacts['features'])
    return brief, artifacts


def test_shared_wall_is_not_a_door_and_different_floors_do_not_connect():
    brief, owner = bound()
    assert evaluate_relations(brief, owner)[0]['status'] == 'passed'
    brief['relations'][0]['requirement']['kind'] = 'direct_door'
    from backend.app.modules.design.generation.maas.masterplan.siting_relations import brief_digest
    brief['brief_id'] = brief_digest(brief)
    owner['brief_id'] = brief['brief_id']
    assert evaluate_relations(brief, owner)[0]['status'] == 'unknown'
    brief['relations'][0]['requirement']['kind'] = 'shares_wall'
    brief['brief_id'] = brief_digest(brief)
    owner['brief_id'] = brief['brief_id']
    owner['features'][1]['properties']['level'] = 1
    from backend.app.modules.design.generation.maas.masterplan.geometry import digest
    owner['geometry_hash'] = digest(owner['features'])
    assert evaluate_relations(brief, owner)[0]['status'] == 'failed'


def test_stale_or_missing_owner_evidence_keeps_every_requirement_unknown():
    brief, owner = bound()
    owner['programme_snapshot_hash'] = 'old'
    result = evaluate_relations(brief, owner)
    assert len(result) == 1 and result[0]['status'] == 'unknown'
    assert result[0]['relation_id'] == 'r1'


def test_changed_requirement_with_unchanged_identity_is_not_accepted():
    brief, owner = bound()
    brief['relations'][0]['requirement']['kind'] = 'near'
    brief['relations'][0]['requirement']['max_distance_m'] = 100
    assert evaluate_relations(brief, owner)[0]['status'] == 'unknown'


def test_relation_evaluation_is_available_through_owner_operation():
    from backend.app.modules.design.generation.maas.masterplan_operations import invoke
    brief, owner = bound()
    result = invoke({'operation': 'evaluate_siting_relations', 'arguments': {'brief': brief, 'owner_artifacts': owner}})
    assert result['status'] == 'succeeded'
    assert result['result']['relations'][0]['status'] == 'passed'


def test_invalid_area_geometry_is_reported_without_crashing_diagnostics():
    result = measure_siting({'site': mapping(box(0, 0, 20, 20))}, [
        feature('building_footprint', LineString([(0, 0), (5, 5)]))], box(0, 0, 5, 5))
    assert result['invalid_area_features']
    assert result['outdoor']['unoccupied_m2'] is None


def test_component_count_ignores_sub_tolerance_area_but_keeps_small_real_pockets():
    from shapely.geometry import MultiPolygon
    from backend.app.modules.design.generation.maas.masterplan.siting_relations import _parts, TOL
    ground = MultiPolygon([box(0, 0, 10, 10), box(20, 0, 20.01, .01),
                           box(30, 0, 30+TOL/10, TOL/10)])
    assert len(_parts(ground)) == 2
