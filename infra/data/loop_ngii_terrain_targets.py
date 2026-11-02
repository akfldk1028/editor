"""One durable bounded worker; source-supported precision jobs lead the frozen cohort."""
import argparse
import faulthandler
import json
import os
import shutil
from pathlib import Path
import sys
import time
from bake_ngii_terrain_targets import run
from ngii_terrain_candidate import packed, reserve, sha


def atomic(path, value):
    temporary=path.with_suffix('.next');temporary.write_bytes(packed(value));temporary.replace(path)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan',type=Path,required=True);p.add_argument('--priority',type=Path,required=True)
    p.add_argument('--supported-keys',type=Path,required=True);p.add_argument('--limit',type=int,default=16)
    a=p.parse_args();root=a.plan.parent;state_path=root/'queue-progress.json'
    lock=(root/'queue.lock').open('a+b')
    if sys.platform=='win32':
        import msvcrt
        lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    plan=json.loads(a.plan.read_text());priority=json.loads(a.priority.read_text())
    supported={row['key'] for row in json.loads(a.supported_keys.read_text())}
    order=sorted(range(len(priority['jobs'])),key=lambda i:(-len(supported.intersection(priority['jobs'][i]['targetKeys'])),-priority['jobs'][i]['targetCount'],i))
    state=json.loads(state_path.read_text()) if state_path.exists() else {'candidateId':plan['candidateId'],
        'cohortSHA256':priority['sha256'],'supportedKeysSHA256':sha(a.supported_keys.read_bytes()),'results':{},'cohortCount':priority['count'],'jobsTotal':len(order)}
    if (state['candidateId'],state['cohortSHA256'],state['supportedKeysSHA256'])!=(plan['candidateId'],priority['sha256'],sha(a.supported_keys.read_bytes())):
        raise ValueError('Queue inputs changed')
    for receipt in state['results'].values():
        if sha(Path(receipt['path']).read_bytes())!=receipt['sha256']:
            raise ValueError('Completed result receipt changed')
    completed=0
    def checkpoint(status,**extra):
        if status=='running':state.pop('error',None)
        state.update(state=status,pid=os.getpid(),updatedAt=time.time(),**extra)
        state['jobsCompleted']=len(state['results'])
        state['targetKeysChecked']=sum(v['targetCount'] for v in state['results'].values())
        state['filledKeys']=sum(v['filled'] for v in state['results'].values())
        stage=Path(plan.get('stageRoot',root/'stage'))
        state['storage']={'freeBytes':shutil.disk_usage(root).free,'reserveBytes':20*1024**3,
                          'stageBytes':sum(p.stat().st_size for p in stage.rglob('*') if p.is_file()) if stage.exists() else 0,
                          'stageRoot':str(stage),'automaticDeletion':False}
        atomic(state_path,state)
    checkpoint('running')
    trace=(root/'worker-stack.log').open('a')
    # CPython gh-140815: asynchronous frame dumps can crash older 3.13 builds.
    # job-phase.json provides progress without walking another thread's frames.
    had_fault_handler=faulthandler.is_enabled()
    if not had_fault_handler:faulthandler.enable(file=trace,all_threads=False)
    try:
        for index in order:
            if str(index) in state['results']:continue
            if completed>=a.limit:break
            reserve(root)
            job=priority['jobs'][index]
            checkpoint('running',currentIndex=index,currentCell=job['cell'],currentTargetCount=job['targetCount'],currentKnownPrecisionKeys=len(supported.intersection(job['targetKeys'])))
            run(a.plan,a.priority,index)
            result_path=root/'target-patches'/('-'.join(map(str,job['cell'])))/'result.json'
            result=json.loads(result_path.read_text())
            if result['cohortSHA256']!=priority['sha256'] or result['candidateId']!=plan['candidateId']:raise ValueError('Result receipt mismatch')
            state['results'][str(index)]={'targetCount':result['targetCount'],'filled':len(result['filledKeys']),
                'unfilled':len(result['unfilledKeys']),'path':str(result_path),'sha256':sha(result_path.read_bytes())}
            completed+=1;checkpoint('running');print(json.dumps(state['results'][str(index)]),flush=True)
        checkpoint('complete' if len(state['results'])==len(order) else 'batch-complete',currentIndex=None)
    except Exception as error:
        storage_error='storage reserve' in str(error).lower() or getattr(error,'errno',None)==28
        checkpoint('needs_storage' if storage_error else 'blocked',error=str(error));raise
    finally:
        if not had_fault_handler:faulthandler.disable()
        trace.close()
        lock.close()


if __name__=='__main__':main()
