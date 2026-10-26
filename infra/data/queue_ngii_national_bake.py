"""Bounded candidate-only coordinator. Never publishes or activates a national release.

Default --limit 16 is a capacity measurement batch, not nationwide completion.
--watch waits 60 seconds between source/storage polls. STOP in output prevents the
next subprocess; an in-progress bounded child is allowed to finish so immutable
assets are not interrupted halfway through writing. A failed partial candidate
needs operator review; this coordinator never deletes/replaces its files.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

RESERVE = 20 * 1024**3
RETRY_GROWTH = 256 * 1024**2


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic(path, value):
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(path)


@contextmanager
def writer_lock(folder):
    with (folder/'queue.lock').open('a+b') as stream:
        if stream.seek(0,2)==0:stream.write(b'0');stream.flush()
        stream.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield


def validate_reusable_inventory(regions, old_pin_path, binding, plan):
    previous=read(old_pin_path);inventory=read(regions)
    for key in ('snapshotSHA256','planFileSHA256'):
        if previous.get(key)!=binding[key]:raise ValueError('Reused inventory source binding mismatch')
    if previous.get('regionsSHA256')!=sha(regions):raise ValueError('Reused inventory SHA256 mismatch')
    rows=inventory.get('regions',[])
    if inventory.get('schema')!='ngii-canonical-regions-v1' or inventory.get('sourceComplete') is not True \
       or inventory.get('planSHA256')!=plan['planSHA256'] or inventory.get('sourceRows')!=plan['expectedRows'] \
       or inventory.get('regionCount')!=len(rows) or not rows \
       or len({r['region14'] for r in rows})!=len(rows) \
       or sum(r['buildings'] for r in rows)!=inventory.get('buildingCount') \
       or any(r['buildings']<1 or r['components']<r['buildings'] for r in rows):
        raise ValueError('Reused inventory coverage invalid')
    return previous['regionsSHA256']


def execute(command,cwd,log,on_started):
    flags=(subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS) if os.name=='nt' else 0
    with log.open('wb') as stream:
        process=subprocess.Popen(command,cwd=cwd,stdout=stream,stderr=subprocess.STDOUT,
                                 env={**os.environ,'NGII_PYTHON':command[0]} if command[0].lower().endswith(('python','python.exe')) else None,
                                 creationflags=flags)
        on_started(process.pid)
        return process.wait()


def coordinate(args, *, runner=execute, free=lambda path:shutil.disk_usage(path).free, sleep=time.sleep):
    output=Path(args.output).resolve();output.mkdir(parents=True,exist_ok=True)
    status_path=output/'queue-status.json';pin_path=output/'queue-inputs.json'
    editor=Path(args.editor_root).resolve();script=editor/'infra/data/ngii_canonical_snapshot.py'
    frontend=editor/'frontend/app/editor';snapshot=Path(args.snapshot).resolve();plan=Path(args.plan).resolve()
    regions=Path(args.regions).resolve();terrain=Path(args.terrain).resolve()
    if args.limit<1:raise ValueError('Positive bounded --limit required')
    if len(args.terrain_sha)!=64 or any(x not in '0123456789abcdef' for x in args.terrain_sha):raise ValueError('Invalid terrain SHA256')
    state={}
    def record(kind,**details):
        nonlocal state
        state={'schema':'ngii-national-bake-queue-v1','state':kind,'pid':os.getpid(),'childPID':None,
               'at':time.time(),'limit':args.limit,'candidateOnly':True,'activeNationalComplete':False,**details}
        atomic(status_path,state);return state
    def stopped():return (output/'STOP').exists()
    def invoke(command,phase):
        if stopped():return None
        log=output/(phase+'.log');record(phase,log=str(log))
        # All children inherit this explicit interpreter for the baker's source verification.
        old=os.environ.get('NGII_PYTHON');os.environ['NGII_PYTHON']=args.python
        try:return runner(command,str(frontend),log,lambda pid:record(phase,childPID=pid,log=str(log)))
        finally:
            if old is None:os.environ.pop('NGII_PYTHON',None)
            else:os.environ['NGII_PYTHON']=old
    with writer_lock(output):
        try:
            blocked=None
            if status_path.exists():
                previous=read(status_path)
                if previous.get('state')=='needs_storage':blocked=previous.get('blockedFreeBytes',previous.get('freeBytes',0))
            while True:
                if stopped():return record('stopped',note='No activation. Running bounded children finish before STOP is honored.')
                available=free(output)
                threshold=max(RESERVE,blocked+RETRY_GROWTH) if blocked is not None else RESERVE
                if available<threshold:
                    record('needs_storage',freeBytes=available,blockedFreeBytes=blocked if blocked is not None else available,reserveBytes=RESERVE,retryAtFreeBytes=threshold)
                    if not args.watch:return state
                    sleep(60);continue
                document=read(snapshot)
                if document.get('schema')!='ngii-canonical-snapshot-v1':raise ValueError('Invalid source snapshot')
                if document.get('complete') is not True:
                    record('waiting-source',snapshot=str(snapshot),freeBytes=available)
                    if not args.watch:return state
                    sleep(60);continue
                binding={'snapshotSHA256':sha(snapshot),'planFileSHA256':sha(plan),'terrainSHA256':args.terrain_sha,
                         'terrainPath':str(terrain),'regionsPath':str(regions),'output':str(output)}
                if pin_path.exists():
                    pin=read(pin_path)
                    if any(pin.get(k)!=v for k,v in binding.items()):raise ValueError('Coordinator candidate inputs changed')
                else:pin=None
                verify=[args.python,'-X','utf8',str(script),'verify','--snapshot',str(snapshot),'--plan',str(plan)]
                result=invoke(verify,'verifying-source')
                if result is None:return record('stopped')
                if result: return record('failed',phase='verifying-source',exitCode=result,error='See verifying-source.log')
                if not pin:
                    if regions.exists():
                        reuse=getattr(args,'reuse_regions_pin',None)
                        if not reuse:raise ValueError('Unbound region inventory requires --reuse-regions-pin')
                        validate_reusable_inventory(regions,reuse,binding,read(plan))
                    else:
                        regions.parent.mkdir(parents=True,exist_ok=True)
                        result=invoke([*verify[:4],'regions','--snapshot',str(snapshot),'--plan',str(plan),'--output',str(regions)],'inventory')
                        if result is None:return record('stopped')
                        if result:return record('failed',phase='inventory',exitCode=result,error='See inventory.log')
                    pin={**binding,'regionsSHA256':sha(regions)};atomic(pin_path,pin)
                elif sha(regions)!=pin['regionsSHA256']:raise ValueError('Pinned region inventory changed')
                if stopped():return record('stopped')
                command=[args.bun,str(frontend/'tools/bake-ngii-region.ts'),'--snapshot',str(snapshot),'--regions',str(regions),
                         '--source-plan',str(plan),'--terrain',str(terrain),'--terrain-sha256',args.terrain_sha,
                         '--output',str(output),'--limit',str(args.limit)]
                result=invoke(command,'baking')
                if result is None:return record('stopped')
                if result:
                    log=output/'baking.log'
                    with log.open('rb') as stream:stream.seek(max(0,log.stat().st_size-65536));tail=stream.read().decode('utf-8',errors='replace')
                    if '20GiB' in tail or 'free-space reserve' in tail:
                        blocked=free(output);record('needs_storage',freeBytes=blocked,blockedFreeBytes=blocked,reserveBytes=RESERVE,
                                                   retryAtFreeBytes=max(RESERVE,blocked+RETRY_GROWTH),exitCode=result,error='See baking.log; incomplete immutable folders require review')
                        if args.watch:sleep(60);continue
                        return state
                    return record('failed',phase='baking',exitCode=result,error='See baking.log; no automatic retry')
                return record('bounded-complete',freeBytes=free(output),regionsSHA256=pin['regionsSHA256'],
                              note='Only requested limit completed. No full-country, catalog, publication or activation claim.')
        except Exception as error:
            return record('failed',error=str(error),phase=state.get('state'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('snapshot','plan','terrain','terrain-sha','output','regions','bun','python'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--editor-root',default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument('--reuse-regions-pin',help='Prior coordinator queue-inputs.json binding the completed inventory')
    parser.add_argument('--watch',action='store_true');parser.add_argument('--limit',type=int,default=16)
    args=parser.parse_args()
    try:result=coordinate(args)
    except Exception as error:
        # Do not overwrite the live owner's status if acquisition of its lock failed.
        print(json.dumps({'state':'failed','pid':os.getpid(),'error':str(error),'candidateOnly':True}),flush=True);raise SystemExit(1)
    print(json.dumps(result),flush=True)
    if result['state']=='failed':raise SystemExit(1)


if __name__=='__main__':main()
