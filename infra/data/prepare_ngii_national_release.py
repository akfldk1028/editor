"""Prepare an inactive B021-only v2 release. Never activates or edits live catalogs.

Runtime v2 wiring is intentionally separate and is not established by preparation.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
import hashlib
import gzip
import json
import zlib
import math
from pathlib import Path
import re
import sqlite3

from ingest_ngii_buildings import completed_source_gate
from ngii_canonical_snapshot import open_snapshot
from release_store import read_json, encoded, digest, atomic_json, seal, HASH_WORKERS

MESH = 'footprint-holes-obb-v3'
PACKING = 'gzip6-mesh-and-metadata-v1'
CONTRACT = 'resolved-ancestor-grid-v1'
HLOD = 'ngii-global-generalized-quadtree-v2'
PROVINCES = {'11','26','27','28','29','30','31','36','41','43','44','46','47','48','50','51','52'}
# Presence checks for known inhabited edge areas. Province labels and an exact
# received inventory cannot detect these omissions in the source itself.
# Passing these probes alone does not establish exhaustive geographic coverage.
GEOGRAPHIC_PROBES = {
    'Baengnyeong': (124.65, 37.95), 'Daecheong': (124.70, 37.83),
    'Yeonpyeong': (125.70, 37.66), 'Ulleung': (130.90, 37.48),
    'Dokdo': (131.87, 37.24), 'Marado': (126.267, 33.117),
    'Jeju': (126.53, 33.50), 'Goseong': (128.36, 38.51),
}
# Edge probes with 0 B021 buildings in the received NGII source inventory. An empty
# result here is recorded as a source coverage gap; any other empty probe still fails.
# Baengnyeong/Daecheong/Yeonpyeong are West Sea border islands; Goseong is the mainland
# northern border (civilian control zone) - 0 source buildings within +/-3 Z14 tiles.
KNOWN_SOURCE_GAPS = {'Baengnyeong', 'Daecheong', 'Yeonpyeong', 'Goseong'}
NATIVE_RECORD_THRESHOLD = .5
# Coarse sanity cap on the MEDIAN region maximum: above this the served terrain is wrong as a
# whole (datum/geoid offset). One outlier anchor (quarry, cliff, reclaimed land) does not trip it.
NATIVE_SANITY_MAX_METRES = 20.0


def native_median(heights):
    values=sorted(r['nativeMaximumMetres'] for r in heights.get('regions') or []
                  if isinstance(r,dict) and isinstance(r.get('nativeMaximumMetres'),(int,float))
                  and not isinstance(r.get('nativeMaximumMetres'),bool) and math.isfinite(r['nativeMaximumMetres']))
    if not values:return None
    middle=len(values)//2
    return values[middle] if len(values)%2 else (values[middle-1]+values[middle])/2


def geographic_presence(actual):
    points=[]
    missing=[]
    for name,(lon,lat) in GEOGRAPHIC_PROBES.items():
        x=int((lon+180)/360*16384)
        y=int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*16384)
        regions={f'14/{xx}/{yy}':actual.get(f'14/{xx}/{yy}',0)
                 for xx in range(x-1,x+2) for yy in range(y-1,y+2)}
        buildings=sum(regions.values())
        if buildings<=0:missing.append(name)
        points.append({'name':name,'point':[lon,lat],'buildings':buildings,
                       'occupiedRegions':{k:v for k,v in regions.items() if v>0}})
    unexpected=[name for name in missing if name not in KNOWN_SOURCE_GAPS]
    if unexpected:raise ValueError('Missing geographic source coverage: '+', '.join(unexpected))
    return {'schema':'ngii-geographic-presence-v1','points':points,
            'sourceCoverageGaps':sorted(missing),
            'scope':'Known inhabited edge-neighborhood presence, not exhaustive land coverage'}


def sha(value):
    if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{64}',value):
        raise ValueError('Invalid SHA256')
    return value


def inside(root, path):
    path=Path(path).resolve()
    if not path.is_relative_to(root):raise ValueError('Candidate path escapes DATA_ROOT')
    return path


def public_url(root, path, namespace='world-buildings'):
    relative=inside(root,path).relative_to(root)
    if namespace not in ('world-buildings','world-terrain') or relative.parts[0]!=namespace:
        raise ValueError('Artifact outside public namespace')
    return '/api/map-data/'+relative.as_posix()


_hash_pool=None


def hash_pool():
    global _hash_pool
    if _hash_pool is None:_hash_pool=ThreadPoolExecutor(max_workers=HASH_WORKERS)
    return _hash_pool


def check_payload(path, item):
    """Hash one payload file (and its gzip-decoded bytes) with a stable stat around the read."""
    before=path.stat()
    gz=path.name.endswith('.b3dm.gz') or path.name in ('footprints.json.gz','ground-source.json.gz')
    if before.st_size!=item['bytes']:raise ValueError('Candidate payload hash mismatch')
    data=path.read_bytes() if gz else None
    if (hashlib.sha256(data).hexdigest() if gz else digest(path))!=sha(item['sha256']):
        raise ValueError('Candidate payload hash mismatch')
    if gz:
        try:decoded=gzip.decompress(data)
        except (OSError,EOFError,zlib.error) as exc:raise ValueError('Invalid gzip mesh') from exc
        if item.get('contentEncoding')!='gzip' or len(decoded)!=item.get('decodedBytes') \
           or hashlib.sha256(decoded).hexdigest()!=sha(item.get('decodedSHA256')):
            raise ValueError('Decoded mesh hash mismatch')
    after=path.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('Candidate payload changed during verification')
    return (after.st_size,after.st_mtime_ns,item['sha256'])


def stamped_digest(path, known):
    before=path.stat();value=digest(path);after=path.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('File changed during verification')
    known[path]=(after.st_size,after.st_mtime_ns,value)
    return value


def payload_files(root, folder, receipt, known=None):
    """Validate receipt paths in order, then hash payloads in parallel. known collects
    {path: (bytes, mtimeNs, sha256)} so seal() need not re-read the same bytes."""
    files={};jobs=[]
    for item in receipt['files']:
        name=item['path']
        if Path(name).is_absolute() or '..' in Path(name).parts or name in files:
            raise ValueError('Invalid or duplicate receipt path')
        path=inside(root,folder/name)
        if not path.is_relative_to(folder):raise ValueError('Candidate payload hash mismatch')
        if receipt.get('assetPacking')==PACKING and (name.endswith('.b3dm') or name in ('footprints.json','ground-source.json')):
            raise ValueError('Unencoded mesh in gzip packing')
        files[name]=path;jobs.append((path,item))
    if 'tileset.json' not in files:raise ValueError('Missing root tileset')
    for (path,_),stamp in zip(jobs,hash_pool().map(lambda job:check_payload(*job),jobs)):
        if known is not None:known[path]=stamp
    return files


def verify_links(files, external=()):
    """Every reachable content reference must resolve to a verified local payload."""
    allowed=set(files.values());pending=[files['tileset.json']];seen=set()
    while pending:
        path=pending.pop()
        if path in seen:continue
        seen.add(path);document=read_json(path)
        if 'root' not in document:raise ValueError('Missing tileset root')
        nodes=[document['root']]
        while nodes:
            node=nodes.pop();nodes.extend(node.get('children',[]))
            content=node.get('content')
            if not content:continue
            uri=content.get('uri')
            if not isinstance(uri,str):raise ValueError('Invalid tileset content reference')
            if uri in external:continue
            if ':' in uri or '?' in uri or '#' in uri or uri.startswith(('/', '\\')):
                raise ValueError('Unverified external tileset content')
            target=(path.parent/uri).resolve()
            if target not in allowed:raise ValueError('Missing verified tileset content')
            if target.suffix=='.json':pending.append(target)


@contextmanager
def source_connection(path, snapshot=False):
    if snapshot:
        document=read_json(path)
        if document.get('complete') is not True:raise ValueError('Canonical snapshot incomplete')
        with open_snapshot(document) as db:yield db
    else:
        with closing(sqlite3.connect(f'file:{Path(path).as_posix()}?mode=ro',uri=True)) as db:
            db.execute('BEGIN')
            yield db


def prepare(root, database, plan_path, regions_path, hlod_input_path, hlod_folder, terrain_pointer, terrain_work, *, snapshot=False):
    root=Path(root).resolve()
    database,plan_path,regions_path,hlod_input_path,hlod_folder,terrain_pointer,terrain_work=[inside(root,p) for p in
        (database,plan_path,regions_path,hlod_input_path,hlod_folder,terrain_pointer,terrain_work)]
    plan=read_json(plan_path);inventory=read_json(regions_path);inputs=read_json(hlod_input_path)
    if plan.get('schema')!='ngii-canonical-plan-v1' or plan.get('storageSchema')!='canonical-sqlite-v2':
        raise ValueError('Unsupported canonical source schema')
    if any(s['manifest'].get('productCode')!='B021' or s['manifest'].get('family')!='NGII-B021'
           or s['manifest'].get('productKind')!='continuous-topographic' for s in plan['sources']):
        raise ValueError('Mixed source family')
    with source_connection(database,snapshot) as db:
        completed_source_gate(db,plan)
        actual=dict(db.execute('SELECT region14,count(*) FROM buildings GROUP BY region14'))
        prefixes={str(r[0]) for r in db.execute('SELECT DISTINCT substr(bjcd,1,2) FROM observations')}
        missing_province={'','-'}
        normalized={{'42':'51','45':'52'}.get(p,p) for p in prefixes-missing_province}
        if normalized!=PROVINCES:raise ValueError('Missing or invalid nationwide province evidence')
        unclassified=db.execute("SELECT count(*) FROM buildings WHERE bjcd IN ('','-')").fetchone()[0]
    rows=inventory.get('regions',[]);expected={r['region14']:r for r in rows}
    if inventory.get('schema')!='ngii-canonical-regions-v1' or inventory.get('sourceComplete') is not True \
       or inventory.get('planSHA256')!=plan['planSHA256'] or inventory.get('sourceRows')!=plan['expectedRows'] \
       or len(expected)!=len(rows) or not rows or inventory.get('regionCount')!=len(rows) \
       or actual!={k:r['buildings'] for k,r in expected.items()} \
       or inventory.get('buildingCount')!=sum(actual.values()) \
       or any(not isinstance(r['components'],int) or r['components']<r['buildings'] for r in rows):
        raise ValueError('Incomplete canonical region inventory')
    geography=geographic_presence(actual)
    geography['sourcePlanSHA256']=plan['planSHA256']
    geography_sha=hashlib.sha256(encoded(geography)).hexdigest()
    terrain=read_json(terrain_pointer);terrain_sha=sha(terrain['sha256']);sha(terrain['vrt_sha256'])
    if terrain.get('heightContract')!=CONTRACT:raise ValueError('Terrain height contract mismatch')
    if not terrain['url'].startswith('/api/map-data/'):raise ValueError('Invalid terrain URL')
    archive=inside(root,root/terrain['url'].removeprefix('/api/map-data/'))
    known={}
    if stamped_digest(archive,known)!=terrain_sha:raise ValueError('Terrain archive hash mismatch')
    plan_file_sha=digest(plan_path)
    if inputs.get('sourcePlanSHA256')!=plan['planSHA256'] or inputs.get('terrainSHA256')!=terrain_sha:
        raise ValueError('HLOD input source/terrain mismatch')
    regional=inputs['regions']
    if len(regional)!=len(expected) or {r['owner'] for r in regional}!=set(expected):
        raise ValueError('National region set mismatch')
    files=[plan_path,regions_path,hlod_input_path,terrain_pointer,archive]
    pins=[];supported=unresolved=components=0
    for row in sorted(regional,key=lambda r:r['owner']):
        folder=inside(root,row['folder']);receipt_path=folder/'candidate-receipt.json';receipt=read_json(receipt_path)
        target=expected[row['owner']]
        if receipt.get('schema')!='ngii-region-candidate-v1' or receipt.get('completeRegion') is not True \
           or receipt.get('owner')!=row['owner'] or receipt.get('buildings')!=target['buildings'] \
           or receipt.get('components')!=target['components'] or receipt.get('sourcePlanSHA256')!=plan['planSHA256'] \
           or receipt.get('sourcePlanFileSHA256')!=plan_file_sha or receipt.get('terrainSHA256')!=terrain_sha \
           or receipt.get('meshRevision')!=MESH or receipt.get('terrainContract')!=CONTRACT or receipt.get('assetPacking')!=PACKING:
            raise ValueError('Regional coverage/identity mismatch')
        if row['uri']!=public_url(root,folder/'tileset.json'):raise ValueError('Regional URL mismatch')
        verified=payload_files(root,folder,receipt,known)
        verify_links(verified)
        ground=json.loads(gzip.decompress(verified['ground-source.json.gz'].read_bytes()));footprints=json.loads(gzip.decompress(verified['footprints.json.gz'].read_bytes()))
        if ground.get('archiveSha256')!=terrain_sha or ground.get('contract')!=CONTRACT \
           or len(ground['buildings'])!=target['buildings'] or len(footprints)!=target['components']:
            raise ValueError('Ground/component evidence mismatch')
        identities=set();region_supported=0
        for building in ground['buildings']:
            g=building['ground'];key=building['id']
            if key in identities or not re.fullmatch('ngii:[a-f0-9]{64}',key) \
               or g.get('archiveSha256')!=terrain_sha or g.get('contract')!=CONTRACT \
               or not math.isfinite(g['height']) or not g.get('sourceLevels') \
               or g.get('ellipsoidZero')!=(-1 in g['sourceLevels']):
                raise ValueError('Invalid ground provenance')
            identities.add(key);region_supported+=int(not g['ellipsoidZero'])
            provenance=building.get('provenance',{});source_row=provenance.get('row')
            if not isinstance(source_row,int) or not any(0<=source_row<s['expectedRows']
                and {k:v for k,v in provenance.items() if k!='row'}==s['manifest'] for s in plan['sources']):
                raise ValueError('Ground record source provenance mismatch')
        by_id={b['id']:b['ground']['height'] for b in ground['buildings']};parts={}
        for footprint in footprints:
            match=re.fullmatch('(ngii:[a-f0-9]{64})/(0|[1-9][0-9]*)',footprint.get('key',''))
            if not match or match[1] not in by_id or footprint.get('z')!=by_id[match[1]]:
                raise ValueError('Footprint ground identity mismatch')
            indices=parts.setdefault(match[1],set());index=int(match[2])
            if index in indices:raise ValueError('Duplicate footprint component')
            indices.add(index)
        if set(parts)!=identities or any(sorted(v)!=list(range(len(v))) for v in parts.values()):
            raise ValueError('Missing footprint component')
        with source_connection(database,snapshot) as source_db:
            if {r[0] for r in source_db.execute('SELECT id FROM buildings WHERE region14=?',(row['owner'],))}!=identities:
                raise ValueError('Canonical building identity coverage mismatch')
        if receipt.get('supportedGroundBuildings')!=region_supported \
           or receipt.get('unresolvedGroundBuildings')!=target['buildings']-region_supported:
            raise ValueError('Unsupported ground counted as recovered')
        supported+=region_supported;unresolved+=target['buildings']-region_supported;components+=target['components']
        pins.append({'owner':row['owner'],'receiptSHA256':stamped_digest(receipt_path,known),'uri':row['uri']})
        files.extend([receipt_path,*verified.values()])
    if digest(plan_path)!=plan_file_sha:raise ValueError('Plan file changed during preparation')
    revision=hashlib.sha256(encoded(pins)).hexdigest()
    hlod_path=hlod_folder/'candidate-receipt.json';hlod=read_json(hlod_path)
    if hlod.get('revision')!=HLOD or hlod.get('mesh')!=MESH or hlod.get('assetPacking')!=PACKING or hlod.get('sourcePlanSHA256')!=plan['planSHA256'] \
       or hlod.get('terrainSHA256')!=terrain_sha or hlod.get('sampleOnly') is not False \
       or hlod.get('completeRegion') is not True or hlod.get('pins')!=pins \
       or hlod.get('regions')!=len(expected) or hlod.get('buildings')!=sum(actual.values()) \
       or hlod.get('components')!=components:
        raise ValueError('Incomplete or inconsistent national HLOD')
    hlod_files=payload_files(root,hlod_folder,hlod,known)
    verify_links(hlod_files,{p['uri'] for p in pins})
    files.extend([hlod_path,*hlod_files.values()])
    receipt_path=terrain_work/'archive-receipt.json';validation_path=terrain_work/'publication-verification.json';height_path=terrain_work/'height-verification.json'
    receipt=read_json(receipt_path);validation=read_json(validation_path);heights=read_json(height_path)
    datum=heights.get('publishedBuildingDatumCheck',{})
    # Native DEM vs served terrain disagreement is recorded evidence, not a publication gate.
    native=heights.get('nativeDisagreement',{})
    native_max=heights.get('absoluteErrorMetres',{}).get('maximum')
    regions_over=native.get('regionsOver');buildings_over=native.get('buildingsOver')
    if receipt.get('sha256')!=terrain_sha or validation.get('sha256')!=terrain_sha or validation.get('httpStatus')!=206 \
       or heights.get('complete') is not True or heights.get('sampleOnly') is not False \
       or heights.get('passed') is not True or heights.get('nativeEvidence')!='recorded' \
       or not isinstance(heights.get('nativeFinite'),int) or isinstance(heights.get('nativeFinite'),bool) or heights['nativeFinite']<=0 \
       or heights.get('terrainArchiveSHA256')!=terrain_sha or heights.get('sourceVrtSHA256')!=terrain['vrt_sha256'] \
       or heights.get('buildingCatalogSHA256')!=revision or not heights.get('sourceFilesSHA256') \
       or heights['sourceFilesSHA256']!=receipt.get('metadata',{}).get('sourceFilesSHA256') \
       or heights.get('missing')!=0 or datum.get('expected')!=components or datum.get('compared')!=components \
       or native.get('gate')!='record-only' or native.get('thresholdMetres')!=NATIVE_RECORD_THRESHOLD        or not isinstance(native_max,(int,float)) or isinstance(native_max,bool) or not math.isfinite(native_max) or native_max<0        or native.get('maxMetres')!=native_max or not isinstance(regions_over,int) or isinstance(regions_over,bool)        or not 0<=regions_over<=len(expected) or native_median(heights) is None or native_median(heights)>NATIVE_SANITY_MAX_METRES \
       or not isinstance(buildings_over,int) or isinstance(buildings_over,bool) or buildings_over<regions_over \
       or not 0<=datum.get('maximumAbsoluteErrorMetres',float('inf'))<=.01:
        raise ValueError('National terrain alignment evidence incomplete')
    files.extend([receipt_path,validation_path,height_path])
    coverage={'schema':'ngii-national-coverage-v1','sourcePlanSHA256':plan['planSHA256'],'catalogRevision':revision,
              'regionCount':len(expected),'buildings':sum(actual.values()),'components':components,
              'provinces':sorted(normalized),'unclassifiedProvinceBuildings':unclassified,'supportedGroundBuildings':supported,'unresolvedGroundBuildings':unresolved,
              'missingRegions':0,'partialRegions':0,'runtimeValidated':False,
              'geographicPresenceSHA256':geography_sha,'sourceCoverageGaps':geography['sourceCoverageGaps']}
    coverage_sha=hashlib.sha256(encoded(coverage)).hexdigest()
    descriptor={'schema':'world-buildings/national-v1','url':public_url(root,hlod_folder/'tileset.json'),
                'sourceSha256':plan['planSHA256'],'terrainVrtSha256':terrain['vrt_sha256'],'catalogRevision':revision,
                'coverageSha256':coverage_sha,'materialRevision':'neutral-opaque-v1','hierarchy':'replace-coarse-ancestors-v1',
                'coverage':{'expectedRegions':len(expected),'completeRegions':len(expected),'missingRegions':0,'partialRegions':0}}
    # The same regions can be sealed with different HLOD builds: evidence is keyed by coverage AND descriptor.
    evidence=root/'management/ngii-national-publications'/coverage_sha/hashlib.sha256(encoded(descriptor)).hexdigest()[:16]
    evidence.mkdir(parents=True,exist_ok=True)
    for name,value in [('coverage.json',coverage),('descriptor.json',descriptor),('geographic-presence.json',geography)]:
        path=evidence/name
        if path.exists() and read_json(path)!=value:raise ValueError('Immutable evidence collision')
        if not path.exists():atomic_json(path,value)
        files.append(path)
    current=root/'releases/current.json'
    payload={'schema':'ace-map-release-v2','sourceFamily':'NGII-B021','terrain':terrain,'nationalBuildings':descriptor,
             'predecessorRelease':read_json(current)['releaseId'] if current.exists() else None,
             'coverage':coverage,'nativeDisagreement':{'maxMetres':native_max,'regionsOver':regions_over,'buildingsOver':buildings_over,
                                     'thresholdMetres':NATIVE_RECORD_THRESHOLD,'gate':'record-only'},
             'runtimeValidationRequired':True}
    return seal(root,payload,files,known=known)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ['data-root','plan','regions','hlod-input','hlod-folder','terrain-pointer','terrain-work']:
        parser.add_argument('--'+name,type=Path,required=True)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--database');source.add_argument('--snapshot')
    args=parser.parse_args()
    result=prepare(args.data_root,args.snapshot or args.database,args.plan,args.regions,args.hlod_input,args.hlod_folder,args.terrain_pointer,args.terrain_work,snapshot=bool(args.snapshot))
    print(result['releaseId'])
