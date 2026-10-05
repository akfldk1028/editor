from concurrent.futures import ThreadPoolExecutor
import json

import pytest

from backend.app.modules.design.native_service import NativeDesignService
from backend.app.modules.design.execution import ExecutionService, ExecutionConflict
from backend.app.modules.design.worker import run_once


@pytest.fixture
def service(tmp_path):
    native = NativeDesignService(tmp_path)
    job = native.create('local','project','scene',2,'spec',{'site_polygon':{'type':'Polygon','coordinates':[[
        [127,37.5],[127.001,37.5],[127.001,37.501],[127,37.501],[127,37.5]]]},
        'job_spec':{'options':{'algorithm':'additive','building_type':'업무시설',
            'Number of generations':2,'num_islands':2,'pop_per_island':8,'tournament_size':4}}})
    return ExecutionService(tmp_path), job


def enqueue(service, job, request='run', seed=42):
    return service.enqueue('local','project',job['job_id'],request,seed,2,True)


def test_request_idempotency_scope_and_concurrent_claim(service):
    execution, job = service
    with ThreadPoolExecutor(4) as pool:
        attempts = list(pool.map(lambda _:enqueue(execution,job),range(4)))
    assert len({a['attempt_id'] for a in attempts}) == 1
    with pytest.raises(ExecutionConflict):enqueue(execution,job,seed=43)
    assert execution.get('other','project',attempts[0]['attempt_id']) is None
    with ThreadPoolExecutor(4) as pool:
        claims = list(pool.map(lambda _:execution.store.claim(),range(4)))
    assert sum(c is not None for c in claims) == 1


def test_real_worker_commits_result_and_events_with_immutable_job(service):
    execution, job = service
    before = execution.jobs.path.read_bytes()
    attempt = enqueue(execution,job)
    assert run_once(execution)
    complete = execution.get('local','project',attempt['attempt_id'])
    assert complete['status'] == 'computed'
    result = execution.result('local','project',attempt['attempt_id'])
    assert result['total_evaluated'] == 20 and result['candidates']
    events = execution.events('local','project',attempt['attempt_id'],after=0)
    assert [e['sequence'] for e in events] == list(range(1,len(events)+1))
    assert events[-1]['type'] == 'computed'
    assert execution.events('local','project',attempt['attempt_id'],after=events[-2]['sequence']) == events[-1:]
    assert execution.jobs.path.read_bytes() == before
    assert not run_once(execution)


def test_queued_cancel_never_computes_and_restart_is_explicit(service):
    execution, job = service
    attempt = enqueue(execution,job)
    execution.cancel('local','project',attempt['attempt_id'])
    assert not run_once(execution)
    assert execution.get('local','project',attempt['attempt_id'])['status'] == 'cancelled'
    restarted = enqueue(execution,job,'restart')
    assert restarted['attempt_id'] != attempt['attempt_id']
    assert run_once(execution)


def test_lost_worker_is_interrupted_and_stale_token_cannot_finish(service):
    execution, job = service
    attempt = enqueue(execution,job)
    claim = execution.store.claim()
    assert run_once(execution) is False
    assert execution.get('local','project',attempt['attempt_id'])['status'] == 'interrupted'
    with pytest.raises(ExecutionConflict):
        execution.store.event(claim['attempt_id'],claim['token'],{'type':'generation'})


def test_compute_failure_persists_failure_without_result(service):
    execution, job = service
    attempt = enqueue(execution,job)
    def fail(*args, **kwargs):raise ValueError('bad evaluator')
    assert run_once(execution,compute_fn=fail)
    assert execution.get('local','project',attempt['attempt_id'])['status'] == 'failed'
    assert execution.result('local','project',attempt['attempt_id']) is None


def test_running_cancellation_retains_partial_result(service):
    from backend.app.modules.design.optimization.service import compute
    execution,job=service
    attempt=enqueue(execution,job)
    def cancelling(prepared,**kwargs):
        forward=kwargs['on_event']
        def event(value):
            forward(value)
            if value['type']=='generation':execution.cancel('local','project',attempt['attempt_id'])
        return compute(prepared,**{**kwargs,'on_event':event})
    assert run_once(execution,compute_fn=cancelling)
    assert execution.get('local','project',attempt['attempt_id'])['status']=='cancelled'
    result=execution.result('local','project',attempt['attempt_id'])
    assert result['status']=='cancelled' and result['total_evaluated']==16


def test_terminal_event_failure_rolls_back_result_and_success(service,monkeypatch):
    execution,job=service
    attempt=enqueue(execution,job)
    original=execution.store.append
    def fail(db,identifier,event):
        if event['type']=='computed':raise OSError('injected terminal write failure')
        return original(db,identifier,event)
    monkeypatch.setattr(execution.store,'append',fail)
    assert run_once(execution)
    assert execution.get('local','project',attempt['attempt_id'])['status']=='failed'
    assert execution.result('local','project',attempt['attempt_id']) is None
    assert not any(e['type']=='computed' for e in execution.events('local','project',attempt['attempt_id']))


def test_os_lock_prevents_false_recovery_and_process_death_allows_restart(service,tmp_path):
    import subprocess
    import sys
    import time
    from pathlib import Path
    execution,job=service
    attempt=enqueue(execution,job)
    marker=tmp_path/'worker-ready'
    script='''
import sys,time
from pathlib import Path
from backend.app.modules.design.execution import ExecutionService
from backend.app.modules.design.worker import run_once
def waiting(*args,**kwargs):
    Path(sys.argv[2]).write_text('running')
    time.sleep(60)
run_once(ExecutionService(sys.argv[1]),compute_fn=waiting)
'''
    process=subprocess.Popen([sys.executable,'-c',script,str(tmp_path),str(marker)],
        cwd=Path(__file__).resolve().parents[2],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        deadline=time.monotonic()+10
        while not marker.exists() and time.monotonic()<deadline:
            assert process.poll() is None
            time.sleep(.02)
        assert marker.exists()
        assert run_once(execution) is False
        assert execution.get('local','project',attempt['attempt_id'])['status']=='running'
        process.kill();process.communicate(timeout=5)
        assert run_once(execution) is False
        assert execution.get('local','project',attempt['attempt_id'])['status']=='interrupted'
        new=enqueue(execution,job,'explicit-restart')
        assert run_once(execution)
        assert execution.get('local','project',new['attempt_id'])['status']=='computed'
    finally:
        if process.poll() is None:process.kill()
        process.communicate(timeout=5)
