"""Acquire one precise geometry variant plus matching metadata per missing sheet."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import threading
import time
import httpx
import source_job_paths as sjp

ROOT = Path(os.environ.get('NGII_EXPANSION_ROOT') or sjp.DATA_ROOT / 'management/national-source-expansion')
RESERVE = 20_000_000_000
local = threading.local()


def identity(name):
    match = re.search(r'(?:^|_)(\d{8,9})_(\d{4})_', name)
    return (match[1], int(match[2])) if match else None


def companion_key(name):
    stem=Path(name).stem
    match=re.search(r'(?:^|_)(\d{8,9}_\d{4}_.+)$',stem)
    return match[1] if match else stem


def choose_files(rows, precise, existing):
    choices = {}
    rank = {'.zip':0, '.dxf':1, '.ngi':2}
    metadata = {}
    for row in rows:
        if Path(row['name']).suffix.lower() in {'.xml','.nda','.xlsx','.xls'}:
            metadata.setdefault(companion_key(row['name']),[]).append(row)
    for row in rows:
        ident = identity(row['name']);ext = Path(row['name']).suffix.lower()
        if not ident or ident[0] not in precise or ident[0] in existing or ext not in rank:continue
        key = (-ident[1], rank[ext], int(row['bytes']))
        if ident[0] not in choices or key < choices[ident[0]][0]:choices[ident[0]]=(key,row)
    result=[]
    for _, row in choices.values():
        result.append(row)
        result.extend(metadata.get(companion_key(row['name']),[]))
    return result


def write(path, data):
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    for attempt in range(50):
        try:temp.replace(path);return
        except PermissionError:
            if attempt==49:raise
            time.sleep(.1)


def download(item):
    name=item['name'];expected=int(item['bytes']);dest=ROOT/'files'
    if Path(name).name!=name or expected<=0:return dict(name=name,state='invalid_manifest')
    target=dest/name;part=dest/(name+'.part');receipt=dest/(name+'.receipt.json')
    if target.exists() and receipt.exists():
        old=json.loads(receipt.read_text(encoding='utf-8'))
        if target.stat().st_size==expected and hashlib.sha256(target.read_bytes()).hexdigest()==old.get('sha256'):return old
    for attempt in range(3):
        try:
            if shutil.disk_usage(ROOT).free < RESERVE+2*expected:return dict(name=name,state='storage_reserve')
            if not hasattr(local,'client'):local.client=httpx.Client(timeout=90,trust_env=False,follow_redirects=True)
            with local.client.stream('GET',item['url']) as response:
                response.raise_for_status()
                if 'text/html' in response.headers.get('content-type',''):raise ValueError('HTML response')
                digest=hashlib.sha256();size=0
                with part.open('wb') as out:
                    for block in response.iter_bytes(1024*1024):
                        if shutil.disk_usage(ROOT).free < RESERVE:return dict(name=name,state='storage_reserve')
                        size+=len(block)
                        if size>expected:raise ValueError('Size exceeded')
                        out.write(block);digest.update(block)
            if size!=expected:raise ValueError('Size mismatch')
            part.replace(target)
            result=dict(name=name,state='size_and_sha_recorded',bytes=size,sha256=digest.hexdigest(),at=time.time())
            write(receipt,result);return result
        except Exception as error:
            if attempt==2:return dict(name=name,state='failed',errorType=type(error).__name__)
            time.sleep(attempt+1)


def main():
    import msvcrt
    (ROOT/'files').mkdir(exist_ok=True)
    lock=(ROOT/'selective-download.lock').open('a+b');lock.write(b'0');lock.flush();lock.seek(0)
    msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    existing=set()
    for p in (sjp.NGII_ORIGINAL_ROOT/'files').iterdir():
        if p.suffix.lower() in {'.zip','.dxf','.ngi'} and p.stat().st_size and identity(p.name):existing.add(identity(p.name)[0])
    results={};seen={};precise=set();loaded=set()
    for p in (ROOT/'files').glob('*.receipt.json'):
        r=json.loads(p.read_text(encoding='utf-8'));target=ROOT/'files'/r['name']
        if target.exists() and target.stat().st_size==r['bytes'] and hashlib.sha256(target.read_bytes()).hexdigest()==r['sha256']:results[r['name']]=r
    def save(state):
        verified=[r for r in results.values() if r['state']=='size_and_sha_recorded']
        write(ROOT/'download-status.json',dict(pid=os.getpid(),at=time.time(),state=state,
            knownManifestFiles=len(seen),verifiedFiles=len(verified),verifiedGeometryFiles=sum(Path(r['name']).suffix in {'.zip','.dxf','.ngi'} for r in verified),
            verifiedBytes=sum(r['bytes'] for r in verified),failedFiles=sum(r['state']=='failed' for r in results.values()),
            freeBytes=shutil.disk_usage(ROOT).free,reserveBytes=RESERVE,geometryValidated=False,
            results=list(results.values())))
    chosen=[];last_saved=None
    while True:
        pattern='[0-9][0-9][0-9][0-9][0-9]-manifest.json' if ROOT==sjp.DATA_ROOT/'management/national-source-expansion' else '*-manifest.json'
        new_manifests=False
        for p in ROOT.glob(pattern):
            if p.name in loaded:continue
            for item in json.loads(p.read_text(encoding='utf-8'))['files']:seen[item['name']]=item
            catalogue=p.with_name(p.name.replace('-manifest','-catalogue'))
            precise.update(str(r['sheet']) for r in json.loads(catalogue.read_text(encoding='utf-8')) if int(r.get('scale') or 999999)<=5000)
            loaded.add(p.name);new_manifests=True
        if new_manifests:chosen=choose_files(list(seen.values()),precise,existing)
        queue=[r for r in chosen if r['name'] not in results][:64]
        if queue:
            save('running')
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                for result in pool.map(download,queue):
                    results[result['name']]=result;save('running')
            last_saved=('running',len(results),len(seen))
            if any(r['state']=='storage_reserve' for r in results.values()):save('storage_reserve');return
        order=json.loads((ROOT/'batch-order-status.json').read_text(encoding='utf-8'))
        if not queue and order['state']=='finished':save('finished');return
        if not queue:
            if shutil.disk_usage(ROOT).free < RESERVE:save('storage_reserve');return
            wait_state='waiting_for_orders' if order['state']!='running' else 'running'
            sig=(wait_state,len(results),len(seen))
            if last_saved!=sig:
                save(wait_state);last_saved=sig
            time.sleep(5)


if __name__=='__main__':main()
