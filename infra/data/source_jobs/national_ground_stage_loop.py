"""Continuously validate newly received original terrain, without activating releases."""
import argparse,hashlib,json,msvcrt,os,shutil,subprocess,sys,time
from pathlib import Path

def signature(root):
    files=sorted([*(root/'files').glob('*.receipt.json'),*root.glob('*-catalogue.json')])
    files += [Path(__file__).with_name(name) for name in ('stage-ngii-dxf-ground.py','ngii_stage_policy.py','ngii_sheet_match.py','ngii_ngi.py','ngii_dxf.py')]
    digest=hashlib.sha256()
    for path in files:
        stat=path.stat();digest.update(f'{path.name}:{stat.st_size}:{stat.st_mtime_ns}\n'.encode())
    return digest.hexdigest()

def save(path,value):
    temporary=path.with_suffix('.next.json')
    temporary.write_text(json.dumps(value,ensure_ascii=False),encoding='utf8')
    os.replace(temporary,path)

def stage_counts(root):
    report=root/'terrain-stage-status.json'
    if not report.exists():return {}
    rows=json.loads(report.read_text(encoding='utf8')).get('results',{}).values()
    counts={'stagedSources':0,'failedSources':0,'excludedSources':0}
    for row in rows:
        key='stagedSources' if row.get('state')=='staged' else 'failedSources' if row.get('state')=='failed' else 'excludedSources'
        counts[key]+=1
    return counts

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,action='append',required=True)
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--interval',type=int,default=300)
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args()
    if args.interval<10:parser.error('Interval must be at least 10 seconds')
    if any(not (root/'files').is_dir() for root in args.root):parser.error('Every source root must contain files/')
    args.work.mkdir(parents=True,exist_ok=True)
    lock=(args.work/'loop.lock').open('a+b');lock.seek(0)
    if not lock.read(1):lock.write(b'0');lock.flush()
    lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    state_path=args.work/'state.json'
    completed=json.loads(state_path.read_text(encoding='utf8')) if state_path.exists() else {}
    while True:
        rows=[]
        for root in args.root:
            root=root.resolve();key=str(root);fingerprint=signature(root)
            row={'root':key,'signature':fingerprint,'state':'unchanged'}
            if completed.get(key)!=fingerprint:
                if shutil.disk_usage(root).free<20_000_000_000:
                    row['state']='storage_reserve'
                else:
                    save(args.work/'status.json',{'pid':os.getpid(),'at':time.time(),'state':'staging','root':key,'activated':False})
                    with (args.work/'stage.log').open('a',encoding='utf8') as log:
                        result=subprocess.run([sys.executable,str(Path(__file__).with_name('stage-ngii-dxf-ground.py')),'--refine-existing','--once'],env=dict(os.environ,NGII_ORIGINAL_ROOT=key),stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
                    row.update(state='staged' if result.returncode==0 else 'retry_pending',exitCode=result.returncode)
                    if result.returncode==0:
                        completed[key]=fingerprint;save(state_path,completed)
            row.update(stage_counts(root))
            if row['state']=='staged' and row.get('failedSources'):row['state']='checked_with_failures'
            elif row['state']=='staged' and row.get('excludedSources'):row['state']='checked_with_source_exclusions'
            rows.append(row)
        save(args.work/'status.json',{'pid':os.getpid(),'at':time.time(),'state':'watching','roots':rows,'intervalSeconds':args.interval,'activated':False,'scope':'Validated source rasters only; building and terrain publication requires separate release checks'})
        if args.once:return
        time.sleep(args.interval)

if __name__=='__main__':main()
