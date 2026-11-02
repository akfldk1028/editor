"""Periodically refresh available sources and process verified local inputs."""
import source_job_paths as sjp
import hashlib, json, msvcrt, os, shutil, subprocess, sys, time
from pathlib import Path
import psutil

ROOT = Path(str(sjp.NGII_ORIGINAL_ROOT))
SCRIPTS = Path(__file__).parent
STATUS = ROOT / 'repair-loop-status.json'
STATE = ROOT / 'repair-loop-state.json'
BUSY = ('stage-ngii-dxf-ground.py', 'finish-ngii-package-batch.py',
        'rebake-ngii-package-regions.py', 'rebuild-national-partial-ground.py',
        'download-ngii-packages.py', 'install-ngii-package-ground.py')

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def write(path, value):
    tmp = path.with_suffix('.loop-tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    for attempt in range(30):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if attempt == 29:
                raise
            time.sleep(.1)

def checkpoint(state, **extra):
    write(STATUS, dict(pid=os.getpid(), at=time.time(), intervalSeconds=300,
                      state=state, **extra))

def fingerprint():
    paths = list((ROOT / 'files').glob('*.receipt.json')) + list(ROOT.glob('*-catalogue.json'))
    paths += [SCRIPTS / n for n in ('stage-ngii-dxf-ground.py', 'ngii_sheet_match.py', 'ngii_ngi.py',
              'install-ngii-package-ground.py', 'finish-ngii-package-batch.py')]
    h = hashlib.sha256()
    for path in sorted(paths):
        stat = path.stat()
        h.update(f'{path.name}:{stat.st_size}:{stat.st_mtime_ns}\n'.encode())
    return h.hexdigest()

def busy():
    for process in psutil.process_iter(['pid', 'cmdline']):
        if process.pid == os.getpid():
            continue
        if any(Path(arg).name in BUSY or Path(arg).name == 'bake-world-buildings.ts'
               for arg in process.info['cmdline'] or []):
            return True
    return False

def main():
    lock = (ROOT / 'repair-loop.lock').open('a+b')
    lock.write(b'0'); lock.flush(); lock.seek(0)
    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    state = read(STATE) if STATE.exists() else {}
    while True:
        try:
            signature = fingerprint()
            if busy():
                checkpoint('waiting_for_active_work')
            elif shutil.disk_usage(sjp.DATA_ROOT).free < 20_000_000_000 or shutil.disk_usage(sjp.NGII_DEM_ROOT).free < 15_000_000_000:
                checkpoint('needs_storage')
            elif state.get('completedSignature') == signature:
                checkpoint('searching_sources', repairedRecords=state.get('repairedRecords'))
                with (ROOT / 'repair-loop.log').open('a', encoding='utf-8') as log:
                    subprocess.run([sys.executable,str(SCRIPTS/'audit-ngii-live-gap-sources.py')],stdout=log,stderr=log,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
                audit=read(ROOT/'live-source-audit.json')
                checkpoint('new_sources_require_download' if audit['newPreciseSheets'] else 'no_new_downloadable_sources',
                           repairedRecords=state.get('repairedRecords'),newPreciseSheets=audit['newPreciseSheets'],
                           requestFailures=audit['requestFailures'],sourceRefreshSeconds=3600,
                           limitation='Search refresh is automatic; authenticated ordering and unavailable originals still require follow-up.')
            elif state.get('failedSignature') == signature and state.get('attempts', 0) >= 3:
                checkpoint('needs_intervention', reason=state.get('reason'))
            else:
                attempts = state.get('attempts', 0) + 1 if state.get('failedSignature') == signature else 1
                try:
                    for script in ('stage-ngii-dxf-ground.py', 'finish-ngii-package-batch.py'):
                        checkpoint('running', step=script, attempt=attempts)
                        with (ROOT / 'repair-loop.log').open('a', encoding='utf-8') as log:
                            subprocess.run([sys.executable, str(SCRIPTS / script)], stdout=log,
                                           stderr=log, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
                    proof = read(ROOT / 'building-publication-check.json')
                    if proof['remainingRepairedButNotPublishedKeys']:
                        raise RuntimeError('Repaired records not fully published')
                    state = dict(completedSignature=signature, repairedRecords=proof['repairedRecordsPublishedInBuildingTiles'])
                    write(STATE, state)
                    checkpoint('cycle_verified', **state)
                except Exception as error:
                    state.update(failedSignature=signature, attempts=attempts, reason=type(error).__name__)
                    write(STATE, state)
                    checkpoint('retry_pending', attempt=attempts, reason=type(error).__name__)
        except Exception as error:
            checkpoint('monitor_error', reason=type(error).__name__)
        time.sleep(300)

if __name__ == '__main__':
    main()
