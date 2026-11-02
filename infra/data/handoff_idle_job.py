"""Replace one identified legacy loop only at a boundary with no running child jobs."""
import argparse,os,subprocess,sys,time
from pathlib import Path
import psutil
from release_store import atomic_json

def matches(process,created,script):
    return abs(process.create_time()-created)<.01 and any(Path(arg)==script for arg in process.cmdline())

def run(pid,created,script,replacement,root):
    status=root/'management/job-handoffs'/f'{pid}.json'
    status.parent.mkdir(parents=True,exist_ok=True)
    while True:
        try:process=psutil.Process(pid)
        except psutil.NoSuchProcess:
            atomic_json(status,{'state':'target_already_exited','oldPid':pid});return
        if not matches(process,created,script):raise ValueError('Process identity changed; handoff refused')
        if process.status()==psutil.STATUS_STOPPED:
            atomic_json(status,{'state':'waiting_for_operator_resume','oldPid':pid});time.sleep(10);continue
        suspended=False
        try:
            # Suspend only the coordinator during inspection, never its workers.
            # This closes the race between observing no children and terminating.
            process.suspend();suspended=True
            children=[child for child in process.children(recursive=True) if child.is_running()]
            if children:
                atomic_json(status,{'state':'waiting_for_children','oldPid':pid,'children':len(children),'at':time.time()})
            else:
                process.terminate();process.wait(timeout=15);suspended=False
                log=root/'management/job-handoffs'/f'{pid}-replacement.log'
                env=os.environ.copy();env['DATA_ROOT']=str(root)
                try:
                    with log.open('ab') as output:
                        child=subprocess.Popen([sys.executable,'-u','-X','utf8',str(replacement)],cwd=str(replacement.parent),env=env,stdout=output,stderr=output,
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                except Exception as error:
                    atomic_json(status,{'state':'replacement_failed','oldPid':pid,'errorType':type(error).__name__});raise
                atomic_json(status,{'state':'restarted','oldPid':pid,'newPid':child.pid,'script':str(replacement),'at':time.time()});return
        finally:
            if suspended:
                try:process.resume()
                except psutil.NoSuchProcess:pass
        time.sleep(10)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--pid',type=int,required=True);p.add_argument('--created',type=float,required=True)
    p.add_argument('--script',type=Path,required=True);p.add_argument('--replacement',type=Path,required=True);p.add_argument('--data-root',type=Path,required=True);a=p.parse_args()
    if not a.replacement.is_file():raise FileNotFoundError('Managed replacement script missing')
    run(a.pid,a.created,a.script,a.replacement,a.data_root)
