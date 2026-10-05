"""Metric geometry utilities; no statutory limits live here."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from shapely.affinity import scale, translate
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, mapping, shape

EPS = 1e-6  # Numerical tolerance in metres, not a legal relaxation.


def number(value, name, *, minimum=0.0, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{name} is outside the supported range")
    return float(value)


def polygon(value, name="polygon"):
    geom = shape(value) if isinstance(value, dict) else value
    if not isinstance(geom, (Polygon, MultiPolygon)) or not geom.is_valid or geom.is_empty:
        raise ValueError(f"{name} must be a nonempty valid polygon")
    if not all(math.isfinite(x) for x in geom.bounds):
        raise ValueError(f"{name} has nonfinite coordinates")
    return geom


def parts(geom):
    if isinstance(geom, Polygon):
        return [geom] if not geom.is_empty else []
    return [p for g in getattr(geom, "geoms", ()) for p in parts(g)]


def union_or_empty(geometries):
    from shapely.ops import unary_union
    return unary_union(list(geometries)) if geometries else GeometryCollection()


def feature(layer, geom, level=0, **props):
    return {"type": "Feature", "geometry": mapping(geom),
            "properties": {"layer": layer, "level": level, **props}}


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def footprint_inside(parcel, target, *, direction=None, align_to=None, module_depth_m=None):
    """Propose a contained footprint, preserving the caller's area ceiling.

    Clipping a generated proposal is allowed; authored geometry is validated separately.
    No setback or minimum footprint is invented here.

    `align_to` (a line on the parcel boundary, e.g. the front road edge): the
    proposal is a rectangle parallel to that edge, pushed against the buildable
    limit on that side - how a practice scheme sits a public building on its
    highest-hierarchy road. Without it the centred oriented box is used.
    """
    parcel = polygon(parcel, "buildable boundary")
    target = number(target, "target footprint")
    if target == 0:
        return Polygon()
    if align_to is not None and not align_to.is_empty:
        aligned = _aligned_footprint(parcel, target, align_to, module_depth_m=module_depth_m)
        if aligned is not None and aligned.area >= 0.98 * min(target, parcel.area):
            return aligned
    candidates = []
    for host in parts(parcel):
        obb = host.minimum_rotated_rectangle
        ratio = min(1.0, math.sqrt(target / obb.area))
        seed = scale(obb, ratio, ratio, origin=obb.centroid)
        anchors = [host.centroid, host.representative_point()]
        # Clipped OBB candidates maintain legality even for deep courtyards.
        for anchor in anchors:
            moved = translate(seed, anchor.x-seed.centroid.x, anchor.y-seed.centroid.y)
            candidates.extend(parts(moved.intersection(host)))
        # The entire connected host can be reduced without crossing a concavity
        # only after intersecting it again. Never return an untested fallback box.
        candidates.extend(parts(host.intersection(seed)))
    candidates = [p for p in candidates if p.area <= target + EPS and parcel.buffer(EPS).covers(p)]
    if not candidates:
        return Polygon()
    def rank(p):
        alignment = (p.centroid.x*direction[0]+p.centroid.y*direction[1]) if direction else 0
        return (p.area, alignment)
    return max(candidates, key=rank)


def _aligned_footprint(parcel, target, edge, *, module_depth_m=None):
    """Rectangle parallel to `edge`, flush with the buildable limit on the edge's side.

    In a frame where the edge is horizontal, the proposal is a box of some width
    along the edge whose depth is found by bisection so that the part inside the
    buildable boundary has exactly the target area (the area inside grows
    monotonically with depth). Several widths are tried, widest first, so a
    narrow frontage yields a bar along the front rather than a deep block.
    """
    from shapely.affinity import rotate as _rotate
    coords = list(edge.coords)
    (x0, y0), (x1, y1) = coords[0], coords[-1]
    angle = math.degrees(math.atan2(y1 - y0, x1 - x0))
    pivot = (0.0, 0.0)
    host = _rotate(parcel, -angle, origin=pivot)
    line = _rotate(edge, -angle, origin=pivot)
    ey = line.centroid.y
    minx, miny, maxx, maxy = host.bounds
    inward = 1.0 if host.centroid.y >= ey else -1.0
    front_y = miny if inward > 0 else maxy
    span = maxy - miny
    lminx, _, lmaxx, _ = line.bounds
    line_cx = (lminx + lmaxx) / 2
    widths = [maxx - minx, (lmaxx - lminx) * 1.5, lmaxx - lminx, (lmaxx - lminx) * 0.8, math.sqrt(target) * 1.4, math.sqrt(target)]
    if module_depth_m:
        # A plate that carries parking is sized in whole parking modules, not in whatever depth
        # happens to hit the target area.  The reference scheme's two plates are both about two
        # modules deep (33.1 and 30.4 m against a 16.0 m module) and ours was 1.50, which is the
        # worst possible number: one module fits and the remaining half module carries nothing.
        # Widths that make the depth n * module come first, deepest plate first.
        module = float(module_depth_m)
        quantised = [target / (n * module) for n in (3, 2, 1) if target / (n * module) > 0]
        widths = [w for w in quantised if w <= (maxx - minx) + EPS] + widths
    best = None

    def inside(width, depth):
        cx = min(max(line_cx, minx + width / 2), maxx - width / 2)
        y_from, y_to = (front_y, front_y + depth) if inward > 0 else (front_y - depth, front_y)
        box_ = Polygon([(cx - width/2, y_from), (cx + width/2, y_from), (cx + width/2, y_to), (cx - width/2, y_to)])
        return box_.intersection(host)

    for width in widths:
        if width <= 0 or width > (maxx - minx) + EPS:
            continue
        lo, hi = 0.0, span
        if inside(width, hi).area < target - EPS:
            continue  # this width cannot reach the target even at full depth
        for _ in range(40):
            mid = (lo + hi) / 2
            if inside(width, mid).area < target:
                lo = mid
            else:
                hi = mid
        clipped = inside(width, hi)
        for part in parts(clipped):
            if part.area <= target + EPS and host.buffer(EPS).covers(part):
                if best is None or part.area > best.area:
                    best = part
        if best is not None and best.area >= 0.98 * target:
            break
    if best is None:
        return None
    return _rotate(best, angle, origin=pivot)
