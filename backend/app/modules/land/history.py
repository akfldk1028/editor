"""Explicit offline import of sparse original audit/result rows, without recalculation."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3


class HistoryImportError(ValueError):
    pass


_TABLES = {'results': 'land_landanalysisresult', 'queries': 'land_landquery'}
_JSON_FIELDS = {'results': {'zones': list, 'sunlight_rules': list, 'law_articles_json': list,
                            'regulations_extended': dict}, 'queries': {'zoning_zones': list}}
_REQUIRED = {'results': {'id', 'created_at', *_JSON_FIELDS['results']},
             'queries': {'id', 'created_at', 'input_type', 'response_time_ms', 'error',
                         'analysis_result_id', *_JSON_FIELDS['queries']}}


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _snapshot(path, destination):
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as source:
        source.execute('PRAGMA query_only=ON')
        source.backup(destination)


def _read_rows(path):
    if not path.is_file() or path.stat().st_size > 512 * 1024 * 1024:
        raise HistoryImportError('History source missing or exceeds import size limit')
    with closing(sqlite3.connect(':memory:')) as db:
        _snapshot(path, db)
        db.row_factory = sqlite3.Row
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise HistoryImportError('History source integrity check failed')
        rows = {}
        for kind, table in _TABLES.items():
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            columns = {row['name'] for row in db.execute('PRAGMA table_info(' + table + ')')}
            if not exists or not _REQUIRED[kind] <= columns:
                raise HistoryImportError('History source schema is unsupported')
            if db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] > 100000:
                raise HistoryImportError('History source exceeds row limit')
            values = [dict(row) for row in db.execute('SELECT * FROM ' + table + ' ORDER BY id')]
            seen = set()
            for row in values:
                identifier = row['id']
                if type(identifier) is not int or identifier <= 0 or identifier in seen:
                    raise HistoryImportError('History source has invalid row identities')
                seen.add(identifier)
                datetime.fromisoformat(row['created_at'])
                for field, expected in _JSON_FIELDS[kind].items():
                    parsed = json.loads(row[field])
                    if not isinstance(parsed, expected):
                        raise HistoryImportError('History source JSON shape is invalid')
                    _canonical(parsed)
                _canonical(row)
                if kind == 'queries':
                    elapsed = row['response_time_ms']
                    if (row['input_type'] not in ('pnu', 'address', 'raw') or not isinstance(row['error'], str)
                            or type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0):
                        raise HistoryImportError('History query fields are invalid')
            rows[kind] = values
        result_ids = {row['id'] for row in rows['results']}
        for row in rows['queries']:
            link = row['analysis_result_id']
            if link is not None and (type(link) is not int or link not in result_ids):
                raise HistoryImportError('History source contains a broken result reference')
        return rows


def _write(db, source_id, rows, digest):
    now = datetime.now(timezone.utc).isoformat()
    db.execute('INSERT OR IGNORE INTO legacy_sources VALUES (?,?)', (source_id, now))
    counts = {}
    for kind, values in rows.items():
        table = 'legacy_' + kind
        inserted = unchanged = 0
        for row in values:
            encoded = _canonical(row)
            row_hash = _hash(encoded)
            previous = db.execute('SELECT row_sha256 FROM ' + table + ' WHERE source_id=? AND source_pk=?',
                                  (source_id, row['id'])).fetchone()
            if previous:
                if previous[0] != row_hash:
                    raise HistoryImportError('History row conflict; import rolled back')
                unchanged += 1
                continue
            parameters = [source_id, row['id'], row['created_at'], encoded, row_hash]
            if kind == 'queries':
                parameters.extend([row['input_type'], row['response_time_ms'], row['error'], row['analysis_result_id']])
            db.execute('INSERT INTO ' + table + ' VALUES (' + ','.join('?' for _ in parameters) + ')', parameters)
            inserted += 1
        counts[kind] = {'total': len(values), 'inserted': inserted, 'unchanged': unchanged}
    db.execute('INSERT OR IGNORE INTO history_imports VALUES (?,?,?,?,?)',
               (source_id, digest, now, len(rows['queries']), len(rows['results'])))
    return counts


def import_history(repository, source_path, source_id, *, dry_run=True):
    """Validate and atomically archive; dry runs never create or migrate the destination."""
    if not isinstance(source_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', source_id):
        raise HistoryImportError('Invalid history source identifier')
    if type(dry_run) is not bool:
        raise HistoryImportError('dry_run must be boolean')
    try:
        path = Path(source_path).resolve(strict=True)
        if (path == repository.path.resolve()
                or (repository.path.exists() and path.samefile(repository.path))):
            raise HistoryImportError('History source and destination must differ')
        rows = _read_rows(path)
        digest = _hash(_canonical(rows))
        if dry_run:
            with closing(sqlite3.connect(':memory:')) as db, db:
                if repository.path.exists():
                    _snapshot(repository.path.resolve(), db)
                repository._ensure_schema(db)
                counts = _write(db, source_id, rows, digest)
        else:
            with repository._transaction() as db:
                counts = _write(db, source_id, rows, digest)
        return {'source_id': source_id, 'dry_run': dry_run, 'snapshot_sha256': digest, **counts}
    except HistoryImportError:
        raise
    except (OSError, sqlite3.Error, ValueError, TypeError, OverflowError):
        raise HistoryImportError('History import failed validation or storage checks') from None
