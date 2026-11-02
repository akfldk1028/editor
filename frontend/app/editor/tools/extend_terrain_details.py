"""Append explicitly requested detail keys to a verified unpublished candidate."""
import argparse
import gzip
import json
from pathlib import Path
import shutil
import sqlite3
import time
import numpy as np
import rasterio
from pmtiles.tile import Compression,TileType,zxy_to_tileid
from pmtiles.writer import write
from terrain_archive import encode_grid,grid_view,read_grid
from incremental_terrain_archive import atomic_json,detail_keys,sha,signature,source_stamps,sampler_signature


def guard_existing_tiles(db):
    def authorize(action,table,column,database,trigger):
        if table=='tiles' and action in (sqlite3.SQLITE_UPDATE,sqlite3.SQLITE_DELETE,sqlite3.SQLITE_DROP_TABLE):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    db.set_authorizer(authorize)


def install_packing(packing,target,checksum,*,atomic_move=False):
    if target.exists():
        if sha(target)!=checksum:raise ValueError('Archive name collision')
        return
    if atomic_move:
        if packing.stat().st_dev!=target.parent.stat().st_dev:
            raise ValueError('Atomic archive install requires the same filesystem')
        packing.rename(target)
    else:
        temporary=target.with_suffix('.copying');shutil.copyfile(packing,temporary)
        if sha(temporary)!=checksum:raise ValueError('Candidate copy checksum mismatch')
        temporary.replace(target)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--work',type=Path,required=True)
    p.add_argument('--dem',type=Path,required=True)
    p.add_argument('--points',type=Path,required=True)
    p.add_argument('--verification-points',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--atomic-install',action='store_true')
    p.add_argument('--reserve-gib',type=float,default=20)
    a=p.parse_args();started=time.monotonic()
    def space_guard():
        if shutil.disk_usage(a.work).free<a.reserve_gib*1024**3:
            raise OSError('Terrain candidate storage reserve reached')
    space_guard()
    def progress(stage,**values):
        atomic_json(a.work/'progress.json',dict(state=stage,elapsedSeconds=round(time.monotonic()-started,2),**values))
    statepath=a.work/'detail-extension.json'
    if statepath.exists():
        state=json.loads(statepath.read_text(encoding='utf8'))
        before=state['beforeReceipt']
        if state['pointsSHA256']!=sha(a.points) or state['builderSHA256']!=sha(Path(__file__)):
            raise ValueError('Detail extension inputs changed')
    else:
        before=json.loads((a.work/'archive-receipt.json').read_text(encoding='utf8'))
        if before.get('published') is not False:
            raise ValueError('Only an explicitly unpublished candidate can be extended')
        status=json.loads((a.work/'progress.json').read_text(encoding='utf8'))
        if status.get('state')!='complete':raise ValueError('Initial candidate must finish verification and packing')
        state=None
    meta=before['metadata'];progress('detail_extension_verifying')
    native_policy=meta.get('nativeBoundaryPolicy')
    if native_policy:
        from native_terrain_boundary import provenance,native_tiles
        current_policy=provenance()
        if any(native_policy.get(k)!=v for k,v in current_policy.items()):
            raise ValueError('Native boundary sampling implementation changed')
        expected_sampler=current_policy['samplerSHA256']
    else:expected_sampler=sampler_signature()
    if sha(a.dem)!=meta['vrt_sha256'] or expected_sampler!=meta['samplerSHA256']:
        raise ValueError('Sampler/source changed')
    direct=source_stamps(a.dem);recursive=source_stamps(a.dem,recursive=True)
    if signature(direct)!=meta['sourceFilesSHA256'] or signature(recursive)!=meta['recursiveSourceFilesSHA256']:
        raise ValueError('Raster dependencies changed')
    archive=a.output/Path(before['url']).name
    if sha(archive)!=before['sha256']:raise ValueError('Prior verified archive checksum mismatch')
    database=a.work/('terrain-'+meta['vrt_sha256'][:16]+'.sqlite')
    db=sqlite3.connect(database)
    guard_existing_tiles(db)
    if state is None:
        if db.execute('SELECT count(*) FROM tiles').fetchone()[0]!=before['tiles']:
            raise ValueError('Checkpoint does not match prior receipt')
        records=json.loads(a.points.read_text(encoding='utf8'))
        keys=[key for key in sorted(detail_keys(records,meta['maxLevel']))
              if not db.execute('SELECT 1 FROM tiles WHERE id=?',(zxy_to_tileid(key[0]+1,key[1],key[2]),)).fetchone()]
        state=dict(beforeReceipt=before,pointsSHA256=sha(a.points),builderSHA256=sha(Path(__file__)),
                   verificationPointsSHA256=sha(a.verification_points),keys=keys,
                   policy='INSERT only; SQLite authorizer rejects UPDATE/DELETE/DROP on tiles')
        atomic_json(statepath,state)
    elif state['verificationPointsSHA256']!=sha(a.verification_points):
        raise ValueError('Verification points changed')
    progress('adding_explicit_detail_keys',addedKeys=len(state['keys']))
    with rasterio.open(a.dem) as source:
        views={}
        try:
            native_grids={}
            if native_policy:
                native_grids={(l,x,y):g for l,x,y,b,g in native_tiles(source,[k for k in state['keys'] if k[0]==20]) if b}
            for index,(level,x,y) in enumerate(state['keys']):
                if index%1000==0:
                    space_guard();progress('adding_explicit_detail_keys',completed=index,addedKeys=len(state['keys']))
                if level not in views:views[level]=grid_view(source,level)
                grid=read_grid(views[level],x,y)
                if (level,x,y) in native_grids:grid=native_grids[(level,x,y)]
                grid=np.where((grid>=-500)&(grid<=9000),grid,np.nan).astype('float32')
                data=gzip.compress(encode_grid(grid),compresslevel=1,mtime=0)
                tileid=zxy_to_tileid(level+1,x,y)
                previous=db.execute('SELECT data FROM tiles WHERE id=?',(tileid,)).fetchone()
                if previous:
                    if previous[0]!=data:raise ValueError('Resumed added tile differs from source')
                else:db.execute('INSERT INTO tiles VALUES(?,?)',(tileid,data))
            db.commit()
        finally:
            for view in views.values():view.close()
    total=before['tiles']+len(state['keys'])
    if db.execute('SELECT count(*) FROM tiles').fetchone()[0]!=total:
        raise ValueError('Unexpected candidate key count')
    if source_stamps(a.dem)!=direct or source_stamps(a.dem,recursive=True)!=recursive:
        raise ValueError('Source changed during sampling')
    extension=dict(previousArchiveSHA256=before['sha256'],previousTiles=before['tiles'],
                   addedTiles=len(state['keys']),pointsSHA256=state['pointsSHA256'],
                   builderSHA256=state['builderSHA256'],preservation=state['policy'])
    if native_policy:extension['nativeBoundaryTilesValidated']=len(native_grids)
    metadata={**meta,'tiles':total,'detailExtension':extension}
    progress('packing_detail_extension',totalTiles=total,addedKeys=len(state['keys']))
    packing=a.work/'terrain.detail-packing.pmtiles';w,s,e,n=meta['bounds']
    with write(str(packing)) as writer:
        for index,(tileid,data) in enumerate(db.execute('SELECT id,data FROM tiles ORDER BY id')):
            if index%10000==0:
                space_guard();progress('packing_detail_extension',packed=index,totalTiles=total)
            writer.write_tile(tileid,data)
        # finalize copies its temporary payload into the final archive.
        if shutil.disk_usage(a.work).free<a.reserve_gib*1024**3+writer.offset+64*1024**2:
            raise OSError('Insufficient reserve for archive finalization')
        writer.finalize(dict(tile_type=TileType.UNKNOWN,tile_compression=Compression.GZIP,
                             min_lon_e7=round(w*1e7),min_lat_e7=round(s*1e7),max_lon_e7=round(e*1e7),max_lat_e7=round(n*1e7)),metadata)
    checksum=sha(packing);target=a.output/('terrain-'+checksum[:20]+'.pmtiles')
    space_guard()
    install_packing(packing,target,checksum,atomic_move=a.atomic_install)
    config=dict(url='/api/map-data/world-terrain/'+target.name,vrt_sha256=meta['vrt_sha256'],sha256=checksum,
                bytes=target.stat().st_size,tiles=total)
    verification=dict(before['verification'],addedKeys=before['verification']['addedKeys']+len(state['keys']),
                      detailExtensionAddedKeys=len(state['keys']),existingTileMutation='denied by SQLite authorizer')
    atomic_json(a.work/'archive-receipt.json',{**config,'metadata':metadata,'published':False,'verification':verification})
    atomic_json(a.work/'detail-points.json',json.loads(a.verification_points.read_text(encoding='utf8')))
    progress('complete',archive=str(target),**config)


if __name__=='__main__':main()
