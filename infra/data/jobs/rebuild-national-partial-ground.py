"""One bounded pass over known ground-gap regions, preserving already published buildings."""
import json,msvcrt,os,re,shutil,subprocess,time
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from paths import DataPaths
paths=DataPaths.from_env()
if "--check-config" in sys.argv:
 print(json.dumps({key:str(getattr(paths,key)) for key in ("editor","data","dem","originals","tiles","buildings","catalog")}));raise SystemExit(0)
import psutil
ROOT=paths.dem;APP=paths.app;SOURCE=paths.originals
STATUS=SOURCE/'national-partial-rebake-status.json'
def write(data):
 temp=STATUS.with_suffix('.tmp');temp.write_text(json.dumps({'pid':os.getpid(),'at':time.time(),**data},indent=2),encoding='utf-8')
 for attempt in range(30):
  try:temp.replace(STATUS);return
  except PermissionError:
   if attempt==29:raise
   time.sleep(.1)
lock=(ROOT/'national-buildings.lock').open('a+b');lock.write(b'0');lock.flush()
while True:
 lock.seek(0)
 try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1);break
 except OSError:write({'state':'waiting_for_publisher'});time.sleep(5)
while any(any('bake-world-buildings.ts' in a for a in (p.info['cmdline'] or [])) for p in psutil.process_iter(['cmdline']) if p.pid!=os.getpid()):write({'state':'waiting_for_publisher'});time.sleep(5)
catalog_path=paths.catalog/'catalog.json';before=json.loads(catalog_path.read_text(encoding='utf-8'));source=before['source']
regions=sorted({r['region'] for r in json.loads((ROOT/'national-gap-exact-points.json').read_text(encoding='utf-8'))})
selection=SOURCE/'national-partial-region-selection.json';selection.write_text(json.dumps(regions),encoding='utf-8')
snapshot=ROOT/f'national-partial-ground-{os.getpid()}.vrt';shutil.copyfile(ROOT/'ngii_dem.vrt',snapshot)
archive=paths.building_archive(source)
env=paths.building_env(source,snapshot);env['WORLD_BUILDINGS_REGIONS_FILE']=str(selection)
published=0;write({'state':'running','selectedRegions':len(regions),'publishedRegions':published})
command=[paths.bun,'tools/bake-world-buildings.ts','--bounds','124.6','33.1','132.0','38.65','--resume']
with (SOURCE/'national-partial-rebake.log').open('a',encoding='utf-8') as log:
 process=subprocess.Popen(command,cwd=APP,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',creationflags=subprocess.CREATE_NO_WINDOW)
 for line in process.stdout:
  log.write(line);log.flush()
  if re.match(r'14-\d+-\d+-.*: \d+ buildings',line):published+=1;write({'state':'running','selectedRegions':len(regions),'publishedRegions':published,'latest':line.strip()})
 code=process.wait()
report=paths.catalog/'last-bake-report.json';shutil.copyfile(report,SOURCE/'national-partial-rebake-report.json')
after=json.loads(catalog_path.read_text(encoding='utf-8'));count=lambda c:sum(sum(r['counts'].values()) for r in c['regions'])
write({'state':'finished_with_ground_gaps' if code==2 else 'finished' if code==0 else 'failed','exitCode':code,'selectedRegions':len(regions),'publishedRegions':published,'catalogRegionsBefore':len(before['regions']),'catalogRegionsAfter':len(after['regions']),'buildingRecordsAdded':count(after)-count(before),'limitation':'Preserves known ground and publishes valid neighbours; unresolved source ground gaps remain explicit.'})
if code in (0,2):paths.publish_catalog()
raise SystemExit(0 if code in (0,2) else code)
