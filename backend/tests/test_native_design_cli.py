from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
import sqlite3

import pytest

from backend.app.modules.design.cli.execute_native import execute_saved_job, main
from backend.app.modules.design.native_repository import canonical_json
from backend.app.modules.design.native_repository import NativeJobUnavailable
from backend.app.modules.design.native_service import NativeDesignService


@pytest.fixture
def saved(tmp_path):
    service = NativeDesignService(tmp_path / 'native')
    payload = {'site_polygon': {'type': 'Polygon', 'coordinates': [
        [[127, 37], [127.001, 37], [127.001, 37.001], [127, 37.001], [127, 37]]]},
        'job_spec': {'options': {'algorithm': 'additive', 'Number of generations': 2}}}
    job = service.create('owner', 'project', 'scene', 2, 'create-1', payload)
    return service.repository, job, tmp_path / 'outputs'


def result(prepared, *, seed, **kwargs):
    effective = deepcopy(prepared['job_spec'])
    return {'status': 'computed', 'seed': seed, 'algorithm': 'additive',
            'engine_version': 'additive-ssiea-v1', 'legal_compliance_verified': False,
            'evidence_mode': 'unverified_search', 'effective_spec': effective,
            'effective_spec_sha256': hashlib.sha256(canonical_json(effective).encode()).hexdigest(),
            'total_evaluated': 2, 'candidates': [], 'rejections': [{'code': 'empty_geometry'}],
            'events': [{'type': 'generation', 'generation': 0}]}


def run(saved, **options):
    repository, job, output = saved
    return execute_saved_job(repository, 'owner', 'project', job['job_id'], seed=7,
                             output_root=output, attempt_id='attempt-1', unverified_search=True,
                             compute_fn=result, **options)


def test_saved_spec_is_read_only_and_result_manifest_is_hashed(saved, monkeypatch):
    repository, job, output = saved
    before = repository.path.read_bytes()
    monkeypatch.setattr('backend.app.modules.design.native_service.prepare_job',
                        lambda _: pytest.fail('stored job must not be prepared again'))
    received = []
    def compute(prepared, **kwargs):
        received.append(deepcopy(prepared))
        produced = result(prepared, **kwargs)
        prepared['job_spec']['options']['algorithm'] = 'changed'
        return produced
    manifest = execute_saved_job(repository, 'owner', 'project', job['job_id'], seed=7,
                                output_root=output, attempt_id='probe', unverified_search=True, compute_fn=compute)
    assert received == [job['prepared']]
    assert repository.path.read_bytes() == before
    assert repository.get_job('owner', 'project', job['job_id']) == job
    assert manifest['input_sha256'] == job['input_sha256']
    assert manifest['prepared_sha256'] == hashlib.sha256(canonical_json(job['prepared'], max_bytes=4*1024*1024, max_depth=36).encode()).hexdigest()
    assert manifest['scene_id'] == 'scene' and manifest['scene_revision'] == 2
    assert manifest['status'] == 'computed' and manifest['legal_compliance_verified'] is False
    assert manifest['lifecycle_managed'] is False
    assert json.loads((output / 'probe' / 'manifest.json').read_text(encoding='utf-8')) == manifest
    raw = (output / 'probe' / manifest['result']['path']).read_bytes()
    assert manifest['result']['sha256'] == hashlib.sha256(raw).hexdigest()
    assert manifest['result']['size'] == len(raw)


@pytest.mark.parametrize(('actor', 'project', 'job_id'), [('other', 'project', None), ('owner', 'other', None), ('owner', 'project', 'f'*32)])
def test_unknown_job_or_scope_fails_before_compute_or_output(saved, actor, project, job_id):
    repository, job, output = saved
    with pytest.raises(LookupError):
        execute_saved_job(repository, actor, project, job_id or job['job_id'], seed=7,
                          output_root=output, attempt_id='probe', unverified_search=True,
                          compute_fn=lambda *_args, **_kwargs: pytest.fail('must not compute'))
    assert not output.exists()


def test_attempt_retry_never_overwrites_and_new_attempt_is_explicit(saved):
    first = run(saved)
    repository, job, output = saved
    original = (output / 'attempt-1' / 'manifest.json').read_bytes()
    with pytest.raises(FileExistsError):
        run(saved)
    assert (output / 'attempt-1' / 'manifest.json').read_bytes() == original
    second = execute_saved_job(repository, 'owner', 'project', job['job_id'], seed=7,
                               output_root=output, attempt_id='attempt-2', unverified_search=True, compute_fn=result)
    assert first['effective_spec_sha256'] == second['effective_spec_sha256']
    assert first['result'] == second['result']


def test_concurrent_attempt_claim_has_exactly_one_writer(saved):
    def call(_):
        try:
            return run(saved)['status']
        except FileExistsError:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(call, range(2))) == ['computed', 'conflict']


@pytest.mark.parametrize('failure', ['compute', 'result', 'manifest'])
def test_failure_never_publishes_terminal_manifest_or_changes_native_job(saved, monkeypatch, failure):
    from backend.app.modules.design.cli import execute_native
    repository, job, output = saved
    before = repository.path.read_bytes()
    real_write = execute_native._atomic_write
    def write(path, data):
        if path.name == failure + '.json':
            raise OSError('injected storage failure')
        return real_write(path, data)
    def compute(prepared, **kwargs):
        if failure == 'compute':
            raise RuntimeError('injected evaluator failure')
        return result(prepared, **kwargs)
    monkeypatch.setattr(execute_native, '_atomic_write', write)
    with pytest.raises((RuntimeError, OSError)):
        execute_saved_job(repository, 'owner', 'project', job['job_id'], seed=7,
                          output_root=output, attempt_id='failed', unverified_search=True, compute_fn=compute)
    assert not (output / 'failed' / 'manifest.json').exists()
    assert repository.path.read_bytes() == before


@pytest.mark.parametrize('seed', [True, -1, 2**64, 1.2, '7'])
def test_seed_is_strict_and_unverified_mode_is_explicit(saved, seed):
    repository, job, output = saved
    with pytest.raises(ValueError):
        execute_saved_job(repository, 'owner', 'project', job['job_id'], seed=seed,
                          output_root=output, attempt_id='probe', unverified_search=True, compute_fn=result)
    assert not output.exists()


def test_no_implicit_legal_mode_or_other_algorithm(saved):
    repository, job, output = saved
    with pytest.raises(ValueError, match='unverified'):
        execute_saved_job(repository, 'owner', 'project', job['job_id'], seed=7,
                          output_root=output, attempt_id='probe', unverified_search=False, compute_fn=result)
    service = NativeDesignService(repository.path.parent)
    payload = deepcopy(job['input']); payload['job_spec']['options']['algorithm'] = 'grid'
    grid = service.create('owner', 'project', 'scene', 2, 'grid', payload)
    with pytest.raises(ValueError, match='additive'):
        execute_saved_job(repository, 'owner', 'project', grid['job_id'], seed=7,
                          output_root=output, attempt_id='probe', unverified_search=True, compute_fn=result)
    assert not output.exists()


@pytest.mark.parametrize('change', [{'effective_spec_sha256': 'a'*64}, {'seed': 8}, {'legal_compliance_verified': True}, {'total_evaluated': float('inf')}])
def test_inconsistent_compute_result_cannot_be_published(saved, change):
    repository, job, output = saved
    def compute(prepared, **kwargs):
        return {**result(prepared, **kwargs), **change}
    with pytest.raises(ValueError):
        execute_saved_job(repository, 'owner', 'project', job['job_id'], seed=7,
                          output_root=output, attempt_id='probe', unverified_search=True, compute_fn=compute)
    assert not (output / 'probe' / 'manifest.json').exists()


def test_cli_parser_requires_explicit_inputs_and_rejects_fractional_seed():
    with pytest.raises(SystemExit) as missing:
        main([])
    assert missing.value.code == 2
    with pytest.raises(SystemExit) as invalid:
        main(['--storage-directory', 'unused', '--actor', 'owner', '--project-id', 'project',
              '--job-id', 'a'*32, '--output-root', 'unused', '--attempt-id', 'probe',
              '--unverified-search', '--seed', '1.2'])
    assert invalid.value.code == 2


def test_cancelled_result_is_explicit_and_never_changes_created_job(saved):
    repository, job, output = saved
    def cancelled(prepared, **kwargs):
        return {**result(prepared, **kwargs), 'status': 'cancelled'}
    manifest = execute_saved_job(repository, 'owner', 'project', job['job_id'], seed=7,
        output_root=output, attempt_id='cancelled', unverified_search=True, compute_fn=cancelled)
    assert manifest['status'] == 'cancelled'
    assert repository.get_job('owner', 'project', job['job_id'])['status'] == 'created'


def test_corrupted_job_fails_before_compute_and_output(saved):
    repository, _job, output = saved
    with sqlite3.connect(repository.path) as database:
        database.execute("UPDATE native_jobs SET record_json='{}'")
    with pytest.raises(NativeJobUnavailable):
        run(saved)
    assert not output.exists()


def test_manifest_rename_failure_keeps_result_uncommitted_and_cleans_temp(saved, monkeypatch):
    from backend.app.modules.design.cli import execute_native
    repository, _job, output = saved
    before = repository.path.read_bytes()
    replace = execute_native.os.replace
    def failing_replace(source, destination):
        if destination.name == 'manifest.json':
            raise OSError('injected rename failure')
        return replace(source, destination)
    monkeypatch.setattr(execute_native.os, 'replace', failing_replace)
    with pytest.raises(OSError):
        run(saved)
    assert [path.name for path in (output / 'attempt-1').iterdir()] == ['result.json']
    assert repository.path.read_bytes() == before
    with pytest.raises(FileExistsError):
        run(saved)


def test_linked_output_root_is_rejected_before_compute(saved, monkeypatch):
    from backend.app.modules.design.cli import execute_native
    _repository, _job, output = saved
    linked = execute_native._linked
    monkeypatch.setattr(execute_native, '_linked', lambda path: path == output or linked(path))
    with pytest.raises(ValueError, match='Linked'):
        run(saved)
    assert not output.exists()
