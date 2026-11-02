"""Bake immutable, resumable geographic heightmap PMTiles from the installed DEM."""
import argparse,concurrent.futures,gzip,hashlib,json,math,os,shutil,sqlite3,sys,threading,time
from pathlib import Path
import numpy as np,rasterio
from rasterio.windows import Window
from pmtiles.writer import write
from pmtiles.tile import zxy_to_tileid,Compression,TileType
from terrain_archive import grid_view,encode_grid

def atomic_json(path,value):
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,indent=2),encoding='utf-8')
    for attempt in range(50):
        try:temp.replace(path);return
        except PermissionError:
            if attempt==49:raise
            time.sleep(.1)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dem',type=Path,required=True);p.add_argument('--work',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--bounds',nargs=4,type=float,default=[124.6,33.1,132,38.65])
    p.add_argument('--levels',nargs=2,type=int,default=[11,15]);p.add_argument('--detail-points',type=Path)
    p.add_argument('--detail-max-level',type=int,default=17)
    p.add_argument('--workers',type=int,default=4);p.add_argument('--publish',action='store_true')
    p.add_argument('--upgrade-omitted-nodata',action='store_true',help='Upgrade the inspected legacy checkpoint: preserve finite tiles and add explicit NoData tiles for completed jobs')
    args=p.parse_args();w,s,e,n=args.bounds
    if not (124<=w<e<=133 and 33<=s<n<=39 and 0<=args.levels[0]<=args.levels[1]<=20 and 17<=args.detail_max_level<=20):p.error('Invalid geographic bounds/levels')
    args.work.mkdir(parents=True,exist_ok=True);args.output.mkdir(parents=True,exist_ok=True)
    digest=hashlib.sha256(args.dem.read_bytes()).hexdigest()
    snapshot=args.dem.with_name('archive-snapshot-'+digest[:16]+'.vrt')
    if not snapshot.exists():shutil.copyfile(args.dem,snapshot)
    if hashlib.sha256(snapshot.read_bytes()).hexdigest()!=digest:raise ValueError('Snapshot changed')
    database=args.work/('terrain-'+digest[:16]+'.sqlite');db=sqlite3.connect(database,timeout=60)
    # Progress/validation readers must not stop the writer on Windows.
    db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA busy_timeout=60000')
    db.execute('CREATE TABLE IF NOT EXISTS tiles(id INTEGER PRIMARY KEY,data BLOB NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY)')
    done={r[0] for r in db.execute('SELECT id FROM jobs')}
    jobs=[]
    for level in range(args.levels[0],args.levels[1]+1):
        width=180/2**level;x0=math.floor((w+180)/width);x1=math.ceil((e+180)/width);y0=math.floor((90-n)/width);y1=math.ceil((90-s)/width)
        for x in range(x0,x1,16):
            for y in range(y0,y1,16):jobs.append((level,[(xx,yy) for xx in range(x,min(x+16,x1)) for yy in range(y,min(y+16,y1))]))
    if args.detail_points:
        points=json.loads(args.detail_points.read_text(encoding='utf-8'));detail={}
        for level in range(16,args.detail_max_level+1):
            width=180/2**level;keys=set()
            for item in points:
                lon,lat=item['point'] if isinstance(item,dict) else item
                x=math.floor((lon+180)/width);y=math.floor((90-lat)/width)
                keys.update((x+dx,y+dy) for dx in (-1,0,1) for dy in (-1,0,1))
            for x,y in keys:detail.setdefault((level,x//16,y//16),[]).append((x,y))
        jobs.extend((level,sorted(keys)) for (level,_,_),keys in detail.items())
    # Fine source windows are cheap and include repaired building locations.
    # Coarse country-wide warps are larger; process them after fine windows.
    jobs.sort(key=lambda job:-job[0])
    def jobid(job):return hashlib.sha256(json.dumps(job,separators=(',',':')).encode()).hexdigest()
    todo=[(jobid(j),j) for j in jobs if jobid(j) not in done]
    local=threading.local();started=time.monotonic();completed=0;written=0
    with rasterio.open(snapshot) as source:
        files=[Path(f) for f in source.files];stamps=[(str(f),f.stat().st_size,f.stat().st_mtime_ns) for f in files]
    signature=hashlib.sha256(json.dumps(stamps).encode()).hexdigest()
    db.execute('CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    previous=db.execute("SELECT value FROM metadata WHERE key='sourceSignature'").fetchone()
    if previous and previous[0]!=signature:raise ValueError('Raster files changed since checkpoint; use a fresh work directory')
    if not previous and done:
        created=getattr(database.stat(),'st_birthtime',database.stat().st_ctime)
        if any(f.stat().st_mtime>created for f in files):raise ValueError('Cannot establish legacy checkpoint provenance; use a fresh work directory')
    db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',('sourceSignature',signature));db.commit()
    sampler_signature=hashlib.sha256(Path(__file__).with_name('terrain_archive.py').read_bytes()+rasterio.__version__.encode()+rasterio.__gdal_version__.encode()+b'height-range:-500:9000;explicit-nodata-v1').hexdigest()
    previous_sampler=db.execute("SELECT value FROM metadata WHERE key='samplerSignature'").fetchone()
    if previous_sampler and previous_sampler[0]!=sampler_signature:raise ValueError('Sampler changed since checkpoint; use a fresh work directory')
    if done and not previous_sampler:
        if not args.upgrade_omitted_nodata:raise ValueError('Legacy checkpoint requires an explicit inspected NoData upgrade or a fresh work directory')
        # Only completed jobs establish that an absent tile was sampled and empty.
        # Unrequested tiles stay absent so sparse finer levels can use ancestors.
        empty=gzip.compress(encode_grid(np.full((33,33),np.nan,dtype='float32')),compresslevel=1,mtime=0)
        for job in jobs:
            if jobid(job) in done:
                level,keys=job
                db.executemany('INSERT OR IGNORE INTO tiles VALUES(?,?)',((zxy_to_tileid(level+1,x,y),empty) for x,y in keys))
        db.commit()
    db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',('samplerSignature',sampler_signature));db.commit()
    def worker(item):
        identity,(level,keys)=item
        if not hasattr(local,'source'):local.source=rasterio.open(snapshot);local.views={}
        if level not in local.views:local.views[level]=grid_view(local.source,level)
        x0=min(x for x,y in keys);y0=min(y for x,y in keys);x1=max(x for x,y in keys);y1=max(y for x,y in keys)
        grid=local.views[level].read(1,window=Window(x0*32,y0*32,(x1-x0+1)*32+1,(y1-y0+1)*32+1))
        rows=[]
        for x,y in keys:
            tile=grid[(y-y0)*32:(y-y0)*32+33,(x-x0)*32:(x-x0)*32+33]
            tile=np.where((tile>=-500)&(tile<=9000),tile,np.nan).astype('float32')
            rows.append((zxy_to_tileid(level+1,x,y),gzip.compress(encode_grid(tile),compresslevel=1,mtime=0)))
        return identity,rows
    def checkpoint(state,**more):
        value=dict(pid=os.getpid(),state=state,source=digest,jobsTotal=len(jobs),jobsPending=len(todo),jobsCompleted=completed,
                   tilesWritten=written,elapsedSeconds=round(time.monotonic()-started,2),**more)
        atomic_json(args.work/'progress.json',value)
    checkpoint('baking')
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        for identity,rows in pool.map(worker,todo):
            db.executemany('INSERT OR REPLACE INTO tiles VALUES(?,?)',rows);db.execute('INSERT OR IGNORE INTO jobs VALUES(?)',(identity,));db.commit()
            completed+=1;written+=len(rows);checkpoint('baking')
    if [(str(f),f.stat().st_size,f.stat().st_mtime_ns) for f in files]!=stamps:raise ValueError('DEM changed during baking')
    count=db.execute('SELECT count(*) FROM tiles').fetchone()[0]
    if not count:raise ValueError('No terrain cells available')
    checkpoint('packing',totalTiles=count)
    archive=args.work/'terrain.packing.pmtiles'
    metadata=dict(schema='ngii-heightmap-v1',size=33,grid='Cesium.GeographicTilingScheme',archiveZoomOffset=1,
                  minLevel=args.levels[0],maxLevel=args.detail_max_level if args.detail_points else args.levels[1],vrt_sha256=digest,
                  sampler='GDAL bilinear display pyramid; NoData preserved',bounds=args.bounds,tiles=count,
                  sourceFilesSHA256=signature,samplerSHA256=sampler_signature,explicitNoData=True)
    with write(str(archive)) as writer:
        for tileid,data in db.execute('SELECT id,data FROM tiles ORDER BY id'):writer.write_tile(tileid,data)
        writer.finalize(dict(tile_type=TileType.UNKNOWN,tile_compression=Compression.GZIP,
                             min_lon_e7=round(w*1e7),min_lat_e7=round(s*1e7),max_lon_e7=round(e*1e7),max_lat_e7=round(n*1e7)),metadata)
    checksum=hashlib.file_digest(archive.open('rb'),'sha256').hexdigest();name='terrain-'+checksum[:20]+'.pmtiles'
    if shutil.disk_usage(args.output).free<archive.stat().st_size+15_000_000_000:raise OSError('Output storage reserve')
    target=args.output/name;temp=target.with_suffix('.copying');shutil.copyfile(archive,temp);temp.replace(target)
    config=dict(url='/api/map-data/world-terrain/'+name,vrt_sha256=digest,sha256=checksum,bytes=target.stat().st_size,tiles=count)
    atomic_json(args.work/'archive-receipt.json',{**config,'metadata':metadata})
    if args.publish:
        atomic_json(args.output/'archive.json',config)
    checkpoint('complete',totalTiles=count,archive=str(target),bytes=target.stat().st_size)

if __name__=='__main__':
    try:main()
    except Exception as error:
        if '--work' in sys.argv:
            status=Path(sys.argv[sys.argv.index('--work')+1])/'progress.json'
            value=json.loads(status.read_text(encoding='utf-8')) if status.exists() else {}
            atomic_json(status,{**value,'state':'failed','errorType':type(error).__name__,'error':str(error)})
        raise
