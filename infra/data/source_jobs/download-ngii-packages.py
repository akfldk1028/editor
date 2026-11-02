"""Download authorized NGII package manifests with disk reserve and receipts."""
import source_job_paths as sjp
import concurrent.futures,hashlib,json,msvcrt,os,shutil,time,threading,re
from pathlib import Path
import httpx
import numpy as np
from scipy.spatial import cKDTree
from pyproj import Transformer

ROOT=Path(str(sjp.NGII_ORIGINAL_ROOT))
DEST=ROOT/'files';DEST.mkdir(exist_ok=True)
lock=(ROOT/'download.lock').open('a+b');lock.write(b'0');lock.flush();lock.seek(0)
msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
STATUS=ROOT/'download-status.json'
local=threading.local()
def write(path,data):
 temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
 for attempt in range(30):
  try:temp.replace(path);return
  except PermissionError:
   if attempt==29:raise
   time.sleep(.1)
def read(path):
 for attempt in range(4):
  try:return json.loads(path.read_text(encoding='utf-8-sig'))
  except (OSError,ValueError):
   if attempt==3:raise
   time.sleep(.2)
def download(item):
 name=item['name'];expected=int(item['bytes'])
 if Path(name).name!=name or expected<=0:raise ValueError('Invalid manifest entry')
 target=DEST/name;receipt=target.with_suffix(target.suffix+'.receipt.json');part=target.with_suffix(target.suffix+'.part')
 if target.exists() and receipt.exists():
  old=json.loads(receipt.read_text(encoding='utf-8'))
  if target.stat().st_size==expected and old.get('sha256')==hashlib.file_digest(target.open('rb'),'sha256').hexdigest():return {'name':name,'state':'verified_cached','bytes':expected}
 for attempt in range(3):
  try:
   if shutil.disk_usage(ROOT).free<20_000_000_000+4*expected:raise OSError('storage reserve')
   if not hasattr(local,'client'):local.client=httpx.Client(timeout=90,follow_redirects=True,trust_env=False)
   with local.client.stream('GET',item['url']) as response:
     response.raise_for_status()
     if 'text/html' in response.headers.get('content-type',''):raise ValueError('HTML instead of original')
     size=0;digest=hashlib.sha256()
     with part.open('wb') as out:
      for block in response.iter_bytes(1024*1024):
       size+=len(block)
       if size>expected:raise ValueError('oversized response')
       out.write(block);digest.update(block)
   if size!=expected:raise ValueError('size mismatch')
   part.replace(target)
   result={'name':name,'state':'size_and_sha_recorded','bytes':size,'sha256':digest.hexdigest(),'at':time.time()}
   write(receipt,result);return result
  except Exception as error:
   if attempt==2:return {'name':name,'state':'failed','errorType':type(error).__name__}
   time.sleep(2*(attempt+1))
seen={};results={}
points=np.array([r['point'] for r in read(Path(str(sjp.NGII_DEM_ROOT / 'national-gap-exact-points.json')))])
x,y=Transformer.from_crs(4326,5179,always_xy=True).transform(points[:,0],points[:,1]);points=np.column_stack([x,y]);point_tree=cKDTree(points)
catalogues_seen=set();needed_sheets=set()
for receipt_path in DEST.glob('*.receipt.json'):
 try:
  old=read(receipt_path);target=DEST/old['name']
  if target.exists() and target.stat().st_size==old['bytes'] and hashlib.file_digest(target.open('rb'),'sha256').hexdigest()==old['sha256']:results[old['name']]=old
 except (OSError,ValueError,KeyError):continue
while True:
 for path in ROOT.glob('*-catalogue.json'):
  if path.name in catalogues_seen:continue
  for row in read(path):
   if int(row.get('scale') or 999999)>5000:continue
   a,b,c,d=[row[k] for k in ['minx','miny','maxx','maxy']]
   nearby=point_tree.query_ball_point([(a+c)/2,(b+d)/2],np.hypot(c-a,d-b)/2)
   if nearby:
    subset=points[nearby]
    if np.any((subset[:,0]>=a)&(subset[:,0]<=c)&(subset[:,1]>=b)&(subset[:,1]<=d)):needed_sheets.add(row['sheet'])
  catalogues_seen.add(path.name)
 manifests=list(ROOT.glob('*-manifest.json'))
 for path in manifests:
  for item in read(path)['files']:
   if item['name'] in seen and seen[item['name']]['bytes']!=item['bytes']:raise ValueError('Conflicting file manifest')
   seen[item['name']]=item
 queue=[item for name,item in seen.items() if name not in results]
 def priority(item):
  match=re.search(r'_(\d{8,9})_\d{4}_',item['name']);needed=match and match[1] in needed_sheets
  ext=Path(item['name']).suffix
  return (0 if needed else 1, {'.zip':0,'.dxf':1,'.xml':2}.get(ext,3),item['bytes'])
 queue.sort(key=priority)
 queue=queue[:128]
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
  for future in concurrent.futures.as_completed([pool.submit(download,item) for item in queue]):
   result=future.result()
   results[result['name']]=result
   write(STATUS,{'pid':os.getpid(),'state':'running','at':time.time(),'knownFiles':len(seen),'finishedFiles':len(results),'failedFiles':sum(r['state']=='failed' for r in results.values()),'bytesVerified':sum(r.get('bytes',0) for r in results.values()),'freeBytes':{d:shutil.disk_usage(d).free for d in sjp.STORAGE_ROOTS}})
 order=ROOT/'batch-order-status.json'
 terminal=order.exists() and json.loads(order.read_text(encoding='utf-8')).get('state')=='finished'
 if terminal and not queue:break
 if not queue:time.sleep(10)
write(STATUS,{'pid':os.getpid(),'state':'finished_with_failures' if any(r['state']=='failed' for r in results.values()) else 'finished','at':time.time(),'knownFiles':len(seen),'finishedFiles':len(results),'results':list(results.values()),'geometryValidated':False})
