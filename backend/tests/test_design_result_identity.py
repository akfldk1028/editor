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
