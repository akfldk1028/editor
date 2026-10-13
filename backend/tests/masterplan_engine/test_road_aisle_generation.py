from copy import deepcopy
import sys
from types import SimpleNamespace
from shapely.geometry import box, mapping, LineString, shape
from backend.app.modules.design.generation.maas.masterplan.geometry import feature


def request_fixture():
    return {'site':mapping(box(0,0,10,8)), 'rules':{'stall_width_m':2.5, 'stall_length_m':5},
            'law':{'required_accessible_spaces':0}, 'options':{'parking_strategy':'ground_surface'},
            'road_aisle_context':{'present':True}}


def install_scope(monkeypatch, *, included=None, status='ready'):
    included = box(0,-3,10,0) if included is None else included
    scope = {'status':status, 'road':box(0,-5,10,0), 'included':included,
             'frontage':LineString([(0,0),(10,0)]), 'required_width_m':6,
             'max_total_spaces':8, 'law':{'input_identity':{'parking_angle':'perpendicular'}}}
    monkeypatch.setitem(sys.modules, 'backend.app.modules.design.generation.maas.masterplan.road_aisle',
                        SimpleNamespace(scope=lambda request:scope))


def test_shallow_site_uses_real_road_depth_without_moving_mass(monkeypatch):
    install_scope(monkeypatch)
    from backend.app.modules.design.generation.maas.masterplan.road_aisle_generation import generate
    request = request_fixture()
    base = [feature('building_footprint',box(8,7,10,8))]
    before = deepcopy(base)
    candidates = generate(request,base,3)
    assert candidates
    candidate = max(candidates,key=lambda c:c['provided'])
    assert candidate['provided'] == 3
    assert candidate['features'][0] == before[0] and base == before
    stalls = [shape(f['geometry']) for f in candidate['features'] if f['properties']['layer']=='parking_stall']
    external = [shape(f['geometry']) for f in candidate['features'] if f['properties']['layer']=='external_road_aisle']
    assert all(shape(request['site']).covers(stall) for stall in stalls)
    assert all(box(0,-3,10,0).covers(road) for road in external)
    assert all(road.intersection(shape(request['site'])).area == 0 for road in external)
    assert min(stall.bounds[1] for stall in stalls) >= 3


def test_insufficient_external_depth_cannot_fake_shallow_site_fit(monkeypatch):
    install_scope(monkeypatch,included=box(0,-1,10,0))
    from backend.app.modules.design.generation.maas.masterplan.road_aisle_generation import generate
    assert generate(request_fixture(),[],3) == []


def test_missing_law_does_not_generate(monkeypatch):
    install_scope(monkeypatch,status='needs_evidence')
    from backend.app.modules.design.generation.maas.masterplan.road_aisle_generation import generate
    assert generate(request_fixture(),[],3) == []


def test_surface_cap_and_blocked_frontage_are_preserved(monkeypatch):
    install_scope(monkeypatch)
    from backend.app.modules.design.generation.maas.masterplan.road_aisle_generation import generate
    request=request_fixture()
    request['options']['max_surface_stalls']=1
    assert max(c['provided'] for c in generate(request,[],3))==1
    request['vehicle_prohibited']=mapping(LineString([(0,0),(10,0)]))
    assert generate(request,[],3)==[]

import json
import pytest


@pytest.mark.parametrize('angle',[0,37])
def test_planner_road_candidate_improves_shallow_site_and_revalidates_serialization(angle):
    from test_road_aisle_geometry import case
    from backend.app.modules.design.generation.maas.masterplan.planner import plan_site
    from backend.app.modules.design.generation.maas.masterplan.validation import validate_plan
    request,_=case()
    from shapely.affinity import scale, rotate
    from backend.app.modules.design.generation.maas.masterplan.geometry import digest
    def transform(g):
        return mapping(rotate(scale(shape(g),xfact=2/3,yfact=1,origin=(0,0)),angle,origin=(0,0)))
    for key in ('site','footprint','frontage'):
        request[key]=transform(request[key])
    context=request['road_aisle_context']
    for key in ('road_polygon','included_road_polygon','frontage'):
        context[key]=transform(context[key])
        context['source_context'][key]=deepcopy(context[key])
    context['source_context_hash']=digest(context['source_context'])
    request['evidence']['road_aisle_law']['source_context_hash']=context['source_context_hash']
    request['rules'].update(accessible_width_m=3.3,accessible_length_m=5,entrance_width_m=3)
    request['law'].update(bcr_pct=60,status='resolved')
    request['options'].update(parking_strategy='ground_surface',max_basement_levels=0,
                              joint_placement_search=False,compact_basement_search=False)
    baseline_request=deepcopy(request)
    del baseline_request['road_aisle_context']
    baseline=plan_site(baseline_request)
    result=plan_site(request)
    assert result['metrics']['provided_parking_stalls'] > baseline['metrics']['provided_parking_stalls'], result['alternatives']
    assert result['metrics']['provided_parking_stalls']==2
    assert any(row.get('pattern')=='road_as_aisle' for row in result['alternatives'])
    assert any(row.get('pattern')!='road_as_aisle' for row in result['alternatives'])
    mass=next(f for f in result['features'] if f['properties']['layer']=='building_footprint')
    assert shape(mass['geometry']).symmetric_difference(shape(request['footprint'])).area < 1e-6
    serialized=json.loads(json.dumps({'features':result['features']}))
    report=validate_plan(json.loads(json.dumps(request)),serialized)
    assert report['geometry_status']=='passed', [c for c in report['checks'] if c['status']=='failed']
    assert report['external_road_aisle']['area_m2'] > 0
    assert 'road_aisle_vehicle_maneuver_review' in report['pending_reviews']
