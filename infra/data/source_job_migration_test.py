import importlib.util
import hashlib
import json
from pathlib import Path
import runpy
import sys

import pytest

spec = importlib.util.spec_from_file_location('source_migration', Path(__file__).with_name('source_job_migration.py'))
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def fixture(tmp_path):
    jobs = tmp_path / 'editor/infra/data/source_jobs'
    jobs.mkdir(parents=True)
    index = tmp_path / 'data/index'
    index.mkdir(parents=True)
    body = b'VALUE = "old"\n'
    (index / 'helper.py').write_bytes(body)
    (jobs / 'helper.py').write_text('VALUE = "managed"\n', encoding='utf-8')
    (jobs / 'migration_manifest.json').write_text(json.dumps({'source_files': [dict(name='helper.py', original_sha256=hashlib.sha256(body).hexdigest())]}))
    return jobs, index, tmp_path / 'backup', body


def test_dry_run_does_not_write(tmp_path):
    jobs, index, backup, body = fixture(tmp_path)
    report = migration.migrate(index, backup, source_jobs=jobs, private_config=tmp_path / 'private.json')
    assert report['state'] == 'planned'
    assert (index / 'helper.py').read_bytes() == body
    assert not backup.exists()


def test_apply_preserves_original_and_module_exports(tmp_path, monkeypatch):
    jobs, index, backup, body = fixture(tmp_path)
    monkeypatch.delenv('EDITOR_ROOT', raising=False)
    report = migration.migrate(index, backup, apply=True, source_jobs=jobs, private_config=tmp_path / 'private.json')
    assert (Path(report['backup']) / 'helper.py').read_bytes() == body
    assert json.loads((Path(report['backup']) / 'receipt.json').read_text())['state'] == 'activated'
    monkeypatch.setattr(sys, 'path', sys.path.copy())
    assert runpy.run_path(str(index / 'helper.py'))['VALUE'] == 'managed'
    helper_spec = importlib.util.spec_from_file_location('migration_helper', index / 'helper.py')
    helper = importlib.util.module_from_spec(helper_spec)
    helper_spec.loader.exec_module(helper)
    assert helper.VALUE == 'managed'
    assert migration.migrate(index, backup, apply=True, source_jobs=jobs, private_config=tmp_path / 'private.json')['state'] == 'already_active'


def test_changed_original_is_rejected_before_any_write(tmp_path):
    jobs, index, backup, body = fixture(tmp_path)
    (index / 'helper.py').write_bytes(body + b'# newer\n')
    with pytest.raises(ValueError, match='changed'):
        migration.migrate(index, backup, apply=True, source_jobs=jobs, private_config=tmp_path / 'private.json')
    assert not backup.exists()


def test_runtime_config_is_external_and_job_dispatch_is_explicit(tmp_path, monkeypatch):
    source = Path(__file__).parent / 'source_jobs/source_job_paths.py'
    for name in ('DATA_ROOT', 'NGII_DEM_ROOT', 'NGII_ORIGINAL_ROOT', 'ACE_SOURCE_DATA_ROOT', 'ACE_INDEX_STATE_ROOT', 'EDITOR_ROOT', 'ACE_AGENT_ROOT'):
        monkeypatch.setenv(name, str(tmp_path / name))
    module = runpy.run_path(str(source))
    assert module['DATA_ROOT'] == tmp_path / 'DATA_ROOT'
    assert module['INDEX_STATE_ROOT'] == tmp_path / 'ACE_INDEX_STATE_ROOT'
    assert module['job_script']('rebake-ngii-package-regions.py') == tmp_path / 'EDITOR_ROOT/infra/data/jobs/rebake-ngii-package-regions.py'
    assert module['job_script']('stage-ngii-dxf-ground.py') == source.parent / 'stage-ngii-dxf-ground.py'
    assert list(tmp_path.iterdir()) == []


def test_existing_sensitive_literals_stay_in_private_storage(tmp_path, monkeypatch):
    jobs, index, backup, body = fixture(tmp_path)
    (index / 'download-ngii-original-probe.py').write_text("directory='private-value'\n")
    private = tmp_path / 'private.json'
    report = migration.migrate(index, backup, source_jobs=jobs, private_config=private)
    assert not private.exists()
    assert 'private-value' not in json.dumps(report)
    report = migration.migrate(index, backup, apply=True, source_jobs=jobs, private_config=private)
    assert json.loads(private.read_text())['NGII_PROBE_DIRECTORY'] == 'private-value'
    assert 'private-value' not in (Path(report['backup']) / 'receipt.json').read_text()
    monkeypatch.setenv('NGII_SOURCE_JOB_CONFIG', str(private))
    monkeypatch.delenv('NGII_PROBE_DIRECTORY', raising=False)
    module = runpy.run_path(str(Path(__file__).parent / 'source_jobs/source_job_paths.py'))
    assert module['required_env']('NGII_PROBE_DIRECTORY') == 'private-value'
    monkeypatch.setenv('NGII_PROBE_DIRECTORY', 'override')
    assert module['required_env']('NGII_PROBE_DIRECTORY') == 'override'
