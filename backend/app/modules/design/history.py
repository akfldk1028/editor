"""Read-only source snapshots and atomic, immutable archives of design rows."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from uuid import UUID

from .repository import JSON_FIELDS


class DesignHistoryError(ValueError):
    pass


TABLES = {'jobs':'design_optimizationjob', 'results':'design_designresult', 'revisions':'design_maasrevisionevent'}
REQUIRED = {'jobs':{'id','created_at','status',*JSON_FIELDS['jobs']},
            'results':{'id','job_id','generation','design_id','is_feasible','is_pareto_optimal',*JSON_FIELDS['results']},
            'revisions':{'id','job_id','created_at',*JSON_FIELDS['revisions']}}


def _canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def _hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _snapshot(path, target):
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        db.backup(target)


def _validate(row, kind):
    if kind == 'results':
        if type(row['id']) is not int or row['id'] < 1:
            raise ValueError('Invalid result identity')
        for key in ('generation','design_id'):
            if type(row[key]) is not int or row[key] < 0:
                raise ValueError('Invalid result sequence')
        for key in ('is_feasible','is_pareto_optimal'):
            if row[key] not in (0,1):
                raise ValueError('Invalid result flag')
    else:
        UUID(row['id'])
        datetime.fromisoformat(row['created_at'])
    if kind == 'jobs' and row['status'] not in ('pending','running','complete','failed','cancelled'):
        raise ValueError('Invalid source status')
    for key in JSON_FIELDS[kind]:
        raw = row[key]
        if key == 'mass_geojson' and raw is None:
            continue
        value = json.loads(raw)
        if key == 'mass_geojson' and value is None:
            continue
        expected = (list,dict) if key == 'inputs' else (list if key in ('constraints','graph_diff') else dict)
        if not isinstance(value, expected):
            raise ValueError('Invalid design JSON shape')
        _canonical(value)
    _canonical(row)


def _read(path):
    if not path.is_file() or path.stat().st_size > 512*1024*1024:
        raise ValueError('Source size invalid')
    with closing(sqlite3.connect(':memory:')) as db:
        _snapshot(path,db)
        db.row_factory=sqlite3.Row
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Source integrity invalid')
        rows={}
        for kind,table in TABLES.items():
            exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()
            if not exists and kind == 'revisions':
                rows[kind]=[]
                continue
            columns={row['name'] for row in db.execute('PRAGMA table_info('+table+')')}
            if not exists or not REQUIRED[kind] <= columns:
                raise ValueError('Source schema unsupported')
            if db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] > 100000:
                raise ValueError('Source exceeds row limit')
            values=[dict(row) for row in db.execute('SELECT * FROM '+table+' ORDER BY id')]
            identities=set()
            for row in values:
                _validate(row,kind)
                if row['id'] in identities:
                    raise ValueError('Duplicate source identity')
                identities.add(row['id'])
            rows[kind]=values
        jobs={row['id'] for row in rows['jobs']}
        for kind in ('results','revisions'):
            for row in rows[kind]:
                link=row['job_id']
                if link not in jobs and not (kind=='revisions' and link is None):
                    raise ValueError('Broken design job reference')
        return rows


def _write(db,source_id,rows,digest):
    now=datetime.now(timezone.utc).isoformat()
    db.execute('INSERT OR IGNORE INTO sources VALUES (?,?)',(source_id,now))
    report={}
    for kind,values in rows.items():
        key={'jobs':'job_id','results':'result_pk','revisions':'revision_id'}[kind]
        inserted=unchanged=0
        for row in values:
            encoded=_canonical(row);row_hash=_hash(encoded)
            old=db.execute('SELECT row_sha256 FROM '+kind+' WHERE source_id=? AND '+key+'=?',
                           (source_id,row['id'])).fetchone()
            if old:
                if old[0]!=row_hash:
                    raise DesignHistoryError('Design history row conflict; import rolled back')
                unchanged+=1
                continue
            if kind=='jobs':
                params=[source_id,row['id'],row['created_at'],row['status'],encoded,row_hash]
            elif kind=='revisions':
                params=[source_id,row['id'],row['job_id'],encoded,row_hash]
            else:
                mass=json.loads(row['mass_geojson']) if row['mass_geojson'] is not None else None
                summary={key:row.get(key) for key in ('ranking','crowding_distance')}
                summary.update(outputs=json.loads(row['outputs']),is_feasible=bool(row['is_feasible']),
                               is_pareto_optimal=bool(row['is_pareto_optimal']))
                params=[source_id,row['id'],row['job_id'],row['generation'],row['design_id'],
                        int(mass is not None),_canonical(summary),encoded,row_hash]
            db.execute('INSERT INTO '+kind+' VALUES ('+','.join('?' for _ in params)+')',params)
            inserted+=1
        report[kind]={'total':len(values),'inserted':inserted,'unchanged':unchanged}
    db.execute('INSERT OR IGNORE INTO imports VALUES (?,?,?,?)',(source_id,digest,now,_canonical(report)))
    return report


def import_history(repository,source_path,source_id='arr-design-main',*,dry_run=True):
    if not isinstance(source_id,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}',source_id):
        raise DesignHistoryError('Invalid design source identifier')
    if type(dry_run) is not bool:
        raise DesignHistoryError('dry_run must be boolean')
    try:
        path=Path(source_path).resolve(strict=True)
        if path==repository.path.resolve() or (repository.path.exists() and path.samefile(repository.path)):
            raise DesignHistoryError('Source and destination must differ')
        rows=_read(path)
        digest=_hash(_canonical(rows))
        if dry_run:
            with closing(sqlite3.connect(':memory:')) as db,db:
                if repository.path.exists():
                    _snapshot(repository.path.resolve(),db)
                repository._ensure_schema(db)
                report=_write(db,source_id,rows,digest)
        else:
            with repository._transaction() as db:
                report=_write(db,source_id,rows,digest)
        return {'source_id':source_id,'dry_run':dry_run,'snapshot_sha256':digest,**report}
    except DesignHistoryError:
        raise
    except (ValueError,TypeError,AttributeError,OSError,sqlite3.Error,OverflowError):
        raise DesignHistoryError('Design history failed validation or storage checks') from None
