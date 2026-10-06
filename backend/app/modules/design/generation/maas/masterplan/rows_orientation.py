"""Aisle directions for the row-and-aisle engine (`rows.row_candidates`)."""
from __future__ import annotations

import math

from shapely.geometry import LineString

from backend.app.modules.design.generation.maas.masterplan.geometry import parts


def _lines(geom):
    if geom is None:
        return []
    return [geom] if isinstance(geom, LineString) else list(getattr(geom, "geoms", ()))


def _segments(lines):
    for line in _lines(lines):
        for a, b in zip(line.coords, list(line.coords)[1:]):
            if math.dist(a[:2], b[:2]) > 0.5:
                yield LineString([a[:2], b[:2]])


def _angle(seg: LineString) -> float:
    (x0, y0), (x1, y1) = seg.coords[0], seg.coords[-1]
    return math.degrees(math.atan2(y1 - y0, x1 - x0)) % 180


def orientation_candidates(site, footprint, frontage, *, limit=8):
    """Aisle directions worth trying: every road edge, site edge and footprint edge direction (deduplicated to 1 deg)."""
    angles = []
    for seg in _segments(frontage):
        angles.append(_angle(seg))
    for poly in (site, footprint):
        if poly is None or poly.is_empty:
            continue
        # A generated mass footprint can come back in several pieces; reading `.exterior` off a
        # MultiPolygon raises, and it did - on the first run where the footprint was small enough to
        # split, which is exactly the practice-scale case this engine is meant to serve.
        for part in parts(poly):
            coords = list(part.exterior.coords)
            for a, b in zip(coords, coords[1:]):
                if math.dist(a, b) > 3.0:
                    angles.append(_angle(LineString([a, b])))
    out = []
    for ang in angles:
        if all(min(abs(ang - o), 180 - abs(ang - o)) > 1.0 for o in out):
            out.append(ang)
    # CAP THE FAN. Every edge over 3 m contributes a direction, so an irregular cadastral parcel
    # offers 20-40 of them and the whole y-sweep, ramp-sweep and tiling nest runs once per angle.
    # Practice lays bays parallel to the site's long dimension (CCDC), and the road edge decides the
    # entrance, so those are the directions worth spending on: the ones already listed that lie
    # closest to the frontage or to the minimum rotated rectangle's two axes come first, and the
    # tail is dropped. Order is preserved among the kept angles so existing results do not shuffle.
    if len(out) > limit:
        anchors = [_angle(max(_segments(frontage), key=lambda s: s.length))] if list(_segments(frontage)) else []
        if site is not None and not site.is_empty:
            box = site.minimum_rotated_rectangle
            coords = list(box.exterior.coords)
            anchors += [_angle(LineString([a, b])) for a, b in zip(coords, coords[1:])][:2]
        def near(ang):
            return min((min(abs(ang - a), 180 - abs(ang - a)) for a in anchors), default=0.0)
        keep = set(sorted(out, key=near)[:limit])
        out = [a for a in out if a in keep]
    return out
