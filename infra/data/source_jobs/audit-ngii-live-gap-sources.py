"""Query the provider's actual download search for each known gap region."""
import source_job_paths as sjp
import collections, concurrent.futures, json, os, re, threading, time
from pathlib import Path
import httpx
from pyproj import Transformer
from ngii_source_schedule import needs_refresh, undiscovered, area_query_form

ROOT=Path(str(sjp.NGII_ORIGINAL_ROOT))
STATUS=ROOT/'live-source-audit.json'
local=threading.local()
transform=Transformer.from_crs(4326,5179,always_xy=True)
groups=collections.defaultdict(list)
for row in json.loads(Path(str(sjp.NGII_DEM_ROOT / 'national-gap-exact-points.json')).read_text(encoding='utf-8')):
    groups[row['region']].append(row['point'])
available=set()
for path in (ROOT/'files').iterdir():
    if path.suffix not in ('.zip','.dxf','.ngi'):continue
    match=re.search(r'_(\d{8,9})_\d{4}_',path.name)
    if match:available.add(match[1])
results={}
if STATUS.exists():
    results=json.loads(STATUS.read_text(encoding='utf-8')).get('results',{})
for result in results.values():
    result['newPreciseSheets']=undiscovered(result.get('preciseSheets',[]),available)

def save(state):
    candidates={item['num'] for row in results.values() for item in row.get('newPreciseSheets',[])}
    value=dict(pid=os.getpid(),at=time.time(),state=state,totalRegions=len(groups),
               regionsChecked=len(results),newPreciseSheets=len(candidates),
               requestFailures=sum(r['state']=='request_failed' for r in results.values()),
               scope='Current downloadable search, not proof of TIN support or national survey availability.',results=results)
    temp=STATUS.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    for attempt in range(30):
        try:temp.replace(STATUS);break
        except PermissionError:
            if attempt==29:raise
            time.sleep(.1)

def query(region):
    if not hasattr(local,'client'):local.client=httpx.Client(timeout=45,trust_env=False)
    ll=groups[region];x,y=transform.transform([p[0] for p in ll],[p[1] for p in ll])
    form=area_query_form(min(x)-1,min(y)-1,max(x)+1,max(y)+1)
    precise=[];scales=collections.Counter()
    for kind in ('0','3'):
        for attempt in range(3):
            try:
                response=local.client.post('https://map.ngii.go.kr/ms/map/suchiQuery.do',data={**form,'type':kind});response.raise_for_status()
                data=response.json()
                if not isinstance(data.get('items'),list):raise ValueError('Invalid catalogue response')
                for row in data['items']:
                    scale=int(row.get('scale') or 999999);scales[str(scale)]+=1
                    if scale<=5000:
                        precise.append({**{k:row.get(k) for k in ('num','name','scale','projection','historyNo','fileExt','minx','miny','maxx','maxy')},'type':kind})
                break
            except Exception as error:
                if attempt==2:return region,dict(state='request_failed',errorType=type(error).__name__)
                time.sleep(attempt+1)
    return region,dict(state='checked',queryVersion=2,checkedAt=time.time(),historicalMissingRecords=len(ll),scales=dict(scales),preciseSheets=precise,
                       newPreciseSheets=[r for r in precise if r['num'] not in available])

save('running')
pending=sorted((r for r in groups if results.get(r,{}).get('queryVersion')!=2 or needs_refresh(results.get(r,{}),time.time())),key=lambda r:-len(groups[r]))
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    for region,row in pool.map(query,pending):
        results[region]=row;save('running')
save('finished')
