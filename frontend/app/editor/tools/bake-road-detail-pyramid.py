"""Prebaked B021 road-area detail imagery: z13..max-zoom tiles from the completed national road index, packed with the
national z0-12 road pyramid into one static PMTiles archive (no server rendering, CDN-servable). Style is the server's
on-demand road tile (backend/app/modules/land/map_road_imagery.py): RGBA 206,205,199, alpha = road-area coverage.

Each z15 block is rasterized once at 4x the max-zoom pixel size; every level z15..max-zoom is the exact area average of
that raster, and z14/z13 sum their z15 children's counts, so each level's alpha is round(255 * covered fraction) of the
same geometry. Display imagery only, never statutory road boundaries. Never activates a release."""
import argparse
import hashlib
import io
import json
import math
from concurrent.futures import ProcessPoolExecutor
import gzip
import os
from pathlib import Path
import shutil
import sqlite3
import time
import zlib

import numpy as np
from PIL import Image
from pmtiles.reader import MmapSource, Reader, all_tiles
from pmtiles.tile import Compression, Entry, TileType, serialize_header, zxy_to_tileid
from pmtiles.writer import optimize_directories
from rasterio.features import rasterize
from rasterio.transform import from_bounds
import shapely

RECIPE = 'b021-road-area-coverage-detail-v1'
COLOR = (206, 205, 199)
SS = 4                      # supersampling per max-zoom pixel (the server tile renders 1024 px for 256)
BLOCK_Z = 15
WORLD = math.pi * 6378137
NATIONAL = (124.0, 33.0, 132.0, 39.0)
RESERVE = 4 * 1024 ** 3
BLOCK_BYTES = 200 * 1024    # PNG bytes per z15 block, above the measured national mean (~150 KB) for the space check
ROOT = 16384                # PMTiles v3: header + root directory live in the first 16 KiB


class ArchiveWriter:
    """PMTiles v3 written in place: tile data from byte 16384 onward as it arrives (any order, identical payloads
    stored once by SHA-256), then metadata and leaf directories, then the header and root directory at the start.
    Needs the archive's size once on disk, not a spool plus a copy."""
    def __init__(self, path):
        self.f = open(path, 'wb')
        self.f.seek(ROOT)
        self.offset = 0
        self.entries = []
        self.seen = {}

    def write_tile(self, tile_id, data):
        key = hashlib.sha256(data).digest()
        if key not in self.seen:
            self.f.write(data)
            self.seen[key] = (self.offset, len(data))
            self.offset += len(data)
        self.entries.append(Entry(tile_id, *self.seen[key], 1))

    def finalize(self, header, metadata):
        self.entries.sort(key=lambda e: e.tile_id)
        if any(a.tile_id == b.tile_id for a, b in zip(self.entries, self.entries[1:])):
            raise ValueError('Duplicate tile id')
        root, leaves, _ = optimize_directories(self.entries, ROOT - 127)
        meta = gzip.compress(json.dumps(metadata).encode())
        end = ROOT + self.offset
        header = dict(header, root_offset=127, root_length=len(root), metadata_offset=end, metadata_length=len(meta),
                      leaf_directory_offset=end + len(meta), leaf_directory_length=len(leaves), tile_data_offset=ROOT,
                      tile_data_length=self.offset, addressed_tiles_count=len(self.entries), tile_entries_count=len(self.entries),
                      tile_contents_count=len(self.seen), clustered=False, internal_compression=Compression.GZIP)
        self.f.write(meta)
        self.f.write(leaves)
        head = serialize_header(header)
        if len(head) != 127 or 127 + len(root) > ROOT:
            raise ValueError('PMTiles root directory exceeds 16 KiB')
        self.f.seek(0)
        self.f.write(head + root)
        self.f.flush()
        os.fsync(self.f.fileno())
        self.f.close()


def mercator(lon, lat):
    return lon * WORLD / 180, math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * 6378137


def tile_bounds(z, x, y):
    span = 2 * WORLD / 2 ** z
    return -WORLD + x * span, WORLD - (y + 1) * span, -WORLD + (x + 1) * span, WORLD - y * span


def png(alpha):
    rgba = np.empty((256, 256, 4), dtype=np.uint8)
    rgba[:, :, :3] = COLOR
    rgba[:, :, 3] = alpha
    out = io.BytesIO()
    Image.fromarray(rgba).save(out, format='PNG', compress_level=6)
    return out.getvalue()


def alpha_of(counts, total):
    return np.rint(counts * (255 / total)).astype(np.uint8)


def sha256(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def blocks(db, bounds):
    """z15 blocks touched by any road bounding box inside bounds (EPSG:3857 metres)."""
    w, s, e, n = bounds
    span = 2 * WORLD / 2 ** BLOCK_Z
    rows = np.array(db.execute('SELECT minx,maxx,miny,maxy FROM bounds WHERE maxx>=? AND minx<=? AND maxy>=? AND miny<=?',
                               (w, e, s, n)).fetchall(), dtype=np.float64).reshape(-1, 4)
    x0 = np.floor((np.maximum(rows[:, 0], w) + WORLD) / span).astype(np.int64)
    x1 = np.floor((np.minimum(rows[:, 1], e) + WORLD) / span).astype(np.int64)
    y0 = np.floor((WORLD - np.minimum(rows[:, 3], n)) / span).astype(np.int64)
    y1 = np.floor((WORLD - np.maximum(rows[:, 2], s)) / span).astype(np.int64)
    found = set(zip(x0[(x0 == x1) & (y0 == y1)].tolist(), y0[(x0 == x1) & (y0 == y1)].tolist()))
    for i in np.nonzero((x0 != x1) | (y0 != y1))[0]:
        found.update((x, y) for x in range(x0[i], x1[i] + 1) for y in range(y0[i], y1[i] + 1))
    # Parents first, then children, so each z13 group finishes contiguously.
    return sorted(found, key=lambda b: (b[0] >> 2, b[1] >> 2, b[0], b[1]))


_db = None
_max_z = None


def init(path, max_z):
    global _db, _max_z
    _db = sqlite3.connect(Path(path).as_uri() + '?mode=ro', uri=True, timeout=30)
    _max_z = max_z


def render(block):
    """One z15 block -> (tiles [(tileid, png)], z15 coverage counts or None)."""
    bx, by = block
    n = 2 ** (_max_z - BLOCK_Z)          # max-zoom tiles per block side
    size = n * 256 * SS
    bounds = tile_bounds(BLOCK_Z, bx, by)
    w, s, e, nn = bounds
    geometries = []
    for (wkb,) in _db.execute('SELECT r.wkb FROM bounds b JOIN roads r ON r.id=b.id WHERE b.minx<=? AND b.maxx>=? AND b.miny<=? AND b.maxy>=?',
                              (e, w, nn, s)):
        decoder = zlib.decompressobj()
        raw = decoder.decompress(wkb, 16 * 1024 ** 2)
        if not decoder.eof or decoder.unused_data:
            raise ValueError('Road geometry exceeds the decode budget')
        geometries.append(shapely.from_wkb(raw))
    if not geometries:
        return [], None
    mask = rasterize([(g, 1) for g in geometries], out_shape=(size, size), transform=from_bounds(*bounds, size, size), dtype=np.uint8)
    # counts[z] = covered supersamples per pixel of level z (total per pixel = (SS * 2**(max_z - z))**2)
    counts = mask.reshape(size // SS, SS, size // SS, SS).sum(axis=(1, 3), dtype=np.uint32)
    tiles = []
    for z in range(_max_z, BLOCK_Z - 1, -1):
        total = (SS * 2 ** (_max_z - z)) ** 2
        per = 2 ** (z - BLOCK_Z)
        for ty in range(per):
            for tx in range(per):
                c = counts[ty * 256:(ty + 1) * 256, tx * 256:(tx + 1) * 256]
                if c.any():
                    tiles.append((zxy_to_tileid(z, bx * per + tx, by * per + ty), png(alpha_of(c, total))))
        if z > BLOCK_Z:
            counts = counts.reshape(counts.shape[0] // 2, 2, counts.shape[1] // 2, 2).sum(axis=(1, 3), dtype=np.uint32)
    return tiles, counts if counts.any() else None


def parent_tiles(z15, max_z):
    """z14 and z13 tiles of one z13 group from its z15 children's counts {(x, y): 256x256 counts}."""
    total15 = (SS * 2 ** (max_z - BLOCK_Z)) ** 2
    out = []
    for z in (14, 13):
        shift = BLOCK_Z - z
        groups = {}
        for (x, y), c in z15.items():
            k = (x >> shift, y >> shift)
            acc = groups.setdefault(k, np.zeros((256 * 2 ** shift, 256 * 2 ** shift), dtype=np.uint32))
            ox, oy = (x - (k[0] << shift)) * 256, (y - (k[1] << shift)) * 256
            acc[oy:oy + 256, ox:ox + 256] = c
        f = 2 ** shift
        for (x, y), acc in groups.items():
            c = acc.reshape(256, f, 256, f).sum(axis=(1, 3), dtype=np.uint64)
            if c.any():
                out.append((zxy_to_tileid(z, x, y), png(alpha_of(c, total15 * f * f))))
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--index-root', type=Path, required=True)
    p.add_argument('--base', type=Path, required=True, help='national z0-12 roads.pmtiles')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--bounds', type=float, nargs=4, default=NATIONAL, metavar=('W', 'S', 'E', 'N'))
    p.add_argument('--max-zoom', type=int, default=18)
    p.add_argument('--workers', type=int, default=6)
    a = p.parse_args()
    if not 16 <= a.max_zoom <= 19:
        raise SystemExit('--max-zoom must be 16..19')
    pointer = json.loads((a.index_root / 'latest.json').read_text(encoding='utf-8'))
    if pointer.get('schema') != 'ngii-native-road-index-pointer-v1' or pointer.get('complete') is not True:
        raise SystemExit('Completed national road index required')
    index = a.index_root / pointer['version'] / pointer['file']
    t0 = time.time()
    if sha256(index) != pointer['sha256']:
        raise SystemExit('Road index fingerprint mismatch')
    base_sha = sha256(a.base)
    identity = {'recipe': RECIPE, 'indexSHA256': pointer['sha256'], 'baseSHA256': base_sha, 'bounds': list(a.bounds),
                'maxZoom': a.max_zoom, 'supersampling': SS, 'implementationSHA256': sha256(__file__)}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    folder = a.output / digest
    if (folder / 'receipt.json').exists():
        print(json.dumps({'state': 'exists', 'output': str(folder)}))
        return
    folder.mkdir(parents=True, exist_ok=True)
    archive, part = folder / 'roads.pmtiles', folder / 'roads.pmtiles.part'
    with open(a.base, 'rb') as f:
        source = MmapSource(f)
        header = Reader(source).header()
        if header['tile_type'] != TileType.PNG or header['max_zoom'] != 12:
            raise SystemExit('Base archive must be the national z0-12 PNG road pyramid')
        base = [(zxy_to_tileid(*zxy), data) for zxy, data in all_tiles(source)]

    # Snap outward to the z13 grid: a z13/z14 tile is built from all of its z15 blocks or not at all.
    span13 = 2 * WORLD / 2 ** 13
    w, s = mercator(a.bounds[0], a.bounds[1])
    e, n = mercator(a.bounds[2], a.bounds[3])
    w, e = (math.floor((w + WORLD) / span13) * span13 - WORLD, math.ceil((e + WORLD) / span13) * span13 - WORLD)
    s, n = (WORLD - math.ceil((WORLD - s) / span13) * span13, WORLD - math.floor((WORLD - n) / span13) * span13)
    with sqlite3.connect(index.as_uri() + '?mode=ro', uri=True) as db:
        todo = blocks(db, (w + 1e-6, s + 1e-6, e - 1e-6, n - 1e-6))
    need = len(todo) * BLOCK_BYTES * 4 ** (a.max_zoom - 18) + RESERVE
    print(json.dumps({'state': 'planned', 'blocks': len(todo), 'needGB': round(need / 1024 ** 3, 1), 'seconds': round(time.time() - t0)}), flush=True)
    if shutil.disk_usage(folder).free < need:
        raise OSError(f'needs_storage: about {need / 1024 ** 3:.1f} GB free required in {folder}')

    written = tile_bytes = done = 0
    group, z15 = None, {}
    # Base levels first, then the detail levels as rendered (the directory is sorted at finalize).
    writer = ArchiveWriter(part)
    for tid, data in base:
        writer.write_tile(tid, data)
    base_tiles, base_bytes = len(base), sum(len(d) for _, d in base)
    del base

    def emit(tiles):
        nonlocal written, tile_bytes
        for tid, data in tiles:
            writer.write_tile(tid, data)
        written += len(tiles)
        tile_bytes += sum(len(d) for _, d in tiles)

    def flush_group():
        emit(parent_tiles(z15, a.max_zoom))
        z15.clear()

    # Results come back in submission order (z13 groups stay contiguous); a dead worker raises BrokenProcessPool.
    with ProcessPoolExecutor(a.workers, initializer=init, initargs=(str(index), a.max_zoom)) as pool:
        for block, (tiles, counts) in zip(todo, pool.map(render, todo, chunksize=4)):
            key = (block[0] >> 2, block[1] >> 2)
            if key != group:
                flush_group()
                group = key
            if counts is not None:
                z15[block] = counts
            emit(tiles)
            done += 1
            if done % 2000 == 0:
                if shutil.disk_usage(folder).free < RESERVE:
                    raise OSError('needs_storage: archive plus reserve')
                print(json.dumps({'state': 'rendering', 'blocks': done, 'of': len(todo), 'tiles': written,
                                  'MB': round(tile_bytes / 1048576), 'seconds': round(time.time() - t0)}), flush=True)
        flush_group()
    bounds_e7 = [round(v * 1e7) for v in header_bounds(header)]
    writer.finalize(dict(tile_type=TileType.PNG, tile_compression=Compression.NONE, min_zoom=0, max_zoom=a.max_zoom,
                         min_lon_e7=bounds_e7[0], min_lat_e7=bounds_e7[1], max_lon_e7=bounds_e7[2], max_lat_e7=bounds_e7[3]),
                    {'recipe': RECIPE, 'identity': identity, 'usage': 'Display imagery only; not statutory road boundaries'})
    os.replace(part, archive)
    receipt = {'schema': 'road-detail-pyramid-v1', 'identity': identity, 'archive': 'roads.pmtiles',
               'archiveSHA256': sha256(archive), 'bytes': archive.stat().st_size, 'baseTiles': base_tiles,
               'detailTiles': written, 'detailBytes': tile_bytes, 'blocks': len(todo), 'seconds': round(time.time() - t0)}
    tmp = folder / 'receipt.json.part'
    tmp.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    os.replace(tmp, folder / 'receipt.json')
    print(json.dumps({'state': 'done', 'output': str(folder), **{k: receipt[k] for k in ('bytes', 'detailTiles', 'seconds')}}))


def header_bounds(header):
    return [header['min_lon_e7'] / 1e7, header['min_lat_e7'] / 1e7, header['max_lon_e7'] / 1e7, header['max_lat_e7'] / 1e7]


if __name__ == '__main__':
    main()
