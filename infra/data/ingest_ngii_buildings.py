"""Receipt-bound, resumable B021 canonical ingestion; never edits the served catalog."""
import argparse
import contextlib
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time
import zlib

from ngii_building_adapter import NgiiBuildingAdapter, HeightPolicy
from ngii_split_zip import stage_members
from ngii_building_batch import adapt_batch

GIB = 1024**3


def digest(data):
    return hashlib.sha256(data).hexdigest()


def packed(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def write_json(path, value):
    path=Path(path)
    temporary=path.with_name(path.name+f'.{os.getpid()}.tmp')
    temporary.write_text(packed(value),encoding='utf-8')
    temporary.replace(path)


def source_plan(root):
    root = Path(root).resolve()
    national = root / 'national-continuous-source-inventory.json'
    metadata = json.loads(national.read_text(encoding='utf-8'))
    if (metadata.get('productCode'), metadata.get('scale'), metadata.get('year'), metadata.get('format')) != ('B021', 5000, 2024, 'SHP'):
        raise ValueError('Unexpected official snapshot')
    sources = {}
    for code, area in sorted(metadata['providerAreas'].items()):
        inventory = root / area['inventoryFile']
        for row in json.loads(inventory.read_text(encoding='utf-8')):
            if 'N3A_B0010000' not in row['shp']:
                continue
            archive = root / row.get('path', f'{code}-files/{row["zip"]}')
            disks = sorted(archive.parent.glob(archive.stem+'.z[0-9][0-9]')) + [archive]
            bindings = []
            for disk in disks:
                receipt_path = disk.with_suffix(disk.suffix+'.receipt.json')
                receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
                if receipt.get('provider') != 'NGII' or receipt.get('format') != 'SHP' or receipt.get('requestedYear', receipt.get('year')) != 2024 or receipt.get('requestedScale', receipt.get('scale')) != 5000:
                    raise ValueError('Unexpected source receipt')
                st = disk.stat()
                if st.st_size != receipt['bytes']:
                    raise ValueError('Source size differs from receipt')
                bindings.append({'path':str(disk), 'bytes':st.st_size, 'mtimeNs':st.st_mtime_ns,
                                 'sha256':receipt['sha256'], 'receiptSHA256':digest(receipt_path.read_bytes())})
            key = digest(packed([[b['sha256'] for b in bindings], row['shp']]).encode())
            alias = {'providerArea':code, 'variant':row.get('variant'), 'archive':str(archive), 'inventorySHA256':digest(inventory.read_bytes())}
            if key in sources:
                sources[key]['aliases'].append(alias)
                continue
            if row['crs'] != 'EPSG:5179' or not {'UFID','NMLY','BJCD'} <= set(row['fields']):
                raise ValueError('Unverified B001 schema')
            sources[key] = {'id':key, 'shp':row['shp'], 'expectedRows':row['features'], 'bindings':bindings,
                            'aliases':[alias], 'manifest':{'family':'NGII-B021','productCode':'B021',
                            'productKind':'continuous-topographic','productReceiptSHA256':bindings[-1]['receiptSHA256'],
                            'layer':'N3A_B0010000','crs':'EPSG:5179','edition':'2024',
                            'sourceManifestSHA256':digest(inventory.read_bytes()),'file':row['zip']}}
    plan = {'schema':'ngii-canonical-plan-v1','storageSchema':'canonical-sqlite-v2','nationalInventorySHA256':digest(national.read_bytes()),
            'heightPolicy':asdict(HeightPolicy()),'sources':list(sources.values()),
            'providerAreaCount':len(metadata['providerAreas']), 'expectedRows':sum(s['expectedRows'] for s in sources.values())}
    plan['planSHA256'] = digest(packed(plan).encode())
    return plan


def tile(lon, lat, z):
    n=2**z
    return f'{z}/{math.floor((lon+180)/360*n)}/{math.floor((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*n)}'


def open_db(path, plan, wal_pages=1000):
    if not isinstance(wal_pages,int) or not 1 <= wal_pages <= 49152:
        raise ValueError('WAL checkpoint pages must be between 1 and 49152')
    db=sqlite3.connect(path)
    db.executescript('''PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; PRAGMA cache_size=-32768;
    CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT);
    CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,expected_rows INTEGER,next_row INTEGER DEFAULT 0,status TEXT DEFAULT 'pending',manifest TEXT);
    CREATE TABLE IF NOT EXISTS buildings(id TEXT PRIMARY KEY,region14 TEXT,region16 TEXT,ufid TEXT,bjcd TEXT,h REAL,height_source TEXT,payload BLOB);
    CREATE INDEX IF NOT EXISTS buildings_region ON buildings(region14,region16);
    CREATE TABLE IF NOT EXISTS observations(source_id TEXT,row_number INTEGER,id TEXT,bjcd TEXT,decision TEXT,PRIMARY KEY(source_id,row_number));
    CREATE TABLE IF NOT EXISTS issues(source_id TEXT,row_number INTEGER,kind TEXT,detail TEXT,PRIMARY KEY(source_id,row_number));''')
    db.execute(f'PRAGMA wal_autocheckpoint={wal_pages}')
    db.execute('PRAGMA journal_size_limit=268435456')
    old=db.execute("SELECT value FROM metadata WHERE key='planSHA256'").fetchone()
    if old and old[0]!=plan['planSHA256']:
        db.close()
        raise ValueError('Resume source plan mismatch')
    with db:
        db.execute("INSERT OR IGNORE INTO metadata VALUES('planSHA256',?)",(plan['planSHA256'],))
        for s in plan['sources']:
            db.execute('INSERT OR IGNORE INTO sources(id,expected_rows,manifest) VALUES(?,?,?)',(s['id'],s['expectedRows'],packed(s.get('manifest',{}))))
    return db


def ingest_batch(db, source, adapter, records, *, values=None, prior_db=None):
    records=list(records)
    if values is not None and len(values)!=len(records):
        raise ValueError('Geometry batch length mismatch')
    start=db.execute('SELECT next_row FROM sources WHERE id=?',(source['id'],)).fetchone()[0]
    with db:
        next_row=start
        for i,(row, props, geom) in enumerate(records):
            if row!=next_row:
                raise ValueError('Noncontiguous source cursor')
            value=adapter.adapt(props,geom,row=row) if values is None else values[i]
            bjcd=str(props.get('BJCD') or '')
            if 'rejected' in value:
                db.execute('INSERT INTO issues VALUES(?,?,?,?)',(source['id'],row,'rejected',packed(value)))
                decision='rejected';key=None
            else:
                key=value['canonicalBuildingId'];height_source=packed(value['heightSource'])
                old=db.execute('SELECT h,height_source FROM buildings WHERE id=?',(key,)).fetchone()
                if old is None and prior_db is not None:
                    old=prior_db.execute('SELECT h,height_source FROM buildings WHERE id=?',(key,)).fetchone()
                if old and old != (value['h'],height_source):
                    db.execute('INSERT INTO issues VALUES(?,?,?,?)',(source['id'],row,'conflict',packed(value)))
                    decision='conflict'
                elif old:
                    decision='duplicate'
                else:
                    lon,lat=value['anchorWGS84'];value['bjcd']=bjcd
                    value['provenance']={'sourceId':source['id'],'row':row}
                    db.execute('INSERT INTO buildings VALUES(?,?,?,?,?,?,?,?)',(key,tile(lon,lat,14),tile(lon,lat,16),value['sourceUFID'],bjcd,value['h'],height_source,zlib.compress(packed(value).encode(),1)))
                    decision='inserted'
            db.execute('INSERT INTO observations VALUES(?,?,?,?,?)',(source['id'],row,key,bjcd,decision))
            next_row+=1
        db.execute("UPDATE sources SET next_row=?,status=CASE WHEN expected_rows=? THEN 'complete' ELSE 'partial' END WHERE id=?",(next_row,next_row,source['id']))
    return next_row-start


def status(db, plan, prior_db=None):
    counts=dict(db.execute('SELECT decision,count(*) FROM observations GROUP BY decision'))
    prefixes=dict(db.execute('SELECT substr(bjcd,1,2),count(*) FROM observations GROUP BY substr(bjcd,1,2)'))
    if prior_db is not None:
        for key,count in prior_db.execute('SELECT decision,count(*) FROM observations GROUP BY decision'):
            counts[key]=counts.get(key,0)+count
        for key,count in prior_db.execute('SELECT substr(bjcd,1,2),count(*) FROM observations GROUP BY substr(bjcd,1,2)'):
            prefixes[key]=prefixes.get(key,0)+count
    done,total=db.execute("SELECT sum(status='complete'),count(*) FROM sources").fetchone()
    return {'planSHA256':plan['planSHA256'],'expectedRows':plan['expectedRows'],'processedRows':sum(counts.values()),
            'counts':counts,'sourcesComplete':done,'sourcesTotal':total,
            'complete':done==total and not counts.get('rejected',0) and not counts.get('conflict',0),
            'bjcdPrefixes':prefixes}


def run(plan, output, max_rows=0, batch_size=2000, geometry_batch=False, wal_pages=1000, prior_db=None, validate_prior=None):
    import pyogrio
    import shapely
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    if (output/'frozen-base.json').exists():
        raise ValueError('Frozen canonical base; resume the snapshot writer instead')
    lock=(output/'ingest.lock').open('a+b')
    if sys.platform=='win32':
        import msvcrt
        lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    db=open_db(output/'buildings.sqlite',plan,wal_pages);processed=0
    try:
        write_json(output/'plan.json',plan)
        for source in plan['sources']:
            cursor=db.execute('SELECT next_row FROM sources WHERE id=?',(source['id'],)).fetchone()[0]
            if cursor==source['expectedRows']:continue
            for b in source['bindings']:
                st=Path(b['path']).stat()
                if (st.st_size,st.st_mtime_ns)!=(b['bytes'],b['mtimeNs']):raise ValueError('Source changed since plan')
            disks=[Path(b['path']) for b in source['bindings']]
            stage=output/'stage'/source['id']
            if len(disks)>1:
                stem=source['shp'][:-4];wanted=[stem+ext for ext in ['.shp','.shx','.dbf','.prj']]
                stage_members(disks,stage,wanted,20*GIB)
                uri=str(stage/source['shp'])
            else:uri=f'zip://{disks[0].as_posix()}!{source["shp"]}'
            adapter=NgiiBuildingAdapter(source['manifest'],HeightPolicy(**plan['heightPolicy']))
            with pyogrio.open_arrow(uri,columns=['UFID','NMLY','BJCD'],skip_features=cursor,batch_size=batch_size,use_pyarrow=True) as (meta,reader):
                geometry_column=meta['geometry_name'] or 'wkb_geometry'
                for batch in reader:
                    if validate_prior is not None:validate_prior()
                    if shutil.disk_usage(output).free<20*GIB:raise RuntimeError('20 GiB storage reserve')
                    wal=output/'buildings.sqlite-wal'
                    if wal.exists() and wal.stat().st_size>256*1024**2:
                        raise RuntimeError('WAL exceeded 256 MiB budget; release long-lived readers before resume')
                    if max_rows and processed>=max_rows:break
                    data=batch.to_pydict();count=batch.num_rows
                    if max_rows:count=min(count,max_rows-processed)
                    geoms=shapely.from_wkb(data[geometry_column][:count])
                    records=[(cursor+i,{k:data[k][i] for k in ['UFID','NMLY','BJCD']},geoms[i]) for i in range(count)]
                    geometry_start=time.perf_counter()
                    values=adapt_batch(adapter,records) if geometry_batch else None
                    geometry_ms=(time.perf_counter()-geometry_start)*1000
                    write_start=time.perf_counter()
                    consumed=ingest_batch(db,source,adapter,records,values=values,prior_db=prior_db);cursor+=consumed;processed+=consumed
                    write_ms=(time.perf_counter()-write_start)*1000
                    # Cheap counters for frequent progress; full grouped report only at stopping boundaries.
                    progress={'source':source['id'],'sourceRow':cursor,'sourceRows':source['expectedRows'],'thisRunRows':processed,'time':time.time(),
                              'geometryBatch':geometry_batch,'geometryMs':geometry_ms,'writeIncludingCheckpointMs':write_ms,
                              'walCheckpointPages':wal_pages,'walBytes':wal.stat().st_size if wal.exists() else 0}
                    write_json(output/'progress.json',progress)
                    print(packed(progress),flush=True)
            if cursor != source['expectedRows'] and not (max_rows and processed>=max_rows):
                raise ValueError(f'Source row count mismatch: {cursor} versus {source["expectedRows"]}')
            if cursor==source['expectedRows'] and stage.exists():
                if stage.resolve().is_relative_to((output/'stage').resolve()):shutil.rmtree(stage)
            if max_rows and processed>=max_rows:break
        done,total,processed_total=db.execute("SELECT sum(status='complete'),count(*),sum(next_row) FROM sources").fetchone()
        if prior_db is not None and max_rows and done!=total:
            result={'planSHA256':plan['planSHA256'],'expectedRows':plan['expectedRows'],'processedRows':processed_total,
                    'sourcesComplete':done,'sourcesTotal':total,'complete':False,'fullStatisticsDeferred':True}
        else:result=status(db,plan,prior_db)
        write_json(output/'status.json',result);print(packed(result),flush=True)
        return result
    finally:
        db.close();lock.close()


def completed_source_gate(db, plan):
    unsigned={k:v for k,v in plan.items() if k!='planSHA256'}
    if digest(packed(unsigned).encode())!=plan['planSHA256']:
        raise ValueError('Plan content hash mismatch')
    stored=db.execute("SELECT value FROM metadata WHERE key='planSHA256'").fetchone()
    if stored!=(plan['planSHA256'],):raise ValueError('Database plan mismatch')
    actual={r[0]:r[1:] for r in db.execute('SELECT id,expected_rows,next_row,status,manifest FROM sources')}
    if set(actual)!={s['id'] for s in plan['sources']}:raise ValueError('Source set mismatch')
    for s in plan['sources']:
        expected,cursor,state,manifest=actual[s['id']]
        if (expected,cursor,state)!=(s['expectedRows'],s['expectedRows'],'complete'):
            raise ValueError('Source ingest incomplete')
        if json.loads(manifest)!=s.get('manifest',{}):raise ValueError('Source manifest mismatch')
        for b in s['bindings']:
            path=Path(b['path']);st=path.stat()
            receipt=path.with_suffix(path.suffix+'.receipt.json')
            if (st.st_size,st.st_mtime_ns)!=(b['bytes'],b['mtimeNs']) or digest(receipt.read_bytes())!=b['receiptSHA256']:
                raise ValueError('Source receipt or file changed')
            value=json.loads(receipt.read_text(encoding='utf-8'))
            if (value['bytes'],value['sha256'])!=(b['bytes'],b['sha256']):raise ValueError('Source binding mismatch')
    if db.execute('SELECT 1 FROM issues LIMIT 1').fetchone():raise ValueError('Source issues unresolved')


def region_inventory(db, plan, *, progress=None):
    """One payload pass, bounded by region count; caller holds a read snapshot."""
    completed_source_gate(db,plan)
    try:
        from orjson import loads as payload_loads
    except ImportError:
        payload_loads=json.loads
    regions={};prefixes={};count=0
    for region,bjcd,payload in db.execute('SELECT region14,bjcd,payload FROM buildings'):
        value=payload_loads(zlib.decompress(payload));g=value['geomWGS84']
        parts=1 if g['type']=='Polygon' else len(g['coordinates']) if g['type']=='MultiPolygon' else 0
        if not parts:raise ValueError('Nonpolygon canonical building')
        row=regions.setdefault(region,{'region14':region,'buildings':0,'components':0})
        row['buildings']+=1;row['components']+=parts;count+=1
        prefix=str(bjcd)[:2];prefixes[prefix]=prefixes.get(prefix,0)+1
        if progress is not None and count%1_000_000==0:progress(count)
    return {'schema':'ngii-canonical-regions-v1','planSHA256':plan['planSHA256'],
            'sourceComplete':True,'sourceRows':plan['expectedRows'],'buildingCount':count,
            'regionCount':len(regions),'bjcdPrefixes':prefixes,'regions':[regions[k] for k in sorted(regions)]}


def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('plan');a.add_argument('--orders',required=True);a.add_argument('--output',required=True)
    a=sub.add_parser('run');a.add_argument('--plan',required=True);a.add_argument('--output',required=True);a.add_argument('--max-rows',type=int,default=0);a.add_argument('--geometry-batch',action='store_true');a.add_argument('--wal-pages',type=int,default=1000)
    a=sub.add_parser('export-region');a.add_argument('--database',required=True);a.add_argument('--region',required=True)
    a=sub.add_parser('regions');a.add_argument('--database',required=True);a.add_argument('--plan',required=True);a.add_argument('--output',required=True)
    a=p.parse_args()
    if a.command=='plan':
        plan=source_plan(a.orders);Path(a.output).parent.mkdir(parents=True,exist_ok=True);Path(a.output).write_text(packed(plan),encoding='utf-8');print(packed({'planSHA256':plan['planSHA256'],'sources':len(plan['sources']),'expectedRows':plan['expectedRows']}))
    elif a.command=='run':run(json.loads(Path(a.plan).read_text(encoding='utf-8')),a.output,a.max_rows,geometry_batch=a.geometry_batch,wal_pages=a.wal_pages)
    elif a.command=='regions':
        db=sqlite3.connect(f'file:{Path(a.database).as_posix()}?mode=ro',uri=True)
        try:
            db.execute('BEGIN')
            result=region_inventory(db,json.loads(Path(a.plan).read_text(encoding='utf-8')))
            write_json(a.output,result)
            print(packed({k:v for k,v in result.items() if k!='regions'}))
        finally:db.close()
    else:
        db=sqlite3.connect(f'file:{Path(a.database).as_posix()}?mode=ro',uri=True)
        manifests={key:json.loads(value) for key,value in db.execute('SELECT id,manifest FROM sources')}
        for row in db.execute('SELECT payload FROM buildings WHERE region14=? ORDER BY region16,id',(a.region,)):
            value=json.loads(zlib.decompress(row[0]));ref=value['provenance']
            value['provenance']={**manifests[ref['sourceId']],'row':ref['row']}
            sys.stdout.buffer.write(packed(value).encode()+b'\n')


if __name__=='__main__':main()
