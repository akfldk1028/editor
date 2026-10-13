import copy
import json
import math
from pathlib import Path

import pytest
from shapely.affinity import rotate
from shapely.geometry import mapping, shape

from backend.app.modules.design.generation.maas.masterplan.planner import plan_site
from backend.app.modules.design.generation.maas.masterplan.geometry import digest


def request():
    return json.loads((Path(__file__).parent/'fixtures/real_668_default_placement.json').read_text(encoding='utf8'))


def test_known_parking_demand_searches_locations_without_a_surface_split():
    req = request()
    assert 'target_surface_stalls' not in req['options']
    original = copy.deepcopy(req)
    result = plan_site(req)
    assert result['joint_search']['proposed_placements'] > 0
    assert result['joint_search']['screen_demand'] == req['law']['required_spaces']
    assert result['handoff']['input_hash'] == digest(original)
    assert req == original


def test_inferred_screen_bound_respects_surface_cap_without_changing_law():
    req = request()
    req['options']['max_surface_stalls'] = 1
    result = plan_site(req)
    assert result['joint_search']['screen_demand'] == 1
    assert result['metrics']['required_parking_stalls'] == 3
    assert 'target_surface_stalls' not in req['options']


def test_multiline_axis_fallback_and_explicit_priority():
    from backend.app.modules.design.generation.maas.masterplan.layout_axis import planning_axis_angle
    req = request()
    req['front_frontage'] = None
    line = max(shape(req['frontage']).geoms, key=lambda g:g.length)
    a,b = list(line.coords)[0],list(line.coords)[-1]
    expected = math.degrees(math.atan2(b[1]-a[1],b[0]-a[0])) % 180
    assert planning_axis_angle(req) == pytest.approx(expected)
    req['options']['layout_axis'] = {'frame':'site_local','vector':[1,1],'source':'test design'}
    assert planning_axis_angle(req) == pytest.approx(45)


@pytest.mark.parametrize('rotation', [0, 37, 83])
def test_multiline_frontage_does_not_freeze_search_to_world_zero(rotation):
    req = request()
    req['options']['joint_placement_search'] = False
    for key, value in list(req.items()):
        if isinstance(value, dict) and value.get('type') in ('Polygon', 'MultiPolygon', 'LineString', 'MultiLineString'):
            req[key] = mapping(rotate(shape(value), rotation, origin=(0,0)))
    line = shape(req['front_frontage'])
    a,b = list(line.coords)[0],list(line.coords)[-1]
    expected = math.degrees(math.atan2(b[1]-a[1],b[0]-a[0])) % 180
    result = plan_site(req)
    assert result['metrics']['layout_axis']['angle_deg'] == pytest.approx(expected)
