import source_job_paths as sjp
import json,hashlib,time
from pathlib import Path
import httpx
root=Path(str(sjp.DATA_ROOT / 'world-buildings'))
catalog=json.loads((root/'catalog.json').read_text());rows=[]
with httpx.Client(base_url='http://127.0.0.1:3003',trust_env=False,timeout=30) as c:
 r=c.get('/api/map-data/world-buildings/catalog.json');print('catalog',r.status_code)
 for region in catalog['regions'][-5:]:
  start=time.perf_counter();r=c.get('/api/map-data'+region['url']);row={'id':region['id'],'manifest':r.status_code}
  if r.status_code==200:
   tree=r.json();uri=tree['root']['content']['uri'];asset=c.get('/api/map-data'+region['url'].rsplit('/',1)[0]+'/'+uri)
   local=(root/region['id']/uri).read_bytes()
   row.update(mesh=asset.status_code,bytes=len(asset.content),matches_local=hashlib.sha256(asset.content).digest()==hashlib.sha256(local).digest())
  row['seconds']=round(time.perf_counter()-start,3);rows.append(row);print(row)
report={'at':time.time(),'regions':len(catalog['regions']),'sample':rows}
Path(str(sjp.NGII_DEM_ROOT / 'national-building-delivery-audit.json')).write_text(json.dumps(report,indent=2))
