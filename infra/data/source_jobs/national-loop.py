"""Local completion loop for the already authorized national terrain job."""
import source_job_paths as sjp
import argparse
import json
import math
import msvcrt
import os
from pathlib import Path
import subprocess
import sys
import time
import psutil

ROOT = Path(str(sjp.NGII_DEM_ROOT))
INDEX = Path(str(sjp.INDEX_STATE_ROOT))
AGENT = Path(str(sjp.AGENT_ROOT / 'SiteContextAgent'))
SCRIPT = AGENT/'scripts/build_national_dem.py'
STATUS = ROOT/'national-loop-status.json'

def read(path):
    try: return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError): return {}

def write(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)

def builders():
    found = []
    for proc in psutil.process_iter(['pid','cmdline']):
        argv = proc.info['cmdline'] or []
        if any(Path(a).name == 'build_national_dem.py' for a in argv) and '--output' in argv:
            out = Path(argv[argv.index('--output')+1]).resolve()
            if out == ROOT.resolve(): found.append(proc)
    return found

def validate(progress):
    import numpy as np
    import rasterio
    from pyproj import Transformer
    signature = progress['source_signature']
    to = Transformer.from_crs(4326,5186,always_xy=True)
    bounds = to.transform_bounds(124.6,33.1,132,38.65)
    expected = {(x,y) for x in range(math.floor(bounds[0]/10000)*10000,math.ceil(bounds[2]/10000)*10000,10000)
                      for y in range(math.floor(bounds[1]/10000)*10000,math.ceil(bounds[3]/10000)*10000,10000)}
    errors, checked, counts = [], 0, {}
    for x,y in sorted(expected):
        path = ROOT/'national-receipts'/f'zznational_{x}_{y}.json'
        row = read(path)
        try:
            assert row.get('signature') == signature, 'source signature mismatch'
            assert row.get('block') == [x,y], 'block mismatch'
            status = row.get('status')
            assert status in ('ok','empty','no cells'), 'missing completion receipt'
            counts[status] = counts.get(status,0)+1
            if status == 'ok':
                with rasterio.open(ROOT/'blocks'/f'{path.stem}.tif') as src:
                    assert src.crs.to_epsg() == 5186 and src.res == (5,5), 'CRS/resolution mismatch'
                    assert src.shape == (2000,2000), 'raster dimensions mismatch'
                    assert tuple(src.bounds) == (x,y,x+10000,y+10000), 'raster bounds mismatch'
                    data = src.read(1,masked=True)
                    assert int(data.count()) == row['valid_cells'], 'valid-cell count mismatch'
                    assert np.isfinite(data.compressed()).all(), 'nonfinite elevation'
                checked += 1
        except Exception as exc:
            errors.append({'block':[x,y],'receipt':str(path),'error':str(exc)})
    report = dict(at=time.time(),expected=len(expected),checked_rasters=checked,counts=counts,errors=errors,
                  scope='Raster integrity and source receipts; not exhaustive land coverage or visual QA')
    write(ROOT/'national-validation.json',report)
    return report

def probe():
    with (ROOT/'national-loop-probes.log').open('a',encoding='utf-8') as log:
        result = subprocess.run([sys.executable,str(sjp.job_script('probe-national-service.py'))],stdout=log,stderr=log,
                                timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
    rows = read(INDEX/'national-service-probes-20261023.json') if result.returncode == 0 else []
    return {'at':time.time(),'locations':len(rows),'terrain_ok':sum(r.get('terrain',{}).get('status')==200 for r in rows),
            'road_geometry_ok':sum(r.get('roads',{}).get('response',{}).get('status')=='ok' for r in rows),
            'scope':'21 sample locations; missing evidence is not replaced by invented data'}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--once',action='store_true');args=ap.parse_args()
    lock=(ROOT/'national-loop.lock').open('a+b');lock.seek(0)
    if os.fstat(lock.fileno()).st_size == 0: lock.write(b'0');lock.flush()
    lock.seek(0)
    try: msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    except OSError: raise SystemExit('National loop already running')
    (ROOT/'national-loop.pid').write_text(str(os.getpid()))
    restarts=read(STATUS).get('restarts',0)
    last_probe=0; probe_result={}; subprocesses=[]
    while True:
        for proc in subprocesses: proc.poll()
        progress=read(ROOT/'national-progress.json'); active=builders()
        state={'at':time.time(),'loop_pid':os.getpid(),'builder_pids':[p.pid for p in active],
               'restarts':restarts,'progress':progress,'state':'monitoring','service_probe':probe_result}
        if len(active)>1:
            state['state']='duplicate_writers_detected';write(STATUS,state);raise SystemExit(2)
        if not active and progress.get('state')=='complete':
            state['state']='validating';write(STATUS,state)
            report=validate(progress)
            if not report['errors']:
                probe_result=probe();state.update(state='conversion_validated',service_probe=probe_result,
                    validation=report,remaining='Full national visual/land-coverage QA and load-time verification remain separate')
                write(STATUS,state);print(json.dumps(state),flush=True);return
            # Retain invalid evidence while allowing only failed blocks to be regenerated.
            if restarts < 3:
                for issue in report['errors']:
                    path=Path(issue['receipt'])
                    if path.exists(): path.rename(path.with_suffix(f'.invalid-{time.time_ns()}'))
        if not active:
            if restarts>=3:
                state['state']='needs_intervention';write(STATUS,state);raise SystemExit(3)
            source_root=Path(str(sjp.SOURCE_DATA_ROOT / 'raw/ngii_map/b020/_전국'))
            source=next(p for p in source_root.iterdir() if (p/'N3P_F0020000.shp').is_file())
            if psutil.disk_usage(str(ROOT)).free < 5*1024**3:
                state['state']='insufficient_disk';write(STATUS,state);raise SystemExit(4)
            with (ROOT/'national-run.log').open('a') as out,(ROOT/'national-run.err').open('a') as err:
                proc=subprocess.Popen([sys.executable,'-u','-X','utf8',str(SCRIPT),'--source',str(source),
                    '--output',str(ROOT),'--workers','4'],cwd=AGENT,stdout=out,stderr=err,
                    creationflags=subprocess.CREATE_NO_WINDOW)
            subprocesses.append(proc);(ROOT/'national-run.pid').write_text(str(proc.pid));restarts+=1
            state.update(restarts=restarts,builder_pids=[proc.pid],state='resumed')
        if time.time()-last_probe>=600:
            try: probe_result=probe()
            except Exception as exc: probe_result={'at':time.time(),'error':str(exc)}
            last_probe=time.time();state['service_probe']=probe_result
        state['at']=time.time();write(STATUS,state)
        print('NATIONAL_LOOP_TICK '+json.dumps(state),flush=True)
        if args.once:return
        time.sleep(30)

if __name__=='__main__':main()
