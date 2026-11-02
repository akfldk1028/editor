"""Single-writer ground candidate bake, reporting recovery against frozen missing keys."""
import argparse,hashlib,json,math,msvcrt,os,re,shutil,subprocess,time
from pathlib import Path
from paths import DataPaths
from release_store import atomic_json,read_json

def duplicate_region_keys(document):
    seen=set();duplicates=set()
    for row in document['regions']:
        if row.get('z')!=14 or any(type(row.get(axis)) is not int or not 0<=row[axis]<16384 for axis in ('x','y')):
            raise ValueError('Invalid building region coordinates')
        key=f"14/{row['x']}/{row['y']}"
        if key in seen:duplicates.add(key)
        seen.add(key)
    return sorted(duplicates)

def include_duplicate_regions(selected,document):
    return sorted(set(selected)|set(duplicate_region_keys(document)))

def require_unique_regions(document):
    duplicates=duplicate_region_keys(document)
    if duplicates:raise ValueError('Duplicate building region coordinates: '+','.join(duplicates))

def compare_ground(before,after,missing):
    def finite(f):return isinstance(f.get('z'),(int,float)) and math.isfinite(f['z']) and -500<=f['z']<=9000
    a={f['key']:f['z'] for f in before if finite(f)};b={f['key']:f['z'] for f in after if finite(f)}
    filled=sorted(missing&b.keys())
    return {'baselineMissing':len(missing),'newlyFilled':len(filled),'newlyFilledKeys':filled,'remaining':len(missing)-len(filled),
        'existingHeightChanged':sum(abs(b[k]-a[k])>.001 for k in a.keys()&b.keys()),'removedFiniteKeys':sorted(a.keys()-b.keys()),
        'unit':'unique source tile feature keys; not cross-tile physical building deduplication','activated':False}

def reconcile_catalog(document,root,missing,cache=None):
    baseline=hashlib.sha256(json.dumps(sorted(missing),ensure_ascii=False).encode()).hexdigest()
    prior=(cache or {}).get('regions',{}) if (cache or {}).get('baselineSHA256')==baseline else {}
    owners=set()
    for key in missing:
        match=re.fullmatch(r'16/(\d+)/(\d+)/(\d+)',key)
        if not match or not (0<=int(match[1])<65536 and 0<=int(match[2])<65536):owners=None;break
        owners.add((int(match[1])//4,int(match[2])//4))
    if any(row.get('z')!=14 or any(type(row.get(axis)) is not int or not 0<=row[axis]<16384 for axis in ('x','y')) for row in document['regions']):owners=None
    current={};filled=set()
    for row in document['regions']:
        if owners is not None and (row['x'],row['y']) not in owners:continue
        path=(root/row['id']/'footprints.json').resolve();stat=path.stat()
        signature=[str(path),stat.st_size,stat.st_mtime_ns];entry=prior.get(row['id'])
        if not entry or entry.get('signature')!=signature:
            keys=compare_ground([],read_json(path),missing)['newlyFilledKeys']
            after=path.stat()
            if [str(path),after.st_size,after.st_mtime_ns]!=signature:raise ValueError('Footprints changed during reconciliation')
            entry={'signature':signature,'filledKeys':keys}
        current[row['id']]=entry;filled.update(entry['filledKeys'])
    return ({'baselineMissing':len(missing),'newlyFilled':len(filled),'newlyFilledKeys':sorted(filled),
        'remaining':len(missing)-len(filled),'reconciliationScope':'all current catalog regions against frozen baseline'},
        {'baselineSHA256':baseline,'regions':current})

def base_signature(path):
    import rasterio
    path=Path(path).resolve()
    with rasterio.open(path) as source:
        dependencies=[Path(p).resolve() for p in source.files if Path(p).resolve()!=path]
    stamps=[(str(p),p.stat().st_size,p.stat().st_mtime_ns) for p in dependencies]
    return hashlib.sha256(path.read_bytes()+json.dumps(stamps).encode()).hexdigest()

def affected(manifest,previous=None):
    import rasterio
    from pyproj import Transformer
    prior={(r['path'],r['sha256']) for r in (previous or {}).get('sources',[])}
    if previous and base_signature(manifest['base'])!=base_signature(previous['base']):
        raise ValueError('Base DEM signature changed; incremental precision bake requires a frozen base')
    current={(r['path'],r['sha256']) for r in manifest['sources']}
    old_common=[(r['path'],r['sha256']) for r in (previous or {}).get('sources',[]) if (r['path'],r['sha256']) in current]
    new_common=[(r['path'],r['sha256']) for r in manifest['sources'] if (r['path'],r['sha256']) in prior]
    sources=[r for r in manifest['sources'] if (r['path'],r['sha256']) not in prior]
    if previous and (not prior.issubset(current) or old_common!=new_common):sources=previous['sources']+manifest['sources']
    to=Transformer.from_crs(5186,4326,always_xy=True);selected=set()
    def tile(lon,lat):return math.floor((lon+180)/360*16384),math.floor((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*16384)
    for row in sources:
        with rasterio.open(row['path']) as ds:
            if ds.crs.to_epsg()!=5186:raise ValueError('Unexpected precision CRS')
            w,s,e,n=to.transform_bounds(*ds.bounds)
        x0,y1=tile(w,s);x1,y0=tile(e,n)
        # MVT buffered footprints can start just beyond their owner tile boundary.
        selected.update(f'14/{x}/{y}' for x in range(x0-1,x1+2) for y in range(y0-1,y1+2))
    return sorted(selected)

def run(args):
    env=dict(os.environ,DATA_ROOT=str(args.data_root),NGII_DEM_ROOT=str(args.dem_root),EDITOR_ROOT=str(Path(__file__).resolve().parents[2]))
    paths=DataPaths.from_env(env);manifest=read_json(args.manifest);work=args.manifest.parent
    signature=base_signature(manifest['base']);stamp_path=work/'base-source-signature.json'
    if stamp_path.exists() and read_json(stamp_path).get('signature')!=signature:raise ValueError('Frozen base DEM signature changed')
    if args.previous_manifest:
        previous_stamp=args.previous_manifest.parent/'base-source-signature.json'
        if previous_stamp.exists() and read_json(previous_stamp).get('signature')!=signature:raise ValueError('Previous frozen base DEM signature changed')
    atomic_json(stamp_path,{'signature':signature,'base':manifest['base']})
    selected=affected(manifest,read_json(args.previous_manifest) if args.previous_manifest else None)
    selection=work/'affected-regions.json'
    lock=(paths.dem/'national-buildings.lock').open('a+b');lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    try:
        if shutil.disk_usage(paths.buildings).free<20_000_000_000:raise OSError('Ground bake storage reserve')
        catalog=paths.catalog/'catalog.json';before_path=work/'catalog-before.json'
        selected=include_duplicate_regions(selected,read_json(catalog));atomic_json(selection,selected)
        if not before_path.exists():shutil.copyfile(catalog,before_path)
        before=read_json(before_path);source=before['source']
        env=paths.building_env(source,manifest['base'],env);env.update(WORLD_PRECISE_DEM_PATH=manifest['precision'],WORLD_BUILDINGS_REGIONS_FILE=str(selection))
        status=work/'building-status.json';atomic_json(status,{'state':'running','pid':os.getpid(),'startedAt':time.time(),'targets':len(selected)})
        with (work/'building-bake.log').open('a',encoding='utf8') as log:
            result=subprocess.run([paths.bun,'tools/bake-world-buildings.ts','--bounds','124.6','33.1','132.0','38.65','--resume'],cwd=paths.app,env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode not in (0,2):
            atomic_json(status,{'state':'failed','exitCode':result.returncode});raise RuntimeError('Building candidate bake failed')
        shutil.copyfile(paths.catalog/'last-bake-report.json',work/'building-report.json')
        selected_set=set(selected)
        def features(document):
            for row in document['regions']:
                if f"{row['z']}/{row['x']}/{row['y']}" in selected_set:
                    yield from read_json(paths.catalog/row['id']/'footprints.json')
        missing={r['key'] for r in read_json(args.baseline_missing)}
        current=read_json(catalog)
        try:require_unique_regions(current)
        except ValueError as error:
            atomic_json(status,{'state':'failed','reason':str(error),'activated':False});raise
        summary=compare_ground(features(before),features(current),missing)
        if summary['removedFiniteKeys']:raise ValueError('Candidate removed previously finite building keys')
        cache_path=paths.catalog/'ground-baseline-reconciliation-cache.json'
        cumulative,cache=reconcile_catalog(current,paths.catalog,missing,read_json(cache_path) if cache_path.exists() else None)
        summary.update(selectedRegionBaselineFilled=summary['newlyFilled'],existingHeightChangedScope='selected regions')
        summary.update(cumulative)
        atomic_json(cache_path,cache)
        atomic_json(work/'building-ground-progress.json',summary)
        atomic_json(status,{'state':'candidate_ready','exitCode':result.returncode,'finishedAt':time.time(),'newlyFilled':summary['newlyFilled'],'remaining':summary['remaining'],'activated':False})
        return summary
    finally:lock.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);p.add_argument('--previous-manifest',type=Path);p.add_argument('--baseline-missing',type=Path,required=True)
    p.add_argument('--data-root',type=Path,required=True);p.add_argument('--dem-root',type=Path,required=True);a=p.parse_args();result=run(a)
    print(json.dumps({k:v for k,v in result.items() if k!='newlyFilledKeys'}))
