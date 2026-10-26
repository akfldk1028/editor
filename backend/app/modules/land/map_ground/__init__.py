"""Agent-independent map ground assembled from complete source responses."""
import asyncio
import json
from collections import OrderedDict

from .cache import SourceCache
from .compose import compose, normalize
from .sources import SourceUnavailable, bbox
from ..map_roads import RoadsUnavailable


class GroundDisplay:
    def __init__(self, roads, *, transport=None):
        self.roads = roads
        self.sources = SourceCache(transport=transport)
        self.pending = {}
        self.geometry_slots = asyncio.Semaphore(2)
        self.ready = OrderedDict()
        self.bytes = 0

    async def _produce(self, key):
        lat, lon, radius = key
        try:
            bounds = bbox(lat, lon, radius)
            replies = await asyncio.gather(self.sources.get('cadastre', bounds), self.sources.get('cover', bounds),
                                           self.roads.get(lat, lon, radius), return_exceptions=True)
            gaps, records, missing = [], {}, []
            ready = {}
            for kind, reply in zip(('cadastre', 'cover', 'roads'), replies):
                if isinstance(reply, Exception):
                    if isinstance(reply, (SourceUnavailable, RoadsUnavailable)):
                        gaps.append(str(reply))
                    else:
                        gaps.append(f'{kind}: source unavailable ({type(reply).__name__})')
                    missing.append(kind)
                else:
                    ready[kind] = reply
            roads = ready.get('roads') or {}
            if roads.get('status') != 'ok' and 'roads' not in missing:
                missing.append('roads')
                gaps.append('roads: ' + roads.get('reason', 'source unavailable'))
            gaps.extend(roads.get('gaps') or [])
            records['roads'] = (roads.get('record') or {}).get('roads') or {}
            revision = (key, tuple((kind, ready[kind]['record'].get('revision'),
                                   ready[kind]['record'].get('retrieved'))
                                  for kind in ('cadastre', 'cover') if kind in ready),
                        records['roads'].get('revision'))
            if not missing and revision in self.ready:
                self.ready.move_to_end(revision)
                return self.ready[revision][0]

            def assemble():
                normalized = {}
                for kind in ('cadastre', 'cover'):
                    if kind not in ready:
                        normalized[kind] = []
                        continue
                    try:
                        normalized[kind] = normalize(ready[kind], kind, lat, lon, radius)
                        records['ground' if kind == 'cadastre' else 'cover'] = {
                            **ready[kind]['record'], 'display_clip_bbox': list(bounds),
                            'display_geometry': 'viewport excerpt; not a whole-parcel geometry'}
                    except Exception as exc:
                        normalized[kind] = []
                        missing.append(kind)
                        gaps.append(f'{kind}: invalid source geometry ({type(exc).__name__})')
                return compose(normalized['cadastre'], normalized['cover'], roads,
                               parcels_available='cadastre' not in missing)
            async with self.geometry_slots:
                features, counts = await asyncio.to_thread(assemble)
            if 'cadastre' in missing and 'cover' not in missing:
                gaps.append('cover: shown without cadastral clipping because parcels are unavailable')
            result = {'status': 'ok' if len(missing) < 3 else 'needs_evidence', 'detail': 'full',
                      'features': features, 'counts': counts, 'gaps': gaps,
                      'missing_evidence': missing, 'record': records}
            if not missing:
                size = await asyncio.to_thread(lambda: len(json.dumps(result)))
                if size <= 8_000_000:
                    self.ready[revision] = result, size
                    self.bytes += size
                    while len(self.ready) > 64 or self.bytes > 32_000_000:
                        self.bytes -= self.ready.popitem(last=False)[1][1]
            return result
        finally:
            self.pending.pop(key, None)

    async def get(self, lat, lon, radius):
        key = lat, lon, radius
        if key not in self.pending:
            if len(self.pending) >= 16:
                raise SourceUnavailable('ground: display busy; retry viewport')
            task = asyncio.create_task(self._produce(key))
            self.pending[key] = task
            task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
        return await asyncio.shield(self.pending[key])
