"""Compare archived display heights with the authoritative five metre sampler."""
import argparse,gzip,hashlib,importlib.util,json,math,sqlite3
from pathlib import Path
import numpy as np,rasterio
from pmtiles.tile import zxy_to_tileid

p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);p.add_argument('--dem',required=True);p.add_argument('--points',type=Path,required=True)
p.add_argument('--level',type=int,default=17)
p.add_argument('--buildings',type=Path)
a=p.parse_args();records=json.loads(a.points.read_text(encoding='utf-8'));points=[r['point'] if isinstance(r,dict) else r for r in records]
spec=importlib.util.spec_from_file_location('sampler',Path(__file__).with_name('sample-building-dem.py'));sampler=importlib.util.module_from_spec(spec);spec.loader.exec_module(sampler)
reference=sampler.sample(a.dem,points)['heights'];db=sqlite3.connect(str(next(a.work.glob('terrain-*.sqlite'))));cache={};differences=[];missing=[];compared=[]
for i,((lon,lat),height) in enumerate(zip(points,reference)):
    width=180/2**a.level;x=math.floor((lon+180)/width);y=math.floor((90-lat)/width);tileid=zxy_to_tileid(a.level+1,x,y)
    if tileid not in cache:
        row=db.execute('SELECT data FROM tiles WHERE id=?',(tileid,)).fetchone();cache[tileid]=np.frombuffer(gzip.decompress(row[0]),dtype='<f4',offset=8).reshape(33,33) if row else None
    grid=cache[tileid];z=None
    if grid is not None:
        fx=((lon+180)/width-x)*32;fy=((90-lat)/width-y)*32;c=min(31,math.floor(fx));r=min(31,math.floor(fy));u=fx-c;v=fy-r;corners=grid[r:r+2,c:c+2]
        if np.isfinite(corners).all():z=float(corners[0,0]*(1-u)*(1-v)+corners[0,1]*u*(1-v)+corners[1,0]*(1-u)*v+corners[1,1]*u*v)
        else:
            weights=np.array([[(1-u)*(1-v),u*(1-v)],[(1-u)*v,u*v]]);weights[~np.isfinite(corners)]=0
            z=float(np.nansum(corners*weights)/weights.sum()) if weights.sum()>1e-12 else float('nan')
    if z is None or not math.isfinite(z) or height is None:missing.append({'index':i,'key':records[i].get('key') if isinstance(records[i],dict) else None,'sourceHeight':height,'archiveHeight':z if z is not None and math.isfinite(z) else None})
    else:
        differences.append(abs(z-height));compared.append({'index':i,'point':[lon,lat],'sourceHeight':height,'archiveHeight':z,'error':abs(z-height)})
report={'records':len(points),'compared':len(differences),'missing':len(missing),'absoluteErrorMetres':dict(zip(['median','p95','maximum'],map(float,np.percentile(differences,[50,95,100])))) if differences else None,'missingRecords':missing,'scope':'Level 17 geographic display grid vs original projected DEM; not survey accuracy.'}
report['scope']=f'Level {a.level} geographic display grid vs original projected DEM; not survey accuracy.'
report['edgeSampling']='Valid-weight bilinear interpolation; exact unsupported vertices remain NoData.'
report['largestDifferences']=sorted(compared,key=lambda r:-r['error'])[:20]
report['sourceVrtSHA256']=hashlib.sha256(Path(a.dem).read_bytes()).hexdigest()
report['terrainArchiveSHA256']=json.loads((a.work/'archive-receipt.json').read_text(encoding='utf-8'))['sha256']
with rasterio.open(a.dem) as source:
    stamps=[(str(Path(f)),Path(f).stat().st_size,Path(f).stat().st_mtime_ns) for f in source.files]
report['sourceFilesSHA256']=hashlib.sha256(json.dumps(stamps).encode()).hexdigest()
if a.buildings:
    report['buildingCatalogSHA256']=hashlib.sha256((a.buildings/'world-buildings/catalog.json').read_bytes()).hexdigest()
    catalog=json.loads((a.buildings/'world-buildings/catalog.json').read_text(encoding='utf-8'));wanted={r['region'] for r in records if isinstance(r,dict) and 'region' in r};published={}
    for region in catalog['regions']:
        if f"{region['z']}/{region['x']}/{region['y']}" not in wanted:continue
        for feature in json.loads((a.buildings/region['footprints'].lstrip('/')).read_text(encoding='utf-8')):
            if isinstance(feature.get('z'),(int,float)) and math.isfinite(feature['z']):published[feature['key']]=feature['z']
    errors=[abs(published[r['key']]-h) for r,h in zip(records,reference) if isinstance(r,dict) and r.get('key') in published and h is not None]
    report['publishedBuildingDatumCheck']={'expected':sum(isinstance(r,dict) and 'key' in r for r in records),'compared':len(errors),'maximumAbsoluteErrorMetres':max(errors) if errors else None}
(a.work/'height-verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in report.items() if k not in ['missingRecords','largestDifferences']}))
