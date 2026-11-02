"""Prebaked ground vector tiles: z14 Mapbox Vector Tiles of EGIS landcover (only the classes the ground style paints,
dissolved per class) and B021 road areas, in one static PMTiles archive (CDN-servable, no server rendering). The browser
draws near ground (z15+) from these at screen resolution; far ground stays on the PNG pyramids, which come from the same
two sources (landcover: the same layer and class colours as egis-lv3-2025-diagram.sld; roads: the same road index).

z13 blocks are the union of the landcover detail plan (children of non-empty z12 base tiles) and the road index's
blocks. Landcover comes from the provider's WFS, one bbox+class-filtered GetFeature per z13 block, request starts at
least the provider interval apart (default 1 s); clipping, dissolving and encoding run in worker processes. Display
geometry only, never statutory boundaries. Provider terms govern redistribution; this tool never activates a release."""
import argparse
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import threading
import time
import zlib

import httpx
import mapbox_vector_tile
from pmtiles.reader import MmapSource, Reader
from pmtiles.tile import Compression, TileType, zxy_to_tileid
import shapely

RECIPE = 'ground-vector-z14-v1'
ENDPOINT = 'https://api.mcee.go.kr/geoserver/wfs'
LAYER = 'EGIS:lv3_2025y'
TILE_Z = 14
EXTENT = 8192                # about 0.3 m map units per step at z14
RESERVE = 4 * 1024 ** 3
BLOCK_BYTES = 1024 ** 2      # gzip MVT bytes per z13 block for the space check (dense urban blocks measure below this)
MAX_RESPONSE = 768 * 1024 ** 2
# Class index -> l3 codes, in egis-lv3-2025-diagram.sld rule order (the browser holds the matching colours).
CLASSES = [('forest', (311, 321, 331)), ('green', (411, 421, 422, 423, 511, 521, 522)),
           ('farm', (211, 212, 221, 222, 231, 241, 251, 252)), ('bare', (611, 612, 613, 621, 623)),
           ('water', (711, 712, 721)), ('paved', (154, 155, 622)), ('rail', (153,))]
CLASS_OF = {str(code): i for i, (_, codes) in enumerate(CLASSES) for code in codes}

_load = lambda name, file: (lambda spec: (spec, importlib.util.module_from_spec(spec)))(
    importlib.util.spec_from_file_location(name, Path(__file__).with_name(file)))
_rs, road = _load('road_pyramid', 'bake-road-detail-pyramid.py'); _rs.loader.exec_module(road)
_ls, landcover = _load('landcover_pyramid', 'bake-landcover-detail-pyramid.py'); _ls.loader.exec_module(landcover)
tile_bounds = road.tile_bounds


class Wfs:
    """GetFeature with request starts at least `interval` apart across threads, patient retries on transient failures."""
    def __init__(self, interval):
        self.interval, self.last, self.lock = interval, float('-inf'), threading.Lock()
        self.client = httpx.Client(timeout=httpx.Timeout(600, connect=10), follow_redirects=False, trust_env=False)
        self.filter = ','.join(f"'{code}'" for code in CLASS_OF)

    def _start(self):
        with self.lock:
            time.sleep(max(0, self.interval - (time.monotonic() - self.last)))
            self.last = time.monotonic()

    def get(self, block, attempts):
        """Raw GeoJSON bytes (parsed in the worker, so in-flight blocks stay small), or None after `attempts` failures."""
        w, s, e, n = tile_bounds(TILE_Z - 1, *block)
        params = {'service': 'WFS', 'version': '2.0.0', 'request': 'GetFeature', 'typeNames': LAYER,
                  'outputFormat': 'application/json', 'propertyName': 'geom,l3_code', 'srsName': 'EPSG:3857', 'count': '1000000',
                  'cql_filter': f"BBOX(geom,{w},{s},{e},{n},'EPSG:3857') AND l3_code IN ({self.filter})"}
        for attempt in range(attempts):
            self._start()
            wait, reason = min(300, 2 ** attempt), ''
            try:
                r = self.client.post(ENDPOINT, data=params)
                # GeoServer reports query errors as HTTP 200 XML ServiceExceptions: those count as failures too.
                if r.status_code == 200 and r.headers.get('content-type', '').startswith('application/json') and len(r.content) <= MAX_RESPONSE:
                    return r.content
                reason = f'{r.status_code} {r.headers.get("content-type", "")} {len(r.content)}B {r.text[:200]!r}'
                retry = r.headers.get('Retry-After', '')
                if retry.isdigit():
                    wait = max(wait, min(900, int(retry)))
            except (httpx.TransportError, OSError) as error:
                reason = repr(error)[:200]
            print(json.dumps({'state': 'retry', 'block': block, 'attempt': attempt + 1, 'wait': wait, 'reason': reason}, ensure_ascii=False), flush=True)
            if attempt + 1 < attempts:
                time.sleep(wait)
        return None


_db = None


def init(path):
    global _db
    _db = sqlite3.connect(Path(path).as_uri() + '?mode=ro', uri=True, timeout=30)


def encode(job):
    """One z13 block -> [(tileid, gzip MVT)] for its non-empty z14 tiles."""
    (bx, by), raw_features = job
    body = json.loads(raw_features)
    if body.get('numberMatched') not in (None, 'unknown', body.get('numberReturned')):
        raise RuntimeError(f'WFS paged block {(bx, by)}: {body.get("numberMatched")} matched')
    features = [(f['geometry'], str(f['properties']['l3_code'])) for f in body['features'] if f.get('geometry')]
    del body, raw_features
    w, s, e, n = tile_bounds(TILE_Z - 1, bx, by)
    roads = []
    for (wkb,) in _db.execute('SELECT r.wkb FROM bounds b JOIN roads r ON r.id=b.id WHERE b.minx<=? AND b.maxx>=? AND b.miny<=? AND b.maxy>=?',
                              (e, w, n, s)):
        decoder = zlib.decompressobj()      # the index stores zlib-compressed WKB (same decode budget as the road pyramid)
        raw = decoder.decompress(wkb, 16 * 1024 ** 2)
        if not decoder.eof or decoder.unused_data:
            raise ValueError('Road geometry exceeds the decode budget')
        roads.append(shapely.make_valid(shapely.from_wkb(raw)))
    classes = [[] for _ in CLASSES]
    for geometry, code in features:
        if code in CLASS_OF:
            classes[CLASS_OF[code]].append(shapely.make_valid(shapely.geometry.shape(geometry)))
    tolerance = (e - w) / 2 / EXTENT / 2
    tiles = []
    for ty in (2 * by, 2 * by + 1):
        for tx in (2 * bx, 2 * bx + 1):
            box = tile_bounds(TILE_Z, tx, ty)
            # A small buffer keeps tile seams closed after the browser's clip.
            pad = (box[2] - box[0]) * 8 / EXTENT
            clip = shapely.box(box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad)
            layers = []
            for name, parts, props in (('landcover', classes, True), ('roads', [roads], False)):
                out = []
                for i, geometries in enumerate(parts):
                    hits = [g for g in geometries if g.intersects(clip)]
                    if not hits:
                        continue
                    try:
                        merged = shapely.union_all(hits)
                    except shapely.errors.GEOSException:
                        # A rare robustness failure must not end a national run: snap to 1 cm and union again.
                        merged = shapely.union_all(shapely.set_precision(hits, 0.01))
                    shape = shapely.simplify(shapely.intersection(merged, clip), tolerance)
                    shape = shapely.GeometryCollection([g for g in shapely.get_parts(shape) if g.geom_type in ('Polygon', 'MultiPolygon') and not g.is_empty])
                    if not shape.is_empty:
                        out.append({'geometry': shapely.union_all(shapely.get_parts(shape)), 'properties': {'c': i} if props else {}})
                if out:
                    layers.append({'name': name, 'features': out})
            if layers:
                data = mapbox_vector_tile.encode(layers, default_options={'quantize_bounds': box, 'extents': EXTENT, 'y_coord_down': False})
                tiles.append((zxy_to_tileid(TILE_Z, tx, ty), gzip.compress(data, 9, mtime=0)))
    return tiles


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--landcover-base', type=Path, required=True, help='national z0-12 landcover.pmtiles (block plan)')
    p.add_argument('--index-root', type=Path, required=True, help='road-index folder with latest.json')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--bounds', type=float, nargs=4, default=landcover.BOUNDS, metavar=('W', 'S', 'E', 'N'))
    p.add_argument('--interval', type=float, default=1.0)
    p.add_argument('--fetchers', type=int, default=1, help='WFS requests in flight (starts stay interval apart)')
    p.add_argument('--workers', type=int, default=3)
    p.add_argument('--plan-only', action='store_true')
    a = p.parse_args()
    t0 = time.time()
    pointer = json.loads((a.index_root / 'latest.json').read_text())
    index = a.index_root / pointer['version'] / pointer['file']
    identity = {'recipe': RECIPE, 'endpoint': ENDPOINT, 'layer': LAYER, 'classes': CLASSES, 'extent': EXTENT,
                'indexSHA256': pointer['sha256'], 'landcoverBaseSHA256': road.sha256(a.landcover_base), 'bounds': list(a.bounds),
                'implementationSHA256': road.sha256(__file__)}
    folder = a.output / hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    if (folder / 'receipt.json').exists():
        print(json.dumps({'state': 'exists', 'output': str(folder)}))
        return
    with open(a.landcover_base, 'rb') as f:
        source = MmapSource(f)
        header = Reader(source).header()
        todo = set(landcover.plan(source, a.bounds))
    db = sqlite3.connect(index.as_uri() + '?mode=ro', uri=True)
    w, s = road.mercator(a.bounds[0], a.bounds[1])
    e, n = road.mercator(a.bounds[2], a.bounds[3])
    todo |= {(x >> 2, y >> 2) for x, y in road.blocks(db, (w, s, e, n))}
    db.close()
    todo = sorted(todo)
    need = len(todo) * BLOCK_BYTES + RESERVE
    print(json.dumps({'state': 'planned', 'blocks': len(todo), 'needGB': round(need / 1024 ** 3, 1), 'seconds': round(time.time() - t0)}), flush=True)
    if a.plan_only:
        return
    folder.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(folder).free < need:
        raise OSError(f'needs_storage: about {need / 1024 ** 3:.1f} GB free required in {folder}')
    # Each finished block is committed to a spool before the next, so a crash or reboot resumes where it stopped.
    spool = sqlite3.connect(folder / 'spool.sqlite', isolation_level=None)
    spool.execute('PRAGMA journal_mode=WAL')
    spool.execute('CREATE TABLE IF NOT EXISTS tiles(tid INTEGER PRIMARY KEY, data BLOB NOT NULL)')
    spool.execute('CREATE TABLE IF NOT EXISTS blocks(bx INTEGER NOT NULL, by INTEGER NOT NULL, PRIMARY KEY(bx, by))')
    finished = set(spool.execute('SELECT bx, by FROM blocks'))
    left = [b for b in todo if b not in finished]
    print(json.dumps({'state': 'resuming', 'finished': len(finished), 'left': len(left)}), flush=True)
    wfs = Wfs(a.interval)
    done = len(finished)
    pending = []

    def collect(item):
        block, future = item
        tiles = future.result()
        spool.execute('BEGIN')
        spool.executemany('INSERT OR REPLACE INTO tiles VALUES (?, ?)', tiles)
        spool.execute('INSERT OR REPLACE INTO blocks VALUES (?, ?)', block)
        spool.execute('COMMIT')

    failed = []
    with ThreadPoolExecutor(a.fetchers) as fetch, ProcessPoolExecutor(a.workers, initializer=init, initargs=(str(index),)) as pool:
        # First pass: a few minutes of retries per block; blocks that still fail wait for the patient pass at the end
        # instead of stalling or ending the run. In-flight responses and jobs stay few: memory, not speed, is the limit.
        fetched = [fetch.submit(wfs.get, block, 8) for block in left[:a.fetchers]]
        for i, block in enumerate(left):
            features = fetched[i].result()
            if i + a.fetchers < len(left):
                fetched.append(fetch.submit(wfs.get, left[i + a.fetchers], 8))
            fetched[i] = None
            if features is None:
                failed.append(block)
                continue
            pending.append((block, pool.submit(encode, (block, features))))
            del features
            while len(pending) > a.workers:
                collect(pending.pop(0))
            done += 1
            if done % 200 == 0:
                if shutil.disk_usage(folder).free < RESERVE:
                    raise OSError('needs_storage: archive plus reserve')
                tiles, size = spool.execute('SELECT count(*), coalesce(sum(length(data)), 0) FROM tiles').fetchone()
                print(json.dumps({'state': 'fetching', 'blocks': done, 'of': len(todo), 'tiles': tiles,
                                  'MB': round(size / 1048576), 'seconds': round(time.time() - t0)}), flush=True)
        for block in failed:
            features = wfs.get(block, 40)
            if features is None:
                raise RuntimeError(f'WFS unavailable for block {block}')
            pending.append((block, pool.submit(encode, (block, features))))
        for item in pending:
            collect(item)
    if spool.execute('SELECT count(*) FROM blocks').fetchone()[0] != len(todo):
        raise RuntimeError('Spool is missing blocks')
    archive, part = folder / 'ground.pmtiles', folder / 'ground.pmtiles.part'
    writer = road.ArchiveWriter(part)
    written = tile_bytes = 0
    for tid, data in spool.execute('SELECT tid, data FROM tiles ORDER BY tid'):
        writer.write_tile(tid, data)
        written += 1
        tile_bytes += len(data)
    print(json.dumps({'state': 'fetched', 'retriedBlocks': len(failed), 'seconds': round(time.time() - t0)}), flush=True)
    bounds_e7 = [header['min_lon_e7'], header['min_lat_e7'], header['max_lon_e7'], header['max_lat_e7']]
    writer.finalize(dict(tile_type=TileType.MVT, tile_compression=Compression.GZIP, min_zoom=TILE_Z, max_zoom=TILE_Z,
                         min_lon_e7=bounds_e7[0], min_lat_e7=bounds_e7[1], max_lon_e7=bounds_e7[2], max_lat_e7=bounds_e7[3]),
                    {'recipe': RECIPE, 'identity': identity, 'vector_layers': [{'id': 'landcover', 'fields': {'c': 'Number'}}, {'id': 'roads', 'fields': {}}],
                     'usage': 'Display geometry only; provider terms govern redistribution'})
    os.replace(part, archive)
    receipt = {'schema': 'ground-vector-tiles-v1', 'identity': identity, 'archive': 'ground.pmtiles',
               'archiveSHA256': road.sha256(archive), 'bytes': archive.stat().st_size, 'tiles': written,
               'tileBytes': tile_bytes, 'blocks': len(todo), 'retriedBlocks': failed, 'seconds': round(time.time() - t0)}
    tmp = folder / 'receipt.json.part'
    tmp.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    os.replace(tmp, folder / 'receipt.json')
    spool.close()
    for name in ('spool.sqlite', 'spool.sqlite-wal', 'spool.sqlite-shm'):
        (folder / name).unlink(missing_ok=True)
    print(json.dumps({'state': 'done', 'output': str(folder), **{k: receipt[k] for k in ('bytes', 'tiles', 'seconds')}}))


if __name__ == '__main__':
    main()
