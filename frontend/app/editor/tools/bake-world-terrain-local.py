"""Publish display grids from installed NGII DEM using SiteContext's sampler.

One writer per output catalog. No network fallback and no invented elevations.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
from datetime import datetime, timezone


def tile_keys(bounds, minimum, maximum):
    west, south, east, north = bounds
    for level in range(minimum, maximum + 1):
        width = 180 / 2 ** level
        for x in range(math.floor((west + 180) / width), math.ceil((east + 180) / width)):
            for y in range(math.floor((90 - north) / width), math.ceil((90 - south) / width)):
                yield level, x, y


def grid_points(level, x, y):
    width = 180 / 2 ** level
    return [(x * width - 180 + i * width / 32, 90 - y * width - j * width / 32)
            for j in range(33) for i in range(33)]


def atomic_json(path, value):
    temporary = path.with_name(path.name + '.next')
    temporary.write_text(json.dumps(value, separators=(',', ':'), allow_nan=False), encoding='utf-8')
    # Windows readers can briefly deny replacement while serving the catalog.
    # Keep the old complete file visible and retry the atomic rename.
    for attempt in range(10):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(min(1, .05 * 2 ** attempt))


def valid_tile(value):
    heights = value.get('heights', [])
    return value.get('size') == 33 and len(heights) == 1089 and all(
        type(h) in (float, int) and math.isfinite(h) and -500 <= h <= 9000 for h in heights)


def verify_resume_source(saved, source):
    dataset = saved.get('dataset')
    if dataset and dataset.get('vrt_sha256') != source['vrt_sha256']:
        raise ValueError('Existing tile uses a different DEM; publish a new snapshot version')
    return not bool(dataset)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bounds', nargs=4, type=float, required=True)
    parser.add_argument('--levels', nargs=2, type=int, default=[11, 17])
    parser.add_argument('--dem', type=Path, required=True)
    parser.add_argument('--site-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('public/world-terrain'))
    parser.add_argument('--version', required=True)
    parser.add_argument('--display-ttl-hours', type=float, help='Explicitly pin this display snapshot for 0..168 hours')
    args = parser.parse_args()
    w, s, e, n = args.bounds
    if not (124 <= w < e <= 133 and 33 <= s < n <= 39 and 11 <= args.levels[0] <= args.levels[1] <= 17):
        parser.error('Expected Korea bounds and levels 11..17')
    if not args.version or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in args.version):
        parser.error('Invalid version')
    if args.display_ttl_hours is not None and not 0 < args.display_ttl_hours <= 168:
        parser.error('Display snapshot lifetime must be greater than zero and at most 168 hours')
    sys.path.insert(0, str(args.site_root.resolve()))
    from sitecontextagent.terrain.dem import _heights_at, DEM_CRS
    import rasterio
    from pyproj import Transformer
    folder = args.output / args.version
    folder.mkdir(parents=True, exist_ok=True)
    catalog_path = args.output / 'catalog.json'
    old = json.loads(catalog_path.read_text(encoding='utf-8')) if catalog_path.exists() else {}
    if old and old.get('version') != args.version:
        parser.error('Use a separate output directory for a different snapshot')
    tiles = set(old.get('tiles', []))
    published_count = len(tiles)
    source = {'vrt_sha256': hashlib.sha256(args.dem.read_bytes()).hexdigest(),
              'sampler': 'SiteContext terrain.dem._heights_at', 'crs': DEM_CRS}
    if args.display_ttl_hours is not None:
        old['displaySnapshot'] = {key: source[key] for key in ('vrt_sha256', 'sampler')}
        old['displaySnapshot']['expiresAt'] = int((time.time() + args.display_ttl_hours * 3600) * 1000)
        published_count = -1
    transform = Transformer.from_crs('EPSG:4326', DEM_CRS, always_xy=True)
    completed = reused = legacy_reused = 0
    failed = []
    started = time.monotonic()

    def checkpoint(state):
        nonlocal published_count
        for item in source['files']:
            stat = Path(item['path']).stat()
            if stat.st_size != item['size'] or stat.st_mtime_ns != item['mtime_ns']:
                raise ValueError('DEM source changed during publication; stop and create a new snapshot')
        if len(tiles) != published_count or not catalog_path.exists():
            atomic_json(catalog_path, {**old, 'version': args.version, 'grid': 'Cesium.GeographicTilingScheme',
                        'size': 33, 'source': old.get('source', 'SiteContext installed NGII DEM; incomplete grids excluded'),
                        'tiles': sorted(tiles)})
            published_count = len(tiles)
        atomic_json(args.output / 'local-bake-progress.json', {'state': state, 'bounds': args.bounds,
                    'levels': args.levels, 'completed': completed, 'reused': reused, 'legacyReused': legacy_reused, 'missing': len(failed),
                    'publishedTotal': len(tiles), 'elapsedSeconds': round(time.monotonic() - started, 1), 'source': source})

    with rasterio.open(args.dem) as raster:
        if raster.crs.to_string() != DEM_CRS:
            parser.error('DEM CRS must match the SiteContext sampler')
        source['files'] = [{'path': str(Path(f).resolve()), 'size': Path(f).stat().st_size,
                            'mtime_ns': Path(f).stat().st_mtime_ns} for f in raster.files if Path(f).resolve() != args.dem.resolve()]
        manifest = folder / 'local-source.json'
        if manifest.exists() and json.loads(manifest.read_text(encoding='utf-8')) != source:
            raise ValueError('Snapshot DEM provenance changed; use a new output directory/version')
        atomic_json(manifest, source)
        for level, x, y in tile_keys(args.bounds, *args.levels):
            key = f'{level}/{x}/{y}'
            path = folder / f'{level}-{x}-{y}.json'
            try:
                saved = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
            except (ValueError, OSError):
                saved = {}
            if valid_tile(saved):
                # Earlier HTTP-generated files have no dataset receipt. Preserve
                # them explicitly as legacy, never attribute them to this DEM.
                if verify_resume_source(saved, source):
                    legacy_reused += 1
                tiles.add(key)
                reused += 1
            else:
                points = grid_points(level, x, y)
                xx, yy = transform.transform(*zip(*points))
                heights = _heights_at(raster, list(zip(xx, yy)))
                if any(h is None for h in heights):
                    failed.append(key)
                else:
                    tile = {'size': 33, 'heights': [round(h, 2) for h in heights],
                            'sampledAt': datetime.now(timezone.utc).isoformat(), 'dataset': {
                                'vrt_sha256': source['vrt_sha256'], 'sampler': source['sampler']}}
                    if not valid_tile(tile):
                        raise ValueError(f'Invalid sampled grid {key}')
                    atomic_json(path, tile)
                    tiles.add(key)
                    completed += 1
            if (completed + reused + len(failed)) % 100 == 0:
                checkpoint('running')
                print(f'Published {completed}; reused {reused}; missing {len(failed)}', flush=True)
    checkpoint('finished-with-gaps' if failed else 'complete')
    atomic_json(args.output / 'local-bake-report.json', {'bounds': args.bounds, 'levels': args.levels,
                'completed': completed, 'reused': reused, 'legacyReused': legacy_reused, 'missing': failed, 'source': source})
    print(f'Finished: published {completed}; reused {reused}; missing {len(failed)}', flush=True)
    return 2 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
