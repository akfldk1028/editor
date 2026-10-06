"""Search-effort helpers for `rows.row_candidates`: band offsets and stall adjacency."""
from __future__ import annotations

from shapely import STRtree
from shapely.geometry import box

from backend.app.modules.design.generation.maas.masterplan.geometry import EPS, parts


def _adjacent_pairs(polygons, tolerance):
    """Unordered pairs of stalls within `tolerance` of each other, through a spatial index.

    The same count as testing every pair, without the O(n^2) distance calls that took 84 % of a
    450-stall search.
    """
    if len(polygons) < 2:
        return 0
    left, right = STRtree(polygons).query(polygons, predicate="dwithin", distance=tolerance)
    return int((left < right).sum())


def _band_offsets(g_ground, aisle, stall_w, stall_l, step, *, straight_entry, limit=None):
    """Aisle-band offsets (y of the band's low edge) for one orientation.

    The full sweep steps `step` from the lowest position that leaves a row on both sides (or both
    edges, for a straight-entry study). A parcel too shallow for a double-loaded module still takes
    ONE loaded row, so its two edge positions are offered instead of nothing.

    `limit` bounds a large envelope: offsets whose band holds no straight two-bay run are dropped
    first (they cost a full evaluation and can yield nothing), then a sample is kept - every module
    pitch offset the tiling needs, thinned evenly, and the one-band positions spread evenly over the
    rest including both extremes.
    """
    minx, miny, maxx, maxy = g_ground.bounds
    y = miny if straight_entry else miny + stall_l
    far_margin = 0 if straight_entry else stall_l
    offsets = []
    while y + aisle + far_margin <= maxy + EPS:
        offsets.append(y)
        y += step
    if not offsets and not straight_entry and maxy - aisle >= miny - EPS:
        offsets = list(dict.fromkeys((miny, maxy - aisle)))
    if limit is None or len(offsets) <= limit:
        return offsets

    def usable(yy):
        band = box(minx - 1, yy, maxx + 1, yy + aisle).intersection(g_ground)
        return any(part.area >= aisle * 2 * stall_w
                   and part.area >= 0.9 * (part.bounds[2] - part.bounds[0]) * aisle for part in parts(band))

    offsets = [yy for yy in offsets if usable(yy)]
    if len(offsets) <= limit:
        return offsets

    def spread(values, count):
        if count <= 0 or not values:
            return []
        if len(values) <= count:
            return list(values)
        if count == 1:
            return [values[0]]
        return [values[round(i * (len(values) - 1) / (count - 1))] for i in range(count)]

    module = 2 * stall_l + aisle
    pitch = [yy for yy in offsets if yy - offsets[0] < module - EPS]
    tiling = spread(pitch, limit // 2)
    rest = [yy for yy in offsets if yy not in set(tiling)]
    return sorted(set(tiling) | set(spread(rest, limit - len(tiling))))
