"""Exercise durable job ownership and events using isolated real SQLite databases."""
import os
from pathlib import Path
import subprocess
import sys
import textwrap

ROOT = Path(__file__).resolve().parents[2]
LIFECYCLE = ROOT / 'backend/app/adapters/design_storage/lifecycle.py'
PRELUDE = '''
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime
ensure_design_runtime()
import json, threading, time, uuid
from datetime import timedelta
from django.db import connections, close_old_connections
from django.utils import timezone
from backend.app.adapters.design_storage.models import OptimizationJob, OptimizationJobEvent, DesignResult
from backend.app.adapters.design_storage import lifecycle as life

def job():
    return OptimizationJob.objects.create(site_polygon={}, job_spec={})

def wait_terminal(j):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        j.refresh_from_db()
        if j.status in life.TERMINAL:
            return
        time.sleep(.02)
    raise AssertionError('job never reached terminal state')
'''


def run_case(tmp_path, code):
    assert LIFECYCLE.exists(), 'Missing durable design lifecycle'
    env = {**os.environ, 'EDITOR_DESIGN_DATABASE': str(tmp_path / 'jobs.sqlite3'), 'EDITOR_DESIGN_DATA_DIR': str(tmp_path / 'data')}
    result = subprocess.run([sys.executable, '-c', PRELUDE + textwrap.dedent(code)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_concurrent_start_claims_once_and_disconnect_does_not_cancel(tmp_path):
    run_case(tmp_path, '''
    j = job()
    entered, release = threading.Event(), threading.Event()
    def producer(job_id, token):
        life.publish(job_id, token, {'type': 'started'})
        entered.set()
        assert release.wait(5)
        life.publish(job_id, token, {'type': 'complete', 'generations': 2})
    barrier = threading.Barrier(6)
    def contender():
        close_old_connections()
        barrier.wait()
        life.start(j.id, producer)
        connections.close_all()
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=6) as pool:
        attempts = [pool.submit(contender) for _ in range(6)]
        for attempt in attempts: attempt.result()
    assert entered.wait(5)
    stream = life.replay(j.id)
    assert 'event: started' in next(stream)
    stream.close()
    release.set()
    wait_terminal(j)
    assert j.status == 'complete'
    assert list(j.events.values_list('kind', flat=True)) == ['started', 'complete']
    life.start(j.id, producer)
    assert j.events.count() == 2
    ''')


def test_terminal_event_and_results_commit_together_before_replay(tmp_path):
    run_case(tmp_path, '''
    j = job()
    def producer(job_id, token):
        def persist():
            DesignResult.objects.create(job_id=job_id, generation=1, design_id=1, inputs=[])
        life.publish(job_id, token, {'type': 'complete', 'generations': 1}, persist=persist)
    life.start(j.id, producer)
    wait_terminal(j)
    output = ''.join(life.replay(j.id))
    assert 'event: complete' in output
    assert j.results.count() == 1
    last = j.events.latest('id')
    assert ''.join(life.replay(j.id, after=last.id)) == ''
    ''')


def test_persistence_failure_rolls_back_results_and_emits_error(tmp_path):
    run_case(tmp_path, '''
    j = job()
    def producer(job_id, token):
        def persist():
            DesignResult.objects.create(job_id=job_id, generation=1, design_id=1, inputs=[])
            raise RuntimeError('disk failure')
        life.publish(job_id, token, {'type': 'complete'}, persist=persist)
    life.start(j.id, producer)
    wait_terminal(j)
    assert j.status == 'failed'
    assert 'disk failure' in j.error
    assert j.results.count() == 0
    assert list(j.events.values_list('kind', flat=True)) == ['error']
    ''')


def test_cancelled_job_rejects_late_completion_and_unknown_cancel(tmp_path):
    run_case(tmp_path, '''
    j = job()
    token = uuid.uuid4()
    OptimizationJob.objects.filter(id=j.id).update(status='running', execution_token=token, heartbeat_at=timezone.now())
    assert life.cancel(j.id).status == 'cancelled'
    assert not life.publish(j.id, token, {'type': 'complete'}, persist=lambda: (_ for _ in ()).throw(AssertionError('late result saved')))
    assert life.cancel(j.id).status == 'cancelled'
    assert list(j.events.values_list('kind', flat=True)) == ['cancelled']
    try:
        life.cancel(uuid.uuid4())
    except OptimizationJob.DoesNotExist:
        pass
    else:
        raise AssertionError('unknown cancellation succeeded')
    ''')


def test_interrupted_owner_fails_explicitly_without_restarting(tmp_path):
    run_case(tmp_path, '''
    j = job()
    old_token = uuid.uuid4()
    OptimizationJob.objects.filter(id=j.id).update(status='running', execution_token=old_token, heartbeat_at=timezone.now()-timedelta(seconds=120))
    life.start(j.id, lambda *_: (_ for _ in ()).throw(AssertionError('unexpected restart')))
    j.refresh_from_db()
    assert j.status == 'failed'
    assert j.events.get().payload['recovery_required'] is True
    assert not life.publish(j.id, old_token, {'type': 'complete'})
    assert 'event: error' in ''.join(life.replay(j.id))
    ''')


def test_producer_returning_without_terminal_event_fails(tmp_path):
    run_case(tmp_path, '''
    j = job()
    life.start(j.id, lambda *_: None)
    wait_terminal(j)
    assert j.status == 'failed'
    assert 'terminal event' in j.error
    ''')


def test_http_run_and_stream_share_producer_and_replay_terminal(tmp_path):
    run_case(tmp_path, '''
    from django.test import RequestFactory
    from backend.app.api.design_runtime import views
    factory = RequestFactory()
    j = job()
    entered, release = threading.Event(), threading.Event()
    def producer(job_id, token):
        life.publish(job_id, token, {'type': 'started'})
        entered.set()
        assert release.wait(5)
        life.publish(job_id, token, {'type': 'complete'})
    views._produce_job = producer
    response = views.run_job(factory.post('/run'), j.id)
    assert response.status_code == 202
    assert entered.wait(5)
    stream = views.job_stream(factory.get('/stream'), j.id)
    assert stream.status_code == 200
    assert b'event: started' in next(iter(stream.streaming_content))
    stream.close()
    release.set()
    wait_terminal(j)
    replay = views.job_stream(factory.get('/stream'), j.id)
    assert b'event: complete' in b''.join(replay.streaming_content)
    assert j.events.count() == 2
    response = views.cancel_job(factory.post('/cancel'), uuid.uuid4())
    assert response.status_code == 404
    response = views.cancel_job(factory.post('/cancel'), j.id)
    assert json.loads(response.content)['status'] == 'complete'
    bad = views.job_stream(factory.get('/stream', HTTP_LAST_EVENT_ID='wrong'), j.id)
    assert bad.status_code == 400
    ''')


def test_original_engine_persists_real_results_without_stream_client(tmp_path):
    run_case(tmp_path, '''
    from django.test import RequestFactory
    from backend.app.api.design_runtime import views
    from backend.app.modules.design.generation.services.constraint_bridge import build_default_job_spec
    polygon = {'type': 'Polygon', 'coordinates': [[[127.0,37.5],[127.0005,37.5],[127.0005,37.5004],[127.0,37.5004],[127.0,37.5]]]}
    spec = build_default_job_spec(1600, [], 'office', 'additive')
    spec['options'].update({'Number of generations': 1, 'num_islands': 1, 'pop_per_island': 4})
    j = OptimizationJob.objects.create(site_polygon=polygon, site_area_m2=1600, job_spec=spec, max_generations=1, population_size=4)
    response = views.run_job(RequestFactory().post('/run'), j.id)
    assert response.status_code == 202
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        j.refresh_from_db()
        if j.status in life.TERMINAL: break
        time.sleep(.05)
    assert j.status == 'complete', j.error
    assert j.results.count() > 0
    assert all(result.mass_geojson and result.mass_geojson.get('geometry') for result in j.results.all())
    assert j.events.filter(kind='complete').count() == 1
    event = j.events.get(kind='complete')
    assert event.payload['pareto_count'] == j.results.count()
    assert 'event: complete' in ''.join(life.replay(j.id))
    ''')


def test_creation_rejects_invalid_algorithm_budgets_and_spec_before_persist(tmp_path):
    run_case(tmp_path, '''
    from django.test import RequestFactory
    from backend.app.api.design_runtime import views
    polygon = {'type': 'Polygon', 'coordinates': [[[127.0,37.5],[127.0005,37.5],[127.0005,37.5004],[127.0,37.5004],[127.0,37.5]]]}
    factory = RequestFactory()
    invalid = [
        {'options': {'algorithm': 'unknown'}},
        {'options': {'Number of generations': 0}},
        {'options': {'Number of generations': -1}},
        {'options': {'Number of generations': True}},
        {'options': {'Number of generations': 10000000}},
        {'options': {'num_islands': []}},
        {'options': {'pop_per_island': 1}},
        {'options': []},
        {'inputs': [], 'outputs': []},
        {'inputs': [{}], 'outputs': [{}]},
        [],
    ]
    for spec in invalid:
        request = factory.post('/jobs', json.dumps({'site_polygon': polygon, 'job_spec': spec}), content_type='application/json')
        result = views.create_job(request)
        assert result.status_code == 400, (spec, result.content)
    assert OptimizationJob.objects.count() == 0
    ''')


def test_empty_final_geometry_fails_instead_of_persisting_false_completion(tmp_path):
    run_case(tmp_path, '''
    from backend.app.api.design_runtime import views
    j = job()
    event = {'type': 'complete', 'pareto_front': [{'id': 1, 'inputs': []}]}
    def producer(job_id, token):
        life.publish(job_id, token, event, persist=lambda: views._save_final_results(j, event, None, 1600))
    life.start(j.id, producer)
    wait_terminal(j)
    assert j.status == 'failed'
    assert j.results.count() == 0
    assert not j.events.filter(kind='complete').exists()
    ''')



def test_get_status_recovers_expired_worker_and_persists_error(tmp_path):
    run_case(tmp_path, '''
    from django.test import RequestFactory
    from backend.app.api.design_runtime import views
    j = job()
    OptimizationJob.objects.filter(id=j.id).update(status='running', heartbeat_at=timezone.now()-timedelta(seconds=120))
    response = views.get_job(RequestFactory().get('/status'), j.id)
    assert response.status_code == 200
    assert json.loads(response.content)['status'] == 'failed'
    assert j.events.get().payload['recovery_required'] is True
    ''')


def test_separate_processes_cannot_start_the_same_job_twice(tmp_path):
    worker = r"""
import os, sys, time
from pathlib import Path
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime
ensure_design_runtime()
from backend.app.adapters.design_storage import lifecycle as life
from backend.app.adapters.design_storage.models import OptimizationJob
job_id = sys.argv[1]
marker = Path(os.environ['EDITOR_DESIGN_DATABASE']).with_suffix('.starts')
def produce(job_id, token):
    with marker.open('a') as output:
        output.write(str(token) + '\n')
    time.sleep(.3)
    life.publish(job_id, token, {'type': 'complete'})
life.start(job_id, produce)
deadline = time.monotonic()+10
while time.monotonic() < deadline:
    if OptimizationJob.objects.get(id=job_id).status in life.TERMINAL:
        break
    time.sleep(.02)
else:
    raise AssertionError('worker did not complete')
"""
    run_case(tmp_path, f'''
    import subprocess, sys, os
    from pathlib import Path
    j = job()
    children = [subprocess.Popen([sys.executable, '-c', {worker!r}, str(j.id)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(4)]
    for child in children:
        stdout, stderr = child.communicate(timeout=15)
        assert child.returncode == 0, stdout + stderr
    j.refresh_from_db()
    assert j.status == 'complete'
    assert j.events.filter(kind='complete').count() == 1
    assert len(Path(os.environ['EDITOR_DESIGN_DATABASE']).with_suffix('.starts').read_text().splitlines()) == 1
    ''')


def test_maas_never_reports_legacy_seed_as_success_after_generation_failure(tmp_path):
    run_case(tmp_path, '''
    from unittest.mock import patch
    from backend.app.api.design_runtime import views
    for mode in ('missing-seed', 'exception', 'empty'):
        j = job()
        event = {'type': 'complete'}
        if mode != 'missing-seed':
            event['best_geojson'] = {'type': 'Feature', 'geometry': {}, 'properties': {}}
        def variants(**kwargs):
            if mode == 'exception':
                raise RuntimeError('generator unavailable')
            return {'generation_status': 'infeasible', 'infeasible_reason': 'parking_evidence_missing', 'feature_collection': {'features': []}}
        def producer(job_id, token):
            converted = views._maas_client_event(event, site_polygon_geojson={}, constraints=[], building_type='office')
            life.publish(job_id, token, converted)
        with patch.object(views, 'generate_legal_mass_variants', variants):
            life.start(j.id, producer)
            wait_terminal(j)
        assert j.status == 'failed', mode
        assert 'MAAS' in j.error
        if mode == 'empty':
            assert 'infeasible' in j.error
            assert 'parking_evidence_missing' in j.error
        assert not j.events.filter(kind='complete').exists()
        assert j.events.get().kind == 'error'
    ''')
