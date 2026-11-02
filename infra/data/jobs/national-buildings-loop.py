"""Single-writer nationwide building publication alongside the terrain converter."""
import json,msvcrt,os,shutil,subprocess,time
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from paths import DataPaths
paths=DataPaths.from_env()
if "--check-config" in sys.argv:
 print(json.dumps({key:str(getattr(paths,key)) for key in ("editor","data","dem","originals","tiles","buildings","catalog")}));raise SystemExit(0)
import psutil
ROOT=paths.dem
APP=paths.app
BUN=Path(paths.bun)
STATUS=ROOT/'national-buildings-status.json'
lock=(ROOT/'national-buildings.lock').open('a+b')
if os.fstat(lock.fileno()).st_size==0:lock.write(b'0');lock.flush()
lock.seek(0)
try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
except OSError:raise SystemExit('Building publication already running')
psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
(ROOT/'national-buildings.pid').write_text(str(os.getpid()))
def read(p):
 try:return json.loads(p.read_text(encoding='utf-8-sig'))
 except (OSError,ValueError):return {}
def status(**fields):
 data={'at':time.time(),'pid':os.getpid(),**fields}
 p=STATUS.with_suffix('.tmp');p.write_text(json.dumps(data,ensure_ascii=False,indent=2));p.replace(STATUS)
 print(json.dumps(data),flush=True)
def snapshot(sequence):
 p=ROOT/f'building-publication-loop-{os.getpid()}-{sequence}.vrt'
 shutil.copyfile(ROOT/'ngii_dem.vrt',p)
 return p
source=read(paths.catalog/'catalog.json')['source']
archive=paths.building_archive(source)
if not archive.is_file():raise SystemExit('Local building archive is missing')
env=paths.building_env(source)
def bake(args,phase):
 # Never overlap another catalog publisher, including a manually started bake.
 while any(any('bake-world-buildings.ts' in a for a in (p.info['cmdline'] or []))
           for p in psutil.process_iter(['cmdline']) if p.pid!=os.getpid()):time.sleep(10)
 if shutil.disk_usage(paths.buildings).free<9*1024**3:
  status(state='needs_storage',phase=phase);raise SystemExit(4)
 status(state='running',phase=phase,args=args)
 for retry in range(3):
  with (ROOT/'national-buildings-bake.log').open('a',encoding='utf-8') as log:
   result=subprocess.run([str(BUN),'tools/bake-world-buildings.ts',*args,'--resume'],cwd=APP,env=env,
    stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
  if result.returncode in (0,2):return result.returncode
  status(state='retrying' if retry<2 else 'failed',phase=phase,exit_code=result.returncode,attempt=retry+1)
  if retry<2:time.sleep(10)
 raise SystemExit(result.returncode)
cities=[('Chuncheon',127.73,37.8813),('Andong',128.7294,36.5684),('Hongseong',126.6608,36.6012),
 ('Ulleung',130.9057,37.4844),('Cheongju',127.489,36.6424),('Changwon',128.6811,35.2285),
 ('Mokpo',126.3922,34.8118),('Sejong',127.289,36.4801),('Suwon',127.0286,37.2636),
 ('Jeonju',127.148,35.8242),('Gangneung',128.8761,37.7519),('Seoul',126.978,37.5665),
 ('Busan',129.0756,35.1796),('Daegu',128.6014,35.8714),('Gwangju',126.8526,35.1595),
 ('Daejeon',127.3845,36.3504),('Incheon',126.7052,37.4563),('Ulsan',129.3114,35.5384),
 ('Jeju',126.5312,33.4996),('Gosan',127.1084,37.7294),('Dokdo',131.8652,37.2411)]
env['WORLD_DEM_PATH']=str(snapshot('cities'))
for name,lon,lat in cities:bake([str(lon),str(lat),'0'],name)
for attempt in range(1,4):
 env['WORLD_DEM_PATH']=str(snapshot(attempt))
 code=bake(['--bounds','124.6','33.1','132.0','38.65'],f'nationwide-pass-{attempt}')
 report=paths.catalog/'last-bake-report.json'
 if report.exists():shutil.copyfile(report,ROOT/f'national-buildings-pass-{attempt}.json')
 if code==0:
  status(state='building_preparation_complete',regions=len(read(paths.catalog/'catalog.json')['regions']),
   limitation='Not full national visual QA, terrain completion, or verified loading latency');break
 if attempt==3:
  status(state='needs_evidence',report=str(ROOT/f'national-buildings-pass-{attempt}.json'));break
 while read(ROOT/'national-progress.json').get('state')=='running':
  status(state='waiting_for_terrain',next_pass=attempt+1);time.sleep(60)

paths.publish_catalog()
