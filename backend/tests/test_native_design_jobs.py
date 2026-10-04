from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import stat
from types import SimpleNamespace

import pytest

from backend.app.modules.design.native_service import NativeDesignService, NativeJobConflict, NativeJobUnavailable


@pytest.fixture
def service(tmp_path, monkeypatch):
    from backend.app.modules.design import native_service
    def prepare(payload):
        if payload.get('invalid'):
            raise ValueError('invalid specification')
        return {'site_polygon': payload['site_polygon'], 'pnu': '', 'address': '',
                'constraints': [], 'job_spec': {'inputs': [], 'outputs': [], 'options': {}},
                'site_area_m2': 100.0, 'max_generations': 2, 'population_size': 6,
                'algorithm': 'additive', 'building_type': '공동주택'}
    monkeypatch.setattr(native_service, 'prepare_job', prepare)
    return NativeDesignService(tmp_path / 'native')


def payload():
    return {'site_polygon': {'type': 'Polygon', 'coordinates': [[[127, 37], [127.001, 37], [127.001, 37.001], [127, 37]]]}}


def create(service, request='request-1', actor='actor', project='project', scene='scene', revision=1, value=None):
    return service.create(actor, project, scene, revision, request, payload() if value is None else value)


def test_read_does_not_initialize_storage(service):
    assert service.list_jobs('actor', 'project') == []
    assert service.get_job('actor', 'project', 'a' * 32) is None
    assert not service.repository.path.parent.exists()


def test_persists_original_and_independent_results_across_reopen(service):
    original = payload()
    before = copy.deepcopy(original)
    result = create(service, value=original)
    assert original == before
    assert result['status'] == 'created' and result['execution_supported'] is False
    assert len(result['job_id']) == 32
    assert result['input'] == before
    assert result['input_sha256'] == hashlib.sha256(json.dumps(before, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    original['site_polygon']['type'] = 'changed'
    result['prepared']['constraints'].append({'changed': True})
    reopened = NativeDesignService(service.repository.path.parent)
    found = reopened.get_job('actor', 'project', result['job_id'])
    assert found['input'] == before and found['prepared']['constraints'] == []
    assert found['scene_id'] == 'scene' and found['scene_revision'] == 1
    summary = reopened.list_jobs('actor', 'project')[0]
    assert 'input' not in summary and 'prepared' not in summary and 'scene_id' not in summary


def test_exact_retry_and_identity_conflicts(service):
    first = create(service)
    reordered = dict(reversed(list(payload().items())))
    assert create(service, value=reordered) == first
    for changes in ({'value': {**payload(), 'address': 'changed'}}, {'scene': 'other'}, {'revision': 2}):
        with pytest.raises(NativeJobConflict):
            create(service, **changes)
    assert len(service.list_jobs('actor', 'project')) == 1


def test_actor_project_isolation(service):
    jobs = [create(service), create(service, actor='other'), create(service, project='other')]
    assert len({job['job_id'] for job in jobs}) == 3
    assert service.get_job('other', 'project', jobs[0]['job_id']) is None
    assert service.get_job('actor', 'other', jobs[0]['job_id']) is None
    assert len(service.list_jobs('actor', 'project')) == 1


def test_concurrent_duplicate_creation_is_atomic(service):
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: create(service), range(20)))
    assert len({job['job_id'] for job in results}) == 1
    assert len(service.list_jobs('actor', 'project')) == 1


def test_invalid_creation_rolls_back_without_record(service):
    with pytest.raises(ValueError):
        create(service, value={**payload(), 'invalid': True})
    assert service.list_jobs('actor', 'project') == []
    assert create(service)['status'] == 'created'


@pytest.mark.parametrize('value', [float('nan'), float('inf'), {1: 'numeric key'}])
def test_invalid_json_does_not_write(service, value):
    with pytest.raises(ValueError):
        create(service, value={**payload(), 'extra': value})
    assert not service.repository.path.exists()


def test_corrupt_record_is_unavailable_on_get_list_retry(service):
    job = create(service)
    with sqlite3.connect(service.repository.path) as db:
        db.execute("UPDATE native_jobs SET record_json='{}'")
    for call in (lambda: service.get_job('actor', 'project', job['job_id']),
                 lambda: service.list_jobs('actor', 'project'), lambda: create(service)):
        with pytest.raises(NativeJobUnavailable):
            call()


def test_changed_actor_index_cannot_expose_another_actors_input(service):
    job = create(service)
    with sqlite3.connect(service.repository.path) as db:
        db.execute("UPDATE native_jobs SET actor='other'")
    with pytest.raises(NativeJobUnavailable):
        service.get_job('other', 'project', job['job_id'])


def test_exact_retry_does_not_reprepare_saved_specification(service, monkeypatch):
    first = create(service)
    def changed_validator(_):
        raise ValueError('new validator must not rewrite previously accepted input')
    monkeypatch.setattr('backend.app.modules.design.native_service.prepare_job', changed_validator)
    assert create(service) == first


def test_future_schema_and_invalid_sqlite_are_unavailable(service):
    create(service)
    with sqlite3.connect(service.repository.path) as db:
        db.execute('PRAGMA user_version=999')
    with pytest.raises(NativeJobUnavailable):
        service.list_jobs('actor', 'project')
    with pytest.raises(NativeJobUnavailable):
        create(service, request='new')
    service.repository.path.write_bytes(b'not sqlite')
    with pytest.raises(NativeJobUnavailable):
        service.list_jobs('actor', 'project')


def test_pagination_and_read_only_bytes(service):
    for index in range(4):
        create(service, request=f'request-{index}')
    path = service.repository.path
    before = path.read_bytes()
    full = service.list_jobs('actor', 'project')
    assert service.list_jobs('actor', 'project', limit=2, offset=1) == full[1:3]
    for item in full:
        service.get_job('actor', 'project', item['job_id'])
    assert path.read_bytes() == before
    for options in ({'limit': 0}, {'limit': True}, {'offset': -1}, {'limit': 101}, {'offset': 2**80}):
        with pytest.raises(ValueError):
            service.list_jobs('actor', 'project', **options)


def test_payload_size_and_depth_are_bounded_before_storage(service):
    nested = {}
    for _ in range(40):
        nested = {'next': nested}
    for value in ({**payload(), 'extra': 'x' * (1024 * 1024)}, {**payload(), 'extra': nested}):
        with pytest.raises(ValueError):
            create(service, value=value)
    assert not service.repository.path.exists()


def test_storage_configuration_error_is_unavailable():
    with pytest.raises(NativeJobUnavailable):
        NativeDesignService('relative/path')


@pytest.mark.parametrize('linked_part', ['root', 'database', 'journal'])
def test_linked_storage_is_rejected_before_access(service, monkeypatch, linked_part):
    path = service.repository.path
    target = {'root': path.parent, 'database': path, 'journal': Path(str(path) + '-journal')}[linked_part]
    original = Path.lstat
    monkeypatch.setattr(Path, 'lstat', lambda candidate, *args, **kwargs:
        SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
        if candidate == target else original(candidate, *args, **kwargs))
    for operation in (lambda: create(service), lambda: service.list_jobs('actor', 'project'),
                      lambda: service.get_job('actor', 'project', 'a' * 32)):
        with pytest.raises(NativeJobUnavailable):
            operation()
    assert not path.exists()


def test_real_specification_preparation_and_archive_isolation(tmp_path):
    archive = tmp_path / 'design.sqlite'
    archive.write_bytes(b'Existing imported archive must stay untouched')
    service = NativeDesignService(tmp_path)
    original = payload()
    original['job_spec'] = {'options': {'building_type': '업무시설', 'algorithm': 'additive'}}
    before = copy.deepcopy(original)
    job = create(service, value=original)
    assert job['prepared']['job_spec']['inputs']
    assert job['prepared']['job_spec']['outputs']
    assert job['building_type'] == '업무시설'
    assert job['max_generations'] == 120 and job['population_size'] == 210
    assert job['input'] == before and original == before
    assert NativeDesignService(tmp_path).get_job('actor', 'project', job['job_id']) == job
    assert archive.read_bytes() == b'Existing imported archive must stay untouched'
