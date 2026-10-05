from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from .artifacts import _linked


class NativeJobConflict(RuntimeError):
    pass


class NativeJobUnavailable(RuntimeError):
    pass


def canonical_json(value, *, max_bytes=1024 * 1024, max_depth=32, max_nodes=100000):
    nodes = 0
    def validate(item, depth=0):
        nonlocal nodes
        nodes += 1
        if depth > max_depth or nodes > max_nodes:
            raise ValueError('Job input exceeds structural limits')
        if isinstance(item, str) and len(item) > max_bytes:
            raise ValueError('Job input exceeds size limit')
        if item is None or type(item) in (str, bool, int):
            return
        if type(item) is float and math.isfinite(item):
            return
        if type(item) is list:
            for child in item:
                validate(child, depth + 1)
            return
        if type(item) is dict and all(type(key) is str for key in item):
            for key, child in item.items():
                validate(key, depth + 1)
                validate(child, depth + 1)
            return
        raise ValueError('Job input must contain finite JSON values and string keys')
    validate(value)
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if len(encoded.encode('utf-8')) > max_bytes:
        raise ValueError('Job input exceeds size limit')
    return encoded


def _sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _record_sha(actor, record):
    return _sha(canonical_json({'actor': actor, 'record': record}, max_bytes=4 * 1024 * 1024, max_depth=36))


def _identifier(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 256 or any(ord(c) < 32 for c in value):
        raise ValueError('Invalid native job identity')


SUMMARY_FIELDS = (
    'job_id', 'project_id', 'request_id', 'status', 'execution_supported', 'created_at',
    'site_area_m2', 'algorithm', 'building_type', 'max_generations', 'population_size',
    'input_sha256', 'scene_revision',
)


class NativeJobRepository:
    def __init__(self, directory):
        try:
            root = Path(directory)
        except (TypeError, ValueError) as exc:
            raise NativeJobUnavailable('Native job directory unavailable') from exc
        if not root.is_absolute():
            raise NativeJobUnavailable('Native job directory must be absolute')
        self.path = root / 'native-jobs.sqlite'
        self._safe_storage()

    def _safe_storage(self):
        try:
            paths = (self.path, *self.path.parents,
                     *(Path(str(self.path) + suffix) for suffix in ('-journal', '-wal', '-shm')))
            if any(_linked(path) for path in paths):
                raise NativeJobUnavailable('Linked native job storage is not supported')
        except OSError as exc:
            raise NativeJobUnavailable('Native job storage unavailable') from exc

    @staticmethod
    def _schema(db):
        if db.execute('PRAGMA user_version').fetchone()[0] != 1:
            raise NativeJobUnavailable('Native job schema unavailable')

    @contextmanager
    def _read(self):
        try:
            self._safe_storage()
            with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=20)) as db:
                db.row_factory = sqlite3.Row
                self._schema(db)
                yield db
        except (sqlite3.Error, OSError) as exc:
            raise NativeJobUnavailable('Native job storage unavailable') from exc

    @contextmanager
    def _write(self):
        try:
            self._safe_storage()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._safe_storage()
            with closing(sqlite3.connect(self.path, timeout=20)) as db:
                db.row_factory = sqlite3.Row
                db.execute('BEGIN IMMEDIATE')
                try:
                    version = db.execute('PRAGMA user_version').fetchone()[0]
                    if version == 0:
                        if db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                            raise NativeJobUnavailable('Native job schema unavailable')
                        db.execute('CREATE TABLE native_jobs ('
                            'job_id TEXT PRIMARY KEY, actor TEXT NOT NULL, project_id TEXT NOT NULL, '
                            'request_id TEXT NOT NULL, created_at TEXT NOT NULL, '
                            'record_json TEXT NOT NULL, record_sha256 TEXT NOT NULL, '
                            'UNIQUE(actor,project_id,request_id))')
                        db.execute('PRAGMA user_version=1')
                        db.commit()
                        db.execute('BEGIN IMMEDIATE')
                    self._schema(db)
                    yield db
                    db.commit()
                except BaseException:
                    db.rollback()
                    raise
        except (sqlite3.Error, OSError) as exc:
            raise NativeJobUnavailable('Native job storage unavailable') from exc

    @staticmethod
    def _decode(row):
        try:
            if not isinstance(row['record_json'], str) or len(row['record_json']) > 4 * 1024 * 1024:
                raise ValueError('Invalid record size')
            value = json.loads(row['record_json'])
            if _record_sha(row['actor'], value) != row['record_sha256']:
                raise ValueError('Record checksum mismatch')
            if not isinstance(value, dict) or set(value) != set(SUMMARY_FIELDS) | {'input', 'prepared', 'scene_id'}:
                raise ValueError('Invalid record shape')
            for key in ('job_id', 'project_id', 'request_id', 'created_at'):
                if value[key] != row[key]:
                    raise ValueError('Record identity mismatch')
            if not re.fullmatch('[0-9a-f]{32}', value['job_id']):
                raise ValueError('Invalid job id')
            if value['status'] != 'created' or value['execution_supported'] is not False:
                raise ValueError('Invalid job state')
            if type(value['scene_revision']) is not int or value['scene_revision'] < 0:
                raise ValueError('Invalid scene revision')
            _identifier(value['scene_id'])
            for key in ('input', 'prepared'):
                if not isinstance(value[key], dict):
                    raise ValueError('Invalid job payload')
            if _sha(canonical_json(value['input'])) != value['input_sha256']:
                raise ValueError('Input checksum mismatch')
            for key in ('site_area_m2', 'algorithm', 'building_type', 'max_generations', 'population_size'):
                if value[key] != value['prepared'][key]:
                    raise ValueError('Prepared summary mismatch')
            return value
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
            raise NativeJobUnavailable('Native job record unavailable') from exc

    def create(self, actor, project_id, scene_id, scene_revision, request_id, payload, prepare):
        for value in (actor, project_id, scene_id, request_id):
            _identifier(value)
        if type(scene_revision) is not int or scene_revision < 0:
            raise ValueError('Invalid scene revision')
        if type(payload) is not dict:
            raise ValueError('Job input must be an object')
        input_json = canonical_json(payload)
        input_hash = _sha(input_json)
        with self._write() as db:
            previous = db.execute('SELECT * FROM native_jobs WHERE actor=? AND project_id=? AND request_id=?',
                                  (actor, project_id, request_id)).fetchone()
            if previous is not None:
                record = self._decode(previous)
                if (record['input_sha256'] != input_hash or record['scene_id'] != scene_id
                        or record['scene_revision'] != scene_revision):
                    raise NativeJobConflict('Native job request identity already has different inputs')
                return record
            prepared = prepare(json.loads(input_json))
            record = {key: prepared[key] for key in
                      ('site_area_m2', 'algorithm', 'building_type', 'max_generations', 'population_size')}
            record.update(job_id=uuid4().hex, project_id=project_id, request_id=request_id,
                          status='created', execution_supported=False,
                          created_at=datetime.now(timezone.utc).isoformat(), scene_id=scene_id,
                          scene_revision=scene_revision, input_sha256=input_hash,
                          input=json.loads(input_json), prepared=prepared)
            record_json = canonical_json(record, max_bytes=4 * 1024 * 1024, max_depth=36)
            db.execute('INSERT INTO native_jobs VALUES (?,?,?,?,?,?,?)',
                       (record['job_id'], actor, project_id, request_id, record['created_at'], record_json, _record_sha(actor, record)))
            return json.loads(record_json)

    def list_jobs(self, actor, project_id, limit=20, offset=0):
        for value in (actor, project_id):
            _identifier(value)
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or not 0 <= offset < 2**63:
            raise ValueError('Invalid native job page')
        self._safe_storage()
        if not self.path.exists():
            return []
        with self._read() as db:
            rows = db.execute('SELECT * FROM native_jobs WHERE actor=? AND project_id=? '
                              'ORDER BY created_at DESC, job_id LIMIT ? OFFSET ?',
                              (actor, project_id, limit, offset)).fetchall()
            return [{key: value[key] for key in SUMMARY_FIELDS} for value in map(self._decode, rows)]

    def get_job(self, actor, project_id, job_id):
        for value in (actor, project_id):
            _identifier(value)
        if not isinstance(job_id, str) or not re.fullmatch('[0-9a-f]{32}', job_id):
            raise ValueError('Invalid native job ID')
        self._safe_storage()
        if not self.path.exists():
            return None
        with self._read() as db:
            row = db.execute('SELECT * FROM native_jobs WHERE actor=? AND project_id=? AND job_id=?',
                             (actor, project_id, job_id)).fetchone()
            return self._decode(row) if row else None
