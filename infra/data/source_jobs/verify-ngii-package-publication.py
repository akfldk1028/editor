import source_job_paths as sjp
import hashlib,json,math,struct,time
from pathlib import Path
import httpx
ROOT=Path(str(sjp.NGII_ORIGINAL_ROOT));APP=Path(str(sjp.DATA_ROOT))
receipt=json.loads((ROOT/'terrain-install-receipt.json').read_text(encoding='utf-8'));wanted=set(receipt['regions']);keys=set(receipt['verifiedKeys'])
before=json.loads((ROOT/'before-partial-ground-rebake.json').read_text(encoding='utf-8'))
catalog=json.loads((APP/'world-buildings/catalog.json').read_text(encoding='utf-8'));seen=set();rows=[]
with httpx.Client(base_url='http://127.0.0.1:3003',timeout=30,trust_env=False) as client:
 for region in catalog['regions']:
  key=f"{region['z']}/{region['x']}/{region['y']}"
  if key not in wanted:continue
  features=json.loads((APP/region['footprints'].lstrip('/')).read_text(encoding='utf-8'));published={f['key'] for f in features if isinstance(f.get('z'),(int,float)) and math.isfinite(f['z'])}
  lost=set(before.get(key,{}).get('keys',[]))-published
  if lost:raise ValueError('Previously published building lost')
  seen.update(keys&published)
  manifest=client.get('/api/map-data'+region['url']);manifest.raise_for_status();tree=manifest.json();pending=[tree['root']];files=set()
  while pending:
   node=pending.pop();files.add(node['content']['uri']);pending.extend(node.get('children',[]))
  folder=(APP/region['url'].lstrip('/')).parent
  for name in files:
   with (folder/name).open('rb') as file:header=file.read(12)
   if len(header)!=12 or header[:4]!=b'b3dm' or struct.unpack('<I',header[8:12])[0]!=(folder/name).stat().st_size:raise ValueError('Invalid referenced building mesh')
  mesh=client.get('/api/map-data'+region['url'].rsplit('/',1)[0]+'/'+tree['root']['content']['uri']);mesh.raise_for_status()
  if hashlib.sha256(mesh.content).hexdigest()!=hashlib.sha256((folder/tree['root']['content']['uri']).read_bytes()).hexdigest():raise ValueError('Served mesh differs from publication')
  rows.append({'region':key,'id':region['id'],'buildings':len(features),'previousBuildingsPreserved':len(before.get(key,{}).get('keys',[])),'meshFilesChecked':len(files),'manifestHTTP':manifest.status_code,'meshHTTP':mesh.status_code})
records=[r for r in json.loads(Path(str(sjp.NGII_DEM_ROOT / 'national-gap-exact-points.json')).read_text(encoding='utf-8')) if r['key'] in keys];ground=[]
with httpx.Client(base_url='http://127.0.0.1:18449',timeout=30,trust_env=False) as client:
 for row in records[::max(1,len(records)//3)][:3]:
  lon,lat=row['point'];response=client.get('/api/v1/land/terrain-heights',params={'west':lon,'south':lat,'east':lon+1e-8,'north':lat+1e-8,'size':2});response.raise_for_status();ground.append({'key':row['key'],'http':response.status_code,'heights':response.json()['heights']})
result={'at':time.time(),'terrainPointsRepaired':len(keys),'repairedRecordsPublishedInBuildingTiles':len(seen),'remainingRepairedButNotPublishedKeys':sorted(keys-seen),'regions':rows,'groundServiceSamples':ground,'scope':'Actual served data and retained feature identities; not a nationwide visual or loading-speed benchmark'}
(ROOT/'building-publication-check.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in result.items() if k not in ['regions','remainingRepairedButNotPublishedKeys']}))
