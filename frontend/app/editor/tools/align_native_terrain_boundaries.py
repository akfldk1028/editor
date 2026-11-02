"""Create an unpublished archive with the authoritative native rule at all L20 boundaries."""
import argparse
import gzip
import json
from pathlib import Path
import shutil
import sqlite3
import time
import numpy as np
import rasterio
from pmtiles.tile import Compression,TileType,tileid_to_zxy,zxy_to_tileid
from pmtiles.writer import write
from terrain_archive import encode_grid
from native_terrain_boundary import native_tiles,provenance,base_signature
from incremental_terrain_archive import atomic_json,sha,source_stamps,signature,verify_reuse_stream


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dem',type=Path,required=True)
    p.add_argument('--source-work',type=Path,required=True)
    p.add_argument('--work',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.work.mkdir(parents=True,exist_ok=True);started=time.monotonic()
    def progress(state,**extra):atomic_json(a.work/'progress.json',dict(state=state,elapsedSeconds=round(time.monotonic()-started,2),**extra))
    progress('checking_native_policy_inputs')
    receipt_path=a.source_work/'archive-receipt.json';receipt=json.loads(receipt_path.read_text(encoding='utf8'));meta=receipt['metadata'];policy=provenance()
    if meta['samplerSHA256']!=base_signature():raise ValueError('Expected the verified GDAL sampler baseline')
    if sha(a.dem)!=meta['vrt_sha256']:raise ValueError('VRT changed')
    stamps=source_stamps(a.dem);recursive=source_stamps(a.dem,recursive=True)
    if signature(stamps)!=meta['sourceFilesSHA256'] or signature(recursive)!=meta['recursiveSourceFilesSHA256']:raise ValueError('Raster dependencies changed')
    if sha(a.output/Path(receipt['url']).name)!=receipt['sha256']:raise ValueError('Baseline archive checksum mismatch')
    identity=dict(sourceReceiptSHA256=sha(receipt_path),sourceVrtSHA256=meta['vrt_sha256'],
                  sourceFilesSHA256=meta['sourceFilesSHA256'],recursiveSourceFilesSHA256=meta['recursiveSourceFilesSHA256'],
                  nativePolicy=policy,builderSHA256=sha(Path(__file__)))
    identity_path=a.work/'native-policy-inputs.json'
    if identity_path.exists():
        if json.loads(identity_path.read_text(encoding='utf8'))!=identity:raise ValueError('Native conversion inputs changed')
    else:atomic_json(identity_path,identity)
    oldpath=a.source_work/('terrain-'+meta['vrt_sha256'][:16]+'.sqlite');old=sqlite3.connect(oldpath.resolve().as_uri()+'?mode=ro',uri=True)
    if old.execute('SELECT count(*) FROM tiles').fetchone()[0]!=receipt['tiles']:raise ValueError('Baseline checkpoint count mismatch')
    low,high=zxy_to_tileid(21,0,0),zxy_to_tileid(22,0,0)
    payloads=dict(old.execute('SELECT id,data FROM tiles WHERE id>=? AND id<?',(low,high)))
    patches=sqlite3.connect(a.work/'native-boundary-patches.sqlite')
    patches.execute('CREATE TABLE IF NOT EXISTS classified(id INTEGER PRIMARY KEY,boundary INTEGER NOT NULL,data BLOB,changed INTEGER NOT NULL,finite_vertices INTEGER NOT NULL,finite_to_nodata INTEGER NOT NULL,nodata_to_finite INTEGER NOT NULL)')
    done={r[0] for r in patches.execute('SELECT id FROM classified')}
    keys=[]
    for tileid in payloads.keys()-done:
        z,x,y=tileid_to_zxy(tileid);keys.append((z-1,x,y))
    progress('classifying_L20_native_support',totalL20Tiles=len(payloads),checkedTiles=len(done))
    checked=len(done)
    with rasterio.open(a.dem) as source:
        for level,x,y,boundary,grid in native_tiles(source,keys,validate=True):
            tileid=zxy_to_tileid(level+1,x,y)
            if boundary:
                data=gzip.compress(encode_grid(grid),compresslevel=1,mtime=0)
                before=np.frombuffer(gzip.decompress(payloads[tileid]),dtype='<f4',offset=8).reshape(33,33)
                was=np.isfinite(before);now=np.isfinite(grid)
                row=(tileid,1,data,int(data!=payloads[tileid]),int(now.sum()),int((was&~now).sum()),int((~was&now).sum()))
            else:row=(tileid,0,None,0,0,0,0)
            patches.execute('INSERT INTO classified VALUES(?,?,?,?,?,?,?)',row);checked+=1
            if checked%100==0:
                patches.commit();progress('classifying_L20_native_support',totalL20Tiles=len(payloads),checkedTiles=checked)
    patches.commit()
    counts=patches.execute('SELECT count(*),sum(boundary),sum(changed),sum(finite_vertices),sum(finite_to_nodata),sum(nodata_to_finite) FROM classified').fetchone()
    if counts[0]!=len(payloads):raise ValueError('Incomplete L20 classification')
    del payloads
    if source_stamps(a.dem)!=stamps or source_stamps(a.dem,recursive=True)!=recursive:raise ValueError('Source changed during native sampling')
    audit=dict(totalL20Tiles=counts[0],boundaryTiles=counts[1],interiorTilesKept=counts[0]-counts[1],changedPayloads=counts[2],
               nativeVerticesChecked=counts[1]*1089,finiteNativeVertices=counts[3],finiteToNoDataVertices=counts[4],noDataToFiniteVertices=counts[5],
               validation='Every boundary vertex matched the authoritative scalar rule, including its NoData mask; no source changes')
    atomic_json(a.work/'native-boundary-validation.json',audit)
    database=a.work/oldpath.name;progress('seeding_native_candidate',**audit)
    db=sqlite3.connect(database)
    if not db.execute("SELECT name FROM sqlite_master WHERE name='tiles'").fetchone():old.backup(db)
    affected={r[0] for r in patches.execute('SELECT id FROM classified WHERE boundary=1')}
    for tileid,data in patches.execute('SELECT id,data FROM classified WHERE changed=1'):
        if not low<=tileid<high:raise ValueError('Attempt to modify a non-L20 tile')
        if db.execute('UPDATE tiles SET data=? WHERE id=?',(data,tileid)).rowcount!=1:raise ValueError('Missing existing boundary key')
    db.commit()
    progress('verifying_native_candidate',totalTiles=receipt['tiles'])
    proof=verify_reuse_stream(iter(old.execute('SELECT id,data FROM tiles ORDER BY id')),iter(db.execute('SELECT id,data FROM tiles ORDER BY id')),affected,set(),
                             lambda checked:progress('verifying_native_candidate',totalTiles=receipt['tiles'],checkedTiles=checked))
    db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',('samplerSignature',policy['samplerSHA256']));db.commit()
    metadata={**meta,'samplerSHA256':policy['samplerSHA256'],
              'sampler':'GDAL bilinear display pyramid, with authoritative native 2x2/containing-cell sampling at every L20 NoData-support boundary',
              'nativeBoundaryPolicy':{**policy,**audit,'previousArchiveSHA256':receipt['sha256']}}
    progress('packing_native_candidate',totalTiles=receipt['tiles'])
    packing=a.work/'terrain.packing.pmtiles';w,s,e,n=meta['bounds']
    with write(str(packing)) as writer:
        for tileid,data in db.execute('SELECT id,data FROM tiles ORDER BY id'):writer.write_tile(tileid,data)
        writer.finalize(dict(tile_type=TileType.UNKNOWN,tile_compression=Compression.GZIP,min_lon_e7=round(w*1e7),min_lat_e7=round(s*1e7),max_lon_e7=round(e*1e7),max_lat_e7=round(n*1e7)),metadata)
    checksum=sha(packing);target=a.output/('terrain-'+checksum[:20]+'.pmtiles')
    if not target.exists():
        temporary=target.with_suffix('.copying');shutil.copyfile(packing,temporary)
        if sha(temporary)!=checksum:raise ValueError('Native candidate copy checksum mismatch')
        temporary.replace(target)
    elif sha(target)!=checksum:raise ValueError('Archive name collision')
    config=dict(url='/api/map-data/world-terrain/'+target.name,vrt_sha256=meta['vrt_sha256'],sha256=checksum,bytes=target.stat().st_size,tiles=receipt['tiles'])
    atomic_json(a.work/'archive-receipt.json',{**config,'metadata':metadata,'published':False,'verification':proof})
    shutil.copyfile(a.source_work/'detail-points.json',a.work/'detail-points.json')
    progress('complete',archive=str(target),**config)


if __name__=='__main__':main()
