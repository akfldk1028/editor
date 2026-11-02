"""Keep journaled original acquisition alive without publishing terrain or repeating orders."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import psutil
import source_job_paths as sjp
from national_original_download import choose_files, identity

ROOT=sjp.DATA_ROOT/'management/national-source-expansion'
SCRIPTS=Path(__file__).parent


def should_resume_order(state):
    return state not in {'running','finished'}


def read(path):
    for attempt in range(30):
        try:return json.loads(path.read_text(encoding='utf-8'))
        except (PermissionError,json.JSONDecodeError):
            if attempt==29:raise
            time.sleep(.1)


def active_downloaders():
    found={}
    for process in psutil.process_iter(['pid','cmdline']):
        try:
            if any(Path(arg).name=='national_original_download.py' for arg in process.info['cmdline'] or []):
                folder=Path(process.environ().get('NGII_EXPANSION_ROOT') or ROOT)
                found[str(folder.resolve())]=process.pid
        except (psutil.NoSuchProcess,psutil.AccessDenied):continue
    return found


def fingerprint(root):
    digest=hashlib.sha256()
    for path in sorted(root.glob('*-manifest.json')):
        stat=path.stat();digest.update(f'{path.name}:{stat.st_size}:{stat.st_mtime_ns}'.encode())
    return digest.hexdigest()


def order_budget(roots):
    existing={identity(p.name)[0] for p in (sjp.NGII_ORIGINAL_ROOT/'files').iterdir()
              if p.suffix.lower() in {'.zip','.dxf','.ngi'} and identity(p.name)}
    pending=0;known=[]
    for root,_ in roots:
        files={};precise=set()
        sizes={entry.name:entry.stat().st_size for entry in os.scandir(root/'files') if entry.is_file()}
        pattern='[0-9][0-9][0-9][0-9][0-9]-manifest.json' if root==ROOT else '*-manifest.json'
        for path in root.glob(pattern):
            known.append(path.as_posix())
            for item in read(path)['files']:files[item['name']]=item
            for row in read(path.with_name(path.name.replace('-manifest','-catalogue'))):
                if int(row.get('scale') or 999999)<=5000:precise.add(str(row['sheet']))
        for item in choose_files(list(files.values()),precise,existing):
            target=root/'files'/item['name'];receipt=target.with_suffix(target.suffix+'.receipt.json')
            present=sizes.get(item['name'])==int(item['bytes']) and receipt.name in sizes
            if not present and item['name'] in sizes and receipt.name in sizes:
                try:present=sizes[item['name']]==read(receipt)['bytes']
                except (OSError,ValueError,KeyError):pass
            if not present:pending+=int(item['bytes'])
    value=dict(at=time.time(),pendingSelectedBytes=pending,knownManifests=known,roots=[str(r) for r,_ in roots],
        reserveBytes=20000000000,pendingWindowBytes=5000000000,
        policy='Pause new orders above pending window. A single in-flight package can exceed window; no following order until backlog drains.')
    temporary=ROOT/'order-budget.tmp';temporary.write_text(json.dumps(value),encoding='utf-8')
    for attempt in range(50):
        try:temporary.replace(ROOT/'order-budget.json');break
        except PermissionError:
            if attempt==49:raise
            time.sleep(.1)


def main():
    import msvcrt
    lock=(ROOT/'acquisition-supervisor.lock').open('a+b');lock.write(b'0');lock.flush();lock.seek(0)
    msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    state_path=ROOT/'acquisition-supervisor-state.json'
    state=read(state_path) if state_path.exists() else {}
    roots=[(ROOT,'package'),(ROOT/'individual-old-missing','individual'),(ROOT/'individual-critical-retry','individual')]
    while True:
        results=[];active=active_downloaders()
        try:order_budget(roots)
        except Exception as error:results.append(dict(state='budget_refresh_failed',errorType=type(error).__name__))
        for root,mode in roots:
            if not (root/'batch-order-status.json').exists():continue
            try:
                order=read(root/'batch-order-status.json')
                if should_resume_order(order['state']):
                    call=subprocess.run(['node',str(SCRIPTS/'national-original-control.cjs'),mode,str(root)],
                        capture_output=True,text=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
                    order_action=json.loads(call.stdout) if call.returncode==0 else {'state':'browser_control_unavailable'}
                else:order_action={'state':order['state']}
                signature=fingerprint(root);key=str(root.resolve());pid=active.get(key)
                download=read(root/'download-status.json') if (root/'download-status.json').exists() else {}
                if not pid and (state.get(key)!=signature or order_action['state'] in {'running','started'} or download.get('state')!='finished'):
                    if shutil.disk_usage(ROOT).free<20_100_000_000:
                        results.append(dict(root=key,state='storage_reserve'));continue
                    env={**os.environ,'NGII_EXPANSION_ROOT':str(root)}
                    with (root/'download.stdout.log').open('a',encoding='utf-8') as out,(root/'download.stderr.log').open('a',encoding='utf-8') as err:
                        process=subprocess.Popen([sys.executable,str(SCRIPTS/'national_original_download.py')],env=env,
                            stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
                    pid=process.pid;state[key]=signature
                elif pid:state[key]=signature
                results.append(dict(root=key,order=order_action,downloadPid=pid))
            except Exception as error:results.append(dict(root=str(root),state='retry_next_cycle',errorType=type(error).__name__))
        if time.time()-state.get('_lastReconciledAt',0)>300:
            with (ROOT/'receipt-reconciliation.log').open('a',encoding='utf-8') as log:
                subprocess.Popen([sys.executable,str(SCRIPTS/'reconcile-national-original-receipts.py')],
                    stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
            state['_lastReconciledAt']=time.time()
        state_path.write_text(json.dumps(state,indent=2),encoding='utf-8')
        report=dict(pid=os.getpid(),at=time.time(),state='monitoring',intervalSeconds=60,roots=results,
            policy='Resume only never-attempted order targets. Existing uncertain journals require provider history reconciliation; no terrain publication.')
        (ROOT/'acquisition-supervisor-status.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        time.sleep(60)


if __name__=='__main__':main()
