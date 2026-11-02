"""Prebaked EGIS landcover detail imagery: z13..max-zoom tiles packed with the national z0-12 landcover pyramid into one
static PMTiles archive (no server rendering, CDN-servable). Style and source are the server's on-demand ground tile
(backend/app/modules/land/map_ground_imagery.py): the same WMS layer and SLD, which has no scale rules, so one GetMap at
the max-zoom pixel size per z13 block is pixel-identical to the per-tile requests. Coarser levels are the
premultiplied-alpha 2x2 box average of the level below (the z0-12 pyramid's rule).

z13 blocks are the children of non-empty z12 base tiles. WMS requests are sequential and rate-limited (the provider's
interval, default 1 s); cutting and PNG encoding run in worker processes. Display imagery only. Provider terms govern
redistribution; this tool never activates a release."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import shutil
import time

import httpx
import numpy as np
from PIL import Image
from pmtiles.reader import MmapSource, Reader, all_tiles
from pmtiles.tile import Compression, TileType, zxy_to_tileid

RECIPE = 'egis-lv3-2025-landcover-detail-v1'
ENDPOINT = 'https://api.mcee.go.kr/geoserver/wms'
LAYER = 'EGIS:lv3_2025y'
STYLE = Path(__file__).resolve().parents[4] / 'backend/app/modules/land/resources/egis-lv3-2025-diagram.sld'
STYLE_SHA = '291c7488d4e43750477445b3646027e69eb3b1bc3888072d16cc369af833fd72'
BOUNDS = (125.0749972065207, 33.09999943194731, 131.87500136217878, 38.37500335369369)
BLOCK_Z = 13
WORLD = math.pi * 6378137
RESERVE = 4 * 1024 ** 3
BLOCK_BYTES = 3 * 1024 ** 2   # PNG bytes per z13 block at z17, above the measured dense-area block for the space check
MAX_RESPONSE = 64 * 1024 ** 2

_road = importlib.util.spec_from_file_location('road_pyramid', Path(__file__).with_name('bake-road-detail-pyramid.py'))
road = importlib.util.module_from_spec(_road)
_road.loader.exec_module(road)


def tile_bounds(z, x, y):
    span = 2 * WORLD / 2 ** z
    return -WORLD + x * span, WORLD - (y + 1) * span, -WORLD + (x + 1) * span, WORLD - y * span


def png(rgba):
    """8-bit palette PNG: seven flat class colours plus antialiased edges fit 256 entries (mean premultiplied error
    about 3/255 on the dense gosan sample) at about a third of the RGBA size."""
    out = io.BytesIO()
    Image.fromarray(rgba).quantize(256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE).save(out, format='PNG', optimize=True)
    return out.getvalue()


def reduce(premult):
    """2x2 box sum of premultiplied (H, W, 4) float32 [r*a, g*a, b*a, a]."""
    h, w, _ = premult.shape
    return premult.reshape(h // 2, 2, w // 2, 2, 4).sum(axis=(1, 3)) / 4


def unpremultiply(premult):
    a = premult[:, :, 3:4]
    rgb = np.divide(premult[:, :, :3], a, out=np.zeros_like(premult[:, :, :3]), where=a > 0)
    return np.dstack([np.rint(rgb), np.rint(a)]).clip(0, 255).astype(np.uint8)


def cut(job):
    """One z13 block image (max-zoom pixels) -> [(tileid, png)] for every non-empty tile of z13..max-zoom."""
    (bx, by), raw, max_z = job
    with Image.open(io.BytesIO(raw)) as image:
        rgba = np.asarray(image.convert('RGBA'))
    tiles = []
    level, z = rgba, max_z
    premult = None
    while True:
        per = 2 ** (z - BLOCK_Z)
        for ty in range(per):
            for tx in range(per):
                t = level[ty * 256:(ty + 1) * 256, tx * 256:(tx + 1) * 256]
                if t[:, :, 3].any():
                    tiles.append((zxy_to_tileid(z, bx * per + tx, by * per + ty), png(np.ascontiguousarray(t))))
        if z == BLOCK_Z:
            return tiles
        if premult is None:
            premult = rgba.astype(np.float32)
            premult[:, :, :3] *= premult[:, :, 3:4] / 255
            del rgba
        premult = reduce(premult)
        # unpremultiply wants alpha in 0..255 and colour premultiplied by alpha/255
        level = unpremultiply(np.dstack([premult[:, :, :3] * 255, premult[:, :, 3:4]]))
        z -= 1


class Wms:
    """Sequential GetMap with the provider interval between request starts, patient retries on transient failures."""
    def __init__(self, style, interval):
        self.style, self.interval, self.last = style, interval, float('-inf')
        self.client = httpx.Client(timeout=httpx.Timeout(120, connect=10), follow_redirects=False, trust_env=False)

    def get(self, block, size):
        params = {'SERVICE': 'WMS', 'REQUEST': 'GetMap', 'VERSION': '1.3.0', 'CRS': 'EPSG:3857', 'LAYERS': LAYER,
                  'STYLES': '', 'FORMAT': 'image/png', 'TRANSPARENT': 'true', 'WIDTH': size, 'HEIGHT': size,
                  'SLD_BODY': self.style, 'BBOX': ','.join(map(str, tile_bounds(BLOCK_Z, *block)))}
        # About 3 h of patience per block: a provider outage pauses the run instead of discarding hours of work.
        for attempt in range(40):
            time.sleep(max(0, self.interval - (time.monotonic() - self.last)))
            self.last = time.monotonic()
            wait = min(300, 2 ** attempt)
            try:
                r = self.client.post(ENDPOINT, data=params)
                if r.status_code == 200 and r.headers.get('content-type', '').startswith('image/png') and len(r.content) <= MAX_RESPONSE:
                    with Image.open(io.BytesIO(r.content)) as image:
                        if image.size == (size, size):
                            return r.content
                if r.status_code not in (429, 500, 502, 503, 504) and r.status_code != 200:
                    raise RuntimeError(f'WMS {r.status_code} for block {block}')
                retry = r.headers.get('Retry-After', '')
                if retry.isdigit():
                    wait = max(wait, min(900, int(retry)))
            except (httpx.TransportError, OSError):
                pass
            print(json.dumps({'state': 'retry', 'block': block, 'attempt': attempt + 1, 'wait': wait}), flush=True)
            time.sleep(wait)
        raise RuntimeError(f'WMS unavailable for block {block}')


def plan(source, bounds):
    """z13 children of non-empty z12 base tiles inside bounds, grouped by z12 parent."""
    w, s, e, n = bounds
    def inside(z, x, y):
        k = 2 ** z
        lat = lambda row: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * row / k))))
        return x / k * 360 - 180 < e and (x + 1) / k * 360 - 180 > w and lat(y + 1) < n and lat(y) > s
    todo = []
    for (z, x, y), data in all_tiles(source):
        if z != 12:
            continue
        with Image.open(io.BytesIO(data)) as image:
            if image.convert('RGBA').getchannel('A').getbbox() is None:
                continue
        todo += [(cx, cy) for cx in (2 * x, 2 * x + 1) for cy in (2 * y, 2 * y + 1) if inside(BLOCK_Z, cx, cy)]
    return sorted(todo, key=lambda b: (b[0] >> 1, b[1] >> 1, b))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--base', type=Path, required=True, help='national z0-12 landcover.pmtiles')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--bounds', type=float, nargs=4, default=BOUNDS, metavar=('W', 'S', 'E', 'N'))
    p.add_argument('--max-zoom', type=int, default=17)
    p.add_argument('--interval', type=float, default=1.0)
    p.add_argument('--workers', type=int, default=3)
    p.add_argument('--plan-only', action='store_true')
    a = p.parse_args()
    if not 16 <= a.max_zoom <= 17:
        raise SystemExit('--max-zoom must be 16..17 (one GetMap per z13 block is at most 4096 px)')
    raw_style = STYLE.read_bytes()
    if hashlib.sha256(raw_style).hexdigest() != STYLE_SHA:
        raise SystemExit('Ground imagery style fingerprint changed')
    t0 = time.time()
    identity = {'recipe': RECIPE, 'endpoint': ENDPOINT, 'layer': LAYER, 'styleSHA256': STYLE_SHA,
                'baseSHA256': road.sha256(a.base), 'bounds': list(a.bounds), 'maxZoom': a.max_zoom,
                'implementationSHA256': road.sha256(__file__)}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    folder = a.output / digest
    if (folder / 'receipt.json').exists():
        print(json.dumps({'state': 'exists', 'output': str(folder)}))
        return
    with open(a.base, 'rb') as f:
        source = MmapSource(f)
        header = Reader(source).header()
        if header['tile_type'] != TileType.PNG or header['max_zoom'] != 12:
            raise SystemExit('Base archive must be the national z0-12 PNG landcover pyramid')
        todo = plan(source, a.bounds)
        base = [(zxy_to_tileid(*zxy), data) for zxy, data in all_tiles(source)]
    need = len(todo) * BLOCK_BYTES + RESERVE
    print(json.dumps({'state': 'planned', 'blocks': len(todo), 'needGB': round(need / 1024 ** 3, 1),
                      'hours': round(len(todo) * a.interval / 3600, 1), 'seconds': round(time.time() - t0)}), flush=True)
    if a.plan_only:
        return
    folder.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(folder).free < need:
        raise OSError(f'needs_storage: about {need / 1024 ** 3:.1f} GB free required in {folder}')
    archive, part = folder / 'landcover.pmtiles', folder / 'landcover.pmtiles.part'
    writer = road.ArchiveWriter(part)
    for tid, data in base:
        writer.write_tile(tid, data)
    base_tiles = len(base)
    del base

    wms = Wms(raw_style.decode('utf-8'), a.interval)
    size = 256 * 2 ** (a.max_zoom - BLOCK_Z)
    written = tile_bytes = done = 0
    pending = []

    def collect(future):
        nonlocal written, tile_bytes
        for tid, data in future.result():
            writer.write_tile(tid, data)
            written += 1
            tile_bytes += len(data)

    with ProcessPoolExecutor(a.workers) as pool:
        for block in todo:
            pending.append(pool.submit(cut, (block, wms.get(block, size), a.max_zoom)))
            while len(pending) > 2 * a.workers:
                collect(pending.pop(0))
            done += 1
            if done % 200 == 0:
                if shutil.disk_usage(folder).free < RESERVE:
                    raise OSError('needs_storage: archive plus reserve')
                print(json.dumps({'state': 'fetching', 'blocks': done, 'of': len(todo), 'tiles': written,
                                  'MB': round(tile_bytes / 1048576), 'seconds': round(time.time() - t0)}), flush=True)
        for future in pending:
            collect(future)
    bounds_e7 = [header['min_lon_e7'], header['min_lat_e7'], header['max_lon_e7'], header['max_lat_e7']]
    writer.finalize(dict(tile_type=TileType.PNG, tile_compression=Compression.NONE, min_zoom=0, max_zoom=a.max_zoom,
                         min_lon_e7=bounds_e7[0], min_lat_e7=bounds_e7[1], max_lon_e7=bounds_e7[2], max_lat_e7=bounds_e7[3]),
                    {'recipe': RECIPE, 'identity': identity, 'usage': 'Display imagery only; provider terms govern redistribution'})
    os.replace(part, archive)
    receipt = {'schema': 'landcover-detail-pyramid-v1', 'identity': identity, 'archive': 'landcover.pmtiles',
               'archiveSHA256': road.sha256(archive), 'bytes': archive.stat().st_size, 'baseTiles': base_tiles,
               'detailTiles': written, 'detailBytes': tile_bytes, 'blocks': len(todo), 'seconds': round(time.time() - t0)}
    tmp = folder / 'receipt.json.part'
    tmp.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    os.replace(tmp, folder / 'receipt.json')
    print(json.dumps({'state': 'done', 'output': str(folder), **{k: receipt[k] for k in ('bytes', 'detailTiles', 'seconds')}}))


if __name__ == '__main__':
    main()
