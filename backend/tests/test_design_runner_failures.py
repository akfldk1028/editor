import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize('case', ['all_fail', 'one_fail', 'single_fail', 'cancel', 'infeasible'])
def test_runner_failures_are_durable_and_distinct_from_cancel_or_infeasibility(tmp_path, case):
    script = r'''
import os, threading, time
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime
ensure_design_runtime()
from backend.app.api.design_runtime import views
from backend.app.adapters.design_storage.models import OptimizationJobEvent
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.api.routes_design_runtime import create_design_runtime_router
case = os.environ['TEST_RUNNER_CASE']
entered, release = threading.Event(), threading.Event()
original = views.evaluate_designs
def evaluate(designs, *args, **kwargs):
    algorithm = args[4]
    if case == 'cancel':
        entered.set()
        assert release.wait(10)
        raise RuntimeError('failure after cancellation')
    if case in {'all_fail', 'single_fail'} or (case == 'one_fail' and algorithm == 'additive'):
        raise RuntimeError('injected evaluator failure')
    if case == 'infeasible':
        outputs = args[2]
        return [[(o['val'] + 100 if o['Requirement'] == 'Less than' else o['val'] - 100)
                 if o['type'] == 'Constraint' else 1.0 for o in outputs] for d in designs]
    return original(designs, *args, **kwargs)
views.evaluate_designs = evaluate
app = FastAPI(); app.include_router(create_design_runtime_router())
c = TestClient(app)
site = {'type':'Polygon','coordinates':[[[127,37.5],[127.0005,37.5],[127.0005,37.5005],[127,37.5005],[127,37.5]]]}
body = {'site_polygon':site,'job_spec':{'options':{'algorithm':'additive' if case == 'single_fail' else 'all','Number of generations':1,'num_islands':1,'pop_per_island':2}}}
if case == 'infeasible':
    body['constraints'] = [{'name':'height','type':'Constraint','Requirement':'Less than','val':1}]
created = c.post('/api/v1/design/jobs', json=body)
assert created.status_code == 202, created.text
job_id = created.json()['id']; base = '/api/v1/design/jobs/' + job_id
assert c.post(base + '/run', json={}).status_code == 202
if case == 'cancel':
    assert entered.wait(10)
    assert c.post(base + '/cancel',json={}).json()['status'] == 'cancelled'
    release.set()
for _ in range(300):
    state = c.get(base).json()
    if state['status'] in {'complete','failed','cancelled'}: break
    time.sleep(.05)
time.sleep(.1)
events = list(OptimizationJobEvent.objects.filter(job_id=job_id).values_list('payload',flat=True))
if case in {'all_fail', 'one_fail', 'single_fail'}:
    assert state['status'] == 'failed', state
    assert 'injected evaluator failure' in state['error']
    assert events[-1]['type'] == 'error', events
    assert not any(event['type'] == 'complete' for event in events)
    if case != 'single_fail':
        expected = 10 if case == 'all_fail' else 1
        assert len(events[-1]['algorithm_errors']) == expected
elif case == 'cancel':
    assert c.get(base).json()['status'] == 'cancelled'
    assert [e['type'] for e in events if e['type'] in {'complete','cancelled','error'}] == ['cancelled']
else:
    assert state['status'] == 'complete', state
    assert events[-1]['type'] == 'complete'
    assert events[-1]['pareto_front'] == []
assert c.get(base + '/results').json()['total_designs'] == 0
'''
    result = subprocess.run([sys.executable, '-c', script], cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, 'EDITOR_DESIGN_DATA_DIR': str(tmp_path), 'EDITOR_DESIGN_DATABASE': str(tmp_path / 'jobs.sqlite3'), 'TEST_RUNNER_CASE': case},
        capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr
