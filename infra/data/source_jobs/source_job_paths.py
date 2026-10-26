"""Explicit local storage roots; imports never create or move data."""
import json
import os
from pathlib import Path


def configured(name, default):
    return Path(os.environ.get(name) or default).expanduser()


DATA_ROOT = configured('DATA_ROOT', 'C:/Data/25_ACE')
NGII_DEM_ROOT = configured('NGII_DEM_ROOT', 'D:/Data/NGII_DEM')
NGII_ORIGINAL_ROOT = configured('NGII_ORIGINAL_ROOT', DATA_ROOT / 'ngii-original-batch')
SOURCE_DATA_ROOT = configured('ACE_SOURCE_DATA_ROOT', 'D:/Data/25_ACE/data')
INDEX_STATE_ROOT = configured('ACE_INDEX_STATE_ROOT', SOURCE_DATA_ROOT / 'index')
EDITOR_ROOT = configured('EDITOR_ROOT', Path(__file__).resolve().parents[3])
AGENT_ROOT = configured('ACE_AGENT_ROOT', EDITOR_ROOT.parent / 'agents')
STORAGE_ROOTS = list(dict.fromkeys([str(DATA_ROOT), str(NGII_DEM_ROOT)]))
SOURCE_JOBS = Path(__file__).resolve().parent
MANAGED_JOBS = {'national-buildings-loop.py', 'rebake-ngii-package-regions.py',
                'rebuild-national-partial-ground.py'}


def job_script(name):
    if Path(name).name != name:
        raise ValueError('Expected a source job filename')
    return (EDITOR_ROOT / 'infra/data/jobs' if name in MANAGED_JOBS else SOURCE_JOBS) / name


def required_env(name):
    value = os.environ.get(name)
    if value:
        return value
    private = configured('NGII_SOURCE_JOB_CONFIG', DATA_ROOT / 'management/source-job-private.json')
    if private.exists():
        value = json.loads(private.read_text(encoding='utf-8')).get(name)
    if not isinstance(value, str) or not value:
        raise RuntimeError('Configure ' + name + ' outside the repository')
    return value
