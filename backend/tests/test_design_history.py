import sqlite3

import pytest

from backend.app.modules.design.repository import DesignRepository
from backend.app.modules.design.history import import_history, DesignHistoryError


JOB = 'a' * 32


def source(path):
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE design_optimizationjob (id TEXT PRIMARY KEY,site_polygon TEXT,job_spec TEXT,constraints TEXT,status TEXT,created_at TEXT)')
        db.execute('CREATE TABLE design_designresult (id INTEGER PRIMARY KEY,job_id TEXT,generation INTEGER,design_id INTEGER,inputs TEXT,outputs TEXT,mass_geojson TEXT,is_feasible INTEGER,is_pareto_optimal INTEGER)')
        db.execute('INSERT INTO design_optimizationjob VALUES (?,?,?,?,?,?)', (JOB,'{}','{}','[]','running','2026-01-01 00:00:00'))
        for pk in (1, 2):
            db.execute('INSERT INTO design_designresult VALUES (?,?,?,?,?,?,?,?,?)',
                       (pk,JOB,pk,7,'[]','{"penalty":0}','{"type":"FeatureCollection","features":[]}',1,1))
    return path


def test_import_preserves_duplicates_and_archives_running_status(tmp_path):
    path = source(tmp_path / 'source.sqlite')
    original = path.read_bytes()
    repo = DesignRepository(tmp_path / 'editor')
    preview = import_history(repo,path,'arr-design-main')
    assert preview['results']['inserted'] == 2 and not repo.path.exists()
    import_history(repo,path,'arr-design-main',dry_run=False)
    assert import_history(repo,path,'arr-design-main',dry_run=False)['results']['unchanged'] == 2
    job = repo.list_jobs()[0]
    assert job['execution_state'] == 'archived' and job['source_status'] == 'running'
    assert job['result_count'] == 2
    assert repo.get_job('arr-design-main',JOB)['data']['site_polygon'] == {}
    results = repo.list_results('arr-design-main',JOB)
    assert {item['result_pk'] for item in results} == {1,2}
    assert all(item['design_id'] == 7 for item in results)
    assert repo.get_result('arr-design-main',JOB,1)['data']['mass_geojson']['type'] == 'FeatureCollection'
    assert path.read_bytes() == original


def test_attachment_selection_are_scoped_durable_and_require_membership(tmp_path):
    path = source(tmp_path/'source.sqlite');repo = DesignRepository(tmp_path/'editor')
    import_history(repo,path,'arr',dry_run=False)
    with pytest.raises(ValueError): repo.select_result('actor','p','arr',JOB,1)
    repo.attach_project('actor','p','scene',3,'arr',JOB)
    repo.select_result('actor','p','arr',JOB,2)
    reopened = DesignRepository(tmp_path/'editor')
    assert reopened.selected_result('actor','p')['result_pk'] == 2
    assert reopened.selected_result('other','p') is None
    assert reopened.project_jobs('other','p') == []
    assert reopened.project_jobs('actor','p')[0]['scene_revision'] == 3
    with pytest.raises(ValueError): repo.select_result('actor','p','arr','b'*32,1)
    with pytest.raises(ValueError): repo.attach_project('actor','p','changed',4,'arr',JOB)


@pytest.mark.parametrize('mutation', ["UPDATE design_designresult SET outputs='bad'",
    "UPDATE design_designresult SET job_id='bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'",
    "UPDATE design_designresult SET outputs='{\"x\":NaN}'"])
def test_invalid_source_does_not_write(tmp_path, mutation):
    path=source(tmp_path/'source.sqlite');repo=DesignRepository(tmp_path/'editor')
    with sqlite3.connect(path) as db: db.execute(mutation)
    with pytest.raises(DesignHistoryError): import_history(repo,path,'arr',dry_run=False)
    assert not repo.path.exists()


def test_conflicting_row_rolls_back_new_job_and_results(tmp_path):
    path=source(tmp_path/'source.sqlite');repo=DesignRepository(tmp_path/'editor')
    import_history(repo,path,'arr',dry_run=False)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE design_designresult SET outputs='{}' WHERE id=2")
        db.execute('INSERT INTO design_optimizationjob SELECT ?,site_polygon,job_spec,constraints,status,created_at FROM design_optimizationjob',('b'*32,))
    with pytest.raises(DesignHistoryError,match='conflict'): import_history(repo,path,'arr',dry_run=False)
    assert repo.get_job('arr','b'*32) is None


def test_optional_revision_rows_preserve_null_and_linked_jobs(tmp_path):
    path=source(tmp_path/'source.sqlite');repo=DesignRepository(tmp_path/'editor')
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE design_maasrevisionevent (id TEXT PRIMARY KEY,job_id TEXT,created_at TEXT,graph_diff TEXT,validation TEXT,reference_evidence TEXT,revision_evaluation TEXT)')
        for identifier,job in [('b'*32,JOB),('c'*32,None)]:
            db.execute('INSERT INTO design_maasrevisionevent VALUES (?,?,?,?,?,?,?)',
                       (identifier,job,'2026-01-01 00:00:00','[]','{}','{}','{}'))
    report=import_history(repo,path,'arr',dry_run=False)
    assert report['revisions']['inserted'] == 2
    with sqlite3.connect(repo.path) as db:
        assert db.execute('SELECT COUNT(*) FROM revisions WHERE job_id IS NULL').fetchone()[0] == 1


def test_dryrun_existing_archive_does_not_write_and_hardlink_alias_rejected(tmp_path):
    import os
    path=source(tmp_path/'source.sqlite');repo=DesignRepository(tmp_path/'editor')
    import_history(repo,path,'arr',dry_run=False)
    before=repo.path.read_bytes()
    assert import_history(repo,path,'arr')['jobs']['unchanged'] == 1
    assert repo.path.read_bytes() == before
    alias=tmp_path/'alias.sqlite';os.link(repo.path,alias)
    with pytest.raises(DesignHistoryError,match='differ'): import_history(repo,alias,'other',dry_run=False)


def test_insert_failure_rolls_back_source_registry_and_all_rows(tmp_path):
    path=source(tmp_path/'source.sqlite');repo=DesignRepository(tmp_path/'editor')
    repo.list_jobs()
    with sqlite3.connect(repo.path) as db:
        db.execute("CREATE TRIGGER reject_results AFTER INSERT ON results BEGIN SELECT RAISE(ABORT,'fixture'); END")
    with pytest.raises(DesignHistoryError): import_history(repo,path,'arr',dry_run=False)
    with sqlite3.connect(repo.path) as db:
        for table in ('sources','jobs','results','revisions','imports'):
            assert db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] == 0
