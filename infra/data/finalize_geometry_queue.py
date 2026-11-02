"""Finalize a completed geometry queue using existing terrain and release verification gates."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from catalog_release import build
from migrate_building_geometry import building_lock
from prepare_map_release import prepare
from queue_building_geometry import REVISION, catalog_inventory, pending_regions
from release_store import activate, atomic_json, read_json, digest


def validate_queue(root, work, expected_release):
    if not re.fullmatch('[a-f0-9]{64}', expected_release):
        raise ValueError('Invalid pinned checkpoint release ID')
    current = read_json(root / 'releases/current.json')
    if current['releaseId'] != expected_release:
        raise ValueError('Active release changed from pinned checkpoint')
    state = read_json(work / 'status.json')
    if state.get('state') != 'completed' or state.get('remaining') != 0:
        raise ValueError('Geometry queue is not completed')
    catalog_path = root / 'world-buildings/catalog.json'
    catalog = read_json(catalog_path)
    if pending_regions(read_json(work / 'plan.json'), catalog):
        raise ValueError('Geometry targets remain incomplete')
    rows = catalog_inventory(catalog)
    if any(row.get('meshRevision') != REVISION for row in rows.values()):
        raise ValueError('Catalog contains non-v3 geometry')
    revision = digest(catalog_path)
    if state.get('catalogSHA256') != revision:
        raise ValueError('Catalog changed after queue completion')
    return current, revision


def health(base_url, release):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def get(path, headers=None):
        request = urllib.request.Request(base_url.rstrip('/') + path, headers=headers or {})
        return opener.open(request, timeout=30)
    with get('/api/map-data/releases/current.json', {'Cache-Control': 'no-cache'}) as response:
        body = json.load(response)
        if response.status != 200 or body.get('releaseId') != release['releaseId']:
            raise ValueError('HTTP active release differs from activated pointer')
    assets = []
    for name, path in [('buildings', release['buildings']['href']), ('terrain', release['terrain']['url'])]:
        if not path.startswith('/api/map-data/'):
            raise ValueError('Expected local HTTP asset route')
        with get(path, {'Range': 'bytes=0-126'}) as response:
            content = response.read(128)
            if response.status != 206 or len(content) != 127 or content[:7] != b'PMTiles':
                raise ValueError(f'HTTP range verification failed: {name}')
            assets.append({'asset': name, 'status': response.status, 'contentRange': response.headers.get('Content-Range')})
    return {'releaseId': release['releaseId'], 'assets': assets, 'checkedAt': time.time()}


def run_command(command, log):
    with log.open('a', encoding='utf-8') as output:
        subprocess.run(command, stdout=output, stderr=subprocess.STDOUT, check=True,
                       creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)


def finalize(args, pins):
    root = args.data_root.resolve()
    state_path = args.queue_work / 'finalization-status.json'
    state = {'state': 'verifying', 'pid': os.getpid(), 'previousReleaseId': args.expected_release,
             'activated': False, 'startedAt': time.time()}
    def stage(name):
        state.update(state=name, updatedAt=time.time())
        atomic_json(state_path, state)
    try:
        with building_lock(args.dem_root):
            checkpoint, revision = validate_queue(root, args.queue_work, args.expected_release)
            if digest(args.dem) != pins['demSHA256'] or digest(args.points) != pins['pointsSHA256']:
                raise ValueError('Pinned DEM or verification points changed')
            receipt = read_json(args.terrain_work / 'archive-receipt.json')
            if receipt['sha256'] != checkpoint['terrain']['sha256'] or pins['demSHA256'] != checkpoint['terrain']['vrt_sha256']:
                raise ValueError('Pinned terrain inputs differ from checkpoint')
            state['catalogSHA256'] = revision
            stage('http_before')
            state['healthBefore'] = health(args.base_url, checkpoint)
            stage('height_verification')
            tools = args.editor_root / 'frontend/app/editor/tools'
            run_command([sys.executable, str(tools/'verify-terrain-archive.py'), '--work', str(args.terrain_work),
                         '--dem', str(args.dem), '--points', str(args.points), '--level', '20', '--buildings', str(root)],
                        args.queue_work/'finalization.log')
            heights = read_json(args.terrain_work / 'height-verification.json')
            datum = heights.get('publishedBuildingDatumCheck', {})
            if heights.get('missing') != 0 or not heights.get('absoluteErrorMetres') or heights['absoluteErrorMetres']['maximum'] > .5:
                raise ValueError('Terrain height accuracy gate failed')
            if datum.get('expected', 0) <= 0 or datum.get('compared') != datum['expected'] or datum.get('maximumAbsoluteErrorMetres', float('inf')) > .01:
                raise ValueError('Published building datum gate failed')
            if heights.get('buildingCatalogSHA256') != revision:
                raise ValueError('Height verification used another catalog')
            stage('terrain_publication_verification')
            run_command([sys.executable, str(tools/'verify-terrain-publication.py'), '--work', str(args.terrain_work),
                         '--public', str(root), '--base-url', args.base_url], args.queue_work/'finalization.log')
            stage('catalog_publication')
            build(root/'world-buildings/catalog.json', root, root/'world-buildings', publish=True)
            validate_queue(root, args.queue_work, args.expected_release)
            stage('release_preparation')
            candidate = prepare(root, args.terrain_work)
            state['candidateReleaseId'] = candidate['releaseId']
            if candidate.get('predecessorRelease') != args.expected_release or candidate['buildingCatalog']['revision'] != revision:
                raise ValueError('Prepared release differs from pinned predecessor/catalog')
            validate_queue(root, args.queue_work, args.expected_release)
            stage('release_activation')
            activated = activate(root, candidate['releaseId'], reason='national-geometry-v3-complete', expected_current=args.expected_release)
            state.update(activated=True, releaseId=activated['releaseId'])
            stage('http_after')
            state['healthAfter'] = health(args.base_url, activated)
            stage('completed')
            return state
    except BaseException as error:
        if state['activated']:
            try:
                restored = activate(root, args.expected_release, reason='rollback', expected_current=state['releaseId'])
                state['rollback'] = {'state':'restored_checkpoint', 'releaseId':restored['releaseId']}
            except BaseException as rollback_error:
                state['rollback'] = {'state':'not_applied', 'error':str(rollback_error)}
        state.update(error=str(error), state='activated_health_failed' if state['activated'] else 'failed', updatedAt=time.time())
        atomic_json(state_path, state)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['data-root', 'dem-root', 'editor-root', 'queue-work', 'terrain-work', 'dem', 'points']:
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--expected-release', required=True)
    parser.add_argument('--base-url', default='http://127.0.0.1:3003')
    args = parser.parse_args()
    args.queue_work.mkdir(parents=True, exist_ok=True)
    pin_path = args.queue_work / 'finalization-pins.json'
    pins = {'expectedReleaseId': args.expected_release, 'dem': str(args.dem.resolve()), 'demSHA256': digest(args.dem),
            'points': str(args.points.resolve()), 'pointsSHA256': digest(args.points), 'terrainWork': str(args.terrain_work.resolve())}
    if pin_path.exists():
        if read_json(pin_path) != pins:
            raise ValueError('Finalization pins changed; inspect before creating a new supervisor')
    else:
        atomic_json(pin_path, pins)
    while True:
        status = read_json(args.queue_work/'status.json') if (args.queue_work/'status.json').exists() else {}
        if status.get('state') == 'completed':
            print(json.dumps(finalize(args, pins)))
            return
        if status.get('state') in ('failed', 'stopped'):
            atomic_json(args.queue_work/'finalization-status.json', {'state':'queue_not_completed', 'queueState':status['state'], 'activated':False})
            raise RuntimeError('Queue stopped without completing; release not changed')
        atomic_json(args.queue_work/'finalization-status.json', {'state':'waiting_for_queue', 'pid':os.getpid(),
                    'remaining':status.get('remaining'), 'heartbeatAt':time.time(), 'activated':False, 'previousReleaseId':args.expected_release})
        time.sleep(10)


if __name__ == '__main__':
    main()
