"""Finish the already authorized package batch, then publish and verify supported ground."""
import source_job_paths as sjp
import json, msvcrt, os, subprocess, sys, time
from pathlib import Path
import psutil

ROOT = Path(str(sjp.NGII_ORIGINAL_ROOT))
STATUS = ROOT / 'batch-finish-status.json'

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def write(state, **extra):
    temp = STATUS.with_suffix('.tmp')
    temp.write_text(json.dumps(dict(pid=os.getpid(), at=time.time(), state=state, **extra)), encoding='utf-8')
    for attempt in range(30):
        try:
            temp.replace(STATUS)
            return
        except PermissionError:
            if attempt == 29:
                raise
            time.sleep(.1)

def wait_for(filename, script, terminal):
    while True:
        data = read(ROOT / filename)
        if data['state'] in terminal:
            return data
        try:
            alive = any(script in arg for arg in psutil.Process(data['pid']).cmdline())
        except (psutil.Error, KeyError):
            alive = False
        if not alive:
            raise RuntimeError('Upstream stopped: ' + script)
        write('waiting', upstream=filename, upstreamState=data['state'])
        time.sleep(10)

def run(script):
    write('running', step=script)
    with (ROOT / 'batch-finish.log').open('a', encoding='utf-8') as log:
        subprocess.run([sys.executable, str(sjp.job_script(script))], stdout=log, stderr=log,
                       check=True, creationflags=subprocess.CREATE_NO_WINDOW)

def main():
    lock = (ROOT / 'batch-finish.lock').open('a+b')
    lock.write(b'0'); lock.flush(); lock.seek(0)
    while True:
        try:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            break
        except OSError:
            time.sleep(5)
    downloads = wait_for('download-status.json', 'download-ngii-packages.py', {'finished', 'finished_with_failures', 'finished_with_metadata_size_exceptions'})
    wait_for('terrain-stage-status.json', 'stage-ngii-dxf-ground.py', {'finished'})
    wait_for('national-partial-rebake-status.json', 'rebuild-national-partial-ground.py', {'finished', 'finished_with_ground_gaps'})
    before = read(ROOT / 'terrain-install-receipt.json')['verifiedKeys']
    run('install-ngii-package-ground.py')
    after = read(ROOT / 'terrain-install-receipt.json')['verifiedKeys']
    if set(after) - set(before):
        run('rebake-ngii-package-regions.py')
    run('verify-ngii-package-publication.py')
    proof = read(ROOT / 'building-publication-check.json')
    if proof['remainingRepairedButNotPublishedKeys']:
        raise RuntimeError('Repaired ground records missing from published buildings')
    run('build-ngii-sheet-ledger.py')
    run('audit-ngii-package-coverage.py')
    failures = sum(row.get('state') == 'failed' for row in downloads.get('results', []))
    write('batch_finished_with_source_gaps', downloadedFiles=downloads['finishedFiles'],
          downloadFailures=failures, repairedRecords=len(after),
          limitation='This completes available package processing, not national precise ground coverage.')

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        write('failed', errorType=type(error).__name__, reason=str(error))
        raise
