"""Durable sequential 16-region geometry migration queue; never activates service releases."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from paths import DataPaths
from release_store import atomic_json
from migrate_building_geometry import building_lock

REVISION = 'footprint-holes-obb-v3'


def catalog_inventory(document):
    rows = {}
    for row in document['regions']:
        if row.get('z') != 14 or any(type(row.get(axis)) is not int or not 0 <= row[axis] < 16384 for axis in ('x', 'y')):
            raise ValueError('Invalid catalog coordinate')
        key = f"14/{row['x']}/{row['y']}"
        if key in rows:
            raise ValueError('Duplicate catalog coordinate: ' + key)
        rows[key] = row
    return rows


def pending_regions(plan, document):
    if document.get('source') != plan['source']:
        raise ValueError('Catalog source changed during geometry queue')
    rows = catalog_inventory(document)
    if set(rows) != set(plan['allCoordinates']):
        raise ValueError('Catalog coordinate coverage changed during geometry queue')
    return [key for key in plan['targets'] if rows[key].get('meshRevision') != REVISION]


def run(args):
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, NGII_DEM_ROOT=str(args.dem_root.resolve()))
    paths = DataPaths.from_env(env)
    catalog_path = paths.catalog / 'catalog.json'
    status_path = work / 'status.json'
    # A separate work-directory lock prevents duplicate queue supervisors. The launcher holds the real DEM writer lock per batch.
    with building_lock(work):
        raw = catalog_path.read_bytes()
        current = json.loads(raw)
        plan_path = work / 'plan.json'
        if plan_path.exists():
            plan = json.loads(plan_path.read_text(encoding='utf-8'))
        else:
            rows = catalog_inventory(current)
            plan = {'revision': REVISION, 'source': current['source'], 'baselineCatalogSHA256': hashlib.sha256(raw).hexdigest(),
                    'createdAt': time.time(), 'allCoordinates': list(rows),
                    'targets': [key for key, row in rows.items() if row.get('meshRevision') != REVISION],
                    'alreadyV3': sum(row.get('meshRevision') == REVISION for row in rows.values())}
            (work / 'catalog-before.json').write_bytes(raw)
            atomic_json(plan_path, plan)
        if plan['revision'] != REVISION:
            raise ValueError('Queue revision changed; use a new work directory')
        batch = max([int(p.name.split('-')[1]) for p in work.glob('batch-*') if p.is_dir() and p.name.split('-')[-1].isdigit()] or [0])
        state = {'state': 'running', 'pid': os.getpid(), 'revision': REVISION, 'startedAt': time.time(),
                 'baselineTargets': len(plan['targets']), 'alreadyV3': plan['alreadyV3'], 'activated': False}
        try:
            while True:
                raw = catalog_path.read_bytes()
                current = json.loads(raw)
                remaining = pending_regions(plan, current)
                state.update(heartbeatAt=time.time(), remaining=len(remaining), migrated=len(plan['targets'])-len(remaining),
                             catalogSHA256=hashlib.sha256(raw).hexdigest(), freeBytes=shutil.disk_usage(paths.buildings).free)
                if not remaining:
                    state.update(state='completed', finishedAt=time.time(), childPid=None)
                    atomic_json(status_path, state)
                    return state
                if (work / 'STOP').exists():
                    state.update(state='stopped', childPid=None)
                    atomic_json(status_path, state)
                    return state
                if state['freeBytes'] < args.reserve_bytes:
                    raise OSError('Geometry queue storage reserve reached')
                batch += 1
                folder = work / f'batch-{batch:06d}'
                folder.mkdir()
                selected = remaining[:16]
                atomic_json(folder / 'regions.json', selected)
                state.update(state='running', batch=batch, batchRegions=selected, batchStartedAt=time.time())
                atomic_json(status_path, state)
                command = [paths.python, str(Path(__file__).with_name('migrate_building_geometry.py')),
                           '--dem-root', str(paths.dem), '--regions-file', str(folder/'regions.json'),
                           '--limit', '16', '--resume', '--reserve-bytes', str(args.reserve_bytes)]
                with (folder / 'run.log').open('w', encoding='utf-8') as log:
                    child = subprocess.Popen(command, cwd=paths.editor, env=env, stdout=log, stderr=subprocess.STDOUT,
                                             creationflags=subprocess.CREATE_NO_WINDOW)
                    state['childPid'] = child.pid
                    atomic_json(status_path, state)
                    try:
                        while True:
                            try:
                                code = child.wait(timeout=10)
                                break
                            except subprocess.TimeoutExpired:
                                state.update(heartbeatAt=time.time(), freeBytes=shutil.disk_usage(paths.buildings).free)
                                atomic_json(status_path, state)
                    finally:
                        if child.poll() is None:
                            # The launcher terminates its writer on interruption; a supervisor must not drop its own lock and leave another writer behind.
                            child.wait()
                latest = paths.catalog / 'last-geometry-migration.json'
                if latest.exists() and latest.stat().st_mtime >= state['batchStartedAt']:
                    report = json.loads(latest.read_text(encoding='utf-8'))
                    if report.get('selected') == selected:
                        shutil.copyfile(latest, folder / 'report.json')
                after = catalog_path.read_bytes()
                remaining_after = pending_regions(plan, json.loads(after))
                receipt = {'exitCode': code, 'catalogBeforeSHA256': state['catalogSHA256'], 'catalogAfterSHA256': hashlib.sha256(after).hexdigest(),
                           'remainingBefore': len(remaining), 'remainingAfter': len(remaining_after), 'finishedAt': time.time()}
                atomic_json(folder / 'receipt.json', receipt)
                state.update(childPid=None, remaining=len(remaining_after), migrated=len(plan['targets'])-len(remaining_after),
                             catalogSHA256=receipt['catalogAfterSHA256'])
                if code:
                    state['errorLog'] = str(folder / 'run.log')
                    raise RuntimeError(f'Batch {batch} failed with exit code {code}; no later batches started')
                if len(remaining_after) >= len(remaining):
                    raise RuntimeError('Batch made no progress; refusing an infinite loop')
        except BaseException as error:
            state.update(state='failed', error=str(error), heartbeatAt=time.time(), childPid=None)
            atomic_json(status_path, state)
            raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dem-root', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--reserve-bytes', type=int, default=20_000_000_000)
    arguments = parser.parse_args()
    if arguments.reserve_bytes < 0:
        parser.error('reserve-bytes must be nonnegative')
    print(json.dumps(run(arguments)))
