"""Bounded map carriageways from the installed NGII source index."""
import asyncio
import hashlib
import importlib.util
import json
import math
import os
import time
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path


class RoadsUnavailable(RuntimeError):
    pass


def _stamp(path):
    stat = path.stat()
    return str(path), stat.st_size, stat.st_mtime_ns


@lru_cache(maxsize=4)
def _resolver(path, stamp):
    spec = importlib.util.spec_from_file_location('_editor_ngii_map_index', path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(Path(path).read_bytes(), path, 'exec'), module.__dict__)
    return module


def _identity(root, folders):
    paths = [root / 'index/registry.json', root / 'index/ngii_index_resolver.py']
    for folder in folders:
        if not folder.is_relative_to(root) or (folder / '.sitecontext-install-incomplete.json').exists():
            raise RoadsUnavailable('NGII road source installation is incomplete')
        paths.extend(sorted(p for p in folder.glob('N3L_A0020000*') if p.is_file()))
    return tuple(_stamp(p) for p in paths)


def _prepare(lat, lon, radius_m):
    from pyproj import Transformer
    root = Path(os.environ.get('NGII_MAP_DATA_ROOT') or
                Path(__file__).resolve().parents[5] / 'data').resolve()
    path = root / 'index/ngii_index_resolver.py'
    try:
        # Do not let the shared resolver build a registry during a map request.
        _stamp(root / 'index/registry.json')
        owner = _resolver(str(path), _stamp(path))
        x, y = Transformer.from_crs(4326, 5186, always_xy=True).transform(lon, lat)
        bbox = Transformer.from_crs(5186, 4326, always_xy=True).transform_bounds(
            x - radius_m, y - radius_m, x + radius_m, y + radius_m)
        folders = tuple(sorted({Path(f).resolve() for f in owner.find_sheets_for_bbox(*bbox)}))
        identity = _identity(root, folders)
        return root, owner, folders, identity, bbox, (x, y)
    except RoadsUnavailable:
        raise
    except Exception as exc:
        raise RoadsUnavailable(f'Local NGII road index unavailable: {type(exc).__name__}') from exc


def _number(row, names):
    for name in names:
        value = row.get(name)
        if value is None:
            continue
        try:
            value = float(value)
        except (ValueError, TypeError, OverflowError):
            continue
        if math.isfinite(value) and value > 0:
            return value
    return None


def _read(prepared, radius_m):
    from pyproj import Transformer
    from shapely.geometry import Point, mapping
    from shapely.ops import transform
    root, owner, folders, identity, bbox, center = prepared
    features, seen, no_width, scanned = [], set(), 0, 0
    window = Point(*center).buffer(radius_m)
    to_deg = Transformer.from_crs(5186, 4326, always_xy=True).transform
    try:
        for folder in folders:
            frame = owner.read_layer(folder, 'N3L_A0020000', 'roads', bbox=bbox)
            if frame is None or frame.empty:
                continue
            scanned += len(frame)
            if scanned > 10000:
                raise RoadsUnavailable('Road viewport exceeds feature budget; request a smaller radius')
            for _, row in frame.to_crs(5186).iterrows():
                geometry = row.geometry
                if geometry is None or geometry.is_empty or not geometry.intersects(window):
                    continue
                if geometry.geom_type not in ('LineString', 'MultiLineString'):
                    continue
                ident = row.get('UFID', row.get('ufid'))
                ident = str(ident) if ident is not None and str(ident) not in ('nan', '<NA>', '') else hashlib.sha256(geometry.wkb).hexdigest()
                if ident in seen:
                    continue
                seen.add(ident)
                lanes = _number(row, ('차로수', 'lanes', 'rdln'))
                road_width = _number(row, ('도로폭', 'width_m', 'rvwd'))
                if lanes is None:
                    no_width += 1
                    continue
                width = lanes * 3.25
                measured = road_width is not None and road_width <= width
                if measured:
                    width = road_width
                surface = geometry.buffer(width / 2, cap_style='flat').intersection(window)
                if surface.is_empty:
                    continue
                features.append({'type': 'Feature', 'geometry': mapping(transform(to_deg, surface)),
                                 'properties': {'layer': 'carriageway', 'width_m': round(width, 2),
                                                'width_status': 'measured' if measured else 'estimated',
                                                'source': 'NGII installed 1:5,000 road centreline', 'id': ident}})
        if _identity(root, folders) != identity:
            raise RoadsUnavailable('NGII road source changed while reading; retry')
    except RoadsUnavailable:
        raise
    except Exception as exc:
        raise RoadsUnavailable(f'Local NGII road read failed: {type(exc).__name__}') from exc
    if not seen:
        return {'status': 'needs_evidence', 'detail': 'roads', 'missing_evidence': ['roads'],
                'reason': 'No installed road centrelines in this viewport; this does not establish absence of roads'}
    gaps = []
    if no_width:
        gaps.append(f'carriageways: {no_width} centreline(s) without lanes left out')
    return {'status': 'ok', 'detail': 'roads',
            'features': {'type': 'FeatureCollection', 'features': features},
            'counts': {'carriageways': len(features)}, 'gaps': gaps,
            'record': {'roads': {'owner': 'NGII source index / editor map display',
                                 'revision': hashlib.sha256(repr(identity).encode()).hexdigest(),
                                 'completeness': 'installed-sheets-only',
                                 'limitations': ['Survey currency and nationwide road completeness are not guaranteed'],
                                 'files': [{'file': str(Path(p).relative_to(root)), 'bytes': size, 'mtime_ns': stamp}
                                           for p, size, stamp in identity],
                                 'method': 'centreline buffered by half of lanes x 3.25 m, capped by surveyed whole-road width; clipped to viewport'}}}


class RoadDisplay:
    def __init__(self):
        self.cache = OrderedDict()
        self.pending = {}
        self.read_slots = asyncio.Semaphore(2)
        self.cache_bytes = 0

    async def _sample(self, key, prepared, radius_m):
        try:
            async with self.read_slots:
                result = await asyncio.to_thread(_read, prepared, radius_m)
            if result['status'] == 'ok':
                size = len(json.dumps(result))
                if size <= 4_000_000:
                    self.cache[key] = (time.monotonic(), result, size)
                    self.cache_bytes += size
                    while len(self.cache) > 64 or self.cache_bytes > 32_000_000:
                        self.cache_bytes -= self.cache.popitem(last=False)[1][2]
            return result
        finally:
            self.pending.pop(key, None)

    async def get(self, lat, lon, radius_m):
        prepared = await asyncio.to_thread(_prepare, lat, lon, radius_m)
        key = (prepared[3], lat, lon, radius_m)
        cached = self.cache.get(key)
        if cached:
            if time.monotonic() - cached[0] < 900:
                self.cache.move_to_end(key)
                return cached[1]
            self.cache_bytes -= self.cache.pop(key)[2]
        if key not in self.pending:
            if len(self.pending) >= 16:
                raise RoadsUnavailable('Road display is busy; retry this viewport')
            task = asyncio.create_task(self._sample(key, prepared, radius_m))
            self.pending[key] = task
            task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
        return await asyncio.shield(self.pending[key])
