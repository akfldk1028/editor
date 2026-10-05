"""One OS-locked worker per storage directory; reads never start execution."""
import argparse
import json
import time

from filelock import FileLock, Timeout

from .artifacts import _linked
from .execution import ExecutionService
from .execution_store import digest
from .optimization.service import compute


def run_once(service,compute_fn=compute):
    service.store.safe()
    lock_path=service.store.path.with_suffix('.worker.lock')
    lock_path.parent.mkdir(parents=True,exist_ok=True)
    if _linked(lock_path):raise ValueError('Linked worker lock is unsupported')
    try:
        with FileLock(str(lock_path),timeout=0):
            # The OS lock is released on process death, so a prior running row is interrupted.
            service.store.recover()
            claim=service.store.claim()
            if claim is None:return False
            attempt,token=claim['attempt_id'],claim['token']
            try:
                if digest(claim['prepared'])!=claim['prepared_sha']:raise ValueError('Prepared specification checksum mismatch')
                def event(value):
                    if value['type'] not in ('computed','cancelled'):
                        service.store.event(attempt,token,value)
                result=compute_fn(json.loads(claim['prepared']),seed=int(claim['seed']),
                    cancelled=lambda:service.store.cancelled(attempt,token),on_event=event)
                service.store.finish(attempt,token,result=result)
            except Exception as error:
                service.store.finish(attempt,token,error=type(error).__name__)
            return True
    except Timeout:
        return False


def main():
    parser=argparse.ArgumentParser(description='Run the native additive execution worker')
    parser.add_argument('--storage-directory',required=True)
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args()
    service=ExecutionService(args.storage_directory)
    while True:
        worked=run_once(service)
        if args.once:return
        if not worked:time.sleep(0.5)


if __name__=='__main__':main()
