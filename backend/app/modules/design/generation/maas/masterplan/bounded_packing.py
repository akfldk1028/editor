"""Bounded large-envelope adapter for the existing parking packer.

The original spine search remains the small-site path. On large envelopes it
can construct hundreds of thousands of identical stall cells before its output
limit applies. The row engine has a distributed, geometry-bounded search and
returns measured stalls, manoeuvre cells and connected aisle polygons. An empty
result is reported as empty geometry; it is never promoted to a parking pass.
"""
from __future__ import annotations

import math
from shapely.affinity import rotate, translate
from shapely import set_precision
from shapely.errors import GEOSException
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.masterplan.geometry import EPS, parts
from backend.app.modules.design.generation.maas.masterplan.parking import pack_level as _pack_small_level, _principal_angles
from backend.app.modules.design.generation.maas.masterplan.rows import row_candidates


_LARGE_ENVELOPE_M2 = 10_000.0
_LEGACY_CELL_WORK_BUDGET = 50_000  # Search operations, never a design/legal limit.


def _legacy_cell_work(envelope, anchors, rules, preferred_angle, allowed_angles):
    """Conservative cell-iteration estimate before any legacy geometry search.

    The legacy engine scans each rotated bounding box, not polygon area, and
    trims demand only after generating cells. Count its axes, spine choices,
    three offsets and both sides of each aisle without constructing any cells.
    """
    width = min(float(rules['stall_width_m']), float(rules['accessible_width_m']))
    step = 2 * max(float(rules['stall_length_m']), float(rules['accessible_length_m'])) + float(rules['aisle_width_m'])
    if not math.isfinite(width) or not math.isfinite(step) or width <= 0 or step <= 0:
        return math.inf
    angles = list(dict.fromkeys(allowed_angles if allowed_angles is not None else
                               [preferred_angle, preferred_angle+90, 0, 90, *_principal_angles(envelope)]))
    work = 0
    for angle in angles:
        x0, y0, x1, y1 = rotate(envelope, -angle, origin=(0, 0)).bounds
        work += (2 + 2*len(anchors)) * 3 * 2 * math.ceil((x1-x0)/width) * (math.ceil((y1-y0)/step)+1)
        if work > _LEGACY_CELL_WORK_BUDGET:
            break
    return work


def _anchor_lines(anchors):
    lines = []
    for anchor in anchors or ():
        if anchor is None or anchor.is_empty:
            continue
        boundary = anchor.boundary if isinstance(anchor, Polygon) else anchor
        if isinstance(boundary, LineString):
            lines.append(boundary)
        else:
            lines.extend(line for line in getattr(boundary, "geoms", ())
                         if isinstance(line, LineString) and not line.is_empty)
    return lines


def _empty(search_count=0):
    return {"stalls": [], "drive": Polygon(), "provided": 0,
            "accessible": 0, "search_count": search_count}


def _width_connected(candidate, anchors, aisle_width):
    """Require a connected full-width vehicle path, not just touching polygons.

    Erosion removes pinched connectors. Re-expanding a road-served component
    identifies the manoeuvre cells reachable through that component. A small
    tolerance keeps an exactly rule-width rectangular aisle from disappearing.
    This is a conservative clearance check, not a swept-path certificate.
    """
    tolerance = max(EPS, 1e-5)
    radius = float(aisle_width) / 2
    erosion = Polygon()
    if not candidate['drive'].is_empty:
        # GEOS can collapse exact-width branches even when another component
        # survives. Evaluate in a local principal frame, not world coordinates.
        try:
            corners = list(candidate['drive'].minimum_rotated_rectangle.exterior.coords)
            a, b = max(zip(corners, corners[1:]), key=lambda pair: math.dist(*pair))
            angle = math.degrees(math.atan2(b[1]-a[1], b[0]-a[0]))
            origin = candidate['drive'].centroid
            local = translate(candidate['drive'], xoff=-origin.x, yoff=-origin.y)
            aligned = rotate(local, -angle, origin=(0, 0)).simplify(1e-9)
            if not aligned.is_valid:
                aligned = aligned.buffer(0)
            if aligned.is_empty or not aligned.is_valid:
                raise GEOSException('invalid principal evaluation frame')
            aligned = set_precision(aligned, 1e-9)
            if aligned.is_empty or not aligned.is_valid:
                raise GEOSException('invalid precision-normalized evaluation frame')
            offset = max(0, radius-tolerance)
            minx, miny, maxx, maxy = aligned.bounds
            rectangle = box(minx, miny, maxx, maxy)
            if (aligned.symmetric_difference(rectangle).area <= 1e-9
                    and maxx-minx > 2*offset and maxy-miny > 2*offset):
                # Exact rectangle erosion avoids GEOS's near-zero-area heuristic;
                # it uses the same offset and never enlarges the feasible core.
                eroded = box(minx+offset, miny+offset, maxx-offset, maxy-offset)
            else:
                eroded = aligned.buffer(-offset)
            erosion = translate(rotate(eroded, angle, origin=(0, 0)), xoff=origin.x, yoff=origin.y)
        except GEOSException:
            # A failed auxiliary frame never aborts or replaces the original
            # geometry's independent full-width test.
            erosion = Polygon()
    # On irregular envelopes the principal frame need not match an aisle.
    # Keep independently valid original-frame components too; never union
    # residuals from different frames into a fictitious connecting passage.
    cores = parts(erosion) + parts(candidate['drive'].buffer(-max(0, radius-tolerance)))
    for core in cores:
        reachable = core.buffer(radius + tolerance)
        served = False
        for anchor in anchors:
            if anchor is None or anchor.is_empty:
                continue
            # Independently rotated/clipped frontage may sit a few ulps outside
            # its coincident drive edge. Use only the existing metric tolerance.
            contact = candidate["drive"].buffer(tolerance).intersection(anchor)
            needed = min(float(aisle_width), anchor.length)
            if (core.distance(anchor) <= radius + tolerance and
                    not contact.is_empty and contact.length + tolerance >= needed):
                served = True
                break
        if served and all(reachable.distance(stall["front"].centroid) <= tolerance
                          for stall in candidate["stalls"]):
            return True
    return False


def pack_level(envelope, anchors, rules, required, accessible=0, *, preferred_angle=0, require_full_width=False, allowed_angles=None, preserve_banks=False, entry_clearance_m=None):
    """Pack one level, preserving the original function signature and evidence."""
    if envelope.is_empty or required <= 0:
        return _empty()
    if (entry_clearance_m is None and envelope.area < _LARGE_ENVELOPE_M2 and
            _legacy_cell_work(envelope, anchors, rules, preferred_angle, allowed_angles) <= _LEGACY_CELL_WORK_BUDGET):
        # The legacy packer has no mixed expanded-bay allocator. Conservatively
        # draw every non-accessible bay at the larger dimensions when a share is
        # required; do not relabel standard-size geometry or alter the snapshot.
        expanded = (float(rules.get("expanded_min_share") or 0) > 0
                    and rules.get("expanded_width_m")
                    and rules.get("expanded_length_m"))
        packing_rules = rules
        if expanded:
            packing_rules = {
                **rules,
                "stall_width_m": max(float(rules["stall_width_m"]), float(rules["expanded_width_m"])),
                "stall_length_m": max(float(rules["stall_length_m"]), float(rules["expanded_length_m"])),
            }
        result = _pack_small_level(envelope, anchors, packing_rules, required, accessible,
                                   preferred_angle=preferred_angle, require_full_width=require_full_width,
                                   allowed_angles=allowed_angles, preserve_banks=preserve_banks)
        if expanded:
            for stall in result["stalls"]:
                if stall["type"] != "accessible":
                    stall["type"] = "expanded"
        # A separate longitudinal spine is unnecessary when a road/landing
        # already opens onto a single aisle. The legacy search requires room
        # for both and can return zero on a valid small one- or two-bay field.
        if not result['provided'] and required > 0 and not envelope.is_empty:
            lines = _anchor_lines(anchors)
            if lines:
                x0, y0, x1, y1 = envelope.bounds
                recovery_step = max(.5, max(x1-x0, y1-y0)/24.)
                direct = row_candidates(envelope, envelope, Polygon(), Polygon(), unary_union(lines),
                                        None, rules, required, accessible, field='single', limit=4,
                                        step=recovery_step, allowed_angles=allowed_angles, preserve_banks=preserve_banks)
                usable = [p for p in direct if _width_connected(p, anchors, rules['aisle_width_m'])
                          and envelope.buffer(EPS).covers(p['drive'])
                          and all(s['polygon'].intersection(p['drive']).area <= EPS for s in p['stalls'])]
                if usable:
                    best = max(usable, key=lambda p: (min(p['accessible'], accessible), p['provided'], -p['drive'].area))
                    result = {**best, 'search_count': result['search_count'] + best.get('search_count', 0)}
        return result

    anchor_lines = _anchor_lines(anchors)
    if not anchor_lines:
        return _empty()
    frontage = unary_union(anchor_lines)
    candidates = row_candidates(
        envelope,
        envelope,
        Polygon(),
        Polygon(),
        frontage,
        None,
        rules,
        required,
        accessible,
        field="auto",
        allowed_angles=allowed_angles,
        preserve_banks=preserve_banks,
        entry_clearance_m=entry_clearance_m,
    )
    # A landing can be a polygon inside the free floor while a surface road is
    # a line at its edge. In either case the selected drive must truly reach a
    # supplied anchor and every stall/manoeuvre cell must stay inside the host.
    host = envelope.buffer(EPS)
    usable = [candidate for candidate in candidates
              if any(candidate["drive"].distance(anchor) <= EPS for anchor in anchors)
              and host.covers(candidate["drive"])
              and all(host.covers(stall["polygon"]) and
                      candidate["drive"].buffer(EPS).covers(stall["front"])
                      for stall in candidate["stalls"])
              and _width_connected(candidate, anchors, rules["aisle_width_m"])]
    if not usable:
        return _empty(search_count=len(candidates))
    best = max(usable, key=lambda candidate: (
        min(candidate["accessible"], accessible),
        candidate["provided"],
        -candidate["drive"].area,
    ))
    return {
        "stalls": best["stalls"],
        "drive": best["drive"],
        "entrance": best.get("entrance"),
        "provided": best["provided"],
        "accessible": best["accessible"],
        "available_spaces": best["provided"],
        "angle_deg": best["angle_deg"],
        "bands": best["bands"],
        "cross_aisles": best["cross_aisles"],
        "dead_end_stalls": best["terms"]["dead_end_stalls"],
        "search_count": len(candidates),
        "pattern": "rows",
    }


__all__ = ["pack_level"]
