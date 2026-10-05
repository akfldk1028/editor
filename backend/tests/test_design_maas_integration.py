"""Synthetic geometry integration: supplied caps are not verified parcel law."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


OFFLINE = r'''
import inspect, os, socket, sys
sys.dont_write_bytecode = True
for key in ('OPENAI_API_KEY','GOOGLE_API_KEY','GEMINI_API_KEY','NEO4J_URI',
            'NEO4J_PASSWORD','LAW_BACKEND_URL','AG_LIGHT_URL','MASS_BRAIN_URL'):
    os.environ.pop(key, None)
os.environ.update(MAAS_DISABLE_PARKING_NEO4J='1', MAAS_CLONE_IMPORT='0',
                  MAAS_D4DESCENT_IMPORT='0', MAAS_LIVE_GEOMETRY_VLM='0')
original_connect = socket.socket.connect
def no_network(self, *args, **kwargs):
    # Windows implements asyncio's internal wake-up socketpair with TCP.
    if inspect.currentframe().f_back.f_code.co_name == '_fallback_socketpair':
        return original_connect(self, *args, **kwargs)
    raise OSError('Network disabled for synthetic geometry integration')
socket.socket.connect = no_network
'''


GEOMETRY = r'''
from shapely.geometry import box, mapping, LineString
from pyproj import Transformer
from backend.app.modules.design.generation.services.site_geometry import utm_to_wgs84
x,y = Transformer.from_crs('EPSG:4326','EPSG:32652',always_xy=True).transform(127,37.5)
site_utm = box(x,y,x+40,y+40)
site = mapping(utm_to_wgs84(site_utm))
mass = {'type':'Feature','geometry':mapping(utm_to_wgs84(box(x+8,y+8,x+32,y+32))),
        'properties':{'num_floors':4,'height':12,'floor_height':3}}
constraints = [{'name':name,'type':'Constraint','Requirement':requirement,'val':value}
    for name,requirement,value in [('bcr','Less than',60),('far','Less than',200),
                                 ('height','Less than',30),('setback','Greater than',.5)]]
road = {'road_width_m':8,'has_sidewalk_separation':True,
        'frontage_geometry':mapping(utm_to_wgs84(LineString([(x,y),(x+40,y)])))}
'''


def isolated(script, tmp_path, timeout=120):
    env = dict(os.environ, EDITOR_DESIGN_DATA_DIR=str(tmp_path),
               EDITOR_DESIGN_DATABASE=str(tmp_path / 'execution.sqlite3'),
               PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
    try:
        child = subprocess.run([sys.executable, '-c', OFFLINE + script],
            cwd=Path(__file__).resolve().parents[2], env=env, text=True,
            encoding='utf-8', capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f'Design integration exceeded {timeout}s; trace: {exc.stdout!r}; stack: {exc.stderr!r}')
    assert child.returncode == 0, child.stdout + child.stderr
    return json.loads(child.stdout.splitlines()[-1])


def test_all_ten_original_algorithms_complete_via_http(tmp_path):
    result = isolated(GEOMETRY + r'''
import json, time
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.api.routes_design_runtime import create_design_runtime_router
app=FastAPI()
app.include_router(create_design_runtime_router())
client=TestClient(app)
created=client.post('/api/v1/design/jobs/',json={'site_polygon':site,'constraints':constraints,
    'job_spec':{'options':{'algorithm':'all','building_type':'업무시설','Number of generations':1,
                          'num_islands':1,'pop_per_island':4,'tournament_size':2,'migrants_count':1}}})
assert created.status_code==202,created.text
job_id=created.json()['id']
started=client.post('/api/v1/design/jobs/'+job_id+'/run/')
assert started.status_code==202,started.text
for _ in range(200):
    job=client.get('/api/v1/design/jobs/'+job_id+'/').json()
    if job['status'] in ('complete','failed','cancelled'):break
    time.sleep(.05)
assert job['status']=='complete',job
from backend.app.adapters.design_storage.models import OptimizationJobEvent
events=[row.payload for row in OptimizationJobEvent.objects.filter(job_id=job_id).order_by('id')]
first=next(event for event in events if event.get('type')=='started')
results=client.get('/api/v1/design/jobs/'+job_id+'/results/').json()
print(json.dumps({'algorithms':first['algorithms'],'job':job,'results':results},default=str))
''', tmp_path, timeout=40)
    assert set(result['algorithms']) == {'additive','subtractive','grid','lshape','ushape',
        'cross','courtyard','tower_podium','hshape','radial'}
    assert result['results']['total_designs'] > 0


def test_maas_explicit_caps_keep_real_geometry_and_normal_gates(tmp_path):
    result = isolated(GEOMETRY + r'''
import json,time
from collections import Counter
from backend.app.modules.design.generation.maas import generate_legal_mass_variants
os.environ['MAAS_PROFILE_GENERATION']='1'
started=time.monotonic()
result=generate_legal_mass_variants(mass_geojson=mass,site_polygon_geojson=site,
    constraints=constraints,building_type='업무시설',max_variants=2,pnu='1168010100106770000',
    preferred_operator='grammar_overlap_shift_terrace',
    parking_options={'road_context':road,'maas_llm_loop':{'enabled':False},
                     'maas_preference_loop':{'enabled':False}})
summary={'seconds':time.monotonic()-started,'count':result['count'],
         'status':result['generation_status'],'reason':result['infeasible_reason'],
         'limits':result['constraints'],'debug':result['selection_debug'],
         'rejected':dict(Counter(item.get('reason') for item in result['rejected'])),
         'features':result['feature_collection']['features']}
print(json.dumps(summary,ensure_ascii=True,default=str))
''', tmp_path, timeout=90)
    print(json.dumps({'seconds':result['seconds'], 'count':result['count'],
        'status':result['status'],
        'parking_pass':result['debug']['legal_pool_parking_mass_stage_pass'],
        'architecture_pass':result['debug']['legal_pool_architecture_order_pass']}, sort_keys=True))
    assert result['limits']['bcr_limit'] == 60
    assert result['limits']['far_limit'] == 200
    assert result['limits']['height_limit'] == 30
    assert result['count'] > 0, result
    assert result['status'] == 'complete'
    assert result['debug']['legal_pool_parking_mass_stage_pass'] > 0
    assert result['debug']['legal_pool_architecture_order_pass'] > 0
    from shapely.geometry import shape
    for feature in result['features']:
        assert shape(feature['geometry']).is_valid
        properties = feature['properties']
        assert properties['bcr'] <= 60.001
        assert properties['far'] <= 200.001
        assert properties['height'] <= 30.001
