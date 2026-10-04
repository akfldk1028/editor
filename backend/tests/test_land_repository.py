from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import importlib
import sqlite3
from uuid import UUID

import pytest


def repository(path):
    return importlib.import_module('backend.app.modules.land.repository').LandRepository(path)


def test_constructor_is_lazy_and_requires_absolute_directory(tmp_path):
    directory = tmp_path / 'new'
    repository(directory)
    assert not directory.exists()
    with pytest.raises(ValueError, match='absolute'):
        repository('relative/path')


def test_saved_record_survives_restart_and_returns_independent_copies(tmp_path):
    repo = repository(tmp_path)
    request = {'input_type': 'raw', 'zones': ['zone']}
    result = {'assessment': {'verified': False}, 'restrictions': []}
    identifier = repo.save(request, result, 12.345)
    assert str(UUID(identifier)) == identifier
    request['zones'].append('changed')
    result['assessment']['verified'] = True
    record = repository(tmp_path).get(identifier)
    assert record['analysis_id'] == identifier
    assert record['request']['zones'] == ['zone']
    assert record['result']['assessment']['verified'] is False
    assert record['elapsed_ms'] == 12.345
    assert datetime.fromisoformat(record['created_at']).utcoffset().total_seconds() == 0
    record['result']['restrictions'].append('modified')
    assert repo.get(identifier)['result']['restrictions'] == []
    assert repo.get('missing') is None


def test_statistics_include_failures_and_deterministic_ties(tmp_path):
    repo = repository(tmp_path)
    assert repo.stats() == {'total_queries': 0, 'avg_response_time_ms': 0,
                            'by_input_type': [], 'error_count': 0}
    for kind, elapsed, error in [('raw', 1.01, ''), ('pnu', 2.02, 'partial'),
                                 ('raw', 3.03, ''), ('address', 4.04, 'failed')]:
        repo.save({'input_type': kind}, {}, elapsed, error)
    assert repo.stats() == {'total_queries': 4, 'avg_response_time_ms': 2.52,
                            'by_input_type': [{'input_type': 'raw', 'count': 2},
                                              {'input_type': 'address', 'count': 1},
                                              {'input_type': 'pnu', 'count': 1}], 'error_count': 2}


@pytest.mark.parametrize('payload,result,elapsed', [
    ({'input_type': 'raw', 'bad': float('nan')}, {}, 1),
    ({'input_type': 'raw'}, {'bad': float('inf')}, 1),
    ({'input_type': 'raw'}, {}, -1),
    ({'input_type': 'raw'}, {}, float('nan')),
    ({'input_type': 'raw'}, {}, float('inf')),
])
def test_invalid_save_does_not_add_partial_record(tmp_path, payload, result, elapsed):
    repo = repository(tmp_path)
    identifier = repo.save({'input_type': 'raw'}, {'kept': True}, 1)
    with pytest.raises(ValueError):
        repo.save(payload, result, elapsed)
    assert repo.stats()['total_queries'] == 1
    assert repo.get(identifier)['result'] == {'kept': True}


def test_future_schema_is_rejected_without_changing_it(tmp_path):
    repo = repository(tmp_path)
    with sqlite3.connect(repo.path) as db:
        db.execute('PRAGMA user_version=99')
    with pytest.raises(ValueError, match='version'):
        repo.stats()
    with sqlite3.connect(repo.path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 99
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0] == 0


def test_failed_insert_rolls_back_and_closes_connection(tmp_path):
    repo = repository(tmp_path)
    repo.save({'input_type': 'raw'}, {'kept': True}, 1)
    with sqlite3.connect(repo.path) as db:
        db.execute("""CREATE TRIGGER reject_analysis AFTER INSERT ON analyses
                      BEGIN SELECT RAISE(ABORT, 'simulated storage failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match='simulated storage failure'):
        repo.save({'input_type': 'raw'}, {'not_saved': True}, 2)
    assert repo.stats()['total_queries'] == 1
    with sqlite3.connect(repo.path) as db:
        db.execute('DROP TRIGGER reject_analysis')
    repo.save({'input_type': 'raw'}, {'recovered': True}, 3)
    assert repo.stats()['total_queries'] == 2


def test_parallel_first_writers_do_not_lose_records(tmp_path):
    def save(index):
        return repository(tmp_path).save({'input_type': 'raw'}, {'index': index}, index)
    with ThreadPoolExecutor(max_workers=8) as workers:
        identifiers = list(workers.map(save, range(24)))
    assert len(set(identifiers)) == 24
    repo = repository(tmp_path)
    assert repo.stats()['total_queries'] == 24
    assert {repo.get(identifier)['result']['index'] for identifier in identifiers} == set(range(24))
