"""Backend-only storage/gap monitoring; no agent, browser or provider login required."""
import argparse,json,os,time
from pathlib import Path
from gap_registry import collect
from release_store import atomic_json
from storage_status import status

def check(root,originals,dem,source):
    gaps=collect(root,originals);registry=status(root,dem,source)
    value={'state':'ok','pid':os.getpid(),'checkedAt':time.time(),'activeRelease':registry['activeRelease'],'unclassified':registry['unclassifiedDirectories'],'gaps':gaps}
    atomic_json(root/'management/monitor-status.json',value);return value

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data-root',type=Path,required=True);p.add_argument('--ngii-originals',type=Path,required=True);p.add_argument('--dem-root',type=Path,required=True);p.add_argument('--source-data-root',type=Path,required=True)
    p.add_argument('--interval',type=int,default=300);p.add_argument('--once',action='store_true');a=p.parse_args()
    if a.interval<30:p.error('Minimum monitoring interval is 30 seconds')
    while True:
        try:print(json.dumps(check(a.data_root,a.ngii_originals,a.dem_root,a.source_data_root)),flush=True)
        except Exception as error:
            atomic_json(a.data_root/'management/monitor-status.json',{'state':'retry_pending','pid':os.getpid(),'checkedAt':time.time(),'errorType':type(error).__name__})
            if a.once:raise
        if a.once:break
        time.sleep(a.interval)
