"""Build an unpublished terrain candidate, retaining unaffected compressed tile bytes."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import json
import math
from pathlib import Path
import shutil
import sqlite3
import threading
import time
import xml.etree.ElementTree as ET

import numpy as np
import rasterio
from rasterio.warp import transform_bounds
from rasterio.windows import Window
from pmtiles.tile import Compression, TileType, tileid_to_zxy, zxy_to_tileid
from pmtiles.writer import write
from terrain_archive import encode_grid, grid_view


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def atomic_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
    temporary.replace(path)


def canonical_vrt(path):
    path = Path(path)
    tree = ET.parse(path)
    for source in tree.findall('.//SourceFilename'):
        p = Path(source.text)
        if source.get('relativeToVRT') == '1':
            p = path.parent / p
        source.text = str(p.resolve())
        source.set('relativeToVRT', '0')
    return ET.tostring(tree.getroot())


def source_stamps(path, recursive=False):
    with rasterio.open(path) as source:
        files = [Path(f) for f in source.files]
    if recursive:
        found = {p.resolve() for p in files}
        pending = list(found)
        while pending:
            p = pending.pop()
            if p.suffix.lower() != '.vrt':
                continue
            with rasterio.open(p) as source:
                for name in source.files:
                    child = Path(name).resolve()
                    if child not in found:
                        found.add(child)
                        pending.append(child)
        files = sorted(found, key=str)
    return [(str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in files]


def signature(stamps):
    return hashlib.sha256(json.dumps(stamps).encode()).hexdigest()


def sampler_signature():
    return hashlib.sha256(Path(__file__).with_name('terrain_archive.py').read_bytes()
                          + rasterio.__version__.encode() + rasterio.__gdal_version__.encode()
                          + b'height-range:-500:9000;explicit-nodata-v1').hexdigest()


def affected_keys(keys, bounds):
    if not keys:
        return []
    arr = np.asarray(keys, dtype=np.int64)
    hit = np.zeros(len(arr), dtype=bool)
    for level in np.unique(arr[:, 0]):
        indices = np.flatnonzero(arr[:, 0] == level)
        width = 180 / 2.0**int(level)
        # Four destination sample spacings cover the bilinear downsample kernel
        # plus approximate-warp error. Source bounds have a separate 50 m pad.
        padding = 4 * width / 32
        west = -180 + arr[indices, 1] * width
        north = 90 - arr[indices, 2] * width
        local = np.zeros(len(indices), dtype=bool)
        for w, s, e, n in bounds:
            local |= ((west <= e + padding) & (west + width >= w - padding)
                      & (north >= s - padding) & (north - width <= n + padding))
        hit[indices] = local
    return [tuple(map(int, row)) for row in arr[hit]]


def replace_existing_tiles(db, rows):
    for tileid, data in rows:
        result = db.execute('UPDATE tiles SET data=? WHERE id=?', (data, tileid))
        if result.rowcount != 1:
            raise ValueError('Unexpected tile key: ' + str(tileid))


def open_checkpoint(path):
    # URI parsing must be enabled on the main connection for mode=ro on ATTACH
    # to take effect, including Windows file:/// drive paths.
    return sqlite3.connect(path, uri=True)


def extension_sources(previous, current):
    old_paths=[str(Path(item['path']).resolve()) for item in previous]
    new_paths=[str(Path(item['path']).resolve()) for item in current]
    if len(set(old_paths))!=len(old_paths) or len(set(new_paths))!=len(new_paths):
        raise ValueError('Duplicate precision paths cannot establish extension order')
    old_map=dict(zip(old_paths,previous))
    preserved=[path for path in new_paths if path in old_map]
    if preserved!=old_paths:
        raise ValueError('Previous precision sources were removed or reordered; rebuild from original base')
    for path,item in zip(new_paths,current):
        if path in old_map and item!=old_map[path]:
            raise ValueError('Previous precision definition changed; rebuild from original base')
    return [item for path,item in zip(new_paths,current) if path not in old_map]


def replacement_sources(previous,current):
    old={item['path']:item for item in previous};new={item['path']:item for item in current}
    if len(old)!=len(previous) or len(new)!=len(current):raise ValueError('Duplicate precision paths')
    retained=set(old)&set(new)
    changes=dict(removed=[p for p in old if p not in new],added=[p for p in new if p not in old],
                 changed=[p for p in old if p in new and old[p]!=new[p]],
                 retainedOrderChanged=[p for p in old if p in retained]!=[p for p in new if p in retained],
                 invalidation='union of all previous and current precision raster bounds')
    # Full union also covers overlap-priority changes between retained rasters.
    sources=list(old.values())+[item for path,item in new.items() if path not in old]
    return sources,changes


def verify_reuse_stream(before,after,affected,added,on_progress=None):
    report=dict(unchangedTileByteDifferences=0,addedKeys=0,removedKeys=0,unexpectedAddedKeys=0,missingRequestedKeys=0)
    old,new=next(before,None),next(after,None);seen=set();checked=0
    while old is not None or new is not None:
        if old is not None and (new is None or old[0]<new[0]):
            report['removedKeys']+=1;old=next(before,None)
        elif new is not None and (old is None or new[0]<old[0]):
            report['addedKeys']+=1
            if new[0] not in added:report['unexpectedAddedKeys']+=1
            seen.add(new[0]);new=next(after,None)
        else:
            if old[0] not in affected and old[1]!=new[1]:report['unchangedTileByteDifferences']+=1
            old,new=next(before,None),next(after,None)
        checked+=1
        if on_progress is not None and checked%50000==0:on_progress(checked)
    report['missingRequestedKeys']=len(added-seen)
    if any(report[k] for k in report if k!='addedKeys'):
        raise ValueError('Unchanged tile bytes/keyset verification failed: '+json.dumps(report))
    return report


def detail_keys(records, maximum=20):
    keys=set()
    for item in records:
        lon,lat=item['point'] if isinstance(item,dict) else item
        if not (124<=lon<=133 and 33<=lat<=39):
            raise ValueError('New detail point is outside the verified Korean domain')
        for level in range(16,maximum+1):
            width=180/2**level
            x,y=math.floor((lon+180)/width),math.floor((90-lat)/width)
            keys.update((level,x+dx,y+dy) for dx in (-1,0,1) for dy in (-1,0,1))
    return keys


def verify_layered_structure(manifest, old=None):
    base, layered = Path(manifest['base']), Path(manifest['layered'])
    if old is not None and canonical_vrt(base) != canonical_vrt(old):
        raise ValueError('Frozen base is not equivalent to the old archive source')
    root = ET.parse(layered).getroot()
    nodes = root.findall('./VRTRasterBand/ComplexSource')
    expected = [base.resolve()] + [Path(item['path']).resolve() for item in manifest['sources']]
    actual = []
    for node in nodes:
        source = node.find('SourceFilename')
        path = Path(source.text)
        actual.append((layered.parent/path if source.get('relativeToVRT') == '1' else path).resolve())
        if node.findtext('NODATA') != '-9999.0' and node.findtext('NODATA') != '-9999':
            raise ValueError('Every layer must preserve explicit NoData')
    if actual != expected:
        raise ValueError('Layered VRT source order differs from the manifest')
    with rasterio.open(old or base) as a, rasterio.open(base) as b, rasterio.open(layered) as c:
        if any((d.crs, d.transform, d.width, d.height) != (a.crs, a.transform, a.width, a.height) for d in (b,c)):
            raise ValueError('Grid changed; safe incremental reuse is unavailable')
    return layered


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--old-dem', type=Path, required=True)
    parser.add_argument('--old-db', type=Path, required=True)
    parser.add_argument('--old-receipt', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--previous-manifest', type=Path)
    parser.add_argument('--new-detail-points', type=Path)
    parser.add_argument('--old-detail-points', type=Path)
    parser.add_argument('--replace-precision-layers',action='store_true',
                        help='Explicitly invalidate the union of old/new precision extents; original base must remain equivalent')
    args = parser.parse_args()
    if args.replace_precision_layers and not args.previous_manifest:parser.error('--replace-precision-layers requires --previous-manifest')
    args.work.mkdir(parents=True, exist_ok=True)
    args.output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    def progress(state, **extra):
        atomic_json(args.work/'progress.json', dict(state=state, elapsedSeconds=round(time.monotonic()-started,2), **extra))
    progress('verifying')
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    receipt = json.loads(args.old_receipt.read_text(encoding='utf-8'))
    meta = receipt['metadata']
    if not meta.get('explicitNoData') or sha(args.old_dem) != meta['vrt_sha256']:
        raise ValueError('Old archive provenance/NoData contract is not verified')
    old_stamps = source_stamps(args.old_dem)
    if signature(old_stamps) != meta['sourceFilesSHA256']:
        raise ValueError('Old archive source files have changed')
    if meta.get('recursiveSourceFilesSHA256') and signature(source_stamps(args.old_dem,recursive=True))!=meta['recursiveSourceFilesSHA256']:
        raise ValueError('Nested old archive sources have changed')
    native_policy=meta.get('nativeBoundaryPolicy')
    if native_policy:
        from native_terrain_boundary import provenance,native_tiles
        current_policy=provenance()
        if any(native_policy.get(k)!=v for k,v in current_policy.items()):
            raise ValueError('Native boundary sampling implementation changed')
        expected_sampler=current_policy['samplerSHA256']
    else:expected_sampler=sampler_signature()
    if expected_sampler != meta['samplerSHA256']:
        raise ValueError('Sampling implementation changed')
    added_sources=manifest['sources']
    replacement=None
    if args.previous_manifest:
        previous=json.loads(args.previous_manifest.read_text(encoding='utf-8'))
        verify_layered_structure(previous)
        if canonical_vrt(previous['layered'])!=canonical_vrt(args.old_dem):
            raise ValueError('Previous manifest does not describe old archive source')
        if canonical_vrt(previous['base'])!=canonical_vrt(manifest['base']):
            raise ValueError('Original canonical base changed')
        if args.replace_precision_layers:
            added_sources,replacement=replacement_sources(previous['sources'],manifest['sources'])
        else:
            added_sources=extension_sources(previous['sources'],manifest['sources'])
        layered=verify_layered_structure(manifest)
        # Existing layers must retain their exact source/destination mapping,
        # not merely their relative position and file hashes.
        def source_nodes(path):
            root=ET.fromstring(canonical_vrt(path))
            return {n.findtext('SourceFilename'):ET.tostring(n) for n in root.findall('./VRTRasterBand/ComplexSource')[1:]}
        old_nodes,new_nodes=source_nodes(args.old_dem),source_nodes(layered)
        if any(new_nodes[path]!=old_nodes[path] for path in old_nodes.keys()&new_nodes.keys()):
            raise ValueError('An existing precision layer mapping changed')
        with rasterio.open(args.old_dem) as a,rasterio.open(layered) as b:
            if (a.crs,a.transform,a.width,a.height)!=(b.crs,b.transform,b.width,b.height):
                raise ValueError('Layered grid changed')
    else:
        layered = verify_layered_structure(manifest, args.old_dem)
    digest = sha(layered)
    bounds = []
    changed_paths={str(Path(item['path']).resolve()) for item in added_sources}
    audit_sources=list(manifest['sources'])
    current_paths={str(Path(item['path']).resolve()) for item in audit_sources}
    audit_sources.extend(item for item in added_sources if str(Path(item['path']).resolve()) not in current_paths)
    progress('checking_precision',sources=len(audit_sources),changedSources=len(added_sources))
    for item in audit_sources:
        path = Path(item['path'])
        if sha(path) != item['sha256']:
            raise ValueError('Precision raster checksum mismatch: ' + str(path))
        with rasterio.open(path) as ds:
            if ds.crs.to_epsg() != 5186 or ds.overviews(1):
                raise ValueError('Unverified precision raster CRS/overview behavior')
            w,s,e,n = ds.bounds
            if str(path.resolve()) in changed_paths:
                bounds.append(transform_bounds(ds.crs,4326,w-50,s-50,e+50,n+50,densify_pts=101))
    stamps = source_stamps(layered, recursive=True)
    recursive_signature = signature(stamps)
    source_signature = signature(source_stamps(layered))
    old = sqlite3.connect(args.old_db.resolve().as_uri()+'?mode=ro',uri=True)
    old_meta = dict(old.execute('SELECT key,value FROM metadata'))
    if old_meta.get('sourceSignature') != meta['sourceFilesSHA256'] or old_meta.get('samplerSignature') != meta['samplerSHA256']:
        raise ValueError('Checkpoint metadata differs from archive receipt')
    count = old.execute('SELECT count(*) FROM tiles').fetchone()[0]
    if count != receipt['tiles']:
        raise ValueError('Checkpoint tile count differs from archive receipt')
    progress('indexing_existing_keys',totalTiles=count)
    keys = []
    existing_ids=set()
    for (tileid,) in old.execute('SELECT id FROM tiles ORDER BY id'):
        z,x,y = tileid_to_zxy(tileid)
        keys.append((z-1,x,y))
        existing_ids.add(tileid)
    progress('selecting_affected_keys',totalTiles=count,changedSources=len(added_sources))
    affected = affected_keys(keys,bounds)
    del keys
    new_records=json.loads(args.new_detail_points.read_text(encoding='utf-8')) if args.new_detail_points else []
    new_keys=sorted(key for key in detail_keys(new_records,meta['maxLevel']) if zxy_to_tileid(key[0]+1,key[1],key[2]) not in existing_ids)
    del existing_ids
    affected.extend(new_keys)
    old_count=count
    count+=len(new_keys)
    if args.old_detail_points:
        combined=json.loads(args.old_detail_points.read_text(encoding='utf-8'))+new_records
        atomic_json(args.work/'detail-points.json',combined)
    groups = {}
    for level,x,y in affected:
        groups.setdefault((level,x//16,y//16),[]).append((x,y))
    jobs = sorted(groups.items(), reverse=True)
    progress('seeding', totalTiles=count, affectedTiles=len(affected), jobs=len(jobs))
    state = dict(vrt_sha256=digest, sourceFilesSHA256=source_signature,
                 samplerSHA256=expected_sampler, oldVrtSHA256=meta['vrt_sha256'],
                 oldSourceFilesSHA256=meta['sourceFilesSHA256'], manifestSHA256=sha(args.manifest),
                 builderSHA256=sha(Path(__file__)), totalTiles=count, affectedTiles=len(affected),
                 reuseTiles=count-len(affected), addedTiles=len(new_keys), recursiveSourceFilesSHA256=recursive_signature,
                 sourceSignatureScheme='rasterio files path/size/mtime_ns')
    if args.previous_manifest:state['previousManifestSHA256']=sha(args.previous_manifest)
    if args.new_detail_points:state['newDetailPointsSHA256']=sha(args.new_detail_points)
    if replacement is not None:state['precisionReplacement']=replacement
    if native_policy:
        state['nativeBoundaryResampling']='Every affected or added L20 tile is reclassified; every boundary vertex is scalar-validated. The inherited nativeBoundaryPolicy counts describe its original full-archive audit.'
    statepath = args.work/'incremental-state.json'
    database = args.work/('terrain-'+digest[:16]+'.sqlite')
    if statepath.exists():
        if json.loads(statepath.read_text()) != state:
            raise ValueError('Incremental inputs changed; use a fresh work directory')
        if not database.exists():
            raise ValueError('Incremental state exists without its checkpoint')
        db = open_checkpoint(database)
    else:
        if database.exists():
            raise ValueError('Unverified seed database already exists')
        db = open_checkpoint(database)
        old.backup(db)
        for table in ('incremental_done','incremental_affected','incremental_added'):
            db.execute('DROP TABLE IF EXISTS '+table)
        db.execute('CREATE TABLE incremental_done(id TEXT PRIMARY KEY)')
        db.execute('CREATE TABLE incremental_affected(id INTEGER PRIMARY KEY)')
        db.execute('CREATE TABLE incremental_added(id INTEGER PRIMARY KEY)')
        new_ids=[zxy_to_tileid(l+1,x,y) for l,x,y in new_keys]
        db.executemany('INSERT INTO incremental_added VALUES(?)',((i,) for i in new_ids))
        empty=gzip.compress(encode_grid(np.full((33,33),np.nan,dtype='float32')),compresslevel=1,mtime=0)
        db.executemany('INSERT INTO tiles VALUES(?,?)',((i,empty) for i in new_ids))
        db.executemany('INSERT INTO incremental_affected VALUES(?)', ((zxy_to_tileid(l+1,x,y),) for l,x,y in affected))
        db.commit()
        atomic_json(statepath,state)
    done = {r[0] for r in db.execute('SELECT id FROM incremental_done')}
    local = threading.local()
    def worker(job):
        (level,gx,gy), xy = job
        identity = f'{level}/{gx}/{gy}'
        if not hasattr(local,'source'):
            local.source = rasterio.open(layered)
            local.views = {}
        if level not in local.views:
            local.views[level] = grid_view(local.source,level)
        x0,y0 = min(x for x,y in xy), min(y for x,y in xy)
        x1,y1 = max(x for x,y in xy), max(y for x,y in xy)
        grid = local.views[level].read(1,window=Window(x0*32,y0*32,(x1-x0+1)*32+1,(y1-y0+1)*32+1))
        rows=[]
        native_grids={}
        if native_policy and level==20:
            native_grids={(x,y):g for _,x,y,b,g in native_tiles(local.source,[(level,x,y) for x,y in xy]) if b}
        for x,y in xy:
            tile=grid[(y-y0)*32:(y-y0)*32+33,(x-x0)*32:(x-x0)*32+33]
            if (x,y) in native_grids:tile=native_grids[(x,y)]
            tile=np.where((tile>=-500)&(tile<=9000),tile,np.nan).astype('float32')
            rows.append((zxy_to_tileid(level+1,x,y),gzip.compress(encode_grid(tile),compresslevel=1,mtime=0)))
        return identity, rows
    pending=[j for j in jobs if '/'.join(map(str,j[0])) not in done]
    completed=len(done)
    progress('baking',jobsTotal=len(jobs),jobsCompleted=completed,affectedTiles=len(affected),addedTiles=len(new_keys),reusedTiles=count-len(affected))
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for identity,rows in pool.map(worker,pending):
            replace_existing_tiles(db,rows)
            db.execute('INSERT INTO incremental_done VALUES(?)',(identity,))
            db.commit()
            completed+=1
            progress('baking',jobsTotal=len(jobs),jobsCompleted=completed,affectedTiles=len(affected),reusedTiles=count-len(affected))
    progress('verifying_sources',jobsCompleted=completed,totalTiles=count)
    if source_stamps(layered,recursive=True)!=stamps or source_stamps(args.old_dem)!=old_stamps:
        raise ValueError('Source files changed during baking')
    progress('verifying_reused_bytes',totalTiles=count,reusedTiles=count-len(affected))
    affected_ids={r[0] for r in db.execute('SELECT id FROM incremental_affected')}
    added_ids={r[0] for r in db.execute('SELECT id FROM incremental_added')}
    proof=verify_reuse_stream(iter(old.execute('SELECT id,data FROM tiles ORDER BY id')),
                             iter(db.execute('SELECT id,data FROM tiles ORDER BY id')),affected_ids,added_ids,
                             lambda checked:progress('verifying_reused_bytes',totalTiles=count,checkedTiles=checked,reusedTiles=count-len(affected)))
    db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',('sourceSignature',source_signature))
    db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',('recursiveSourceSignature',recursive_signature))
    db.commit()
    progress('packing',totalTiles=count,affectedTiles=len(affected),reusedTiles=count-len(affected))
    metadata={**meta,'tiles':count,'vrt_sha256':digest,'sourceFilesSHA256':source_signature,
              'recursiveSourceFilesSHA256':recursive_signature,
              'sourceSignatureScheme':state['sourceSignatureScheme'],'samplerSHA256':expected_sampler,
              'incremental':state,'explicitNoData':True}
    archive=args.work/'terrain.packing.pmtiles'
    w,s,e,n=meta['bounds']
    with write(str(archive)) as writer:
        for tileid,data in db.execute('SELECT id,data FROM tiles ORDER BY id'):
            writer.write_tile(tileid,data)
        writer.finalize(dict(tile_type=TileType.UNKNOWN,tile_compression=Compression.GZIP,
                             min_lon_e7=round(w*1e7),min_lat_e7=round(s*1e7),max_lon_e7=round(e*1e7),max_lat_e7=round(n*1e7)),metadata)
    checksum=sha(archive)
    target=args.output/('terrain-'+checksum[:20]+'.pmtiles')
    if target.exists():
        if sha(target)!=checksum:raise ValueError('Archive name collision')
    else:
        temporary=target.with_suffix('.copying')
        shutil.copyfile(archive,temporary)
        if sha(temporary)!=checksum:raise ValueError('Candidate copy checksum mismatch')
        temporary.replace(target)
    config=dict(url='/api/map-data/world-terrain/'+target.name,vrt_sha256=digest,sha256=checksum,bytes=target.stat().st_size,tiles=count)
    atomic_json(args.work/'archive-receipt.json',{**config,'metadata':metadata,'published':False,
                'verification':dict(proof,oldTiles=old_count)})
    progress('complete',archive=str(target),**config)


if __name__=='__main__':
    main()
