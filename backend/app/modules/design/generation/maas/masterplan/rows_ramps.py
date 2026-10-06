"""Ramp builders off a row-and-aisle field: in line, straight off the aisle, and turning."""
from __future__ import annotations

import math

from shapely.geometry import LineString, box
from shapely.ops import substring

from backend.app.modules.design.generation.maas.masterplan.geometry import EPS


def _inline_at_aisle_end(xs, y, aisle, xdir, spec, ax0, ax1):
    """The ramp CONTINUES the aisle instead of leaving it sideways.

    This is how the reference scheme reads as one roadway: you enter, drive the row, and the ramp is
    the far end of that same drive (고산 ALT1 배치도 - the 지하주차장 mouth is in line with the run,
    not hung off its side).  A ramp that leaves at right angles against the building face reads as an
    appendage and makes the ground and basement plans look unrelated.
    """
    w, length, landing = spec["width_m"], spec["length_m"], spec["landing_m"]
    if w > aisle + EPS:            # an in-line ramp cannot be wider than the aisle it continues
        return None
    y0 = y + (aisle - w) / 2       # centred on the aisle
    if xdir > 0:                   # continue past the high-x end
        x0 = ax1
        poly = box(x0, y0, x0 + length, y0 + w)
        upper = box(x0, y0, x0 + landing, y0 + w)
        lower = box(x0 + length - landing, y0, x0 + length, y0 + w)
        center = LineString([(x0 + p["distance_m"], y0 + w / 2, p["z_m"]) for p in spec["profile"]])
    else:
        x0 = ax0
        poly = box(x0 - length, y0, x0, y0 + w)
        upper = box(x0 - landing, y0, x0, y0 + w)
        lower = box(x0 - length, y0, x0 - length + landing, y0 + w)
        center = LineString([(x0 - p["distance_m"], y0 + w / 2, p["z_m"]) for p in spec["profile"]])
    return poly, upper, lower, center, spec, None


def _straight_off_aisle(xs, y, aisle, ydir, spec):
    """The ramp leaves the aisle at right angles and runs straight (the existing arrangement)."""
    w, length, landing = spec["width_m"], spec["length_m"], spec["landing_m"]
    if ydir > 0:
        poly = box(xs, y + aisle, xs + w, y + aisle + length)
        upper = box(xs, y + aisle, xs + w, y + aisle + landing)
        lower = box(xs, y + aisle + length - landing, xs + w, y + aisle + length)
        center = LineString([(xs + w / 2, y + aisle + p["distance_m"], p["z_m"]) for p in spec["profile"]])
    else:
        poly = box(xs, y - length, xs + w, y)
        upper = box(xs, y - landing, xs + w, y)
        lower = box(xs, y - length, xs + w, y - length + landing)
        center = LineString([(xs + w / 2, y - p["distance_m"], p["z_m"]) for p in spec["profile"]])
    return poly, upper, lower, center, spec, None


def _curved_at_aisle_end(y, aisle, xdir, hand, spec, min_radius, ax0, ax1, *, lead_fraction=0.5, turn_deg=90.0):
    """The ramp leaves IN LINE with the aisle and then turns - what practice actually draws.

    고산 ALT1/ALT2 both continue the surface drive past the last stall and turn the ramp down; a
    straight in-line run rarely fits a Korean parcel, which is why the reference scheme curves it.
    Heading starts along the aisle axis, so the drive reads as one roadway rather than an appendage.
    """
    start = (ax1 if xdir > 0 else ax0, y + aisle / 2)
    head = 0.0 if xdir > 0 else math.pi
    return _curved_ramp(start, head, hand, spec, min_radius, lead_fraction=lead_fraction, turn_deg=turn_deg)


def _curved_ramp(start, head, hand, spec, min_radius, *, lead_fraction=0.5, turn_deg=90.0, steps=32):
    """Lead straight, one arc on a fixed radius, tail straight; the centreline is exactly the ramp run.

    The arc is drawn as `steps` chords on the true circle, so every arc vertex sits at `radius` from
    the centre and the drawn turn is never tighter than the rule. Lead and tail absorb the run left
    after the CHORD length (not the ideal arc length): the centreline then measures exactly
    `spec["length_m"]`, and every grade station of `spec["profile"]` is a vertex carrying its own z.
    `lead_fraction` is the share of the slack straight placed before the turn (0 = turn right after
    the upper landing); `turn_deg` is the turn angle.
    """
    w, total, landing = spec["width_m"], spec["length_m"], spec["landing_m"]
    theta = math.radians(turn_deg)
    radius = (min_radius or 0.0) + w / 2
    if radius <= 0 or not 0 < theta <= math.pi or not 0.0 <= lead_fraction <= 1.0:
        return None
    arc_len = steps * 2 * radius * math.sin(theta / (2 * steps))
    slack = total - arc_len - 2 * landing
    if slack < -EPS:
        return None
    slack = max(slack, 0.0)
    lead = landing + slack * lead_fraction
    tail = total - arc_len - lead
    p0 = (start[0] + math.cos(head) * lead, start[1] + math.sin(head) * lead)
    centre = (p0[0] + math.cos(head + hand * math.pi / 2) * radius, p0[1] + math.sin(head + hand * math.pi / 2) * radius)
    a0 = math.atan2(p0[1] - centre[1], p0[0] - centre[0])
    arc = [(centre[0] + radius * math.cos(a0 + hand * theta * i / steps),
            centre[1] + radius * math.sin(a0 + hand * theta * i / steps)) for i in range(steps + 1)]
    end_head = head + hand * theta
    p1 = arc[-1]
    p2 = (p1[0] + math.cos(end_head) * tail, p1[1] + math.sin(end_head) * tail)
    spine = LineString([start, p0, *arc[1:], p2])
    poly = spine.buffer(w / 2, cap_style=2, join_style=1, quad_segs=32)
    # THE LANDING IS THE FLAT PART, NOT THE WHOLE STRAIGHT. `lead`/`tail` carry the landing plus a
    # share of the slack run, and that slack is already on grade in `spec["profile"]`. Handing the whole
    # straight out as a landing let the drive be drawn onto the slope, which is why every curved-ramp
    # scheme failed `drive_obstructions` at all three levels and no curved ramp ever reached a sheet.
    upper = substring(spine, 0, landing).buffer(w / 2, cap_style=2, join_style=1, quad_segs=32)
    lower = substring(spine, spine.length - landing, spine.length).buffer(
        w / 2, cap_style=2, join_style=1, quad_segs=32)
    return poly, upper, lower, _graded_centerline(spine, spec["profile"]), spec, radius


def _graded_centerline(spine, profile):
    """The 2-D spine with every grade station inserted as a vertex and z read by run distance."""
    pts = list(spine.coords)
    run = [0.0]
    for a, b in zip(pts, pts[1:]):
        run.append(run[-1] + math.dist(a, b))
    stations = sorted((float(p["distance_m"]), float(p["z_m"])) for p in profile)
    merged = list(zip(run, pts))
    for d, _ in stations:
        if any(abs(d - r) <= 1e-9 for r, _ in merged):
            continue
        for (r0, a), (r1, b) in zip(merged, merged[1:]):
            if r0 < d < r1:
                t = (d - r0) / (r1 - r0)
                merged.append((d, (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)))
                break
        merged.sort(key=lambda item: item[0])

    def z_at(d):
        for (d0, z0), (d1, z1) in zip(stations, stations[1:]):
            if d <= d1 + 1e-9:
                return z0 if d1 - d0 <= EPS else z0 + (z1 - z0) * (d - d0) / (d1 - d0)
        return stations[-1][1]

    return LineString([(x, yy, z_at(d)) for d, (x, yy) in merged])

def _curved_off_aisle(xs, y, aisle, ydir, hand, spec, min_radius):
    """The ramp leaves the aisle, turns 90 degrees and runs back parallel to it.

    This is the arrangement the reference scheme draws where a straight run would cross the plate:
    a quarter turn on a fixed radius with straight lead and tail.  The radius is the rule's minimum
    inner radius plus half the band; the remaining run length is split between lead and tail.
    """
    start = (xs + spec["width_m"] / 2, y + aisle if ydir > 0 else y)
    head = math.pi / 2 if ydir > 0 else -math.pi / 2
    return _curved_ramp(start, head, hand, spec, min_radius)
