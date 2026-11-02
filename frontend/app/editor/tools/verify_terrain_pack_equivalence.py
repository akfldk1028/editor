"""Independent pack-equivalence experiment. Does not sample native DEM or activate releases."""
import gzip
import hashlib
import heapq
import itertools
import json
from pathlib import Path
import sqlite3
import time
import argparse
import os
import shutil

from pmtiles.reader import Reader, all_tiles
from pmtiles.tile import Compression, TileType, zxy_to_tileid


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def stable(path):
    s=path.stat()
    return s.st_size,s.st_mtime_ns,s.st_ino


def verify(base, overlay, packed, *, proof_sha, identity_sha, source_pins, allow_sample=False, expected_buildings=None, stop=lambda:False):
    start=time.monotonic();base,overlay,packed=map(lambda x:Path(x).resolve(),(base,overlay,packed))
    if stop():raise InterruptedError('Verification stopped')
    if len({base,overlay,packed})!=3:raise ValueError('Inputs must be distinct')
    if (overlay.parent/'refinement.lock').exists():raise ValueError('Refiner active')
    for suffix in ('-wal','-journal'):
        p=Path(str(overlay)+suffix)
        if p.exists() and p.stat().st_size:raise ValueError('Overlay not immutable')
    before={p:stable(p) for p in (base,overlay,packed)}
    hashes={str(p):file_sha(p) for p in before}
    with sqlite3.connect(overlay.as_uri()+'?mode=ro',uri=True) as db,base.open('rb') as bf,packed.open('rb') as pf:
        db.execute('PRAGMA query_only=ON');db.execute('PRAGMA cache_size=-4096')
        meta=dict(db.execute('SELECT key,value FROM metadata'))
        identity=json.loads(meta['identity']);proof=json.loads(meta['verification'])
        if digest(meta['identity'].encode())!=identity_sha or digest(meta['verification'].encode())!=proof_sha:raise ValueError('Proof/identity SHA mismatch')
        if proof['identitySHA256']!=identity_sha or identity['sourcePins']!=source_pins:raise ValueError('Source identity mismatch')
        if identity['contract']!='resolved-ancestor-grid-v1':raise ValueError('Unsupported contract')
        sample=proof['sampleOnly']
        if type(sample) is not bool or identity['sampleOnly']!=sample or proof['complete'] is not (not sample):raise ValueError('Completion contradiction')
        if sample and not allow_sample:raise ValueError('Sample cannot authorize national proof')
        if proof['passed'] is not True or proof['finalNeighbourCheck'] is not True or proof['independentPackedArchiveVerificationRequired'] is not True:raise ValueError('Final native proof required')
        if not 0<=proof['maximumAbsoluteErrorMetres']<=.5 or proof['nativeFinite']<=0 or proof['nativeNoData']<0:raise ValueError('Native quality gate failed')
        owners=identity['selected']
        if len(set(owners))!=len(owners) or len(owners)!=proof['regions'] or (not sample and len(owners)!=proof['expectedRegions']):raise ValueError('Owner coverage mismatch')
        initial=dict(db.execute('SELECT owner,receipt FROM regions'));final=dict(db.execute('SELECT owner,receipt FROM final_checks'))
        if set(initial)!=set(owners) or set(final)!=set(owners):raise ValueError('Final owner set mismatch')
        if any(json.loads(v)['passed'] is not True for v in initial.values()):raise ValueError('Failed original region')
        checks=[json.loads(v) for v in final.values()]
        if any(not 0<=r['maximum']<=.5 or r['nativeFinite']<0 or r['nativeNoData']<0 for r in checks):raise ValueError('Invalid final check')
        if (sum(r['nativeFinite'] for r in checks),sum(r['nativeNoData'] for r in checks),max(r['maximum'] for r in checks))!=(proof['nativeFinite'],proof['nativeNoData'],proof['maximumAbsoluteErrorMetres']):raise ValueError('Final proof totals mismatch')
        if expected_buildings is not None:
            if set(expected_buildings)!=set(owners):raise ValueError('Canonical owner set mismatch')
            for owner,raw in final.items():
                row=json.loads(raw)
                if type(row['nativeFinite']) is not int or type(row['nativeNoData']) is not int or row['nativeFinite']+row['nativeNoData']!=expected_buildings[owner]:raise ValueError('Canonical native point count mismatch')
                if json.loads(initial[owner]).get('buildings')!=expected_buildings[owner]:raise ValueError('Original region building count mismatch')
        def read(f):
            def get(offset,length):f.seek(offset);return f.read(length)
            return get
        br,pr=read(bf),read(pf);breader,preader=Reader(br),Reader(pr);bm,pm=breader.metadata(),preader.metadata()
        if hashes[str(base)]!=proof['baseArchiveSHA256'] or source_pins['terrainSHA256']!=hashes[str(base)]:raise ValueError('Base SHA mismatch')
        for native_key,archive_key in [('sourceVrtSHA256','vrt_sha256'),('sourceFilesSHA256','sourceFilesSHA256'),('recursiveSourceFilesSHA256','recursiveSourceFilesSHA256')]:
            if proof['sourceFingerprint'][native_key]!=bm[archive_key]:raise ValueError('Native source fingerprint mismatch')
        n,last,overlay_bytes=db.execute('SELECT count(*),coalesce(max(id),0),coalesce(sum(length(data)),0) FROM tiles').fetchone()
        if json.loads(meta['finalGeneration'])!={'n':n,'last':last} or proof['added']!={'tiles':n,'bytes':overlay_bytes}:raise ValueError('Final tile generation changed')
        bh,ph=breader.header(),preader.header()
        for k in ('min_lon_e7','min_lat_e7','max_lon_e7','max_lat_e7'):
            if bh[k]!=ph[k]:raise ValueError('Packed bounds mismatch')
        if ph['tile_type']!=TileType.UNKNOWN or ph['tile_compression']!=Compression.GZIP:raise ValueError('Packed encoding mismatch')
        def added():
            for tileid,level,x,y,data,checksum in db.execute('SELECT id,level,x,y,data,decoded_sha256 FROM tiles ORDER BY id'):
                decoded=gzip.decompress(data)
                if not 16<=level<=20 or tileid!=zxy_to_tileid(level+1,x,y) or digest(decoded)!=checksum or len(decoded)!=4364 or decoded[:8]!=b'HTM1!\x00\x00\x00':raise ValueError('Overlay decoded grid mismatch')
                yield tileid,data
        expected=heapq.merge(((zxy_to_tileid(*k),v) for k,v in all_tiles(br)),added(),key=lambda r:r[0])
        zoom_range=[99,-1]
        def actual_tiles():
            for k,v in all_tiles(pr):
                zoom_range[0]=min(zoom_range[0],k[0]);zoom_range[1]=max(zoom_range[1],k[0])
                yield zxy_to_tileid(*k),v
        actual=actual_tiles();previous=-1;count=0;payload_bytes=0
        for a,b in itertools.zip_longest(expected,actual):
            if count%1024==0 and stop():raise InterruptedError('Verification stopped')
            if a is None or b is None or a!=b:raise ValueError('Packed key/payload mismatch')
            if a[0]<=previous:raise ValueError('Duplicate or unordered tile')
            previous=a[0];count+=1;payload_bytes+=len(a[1])
        expected_meta={**bm,'maxLevel':20,'adaptiveRefinement':{'recipe':identity['recipe'],'baseArchiveSHA256':proof['baseArchiveSHA256'],'identitySHA256':identity_sha,'sampleOnly':sample},'explicitNoData':True,'tiles':count}
        if pm!=expected_meta or ph['addressed_tiles_count']!=count or [ph['min_zoom'],ph['max_zoom']]!=zoom_range:raise ValueError('Packed metadata/count mismatch')
    if stop():raise InterruptedError('Verification stopped')
    if any(stable(p)!=s for p,s in before.items()):raise ValueError('Inputs changed during verification')
    return {'schema':'ngii-packed-exact-equivalence-proof-v1','method':'final-native-proof-transferred-by-exact-payload-equivalence','nativeFresh':False,'sampleOnly':sample,'complete':not sample,'passed':True,'published':False,'archiveSHA256':hashes[str(packed)],'overlaySHA256':hashes[str(overlay)],'baseSHA256':hashes[str(base)],'sourceProofSHA256':proof_sha,'sourceIdentitySHA256':identity_sha,'sourcePins':source_pins,'sourceFingerprint':proof['sourceFingerprint'],'nativeFinite':proof['nativeFinite'],'nativeNoData':proof['nativeNoData'],'maximumAbsoluteErrorMetres':proof['maximumAbsoluteErrorMetres'],'allTileKeysAndEncodedBytesEqual':True,'allOverlayDecodedHashesChecked':True,'metadataEqual':True,'tiles':count,'payloadBytes':payload_bytes,'elapsedSeconds':time.monotonic()-start}


def verify_files(*,base,overlay,packed,inputs,proof,inputs_file_sha,proof_file_sha,regions,snapshot,plan,queue_inputs,output,stop_file=None):
    paths={k:Path(v).resolve() for k,v in locals().copy().items() if k in ('base','overlay','packed','inputs','proof','regions','snapshot','plan','queue_inputs','output')}
    output=paths.pop('output')
    if output in paths.values():raise ValueError('Output must be distinct from inputs')
    output.parent.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(output.parent).free<20*1024**3:raise ValueError('needs_storage:20GiB reserve')
    stopped=lambda:bool(stop_file and Path(stop_file).exists())
    if stopped():raise InterruptedError('Verification stopped')
    stamps={p:stable(p) for p in paths.values()}
    external={k:file_sha(paths[k]) for k in ('inputs','proof','regions','snapshot','plan','queue_inputs')}
    if external['inputs']!=inputs_file_sha or external['proof']!=proof_file_sha:raise ValueError('External proof/inputs file SHA mismatch')
    read=lambda k:json.loads(paths[k].read_text(encoding='utf-8'))
    identity,final,inventory,source_plan,queue=map(read,('inputs','proof','regions','plan','queue_inputs'))
    with sqlite3.connect(paths['overlay'].as_uri()+'?mode=ro',uri=True) as db:
        raw=dict(db.execute('SELECT key,value FROM metadata'))
    if json.loads(raw['identity'])!=identity or json.loads(raw['verification'])!=final:raise ValueError('External and SQLite proof/identity differ')
    pins=identity['sourcePins']
    for key,name in [('snapshotSHA256','snapshot'),('planFileSHA256','plan'),('regionsSHA256','regions')]:
        if pins.get(key)!=external[name] or queue.get(key)!=external[name]:raise ValueError('Canonical source binding mismatch')
    if Path(pins['terrainPath']).resolve()!=paths['base'] or Path(pins['regionsPath']).resolve()!=paths['regions']:raise ValueError('Canonical source path mismatch')
    rows=inventory.get('regions',[])
    if inventory.get('schema')!='ngii-canonical-regions-v1' or inventory.get('sourceComplete') is not True or inventory.get('planSHA256')!=source_plan['planSHA256'] or identity.get('sourcePlanSHA256')!=source_plan['planSHA256'] or inventory.get('sourceRows')!=source_plan['expectedRows'] or inventory.get('regionCount')!=len(rows) or not rows:raise ValueError('Canonical inventory incomplete')
    owners={r['region14']:r['buildings'] for r in rows}
    if len(owners)!=len(rows) or any(type(r['buildings']) is not int or r['buildings']<1 or r['components']<r['buildings'] for r in rows) or sum(owners.values())!=inventory.get('buildingCount'):raise ValueError('Canonical inventory counts invalid')
    result=verify(paths['base'],paths['overlay'],paths['packed'],proof_sha=digest(raw['verification'].encode()),identity_sha=digest(raw['identity'].encode()),source_pins=pins,expected_buildings=owners,stop=stopped)
    if any(stable(p)!=s for p,s in stamps.items()) or any(file_sha(paths[k])!=v for k,v in external.items()):raise ValueError('External evidence changed')
    if stopped():raise InterruptedError('Verification stopped')
    result.update(sourceProofFileSHA256=external['proof'],sourceInputsFileSHA256=external['inputs'],regionsSHA256=external['regions'],queueInputsSHA256=external['queue_inputs'],compared=sum(owners.values()),regions=len(owners))
    if output.exists():
        prior=json.loads(output.read_text())
        if {k:v for k,v in prior.items() if k!='elapsedSeconds'}!={k:v for k,v in result.items() if k!='elapsedSeconds'}:raise ValueError('Existing proof identity changed')
        return prior
    temp=output.with_name(output.name+'.part')
    if temp.exists():raise ValueError('Unreviewed partial proof exists')
    with temp.open('xb') as f:f.write(json.dumps(result,sort_keys=True,separators=(',',':')).encode());f.flush();os.fsync(f.fileno())
    if stopped():temp.unlink();raise InterruptedError('Verification stopped')
    temp.replace(output)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('base','overlay','packed','inputs','proof','inputs-file-sha','proof-file-sha','regions','snapshot','plan','queue-inputs','output'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--stop-file')
    args=vars(parser.parse_args())
    try:print(json.dumps(verify_files(**args)),flush=True)
    except InterruptedError:print(json.dumps({'state':'stopped','passed':False,'complete':False,'nativeFresh':False}),flush=True);raise SystemExit(2)
