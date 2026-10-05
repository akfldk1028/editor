import os
from pathlib import Path
import subprocess
import sys


def test_candidate_identity_survives_front_reordering_and_reappearance():
    from backend.app.api.design_runtime.result_identity import canonicalize_result_event
    ids = {}
    first = {'id': 7, 'uid': 'additive:7', 'algorithm': 'additive'}
    second = {'id': 7, 'uid': 'subtractive:7', 'algorithm': 'subtractive'}
    initial = canonicalize_result_event({'type': 'generation', 'pareto_front': [first, second], 'best': second}, ids)
    intermediate = canonicalize_result_event({'type': 'generation', 'pareto_front': [second]}, ids)
    final = canonicalize_result_event({'type': 'complete', 'pareto_front': [second, first]}, ids)
    assert [row['id'] for row in initial['pareto_front']] == [0, 1]
    assert initial['best']['id'] == intermediate['pareto_front'][0]['id'] == 1
    assert [row['id'] for row in final['pareto_front']] == [1, 0]
    assert first['id'] == second['id'] == 7
    assert all(row['source_design_id'] == 7 for row in final['pareto_front'])


def test_real_all_mode_result_ids_and_legacy_ambiguity(tmp_path):
    script = r'''
import random, time
random.seed(41)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.api.routes_design_runtime import create_design_runtime_router
app = FastAPI()
app.include_router(create_design_runtime_router())
c = TestClient(app, raise_server_exceptions=False)
site = {'type':'Polygon','coordinates':[[[127,37.5],[127.0005,37.5],[127.0005,37.5005],[127,37.5005],[127,37.5]]]}
created = c.post('/api/v1/design/jobs', json={'site_polygon':site,'job_spec':{'options':{'algorithm':'all','Number of generations':1,'num_islands':1,'pop_per_island':2}}})
assert created.status_code == 202, created.text
base = '/api/v1/design/jobs/' + created.json()['id']
assert c.post(base + '/run', json={}).status_code == 202
for _ in range(200):
    state = c.get(base).json()
    if state['status'] in {'complete','failed','cancelled'}: break
    time.sleep(.05)
assert state['status'] == 'complete', state
results = c.get(base + '/results').json()['designs']
assert len(results) > 1
ids = [d['design_id'] for d in results]
assert len(ids) == len(set(ids)), ids
from backend.app.adapters.design_storage.models import OptimizationJobEvent, OptimizationJob, DesignResult
events = list(OptimizationJobEvent.objects.filter(job_id=created.json()['id']).values_list('payload',flat=True))
identity_ids = {}
for event in events:
    for design in event.get('pareto_front', []):
        previous = identity_ids.setdefault(design['uid'], design['id'])
        assert previous == design['id']
    for feature in event.get('pareto_geojson', []):
        assert identity_ids[feature['properties']['design_uid']] == feature['properties']['design_id']
for result in results:
    identity = result['outputs']['result_identity']
    assert identity['uid'] == identity['algorithm'] + ':' + str(identity['source_design_id'])
    assert identity_ids[identity['uid']] == result['design_id']
    detail = c.get(base + '/results/' + str(result['design_id']))
    assert detail.status_code == 200, detail.text
    assert detail.json()['mass_geojson'] == result['mass_geojson']
    evidence = c.get(base + '/results/' + str(result['design_id']) + '/evidence')
    assert evidence.status_code == 200, evidence.text
legacy = OptimizationJob.objects.create(site_polygon=site, job_spec={}, status='complete')
for _ in range(2):
    DesignResult.objects.create(job=legacy, generation=1, design_id=7, inputs=[], outputs={})
legacy_url = '/api/v1/design/jobs/' + str(legacy.id) + '/results/7'
for suffix in ('', '/evidence', '/aesthetic'):
    response = c.post(legacy_url + suffix, json={}) if suffix == '/aesthetic' else c.get(legacy_url + suffix)
    assert response.status_code == 409, response.text
assert legacy.results.count() == 2
count = OptimizationJob.objects.count()
huge = c.post('/api/v1/design/jobs',json={'site_polygon':site,'constraints':[{'name':'height','type':'Constraint','Requirement':'Less than','val':10**400}]})
assert huge.status_code == 400, huge.text
assert OptimizationJob.objects.count() == count
'''
    result = subprocess.run([sys.executable, '-c', script], cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, 'EDITOR_DESIGN_DATA_DIR': str(tmp_path), 'EDITOR_DESIGN_DATABASE': str(tmp_path / 'jobs.sqlite3')},
        capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def test_historical_duplicate_ids_resolve_only_exact_uid_without_mutation(tmp_path):
    script = r'''
import copy, json
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.api.routes_design_runtime import create_design_runtime_router
app=FastAPI()
app.include_router(create_design_runtime_router())
c=TestClient(app,raise_server_exceptions=False)
assert c.get('/api/v1/design/jobs/00000000-0000-0000-0000-000000000000').status_code==404
from backend.app.adapters.design_storage.models import OptimizationJob,DesignResult
site={'type':'Polygon','coordinates':[[[127,37.5],[127.001,37.5],[127.001,37.501],[127,37.501],[127,37.5]]]}
job=OptimizationJob.objects.create(site_polygon=site,site_area_m2=10000,job_spec={},status='complete')
def row(number,uid,offset=0,identity=True,feature_uid=True):
    x=127.0001+offset
    feature={'type':'Feature','geometry':{'type':'Polygon','coordinates':[[[x,37.5001],[x+.00015,37.5001],[x+.00015,37.5003],[x,37.5003],[x,37.5001]]]},
             'properties':{'design_id':number,'height':9,'num_floors':3,'floor_height':3,'marker':uid}}
    if feature_uid: feature['properties']['design_uid']=uid
    outputs={'result_identity':{'uid':uid}} if identity else {}
    return DesignResult.objects.create(job=job,generation=1,design_id=number,inputs=[],outputs=outputs,mass_geojson=feature,is_pareto_optimal=True)
a=row(7,'additive:7',identity=False)
b=row(7,'subtractive:7',.0004,feature_uid=False)
row(8,'tower:8')
conflict=row(9,'stored:9')
conflict.mass_geojson['properties']['design_uid']='conflicting:9'
conflict.save()
for _ in range(2): row(11,'unknown',identity=False,feature_uid=False)
for _ in range(2): row(12,'repeated:12')
before=list(DesignResult.objects.order_by('pk').values())
base='/api/v1/design/jobs/'+str(job.id)+'/results/'
def request(number,suffix,uid=None,body=None):
    query={'design_uid':uid} if uid is not None else {}
    return c.post(base+str(number)+suffix,params=query,json=body or {}) if suffix=='/aesthetic' else c.get(base+str(number)+suffix,params=query)
for selected in (a,b):
    uid=selected.mass_geojson['properties']['marker']
    detail=request(7,'',uid)
    assert detail.status_code==200,detail.text
    assert detail.json()['mass_geojson']==selected.mass_geojson
    assert detail.json()['design_uid']==uid
    evidence=request(7,'/evidence',uid)
    assert evidence.status_code==200,evidence.text
    assert evidence.json()['geometry']['mass_geojson']==selected.mass_geojson
    assert evidence.json()['candidate']['design_uid']==uid
    aesthetic=request(7,'/aesthetic',body={'design_uid':uid,'provider':'placeholder','attach_to_evidence':True})
    assert aesthetic.status_code==200,aesthetic.text
    payload=aesthetic.json()
    assert payload['job']['locked_geometry']['mass_geojson']==selected.mass_geojson,payload
    assert payload['evidence']['candidate']['design_uid']==uid,payload
for suffix in ('','/evidence','/aesthetic'):
    for number,uid,status in [(7,None,409),(7,'unknown:7',404),(7,'tower:8',404),(8,'additive:7',404),
                              (9,'stored:9',409),(9,'conflicting:9',409),(11,'unknown',404),(12,'repeated:12',409),
                              (7,'',400),(7,'  additive:7',404)]:
        response=request(number,suffix,uid)
        assert response.status_code==status,(number,uid,suffix,response.status_code,response.text)
    assert request(8,suffix).status_code==200
response=request(7,'/aesthetic','additive:7',{'design_uid':'subtractive:7'})
assert response.status_code==400,response.text
for invalid in ([],None,7,{'nested':'uid'}):
    response=request(7,'/aesthetic',body={'design_uid':invalid})
    assert response.status_code==400,response.text
assert c.get(base+'7/evidence?design_uid=additive%3A7&design_uid=subtractive%3A7').status_code==400
assert list(DesignResult.objects.order_by('pk').values())==before
print('UID detail, real evidence and placeholder aesthetic preserve every stored row')
'''
    result = subprocess.run([sys.executable, '-c', script], cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, 'EDITOR_DESIGN_DATA_DIR': str(tmp_path), 'EDITOR_DESIGN_DATABASE': str(tmp_path / 'uid.sqlite3')},
        capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
