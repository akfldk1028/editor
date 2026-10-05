from copy import deepcopy
import json
import random

import pytest

from backend.app.modules.design.job_spec import prepare_job
from backend.app.modules.design.optimization.service import compute


def prepared():
    return prepare_job({'site_polygon': {'type': 'Polygon', 'coordinates': [[
        [127,37.5],[127.001,37.5],[127.001,37.501],[127,37.501],[127,37.5]]]},
        'job_spec': {'options': {'algorithm': 'additive', 'building_type': '업무시설',
            'Number of generations': 2, 'num_islands': 2, 'pop_per_island': 8,
            'migration_interval': 1, 'migrants_count': 1, 'tournament_size': 4}}})


def test_compute_is_reproducible_consumes_frozen_spec_and_produces_geometry():
    value = prepared(); original = deepcopy(value); state = random.getstate(); events = []
    result = compute(value, seed=42, on_event=events.append)
    assert value == original and random.getstate() == state
    assert result == compute(value, seed=42)
    assert result['status'] == 'computed'
    assert result['legal_compliance_verified'] is False
    assert result['total_evaluated'] == 20
    assert result['candidates']
    assert all(c['geometry']['type'] == 'Feature' for c in result['candidates'])
    assert events[0]['type'] == 'started' and events[-1]['type'] == 'computed'
    json.dumps(result, allow_nan=False)


def test_cancel_before_initial_evaluation_records_no_candidate():
    result = compute(prepared(), seed=7, cancelled=lambda: True)
    assert result['status'] == 'cancelled'
    assert result['total_evaluated'] == 0 and result['candidates'] == []


def test_unsupported_algorithm_and_invalid_seed_fail_before_computation():
    value = prepared(); value['algorithm'] = 'grid'
    with pytest.raises(ValueError): compute(value, seed=1)
    for seed in (True, -1, 2**64, 1.5):
        with pytest.raises(ValueError): compute(prepared(), seed=seed)


def test_frozen_spec_missing_options_pins_engine_defaults_without_mutation():
    value = prepared(); value['job_spec'].pop('options')
    original = deepcopy(value)
    result = compute(value, seed=1, cancelled=lambda: True)
    options = result['effective_spec']['options']
    assert options['num_islands'] == 5 and options['pop_per_island'] == 15
    assert value == original


def test_event_failure_is_not_swallowed_as_success():
    def fail(event): raise OSError('event store unavailable')
    with pytest.raises(OSError): compute(prepared(), seed=1, on_event=fail)


def test_empty_geometry_never_becomes_a_successful_candidate(monkeypatch):
    from backend.app.modules.design.optimization import service
    monkeypatch.setattr(service, 'evaluate_candidate', lambda *args, **kwargs: {
        'outputs': [], 'metrics': {}, 'geometry': None, 'repair': {},
        'rejections': [{'code': 'empty_geometry', 'message': 'No valid mass'}]})
    result = compute(prepared(), seed=42)
    assert result['candidates'] == []
    assert len(result['rejections']) == result['total_evaluated'] == 20
    assert all(r['reasons'][0]['code'] == 'empty_geometry' for r in result['rejections'])
    json.dumps(result, allow_nan=False)


def test_generation_boundary_cancellation_preserves_partial_evidence():
    stopped = False
    def event(value):
        nonlocal stopped
        if value['type'] == 'generation': stopped = True
    result = compute(prepared(), seed=42, on_event=event, cancelled=lambda: stopped)
    assert result['status'] == 'cancelled' and result['total_evaluated'] == 16
    assert result['events'][-1]['type'] == 'cancelled'


def test_invalid_context_fails_before_started_event():
    events = []
    with pytest.raises(ValueError):
        compute(prepared(), seed=1, limits={'height_limit_m': -1}, on_event=events.append)
    assert events == []


def test_valid_but_constraint_violating_geometry_retains_penalties():
    value = prepared()
    value['job_spec']['outputs'].append({'name': 'landscaping_pct', 'type': 'Constraint',
        'Requirement': 'Greater than', 'val': 100})
    result = compute(value, seed=42)
    assert result['candidates'] == []
    measured = [r for r in result['rejections'] if r['reasons'][0]['code'] == 'constraints_unsatisfied']
    assert measured and all(r['outputs'] and 0 < r['penalty'] < 1e12 for r in measured)


def test_default_search_result_can_be_published_without_relaxing_input_limits(tmp_path):
    from backend.app.modules.design.native_service import NativeDesignService
    from backend.app.modules.design.native_repository import canonical_json
    from backend.app.modules.design.cli.execute_native import execute_saved_job
    value = prepared()
    service = NativeDesignService(tmp_path/'storage')
    job = service.create('local','project','scene',2,'default',{
        'site_polygon':value['site_polygon'],
        'job_spec':{'options':{'algorithm':'additive','building_type':'업무시설'}}})
    before = service.repository.path.read_bytes()
    manifest = execute_saved_job(service.repository,'local','project',job['job_id'],seed=42,
        output_root=tmp_path/'results',attempt_id='default',unverified_search=True)
    result = json.loads((tmp_path/'results/default/result.json').read_text(encoding='utf-8'))
    assert manifest['total_evaluated'] == 1050 and result['candidates']
    assert service.repository.path.read_bytes() == before
    with pytest.raises(ValueError): canonical_json([0]*100001)
