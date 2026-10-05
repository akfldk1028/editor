from copy import deepcopy
import pytest
from shapely.geometry import box, LineString, mapping, shape
from backend.app.modules.design.generation.maas.masterplan import core_repacking as engine
from backend.app.modules.design.generation.maas.masterplan.geometry import feature


@pytest.mark.parametrize('explicit_axis', [False, True])
@pytest.mark.parametrize('review_pending', [False, True, 'check_only'])
@pytest.mark.parametrize('empty_frontage', [False, True])
def test_repacking_preserves_ramp_constraints_and_recomputes_excavation(monkeypatch, explicit_axis, review_pending, empty_frontage):
    plate, ramp = box(0, 0, 20, 20), box(20, 0, 26, 20)
    core = box(2, 2, 4, 6)
    profile = [{'distance_m': 0, 'z_m': 0}, {'distance_m': 4, 'z_m': 0},
               {'distance_m': 16, 'z_m': -3}, {'distance_m': 20, 'z_m': -3}]
    r = {'pnu': 'test', 'crs': 'local', 'site': mapping(box(0, 0, 30, 30)),
         'basement_boundary': mapping(plate), 'footprint': mapping(plate),
         'core': mapping(core), 'frontage': mapping(LineString([(0, 0), (20, 0)])),
         'options': {'allow_core_repair': True, 'core_vehicle_clearance_m': 1.5,
                     'basement_floor_height_m': 3, 'target_parking_stalls': 1,
                     'vehicle': {'turning_radius_outer_m': 7.2}, 'turn_lane_m': 6.5},
         'law': {}, 'rules': {'aisle_width_m': 6, 'stall_width_m': 2.5, 'stall_length_m': 5}}
    source = {'features': [feature('basement_boundary', plate.union(ramp), -1),
               feature('building_core', core, 0), feature('building_core', core, -1),
               feature('ramp', ramp, 0, from_level=0, to_level=-1, width_m=6, profile=profile),
               feature('ramp_centerline', LineString([(23, 0), (23, 20)]), 0, from_level=0, to_level=-1)],
              'metrics': {'area_per_stall_m2': 999, 'excavation_over_footprint': 999},
              'levels': [{'level': 0, 'provided_spaces': 0}], 'blocking': []}
    original = deepcopy(source)
    from shapely.geometry import MultiLineString
    r['frontage'] = mapping(MultiLineString([[(0, 0), (1, 0)], [(0, 0), (0, 20)]]))
    if empty_frontage:
        r['frontage'] = mapping(LineString([(0, 0), (0, 0)]))
    if explicit_axis:
        r['options']['layout_axis'] = {'frame': 'site_local', 'vector': [1, 1], 'source': 'fixture'}
    captured = []
    def solve(*args, **kwargs):
        captured.append(kwargs)
        return {'zone': None, 'parking': {'stalls': [{'polygon': box(5, 6, 7.5, 11),
                 'type': 'standard_90deg', 'width_m': 2.5, 'length_m': 5}],
                 'drive': box(0, 0, 20, 6), 'provided': 1, 'accessible': 0}}
    monkeypatch.setattr(engine, 'solve_basement_level', solve)
    monkeypatch.setattr(engine, 'validate_plan', lambda *a: {'checks': [{'id': 'owner_review', 'status': 'needs_evidence'}] if review_pending == 'check_only' else [], 'geometry_status': 'needs_evidence' if review_pending is True else 'passed'})
    if empty_frontage and not explicit_axis:
        with pytest.raises(ValueError, match='nonzero frontage'):
            engine.repack_core(r, source)
        assert not captured
        return
    result = engine.repack_core(r, source)
    assert source == original
    assert captured[0]['turn_radius_m'] == 7.2
    assert captured[0]['turn_lane_m'] == 6.5
    assert captured[0]['require_full_width'] is True
    assert captured[0]['angle'] == pytest.approx(45 if explicit_axis else 90)
    assert result['status'] == ('needs_evidence' if review_pending else 'resolved')
    basement = next(f for f in result['features'] if f['properties']['layer'] == 'basement_boundary')
    assert shape(basement['geometry']).covers(ramp)
    assert result['metrics']['excavation_m2'] == 520
    assert result['metrics']['excavation_over_footprint'] == pytest.approx(1.3)
    stats = engine.level_efficiency(result['features'], r['rules'])
    assert result['metrics']['area_per_stall_m2'] == round(sum(v['parking_area_m2'] for v in stats.values()), 2)
    assert [f for f in result['features'] if f['properties']['layer'] == 'ramp'] == [original['features'][3]]


def test_small_packer_filters_width_before_choosing_a_winner():
    from backend.app.modules.design.generation.maas.masterplan.bounded_packing import pack_level, _width_connected
    # A real wide field entered through a narrow throat must not be selected
    # merely because the polygons touch and it holds many stalls.
    host = box(0, 0, 24, 32).union(box(-8, 14, 0, 16))
    entrance = LineString([(-8, 14), (-8, 16)])
    rules = {'aisle_width_m': 6, 'stall_width_m': 2.5, 'stall_length_m': 5,
             'accessible_width_m': 3.3, 'accessible_length_m': 5}
    got = pack_level(host, [entrance], rules, 20, require_full_width=True)
    assert not got['stalls'] or _width_connected(got, [entrance], 6)
