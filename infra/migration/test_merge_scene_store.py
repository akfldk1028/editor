import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

MODULE = Path(__file__).with_name('merge_scene_store.py')
SCHEMA = '''
CREATE TABLE scenes(id TEXT PRIMARY KEY, name TEXT NOT NULL, graph_json TEXT NOT NULL);
CREATE TABLE scene_revisions(scene_id TEXT, version INTEGER, graph_json TEXT, PRIMARY KEY(scene_id, version), FOREIGN KEY(scene_id) REFERENCES scenes(id));
CREATE TABLE scene_events(event_id INTEGER PRIMARY KEY AUTOINCREMENT, scene_id TEXT, version INTEGER, kind TEXT, FOREIGN KEY(scene_id) REFERENCES scenes(id));
'''


def merger():
    assert MODULE.exists(), 'Missing preservation-aware scene merge utility'
    spec = importlib.util.spec_from_file_location('merge_scene_store', MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def database(path, scene, event_id):
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        db.execute('INSERT INTO scenes VALUES(?,?,?)', (scene, scene, '{"nodes":{}}'))
        db.execute('INSERT INTO scene_revisions VALUES(?,?,?)', (scene, 1, '{"nodes":{}}'))
        db.execute('INSERT INTO scene_events VALUES(?,?,?,?)', (event_id, scene, 1, 'save'))
    return path


def rows(path, table):
    with sqlite3.connect(path) as db:
        return db.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall()


def test_merge_keeps_both_histories_and_backup_and_is_idempotent(tmp_path):
    module = merger()
    src = database(tmp_path / 'source.db', 'old', 8)
    dst = database(tmp_path / 'destination.db', 'current', 2)
    source_bytes = src.read_bytes()
    before = {t: rows(dst, t) for t in module.TABLES}
    with sqlite3.connect(dst) as db:
        db.execute('CREATE TABLE unrelated(value TEXT)')
        db.execute("INSERT INTO unrelated VALUES('keep')")
    receipt = module.merge(src, dst, tmp_path / 'run')
    assert receipt['inserted'] == {'scenes': 1, 'scene_revisions': 1, 'scene_events': 1}
    assert rows(dst, 'scenes') == [('current', 'current', '{"nodes":{}}'), ('old', 'old', '{"nodes":{}}')]
    assert rows(dst, 'scene_events') == [(2, 'current', 1, 'save'), (8, 'old', 1, 'save')]
    assert rows(dst, 'unrelated') == [('keep',)]
    assert src.read_bytes() == source_bytes
    for table in module.TABLES:
        assert rows(receipt['backup'], table) == before[table]
    assert json.loads((tmp_path / 'run/receipt.json').read_text())['status'] == 'committed'
    again = module.merge(src, dst, tmp_path / 'again')
    assert again['inserted'] == dict.fromkeys(module.TABLES, 0)
    with sqlite3.connect(dst) as db:
        cursor = db.execute("INSERT INTO scene_events(scene_id,version,kind) VALUES('current',2,'save')")
        assert cursor.lastrowid == 9


@pytest.mark.parametrize('table', ['scenes', 'scene_revisions', 'scene_events'])
def test_conflicting_ids_abort_without_modifying_any_rows(tmp_path, table):
    module = merger()
    src = database(tmp_path / 'source.db', 'same', 1)
    dst = database(tmp_path / 'destination.db', 'same', 1)
    column = {'scenes': 'name', 'scene_revisions': 'graph_json', 'scene_events': 'kind'}[table]
    with sqlite3.connect(src) as db:
        db.execute(f"UPDATE {table} SET {column}='conflict'")
        db.execute("INSERT INTO scenes VALUES('new','new','{}')")
    before = {t: rows(dst, t) for t in module.TABLES}
    with pytest.raises(ValueError, match='conflict'):
        module.merge(src, dst, tmp_path / 'run')
    assert {t: rows(dst, t) for t in module.TABLES} == before


def test_dry_run_is_readonly_and_reports_insertions(tmp_path):
    module = merger()
    src = database(tmp_path / 'source.db', 'old', 8)
    dst = database(tmp_path / 'destination.db', 'current', 2)
    before = dst.read_bytes()
    result = module.merge(src, dst, tmp_path / 'run', dry_run=True)
    assert result['inserted']['scenes'] == 1
    assert result['status'] == 'dry-run'
    assert dst.read_bytes() == before
    assert not (tmp_path / 'run').exists()


def test_late_constraint_failure_rolls_back_scenes_and_revisions(tmp_path):
    module = merger()
    src = database(tmp_path / 'source.db', 'old', 8)
    dst = database(tmp_path / 'destination.db', 'current', 2)
    with sqlite3.connect(dst) as db:
        db.execute('DROP TABLE scene_events')
        db.execute("CREATE TABLE scene_events(event_id INTEGER PRIMARY KEY AUTOINCREMENT, scene_id TEXT, version INTEGER, kind TEXT CHECK(kind='allowed'), FOREIGN KEY(scene_id) REFERENCES scenes(id))")
    before = {t: rows(dst, t) for t in module.TABLES}
    with pytest.raises(sqlite3.IntegrityError):
        module.merge(src, dst, tmp_path / 'run')
    assert {t: rows(dst, t) for t in module.TABLES} == before
    assert json.loads((tmp_path / 'run/receipt.json').read_text())['status'] == 'rolled-back'


def test_merge_backs_up_committed_wal_records(tmp_path):
    module = merger()
    src = database(tmp_path / 'source.db', 'old', 8)
    dst = database(tmp_path / 'destination.db', 'current', 2)
    with sqlite3.connect(dst) as live:
        live.execute('PRAGMA journal_mode=WAL')
        live.execute("UPDATE scenes SET name='live edit'")
        live.commit()
        receipt = module.merge(src, dst, tmp_path / 'run')
        assert rows(receipt['backup'], 'scenes') == [('current', 'live edit', '{"nodes":{}}')]
        assert live.execute("SELECT name FROM scenes WHERE id='current'").fetchone() == ('live edit',)


def test_orphaned_history_is_rejected_without_writes(tmp_path):
    module = merger()
    src = database(tmp_path / 'source.db', 'old', 8)
    dst = database(tmp_path / 'destination.db', 'current', 2)
    with sqlite3.connect(src) as db:
        db.execute("UPDATE scene_revisions SET scene_id='missing'")
    before = dst.read_bytes()
    with pytest.raises(ValueError, match='foreign key'):
        module.merge(src, dst, tmp_path / 'run')
    assert dst.read_bytes() == before


def test_existing_receipt_directory_cannot_be_overwritten(tmp_path):
    module = merger()
    src = database(tmp_path / 'source.db', 'old', 8)
    dst = database(tmp_path / 'destination.db', 'current', 2)
    output = tmp_path / 'run'
    output.mkdir()
    (output / 'receipt.json').write_text('previous evidence')
    before = dst.read_bytes()
    with pytest.raises(FileExistsError):
        module.merge(src, dst, output)
    assert dst.read_bytes() == before
    assert (output / 'receipt.json').read_text() == 'previous evidence'
