"""One logical B021 snapshot: frozen compressed base + writable uncompressed delta.

No source rows or geometry are transformed again. The original writer lock guards
both files. The union remains incomplete until every original source is complete.
"""
import argparse
from contextlib import closing, contextmanager
import json
import os
from pathlib import Path
import sqlite3
import sys
import zlib

from ingest_ngii_buildings import open_db, run, packed, write_json, region_inventory, completed_source_gate


def readonly(path):
    return sqlite3.connect(f'file:{Path(path).resolve().as_posix()}?mode=ro',uri=True)


def identity(path):
    path=Path(path).resolve();st=path.stat()
    return {'path':path.as_posix(),'bytes':st.st_size,'mtimeNs':str(st.st_mtime_ns)}


def verify_base(snapshot):
    if identity(snapshot['base']['path'])!={k:snapshot['base'][k] for k in ('path','bytes','mtimeNs')}:
        raise ValueError('Frozen canonical base changed')
    wal=Path(snapshot['base']['path']+'-wal')
    if wal.exists() and wal.stat().st_size:
        raise ValueError('Frozen base has uncheckpointed writes')


@contextmanager
def writer_lock(base):
    lock=(Path(base).parent/'ingest.lock').open('a+b')
    try:
        if lock.seek(0,2)==0:lock.write(b'0');lock.flush()
        lock.seek(0)
        if sys.platform=='win32':
            import msvcrt
            msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield
    finally:lock.close()


def initialize(plan,base,output):
    base=Path(base).resolve();output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    if output/'buildings.sqlite'==base:raise ValueError('Delta must not overwrite base')
    path=output/'canonical-snapshot.json'
    marker=base.parent/'frozen-base.json'
    binding={'schema':'ngii-frozen-base-v1','snapshot':path.as_posix(),'planSHA256':plan['planSHA256']}
    if marker.exists() and json.loads(marker.read_text(encoding='utf-8'))!=binding:
        raise ValueError('Base already belongs to another snapshot')
    if path.exists():
        snapshot=json.loads(path.read_text(encoding='utf-8'));verify_base(snapshot)
        if snapshot['planSHA256']!=plan['planSHA256'] or snapshot['base']['path']!=base.as_posix():
            raise ValueError('Snapshot source identity mismatch')
        if not marker.exists():write_json(marker,binding)
        return snapshot
    with closing(readonly(base)) as prior:
        if prior.execute("SELECT value FROM metadata WHERE key='planSHA256'").fetchone()!=(plan['planSHA256'],):
            raise ValueError('Base plan mismatch')
        cursors=list(prior.execute('SELECT id,expected_rows,next_row,status,manifest FROM sources ORDER BY id'))
        if prior.execute('SELECT 1 FROM issues LIMIT 1').fetchone():raise ValueError('Base issues unresolved')
    snapshot={'schema':'ngii-canonical-snapshot-v1','planSHA256':plan['planSHA256'],
              'base':{**identity(base),'sourceCursors':cursors},'delta':{'path':(output/'buildings.sqlite').as_posix()},'complete':False}
    verify_base(snapshot)
    with closing(open_db(output/'buildings.sqlite',plan)) as db:
        initialized=db.execute("SELECT value FROM metadata WHERE key='baseIdentity'").fetchone()
        pin=packed(snapshot['base'])
        if initialized and initialized!=(pin,):raise ValueError('Delta base identity mismatch')
        if not initialized:
            if db.execute('SELECT 1 FROM observations LIMIT 1').fetchone():raise ValueError('Unbound delta already has rows')
            with db:
                for key,expected,cursor,state,manifest in cursors:
                    db.execute('UPDATE sources SET expected_rows=?,next_row=?,status=?,manifest=? WHERE id=?',(expected,cursor,state,manifest,key))
                db.execute("INSERT INTO metadata VALUES('baseIdentity',?)",(pin,))
    write_json(path,snapshot)
    write_json(marker,binding)
    return snapshot


@contextmanager
def open_snapshot(snapshot):
    if snapshot.get('schema')!='ngii-canonical-snapshot-v1':raise ValueError('Invalid snapshot schema')
    verify_base(snapshot)
    if snapshot.get('complete'):
        wal=Path(snapshot['delta']['path']+'-wal')
        if identity(snapshot['delta']['path'])!=snapshot['delta'] or (wal.exists() and wal.stat().st_size):
            raise ValueError('Completed delta changed')
    db=sqlite3.connect(':memory:',uri=True)
    try:
        for alias in ('base','delta'):
            path=Path(snapshot[alias]['path']).resolve()
            db.execute(f'ATTACH DATABASE ? AS {alias}',(f'file:{path.as_posix()}?mode=ro',))
        db.executescript('''
        CREATE TEMP VIEW metadata AS SELECT * FROM delta.metadata;
        CREATE TEMP VIEW sources AS SELECT * FROM delta.sources;
        CREATE TEMP VIEW buildings AS SELECT * FROM base.buildings UNION ALL SELECT * FROM delta.buildings;
        CREATE TEMP VIEW observations AS SELECT * FROM base.observations UNION ALL SELECT * FROM delta.observations;
        CREATE TEMP VIEW issues AS SELECT * FROM base.issues UNION ALL SELECT * FROM delta.issues;
        PRAGMA query_only=ON; BEGIN;
        ''')
        if db.execute("SELECT value FROM metadata WHERE key='planSHA256'").fetchone()!=(snapshot['planSHA256'],):
            raise ValueError('Delta plan mismatch')
        if json.loads(db.execute("SELECT value FROM metadata WHERE key='baseIdentity'").fetchone()[0])!=json.loads(packed(snapshot['base'])):
            raise ValueError('Delta base binding mismatch')
        yield db
    finally:db.close()


def verify_partition(snapshot):
    """Count contiguous per-source observations through indexed ranges; no full-data copy."""
    with open_snapshot(snapshot) as db:
        for key,expected,split,state,manifest in snapshot['base']['sourceCursors']:
            row=db.execute('SELECT expected_rows,next_row FROM delta.sources WHERE id=?',(key,)).fetchone()
            if not row or row[0]!=expected or not split<=row[1]<=expected:raise ValueError('Invalid cumulative source cursor')
            for alias,lower,upper in [('base',0,split),('delta',split,row[1])]:
                count,first,last=db.execute(f'SELECT count(*),min(row_number),max(row_number) FROM {alias}.observations WHERE source_id=?',(key,)).fetchone()
                if count!=upper-lower or (count and (first!=lower or last!=upper-1)):
                    raise ValueError('Observation partition gap or overlap')
        if db.execute('SELECT 1 FROM delta.buildings d JOIN base.buildings b ON d.id=b.id LIMIT 1').fetchone():
            raise ValueError('Duplicate canonical ID across snapshot')


def ingest(plan,base,output,*,max_rows=0):
    with writer_lock(base):
        snapshot=initialize(plan,base,output)
        with closing(readonly(base)) as prior:
            result=run(plan,output,max_rows=max_rows,geometry_batch=True,wal_pages=16384,
                       prior_db=prior,validate_prior=lambda:verify_base(snapshot))
        verify_base(snapshot)
        if result['complete']:
            verify_partition(snapshot);snapshot['complete']=True
            snapshot['delta'].update(identity(snapshot['delta']['path']))
            write_json(Path(output)/'canonical-snapshot.json',snapshot)
        return result


def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
    q=sub.add_parser('run');q.add_argument('--plan',required=True);q.add_argument('--base',required=True);q.add_argument('--output',required=True);q.add_argument('--max-rows',type=int,default=0)
    for name in ('regions','export-region','verify'):
        q=sub.add_parser(name);q.add_argument('--snapshot',required=True)
        if name in ('regions','verify'):q.add_argument('--plan',required=True)
        if name=='regions':q.add_argument('--output',required=True)
        if name=='export-region':q.add_argument('--region',required=True)
    a=p.parse_args()
    if a.command=='run':ingest(json.loads(Path(a.plan).read_text(encoding='utf-8')),a.base,a.output,max_rows=a.max_rows)
    else:
        snapshot=json.loads(Path(a.snapshot).read_text(encoding='utf-8'))
        if a.command in ('verify','regions') and snapshot.get('complete') is not True:
            raise ValueError('Canonical snapshot incomplete')
        with open_snapshot(snapshot) as db:
            if a.command=='verify':
                if snapshot.get('complete') is not True:raise ValueError('Canonical snapshot incomplete')
                completed_source_gate(db,json.loads(Path(a.plan).read_text(encoding='utf-8')))
                print(json.dumps({'complete':True,'planSHA256':snapshot['planSHA256']}))
            elif a.command=='regions':
                if snapshot.get('complete') is not True:raise ValueError('Canonical snapshot incomplete')
                result=region_inventory(db,json.loads(Path(a.plan).read_text(encoding='utf-8')));write_json(a.output,result)
            else:
                manifests={k:json.loads(v) for k,v in db.execute('SELECT id,manifest FROM sources')}
                for payload, in db.execute('SELECT payload FROM buildings WHERE region14=? ORDER BY region16,id',(a.region,)):
                    value=json.loads(zlib.decompress(payload));ref=value['provenance'];value['provenance']={**manifests[ref['sourceId']],'row':ref['row']}
                    sys.stdout.buffer.write(packed(value).encode()+b'\n')


if __name__=='__main__':main()
