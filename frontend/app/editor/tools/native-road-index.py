"""Immutable native B021 road index candidate. No serving pointers or source writes."""
import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time
import zlib

import numpy as np
import pyogrio
from PIL import Image
from pyproj import Transformer
from rasterio.features import rasterize
from rasterio.transform import from_bounds
import shapely
from shapely.geometry import box

spec=importlib.util.spec_from_file_location('national_roads',Path(__file__).with_name('bake-ngii-national-roads.py'))
road=importlib.util.module_from_spec(spec);spec.loader.exec_module(road)
CHECKPOINT=8192
RESERVE=20*1024**3


def road_id(ordinal,fid):
    if type(ordinal) is not int or not 1<=ordinal<=17 or type(fid) is not int or not 0<=fid<2**32:
        raise ValueError('Road identity requires source ordinal1..17 and uint32 FID')
    return (ordinal<<32)|fid


def restore_id(identifier,sources):
    ordinal=identifier>>32;fid=identifier&0xffffffff
    if road_id(ordinal,fid)!=identifier or ordinal not in sources:raise ValueError('Unknown indexed source ordinal')
    return sources[ordinal],fid


def space(folder,extra=64*1024**2):
    if shutil.disk_usage(folder).free<RESERVE+extra:raise OSError('needs_storage: 20GiB reserve')


@contextmanager
def locked(folder):
    with (folder/'index.lock').open('a+b') as f:
        if f.seek(0,2)==0:f.write(b'0');f.flush()
        f.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield


def load_inputs(plan_path,receipt_path):
    plan=json.loads(Path(plan_path).read_bytes());receipt=json.loads(Path(receipt_path).read_bytes());items=plan['sourceItems']
    if (len(items)!=17 or len({s['sourceId'] for s in items})!=17 or not receipt['completeCoverage']
        or receipt['repairedFeatures']!=37 or receipt['rejectedFeatures']!=0
        or receipt['acceptedFeatures']!=sum(i['features'] for i in items)
        or receipt['sourcePlanSHA256']!=hashlib.sha256(road.common.encoded(items)).hexdigest()):raise ValueError('Completed national road proof required')
    expected={}
    source_map={s['sourceId']:s for s in items}
    if {a['sourceId'] for a in receipt['sourceAudits']}!=set(source_map) or len(receipt['sourceAudits'])!=17:
        raise ValueError('Prior source audit set differs')
    for audit in receipt['sourceAudits']:
        if audit['acceptedFeatures']!=source_map[audit['sourceId']]['features'] or audit['rejectedFeatures']!=0:
            raise ValueError('Prior source count proof differs')
        if road.common.sha(audit['audit'])!=audit['auditSHA256']:raise ValueError('Prior repair audit changed')
        for line in Path(audit['audit']).read_bytes().splitlines():
            r=json.loads(line);expected[(r['sourceId'],int(r['FID']))]=r
    if len(expected)!=37 or any(r['status']!='repaired' for r in expected.values()):raise ValueError('Expected exact37 repair proof')
    road.assert_sources(items)
    return items,expected


def stream(item,cursor):
    uri='/vsizip/'+Path(item['path']).as_posix()+'/N3A_A0010000.shp'
    with pyogrio.open_arrow(uri,columns=['UFID'],return_fids=True,skip_features=cursor,batch_size=256,use_pyarrow=True) as (meta,reader):
        if str(meta['crs'])!='EPSG:5179':raise ValueError('Source CRS differs')
        for batch in reader:yield batch.to_pylist(),meta['geometry_name'] or 'wkb_geometry',meta['fid_column']


def initialize(db,identity,items):
    db.executescript('''PRAGMA journal_mode=DELETE; PRAGMA synchronous=FULL; PRAGMA cache_size=-16384;
    PRAGMA temp_store=FILE; PRAGMA threads=1;
    CREATE TABLE IF NOT EXISTS metadata(identity TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS sources(sourceId TEXT PRIMARY KEY,ordinal INTEGER UNIQUE NOT NULL,expected INTEGER,next_row INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS roads(id INTEGER PRIMARY KEY,wkb BLOB NOT NULL);
    CREATE VIRTUAL TABLE IF NOT EXISTS bounds USING rtree(id,minx,maxx,miny,maxy);
    CREATE TABLE IF NOT EXISTS repairs(sourceId TEXT,fid INTEGER,record TEXT,PRIMARY KEY(sourceId,fid));''')
    pin=road.common.encoded(identity).decode();old=db.execute('SELECT identity FROM metadata').fetchone()
    if old and old[0]!=pin:raise ValueError('Index identity changed')
    if not old:
        with db:
            db.execute('INSERT INTO metadata VALUES(?)',(pin,))
            db.executemany('INSERT INTO sources VALUES(?,?,?,0)',[(i['sourceId'],identity['sourceOrdinals'][i['sourceId']],i['features']) for i in items])


def build(items,expected,output,*,source_id=None,max_rows=0,iterator=stream):
    selected=[s for s in items if source_id is None or s['sourceId']==source_id]
    if not selected:raise ValueError('Unknown source')
    ordinals={key:i+1 for i,key in enumerate(sorted(s['sourceId'] for s in items))}
    if len(ordinals)!=len(items) or len(items)>17:raise ValueError('Invalid unique road source set')
    identity={'schema':'ngii-native-road-index-v2','sources':selected,'sourceOrdinals':ordinals,'sourceCRS':'EPSG:5179','targetCRS':'EPSG:3857',
              'storage':'float64-WKB-zlib1-rtree-ordinal32-fid32-v2','implementationSHA256':road.common.sha(__file__),
              'projectionSHA256':road.common.sha(road.__file__),'expectedRepairs':list(expected.values()),
              'nationalSelection':source_id is None and len(selected)==17}
    folder=Path(output).resolve()/hashlib.sha256(road.common.encoded(identity)).hexdigest();folder.mkdir(parents=True,exist_ok=True)
    with locked(folder):
        space(folder);road.assert_sources(selected)
        final=folder/'roads.sqlite';stage=folder/'roads.staging.sqlite'
        if final.exists():
            receipt=json.loads((folder/'receipt.json').read_bytes())
            if road.common.sha(final)!=receipt['sha256']:raise ValueError('Immutable index changed')
            return receipt
        db=sqlite3.connect(stage)
        try:initialize(db,identity,selected)
        except Exception:
            db.close();raise
        started=time.monotonic();initial=db.execute('SELECT sum(next_row) FROM sources').fetchone()[0];total=initial
        project=Transformer.from_crs(5179,3857,always_xy=True).transform
        # Full Mercator coverage prevents the display-mask's Korea bbox clipping source polygons.
        coverage=box(-road.common.HALF_WORLD,-road.common.HALF_WORLD,road.common.HALF_WORLD,road.common.HALF_WORLD)
        try:
            for item in selected:
                cursor=db.execute('SELECT next_row FROM sources WHERE sourceId=?',(item['sourceId'],)).fetchone()[0]
                if cursor==item['features']:continue
                pending=0;db.execute('BEGIN')
                for rows,geom,fid in iterator(item,cursor):
                    if max_rows and total>=max_rows:break
                    if max_rows:rows=rows[:max_rows-total]
                    records=[]
                    def audit(r):
                        if expected.get((r['sourceId'],int(r['FID'])))!=r:raise ValueError('Repair differs from completed source audit')
                        records.append(r)
                    geometries=road.project_road_batch(rows,geom,fid,item,coverage,project,audit)
                    packed=[]
                    for row,g in zip(rows,geometries):
                        if g.is_empty or not np.isfinite(g.bounds).all():raise ValueError('Empty/nonfinite projected road')
                        raw=shapely.to_wkb(g,byte_order=1,output_dimension=2)
                        packed.append((road_id(ordinals[item['sourceId']],row[fid]),zlib.compress(raw,1),g.bounds))
                    space(folder,64*1024**2+2*sum(len(blob)+8192 for _,blob,_ in packed))
                    for feature_id,blob,bounds in packed:
                        db.execute('INSERT INTO roads(id,wkb) VALUES(?,?)',(feature_id,blob))
                        w,s,e,n=bounds;db.execute('INSERT INTO bounds VALUES(?,?,?,?,?)',(feature_id,w,e,s,n))
                    for r in records:db.execute('INSERT INTO repairs VALUES(?,?,?)',(r['sourceId'],int(r['FID']),road.common.encoded(r).decode()))
                    cursor+=len(rows);total+=len(rows);pending+=len(rows)
                    db.execute('UPDATE sources SET next_row=? WHERE sourceId=?',(cursor,item['sourceId']))
                    if pending>=CHECKPOINT:
                        space(folder);road.assert_sources(selected);db.commit();pending=0
                        road.atomic_json(folder/'progress.json',{'rows':total,'complete':False,'sourceId':item['sourceId'],'cursor':cursor})
                        db.execute('BEGIN')
                space(folder);road.assert_sources(selected);db.commit()
                if max_rows and total>=max_rows:break
            counts=list(db.execute('SELECT sourceId,expected,next_row FROM sources ORDER BY sourceId'))
            repairs=[json.loads(r[0]) for r in db.execute('SELECT record FROM repairs ORDER BY sourceId,fid')]
            complete=identity['nationalSelection'] and all(e==n for _,e,n in counts)
            if complete and {(r['sourceId'],int(r['FID'])):r for r in repairs}!=expected:raise ValueError('National repair proof differs')
            result={'schema':identity['schema'],'folder':str(folder),'complete':complete,'published':False,'sampleOnly':not complete,
                    'rows':total,'rowsAdded':total-initial,'sourceCursors':counts,'repairs':len(repairs),'rejected':0,
                    'seconds':time.monotonic()-started,'bytes':stage.stat().st_size,'sourceCount':len(selected)}
        except Exception:
            db.rollback();raise
        finally:db.close()
        road.assert_sources(selected)
        if complete:
            stage.rename(final);result.update(file=str(final),sha256=road.common.sha(final))
            road.atomic_json(folder/'receipt.json',result)
        else:result['file']=str(stage)
        road.atomic_json(folder/'inputs.json',identity);road.atomic_json(folder/'progress.json',result)
        return result


def query_png(path,z,x,y):
    if not 13<=z<=17 or not 0<=x<2**z or not 0<=y<2**z:raise ValueError('Expected detail tile13..17')
    bounds=road.common.tile_bounds(z,x,y);w,s,e,n=bounds;mask=np.zeros((256,256),dtype=np.uint8);count=0
    db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
    try:
        db.execute('PRAGMA cache_size=-8192');cursor=db.execute('SELECT r.wkb FROM bounds b JOIN roads r ON r.id=b.id WHERE b.minx<=? AND b.maxx>=? AND b.miny<=? AND b.maxy>=?',(e,w,n,s))
        while rows:=cursor.fetchmany(256):
            geometries=[shapely.from_wkb(zlib.decompress(r[0])) for r in rows];count+=len(rows)
            rasterize([(g,255) for g in geometries],out=mask,transform=from_bounds(*bounds,256,256))
    finally:db.close()
    rgba=np.zeros((256,256,4),dtype=np.uint8);rgba[mask!=0]=[206,205,199,255]
    stream=io.BytesIO();Image.fromarray(rgba).save(stream,format='PNG',compress_level=6)
    return stream.getvalue(),count


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source-plan',required=True);p.add_argument('--source-receipt',required=True)
    p.add_argument('--output',default=str(Path(os.environ.get('DATA_ROOT','.'))/'world-ground/road-index'))
    p.add_argument('--source-id');p.add_argument('--max-rows',type=int,default=0);a=p.parse_args()
    if a.max_rows<0:p.error('max-rows must be nonnegative')
    items,expected=load_inputs(a.source_plan,a.source_receipt)
    print(json.dumps(build(items,expected,a.output,source_id=a.source_id,max_rows=a.max_rows)),flush=True)
