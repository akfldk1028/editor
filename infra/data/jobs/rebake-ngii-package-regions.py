import json,math,msvcrt,os,shutil,subprocess,time
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from paths import DataPaths
paths=DataPaths.from_env()
if "--check-config" in sys.argv:
 print(json.dumps({key:str(getattr(paths,key)) for key in ("editor","data","dem","originals","tiles","buildings","catalog")}));raise SystemExit(0)
import psutil
ROOT=paths.dem;SOURCE=paths.originals;APP=paths.app
lock=(ROOT/'national-buildings.lock').open('a+b');lock.write(b'0');lock.flush();lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
receipt=json.loads((SOURCE/'terrain-install-receipt.json').read_text(encoding='utf-8'))
catalog=json.loads((paths.catalog/'catalog.json').read_text(encoding='utf-8'))
snapshot=ROOT/f'package-rebake-{os.getpid()}.vrt';shutil.copyfile(ROOT/'ngii_dem.vrt',snapshot)
source=catalog['source'];archive=paths.building_archive(source)
if not archive.is_file():raise FileNotFoundError('Local building archive')
env=paths.building_env(source,snapshot)
rows=[];status=SOURCE/'building-rebake-status.json'
def checkpoint(state):
 data={'pid':os.getpid(),'state':state,'at':time.time(),'total':len(receipt['regions']),'completed':len(rows),'results':rows,'limitation':'Buildings without a trustworthy ground datum remain unpublished; valid neighbours can be published independently.'}
 temp=status.with_suffix('.tmp');temp.write_text(json.dumps(data,indent=2),encoding='utf-8');temp.replace(status)
checkpoint('running')
for region in receipt['regions']:
 while any(any('bake-world-buildings.ts' in a for a in (p.info['cmdline'] or [])) for p in psutil.process_iter(['cmdline']) if p.pid!=os.getpid()):time.sleep(5)
 z,x,y=map(int,region.split('/'));n=2**z;lon=(x+.5)/n*360-180;lat=math.degrees(math.atan(math.sinh(math.pi*(1-2*(y+.5)/n))))
 if shutil.disk_usage(paths.buildings).free<10_000_000_000:raise OSError('Building storage reserve')
 with (SOURCE/'building-rebake.log').open('a',encoding='utf-8') as log:
  process=subprocess.run([paths.bun,'tools/bake-world-buildings.ts',str(lon),str(lat),'0','--refresh-ground'],cwd=APP,env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
 row={'region':region,'exitCode':process.returncode}
 report=paths.catalog/'last-bake-report.json'
 if report.exists():
  saved=SOURCE/('rebake-'+region.replace('/','-')+'.json');shutil.copyfile(report,saved);row['report']=str(saved)
 rows.append(row);checkpoint('running')
 if process.returncode not in (0,2):checkpoint('failed');raise SystemExit(process.returncode)
paths.publish_catalog()
checkpoint('finished')
