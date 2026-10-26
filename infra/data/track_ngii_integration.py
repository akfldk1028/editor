"""Read-only integration status; candidates are never treated as published assets."""
import argparse
from contextlib import closing
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time

import httpx
import psutil


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def filled_union(results, cohort):
    keys = set()
    rejected = 0
    for result in results:
        if not cohort or result.get('cohortSHA256') != cohort:
            rejected += 1
        else:
            keys.update(result.get('filledKeys', []))
    return {'filledKeysUnion': len(keys), 'rejectedCohortResults': rejected}


def database_status(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        expected, processed, complete, sources = db.execute("SELECT sum(expected_rows),sum(next_row),sum(status='complete'),count(*) FROM sources").fetchone()
        issues = db.execute('SELECT count(*) FROM issues').fetchone()[0]
    return {'expectedRows': expected or 0, 'processedRows': processed or 0, 'completeSources': complete or 0, 'sources': sources, 'issues': issues}


def worker_matches(args, database, cwd):
    if not any(Path(a).name == 'ingest_ngii_buildings.py' for a in args) or 'run' not in args or '--output' not in args:
        return False
    try:
        output = Path(args[args.index('--output') + 1])
        return (cwd / output / 'buildings.sqlite').resolve() == database.resolve()
    except (IndexError, OSError):
        return False


def workers(database):
    found = []
    for process in psutil.process_iter(['pid', 'cmdline']):
        try:
            if worker_matches(process.info['cmdline'] or [], database, Path(process.cwd())):
                found.append({'pid': process.pid, 'createdAt': process.create_time()})
        except (psutil.Error, OSError):
            pass
    return found


def terrain_worker_matches(args, candidate, cwd):
    if not any(Path(a).name == 'loop_ngii_terrain_targets.py' for a in args) or '--plan' not in args:
        return False
    try:
        return (cwd / args[args.index('--plan') + 1]).resolve() == (candidate / 'plan.json').resolve()
    except (IndexError, OSError):
        return False


def terrain_alerts(state):
    alerts = []
    if state.get('state') in ('failed', 'needs_storage'):
        alerts.append('terrain_' + state['state'])
    if not state.get('workerAlive'):
        if state.get('jobsCompleted', 0) < state.get('jobsTotal', 0):
            alerts.append('terrain_work_remaining_worker_missing')
        elif state.get('state') == 'running':
            alerts.append('terrain_running_worker_missing')
    return alerts


def terrain_status(paths, active):
    snapshots, results, errors = [], [], []
    cohort = None
    for path in paths:
        try:
            state = read(path / 'queue-progress.json')
            cohort = cohort or state.get('cohortSHA256')
            summary = {k: v for k, v in state.items() if k != 'results'}
            summary['healthPrimary'] = path.resolve() == active.resolve()
            summary['workerAlive'] = False
            try:
                process = psutil.Process(int(state['pid']))
                summary['workerAlive'] = terrain_worker_matches(process.cmdline(), path, Path(process.cwd()))
                if summary['workerAlive']:
                    summary['workerCreatedAt'] = process.create_time()
            except (psutil.Error, OSError, KeyError, TypeError, ValueError):
                pass
            snapshots.append(summary)
            for entry in state.get('results', {}).values():
                raw = Path(entry['path']).read_bytes()
                if hashlib.sha256(raw).hexdigest() != entry['sha256']:
                    raise ValueError('Candidate result SHA mismatch: ' + entry['path'])
                result = json.loads(raw)
                if result.get('cohortSHA256') != state.get('cohortSHA256'):
                    raise ValueError('Result/queue cohort mismatch')
                results.append(result)
        except (OSError, ValueError, KeyError) as exc:
            errors.append(str(exc))
    primary = next((s for s in snapshots if s['healthPrimary']), None)
    alerts = terrain_alerts(primary) if primary else ['terrain_active_candidate_unreadable']
    return {'publicationStatus': 'candidate-only not published', 'activeCandidate': str(active), 'alerts': alerts, 'cohortSHA256': cohort, **filled_union(results, cohort), 'candidates': snapshots, 'errors': errors}


def range_probe(client, url):
    with client.stream('GET', url, headers={'Range': 'bytes=0-126'}) as response:
        return {'url': url, 'status': response.status_code, 'contentRange': response.headers.get('content-range'), 'range206': response.status_code == 206 and response.headers.get('content-range', '').startswith('bytes 0-126/')}


def building_url(url):
    return '/api/map-data/' + url.lstrip('/')


def snapshot(args):
    row = {'at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'pid': os.getpid(), 'intervalSeconds': args.interval, 'alerts': [], 'browserPerformanceMeasured': False, 'automaticAgentWake': False}
    for name, action in [
        ('canonical', lambda: {**database_status(args.database), 'database': str(args.database), 'workers': workers(args.database)}),
        ('terrainCandidates', lambda: terrain_status(args.candidate, args.active_candidate)),
    ]:
        try:
            row[name] = action()
        except Exception as exc:
            row[name] = {'error': str(exc)}
            row['alerts'].append(name + '_read_failed')
    canonical = row.get('canonical', {})
    if canonical.get('processedRows', 0) < canonical.get('expectedRows', 0) and not canonical.get('workers'):
        row['alerts'].append('canonical_worker_missing')
    if canonical.get('issues'):
        row['alerts'].append('canonical_issues_present')
    terrain = row.get('terrainCandidates', {})
    row['alerts'].extend(terrain.get('alerts', []))
    if terrain.get('errors') or terrain.get('rejectedCohortResults'):
        row['alerts'].append('candidate_evidence_mismatch')
    row['storage'] = {}
    for drive in args.drive:
        try:
            free = shutil.disk_usage(drive).free
            row['storage'][drive] = {'freeBytes': free, 'reserveBytes': 20 * 1024**3}
            if free < 20 * 1024**3:
                row['alerts'].append('storage_below_20GiB:' + drive)
        except OSError as exc:
            row['storage'][drive] = {'error': str(exc)}
    try:
        release = read(args.data_root / 'releases/current.json')
        row['currentRelease'] = release
        index = read(args.data_root / 'world-buildings' / release['buildingCatalog']['index'])
        shard = read(args.data_root / 'world-buildings' / index['shards'][0]['href'])
        region = shard['regions'][0]
        with httpx.Client(base_url=args.base_url, trust_env=False, timeout=8) as client:
            url = building_url(region['url'])
            response = client.get(url)
            row['delivery'] = {'building': {'url': url, 'status': response.status_code, 'validTileset': response.status_code == 200 and 'root' in response.json()}, 'terrain': range_probe(client, release['terrain']['url'])}
        if not row['delivery']['building']['validTileset'] or not row['delivery']['terrain']['range206']:
            row['alerts'].append('current_delivery_failed')
    except Exception as exc:
        row['delivery'] = {'error': str(exc)}
        row['alerts'].append('current_delivery_failed')
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, default=Path(os.environ.get('DATA_ROOT', 'C:/Data/25_ACE')))
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--candidate', action='append', type=Path, required=True)
    parser.add_argument('--active-candidate', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--base-url', default='http://127.0.0.1:3003')
    parser.add_argument('--drive', action='append')
    parser.add_argument('--interval', type=float, default=300)
    parser.add_argument('--iterations', type=int, default=0)
    args = parser.parse_args()
    if args.interval <= 0 or args.iterations < 0:
        parser.error('interval must be positive; iterations must be nonnegative')
    if args.active_candidate.resolve() not in [p.resolve() for p in args.candidate]:
        parser.error('--active-candidate must be one of the pinned --candidate paths')
    args.output = args.output or args.data_root / 'management/national-integration-monitor'
    args.drive = args.drive or ['C:/', 'D:/']
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / 'monitor.lock').open('a+b') as lock:
        if lock.tell() == 0:
            lock.write(b'0'); lock.flush()
        lock.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise SystemExit('Integration monitor already running')
        (args.output / 'monitor.pid').write_text(str(os.getpid()))
        count = 0
        while True:
            start = time.monotonic()
            row = snapshot(args)
            raw = json.dumps(row, ensure_ascii=False)
            temp = args.output / 'latest.tmp'
            temp.write_text(raw, encoding='utf-8')
            temp.replace(args.output / 'latest.json')
            with (args.output / 'history.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(raw + '\n')
            print(json.dumps({'at': row['at'], 'pid': row['pid'], 'alerts': row['alerts'], 'processedRows': row.get('canonical', {}).get('processedRows'), 'filledKeysUnion': row.get('terrainCandidates', {}).get('filledKeysUnion')}), flush=True)
            count += 1
            if args.iterations and count >= args.iterations:
                break
            time.sleep(max(0, args.interval - (time.monotonic() - start)))


if __name__ == '__main__':
    main()
