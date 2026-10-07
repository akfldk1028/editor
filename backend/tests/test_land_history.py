import json
import sqlite3

import pytest

from backend.app.modules.land.history import HistoryImportError, import_history
from backend.app.modules.land.repository import LandRepository


def source(path):
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE land_landanalysisresult (id INTEGER PRIMARY KEY, created_at TEXT, zones TEXT, sunlight_rules TEXT, law_articles_json TEXT, regulations_extended TEXT)')
        db.execute('CREATE TABLE land_landquery (id INTEGER PRIMARY KEY, created_at TEXT, input_type TEXT, response_time_ms REAL, error TEXT, analysis_result_id INTEGER, zoning_zones TEXT, raw_input TEXT)')
        for identifier in (1, 2):
            db.execute('INSERT INTO land_landanalysisresult VALUES (?, ?, ?, ?, ?, ?)',
                (identifier, '2026-01-01 00:00:00', '["zone"]', '[]', '[]', '{}'))
        for identifier, link in [(1, 1), (2, None)]:
            db.execute('INSERT INTO land_landquery VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (identifier, '2026-01-01 00:00:00', 'raw', 10, 'partial' if identifier == 2 else '', link, '["zone"]', 'private input'))
    return path


def test_dry_run_is_read_only_then_repeat_is_idempotent(tmp_path):
    path = source(tmp_path / 'source.sqlite')
    original = path.read_bytes()
    repo = LandRepository(tmp_path / 'destination')
    preview = import_history(repo, path, 'arr-main')
    assert preview['queries'] == {'total':2, 'inserted':2, 'unchanged':0}
    assert not repo.path.exists()
    assert 'private' not in json.dumps(preview)
    imported = import_history(repo, path, 'arr-main', dry_run=False)
    assert imported['snapshot_sha256'] == preview['snapshot_sha256']
    again = import_history(repo, path, 'arr-main', dry_run=False)
    assert again['queries'] == {'total':2, 'inserted':0, 'unchanged':2}
    assert repo.get_history('arr-main', 'results', 2)['row']['id'] == 2
    assert repo.get_history('arr-main', 'queries', 2)['row']['analysis_result_id'] is None
    assert path.read_bytes() == original
    before = repo.path.read_bytes()
    assert import_history(repo, path, 'arr-main')['queries']['unchanged'] == 2
    assert repo.path.read_bytes() == before


def test_changed_row_rolls_back_new_rows_and_manifest(tmp_path):
    path = source(tmp_path / 'source.sqlite')
    repo = LandRepository(tmp_path / 'destination')
    import_history(repo, path, 'arr', dry_run=False)
    with sqlite3.connect(path) as db:
        db.execute('UPDATE land_landquery SET error=? WHERE id=2', ('changed',))
        db.execute("INSERT INTO land_landanalysisresult SELECT 3,created_at,zones,sunlight_rules,law_articles_json,regulations_extended FROM land_landanalysisresult WHERE id=1")
    with pytest.raises(HistoryImportError, match='conflict'):
        import_history(repo, path, 'arr', dry_run=False)
    assert repo.get_history('arr', 'results', 3) is None
    with sqlite3.connect(repo.path) as db:
        assert db.execute('SELECT COUNT(*) FROM history_imports').fetchone()[0] == 1


@pytest.mark.parametrize('sql', [
    "UPDATE land_landanalysisresult SET zones='bad'",
    "UPDATE land_landanalysisresult SET regulations_extended='{\"x\":NaN}'",
    'UPDATE land_landquery SET analysis_result_id=999 WHERE id=1',
    'UPDATE land_landquery SET response_time_ms=-1',
    "UPDATE land_landquery SET created_at='bad'",
])
def test_invalid_source_cannot_mutate_destination(tmp_path, sql):
    path = source(tmp_path / 'source.sqlite')
    with sqlite3.connect(path) as db: db.execute(sql)
    repo = LandRepository(tmp_path / 'destination')
    with pytest.raises(HistoryImportError): import_history(repo, path, 'arr', dry_run=False)
    assert not repo.path.exists()


def test_weighted_stats_counts_queries_not_orphan_results(tmp_path):
    path = source(tmp_path / 'source.sqlite')
    repo = LandRepository(tmp_path / 'destination')
    repo.save({'input_type':'pnu'}, {}, 100)
    import_history(repo, path, 'arr', dry_run=False)
    assert repo.stats()['total_queries'] == 1
    assert repo.stats('imported')['total_queries'] == 2
    assert repo.stats('all') == {'total_queries':3, 'avg_response_time_ms':40,
        'error_count':1, 'by_input_type':[{'input_type':'raw','count':2}, {'input_type':'pnu','count':1}]}


def test_v2_migration_preserves_existing_records(tmp_path):
    repo = LandRepository(tmp_path)
    with sqlite3.connect(repo.path) as db:
        db.execute('CREATE TABLE analyses (analysis_id TEXT PRIMARY KEY,created_at TEXT,input_type TEXT,request_json TEXT,result_json TEXT,elapsed_ms REAL,error TEXT)')
        db.execute('CREATE TABLE land_cache (pnu TEXT PRIMARY KEY,fetched_at TEXT,result_json TEXT)')
        db.execute('CREATE TABLE zone_cache (cache_key TEXT PRIMARY KEY,fetched_at TEXT,features_json TEXT)')
        db.execute("INSERT INTO analyses VALUES ('old','2026-01-01','raw','{}','{}',5,'')")
        db.execute('PRAGMA user_version=2')
    assert repo.stats()['total_queries'] == 1
    assert repo.get('old')['elapsed_ms'] == 5
    with sqlite3.connect(repo.path) as db: assert db.execute('PRAGMA user_version').fetchone()[0] == 4


def test_append_only_snapshot_import_and_namespaced_retrieval(tmp_path):
    path = source(tmp_path / 'source.sqlite')
    repo = LandRepository(tmp_path / 'destination')
    import_history(repo, path, 'first', dry_run=False)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO land_landquery SELECT 3,created_at,input_type,response_time_ms,error,NULL,zoning_zones,raw_input FROM land_landquery WHERE id=1")
    report = import_history(repo, path, 'first', dry_run=False)
    assert report['queries'] == {'total':3, 'inserted':1, 'unchanged':2}
    import_history(repo, path, 'second', dry_run=False)
    assert len(repo.list_history()) == 6
    assert [row['source_pk'] for row in repo.list_history(source_id='first', limit=1, offset=1)] == [2]
    assert repo.get_history('missing', 'queries', 1) is None
    assert repo.get_history('first', 'queries', 3)['row']['analysis_result_id'] is None


def test_destination_insert_failure_rolls_back_whole_import(tmp_path):
    path = source(tmp_path / 'source.sqlite')
    repo = LandRepository(tmp_path / 'destination')
    repo.stats()
    with sqlite3.connect(repo.path) as db:
        db.execute("CREATE TRIGGER reject_import AFTER INSERT ON legacy_queries BEGIN SELECT RAISE(ABORT,'failure'); END")
    with pytest.raises(HistoryImportError): import_history(repo, path, 'arr', dry_run=False)
    with sqlite3.connect(repo.path) as db:
        for table in ('legacy_queries', 'legacy_results', 'legacy_sources', 'history_imports'):
            assert db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] == 0


@pytest.mark.parametrize('identifier', ['', '../private', 'space name'])
def test_source_identifier_is_safe_and_validated_first(tmp_path, identifier):
    with pytest.raises(HistoryImportError):
        import_history(LandRepository(tmp_path / 'target'), tmp_path / 'absent', identifier)


def test_hardlink_source_destination_alias_is_rejected(tmp_path):
    import os
    path = source(tmp_path / 'source.sqlite')
    target = tmp_path / 'target'
    target.mkdir()
    repo = LandRepository(target)
    os.link(path, repo.path)
    with pytest.raises(HistoryImportError, match='differ'):
        import_history(repo, path, 'arr', dry_run=False)
