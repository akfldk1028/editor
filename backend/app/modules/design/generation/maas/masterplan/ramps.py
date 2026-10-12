"""Ramp proposals - straight and curved - with explicit level landings and grade profiles.

The curved form is what practice draws where a straight run will not fit beside the plate: the
reference scheme (고산동 주민센터 ALT1/ALT2 지하1층) turns 90 degrees on a 9.75 m centreline radius
with a 6.50 m structural band, i.e. an inner radius of 6.8 m against the 6 m the 시행규칙 requires,
and the band width is exactly the 6.5 m the rule sets for a two-lane curved ramp.  Every value used
here comes from the rule snapshot; the 9.75 m is an observation, not a constant.
"""
from __future__ import annotations

import math
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import substring

from backend.app.modules.design.generation.maas.masterplan.geometry import EPS, number


def rectangle(origin, along, across, x0, y0, x1, y1):
    def point(x, y):
        return (origin[0]+across[0]*x+along[0]*y,
                origin[1]+across[1]*x+along[1]*y)
    return Polygon([point(x0,y0), point(x1,y0), point(x1,y1), point(x0,y1)])


def ramp_profile(rules, height, *, grade=None, width=None, run_length_m=None):
    """Landing - transition - main grade - transition - landing from the rule snapshot; None if the drop is too small.

    `grade`/`width` override the straight-ramp rule values for a curved run (제6조제1항제5호다목·라목).
    """
    width = number(width if width is not None else rules["ramp_width_m"], "ramp width", minimum=.1)
    grade = number(grade if grade is not None else rules["ramp_max_slope"], "ramp grade", minimum=.001, maximum=.5)
    transition = number(rules["transition_length_m"], "transition length")
    transition_grade = number(rules["transition_slope"], "transition grade", maximum=grade)
    landing = number(rules["aisle_width_m"], "landing manoeuvre space", minimum=.1)
    height = number(height, "basement floor height", minimum=.1)
    middle_drop = height - 2*transition*transition_grade
    if middle_drop <= EPS:
        return None
    middle = middle_drop/grade
    if run_length_m is not None:
        middle = max(middle, float(run_length_m) - 2*landing - 2*transition)
        # A longer path may use a gentler grade. Keep transitions no steeper
        # than the main run, without exceeding either snapshot limit.
        transition_grade = min(transition_grade, height/(middle + 2*transition))
        middle_drop = height - 2*transition*transition_grade
    distances = [0, landing, landing+transition, landing+transition+middle,
                 landing+2*transition+middle, 2*landing+2*transition+middle]
    zs = [0, 0, -transition*transition_grade,
          -height+transition*transition_grade, -height, -height]
    return {"profile": [{"distance_m": d, "z_m": z} for d, z in zip(distances, zs)], "distances": distances, "zs": zs,
            "length_m": distances[-1], "landing_m": landing, "width_m": width}


def ramp_candidates(site, frontage, obstacles, rules, height, *, limit=12, accept=None):
    """Return only ramps fully inside the excavation and clear of obstructions."""
    spec = ramp_profile(rules, height)
    if spec is None:
        return []
    width, distances, zs, profile, landing = spec["width_m"], spec["distances"], spec["zs"], spec["profile"], spec["landing_m"]
    height = number(height, "basement floor height", minimum=.1)
    lines = [frontage] if isinstance(frontage, LineString) else list(getattr(frontage, "geoms", ()))
    candidates = []

    def add(origin, along, across, orientation):
        """A ramp of `width` across and full length along, starting at `origin`."""
        area = rectangle(origin,along,across,0,0,width,distances[-1])
        if not site.buffer(EPS).covers(area) or area.intersection(obstacles).area > EPS:
            return False
        upper = rectangle(origin,along,across,0,0,width,landing)
        lower = rectangle(origin,along,across,0,distances[-1]-landing,width,distances[-1])
        center = LineString([(origin[0]+across[0]*width/2+along[0]*d,
                              origin[1]+across[1]*width/2+along[1]*d,z)
                             for d,z in zip(distances,zs)])
        candidate={"polygon": area, "upper_landing": upper,
                           "lower_landing": lower, "centerline": center,
                           "profile": profile, "width_m": width,
                           "length_m": distances[-1], "height_m": height,
                           "orientation": orientation}
        if accept is not None and not accept(candidate):
            return False
        candidates.append(candidate)
        return True

    # Practice puts the ramp along a boundary, beside the building, so the
    # basement floor stays whole: those candidates come first (they need the
    # edge to be at least the ramp's length); perpendicular ramps follow.
    for line in lines:
        for a,b in zip(line.coords, list(line.coords)[1:]):
            length = math.dist(a[:2],b[:2])
            if length < distances[-1]:
                continue
            along = ((b[0]-a[0])/length,(b[1]-a[1])/length)
            for sign in (1,-1):
                inward = (-along[1]*sign, along[0]*sign)
                for start, direction in ((a, along), (b, (-along[0], -along[1]))):
                    # ramp runs from this end of the edge toward the other, hugging the boundary
                    add(start, direction, inward, "parallel_to_edge")
                    if len(candidates) >= limit:
                        return candidates
    for line in lines:
        for a,b in zip(line.coords, list(line.coords)[1:]):
            length = math.dist(a[:2],b[:2])
            if length < width:
                continue
            across = ((b[0]-a[0])/length,(b[1]-a[1])/length)
            for sign in (1,-1):
                inward = (-across[1]*sign, across[0]*sign)
                offsets = [0, length-width, (length-width)/2, (length-width)/4, 3*(length-width)/4]
                landmarks = set(offsets)
                # Include the interior of the frontage: five landmarks missed
                # valid portals on the frozen Gosan parcel. Bound the work on
                # long edges while retaining half-metre sampling on normal lots.
                steps = min(256, max(1, math.ceil((length-width)/.5)))
                offsets += [(length-width)*i/steps for i in range(1, steps)]
                for offset in dict.fromkeys(offsets):
                    origin = (a[0]+across[0]*offset,a[1]+across[1]*offset)
                    added = add(origin, inward, across, "perpendicular_to_edge")
                    # Dense portal recovery must not send a dozen nearly
                    # identical floors through the expensive downstream packer.
                    if added and offset not in landmarks and len(candidates) >= min(limit, 3):
                        return candidates
                    if len(candidates) >= limit:
                        return candidates
    if not candidates:
        from backend.app.modules.design.generation.maas.masterplan.ramp_access import interior_ramp_candidates
        return interior_ramp_candidates(site, frontage, obstacles, rules, height, spec, limit=limit, accept=accept)
    return candidates


def _arc(center, radius, start_angle, sweep, steps=48):
    return [(center[0] + radius*math.cos(start_angle + sweep*i/steps),
             center[1] + radius*math.sin(start_angle + sweep*i/steps)) for i in range(steps + 1)]


def curved_ramp_candidates(site, frontage, obstacles, rules, height, *, turns=(90.0, 180.0, 45.0, 135.0), limit=8, accept=None):
    """Entry straight - circular turn - exit straight, at the curved-ramp rule's width and grade.

    The turn radius is whatever the required run length asks for, never tighter than
    `curve_min_inner_radius_m` + half the width.  Returns the same candidate shape as
    `ramp_candidates`, with the measured radius carried for the validator to re-check.
    """
    if limit <= 0:
        return []
    turns = tuple(dict.fromkeys(turns))
    if any(not math.isfinite(t) or not 0 < t < 360 for t in turns):
        raise ValueError('curve turns must be finite and between 0 and 360 degrees')
    if len(turns) > 1:
        # A first-fit cap previously consumed the entire budget with one angle.
        quota = math.ceil(limit / len(turns))
        families = [curved_ramp_candidates(site, frontage, obstacles, rules, height,
                    turns=(turn,), limit=quota, accept=accept) for turn in turns]
        retained = [family[i] for i in range(quota) for family in families if i < len(family)][:limit]
        for turn, family in zip(turns, families):
            if len(retained) >= limit:
                break
            if len(family) == quota:
                expanded = curved_ramp_candidates(site, frontage, obstacles, rules, height,
                    turns=(turn,), limit=quota + limit - len(retained), accept=accept)
                retained.extend(expanded[quota:])
        return retained
    width = rules.get("curved_ramp_width_m") or rules.get("ramp_width_m")
    grade = rules.get("curved_ramp_max_slope") or rules.get("ramp_max_slope")
    inner_min = rules.get("curve_min_inner_radius_m")
    if not width or not grade or inner_min is None:
        return []  # the snapshot does not carry the curved-ramp rule: propose nothing
    spec = ramp_profile(rules, height, grade=grade, width=width)
    if spec is None:
        return []
    total, landing, profile = spec["length_m"], spec["landing_m"], spec["profile"]
    radius_min = float(inner_min) + width/2
    lines = [frontage] if isinstance(frontage, LineString) else list(getattr(frontage, "geoms", ()))
    candidates = []
    for line in lines:
        for a, b in zip(line.coords, list(line.coords)[1:]):
            span = math.dist(a[:2], b[:2])
            if span < width:
                continue
            along = ((b[0]-a[0])/span, (b[1]-a[1])/span)
            for sign in (1, -1):
                inward = (-along[1]*sign, along[0]*sign)
                for turn_deg in turns:
                    theta = math.radians(turn_deg)
                    # a tight turn with long straights (what practice draws) through to a single
                    # sweeping arc that uses the whole run
                    radii = [radius_min, radius_min*1.4, radius_min*2.0, (total - 2*landing)/theta]
                    for radius in sorted({round(r, 3) for r in radii if r >= radius_min - EPS}):
                        arc_len = radius*theta
                        target_run = max(total, arc_len + 2*landing)
                        slack = max(0.0, target_run - arc_len - 2*landing)
                        for split in (0.5, 0.0, 1.0, 0.25, 0.75):
                            lead = landing + slack*split
                            tail = landing + slack*(1-split)
                            for hand in (1, -1):
                                for offset in dict.fromkeys(
                                        [span*f for f in (0.15,0.5,0.85)] +
                                        [width/2+(span-width)*f for f in (0.0,1.0,0.25,0.75)]):
                                    start = (a[0] + along[0]*offset, a[1] + along[1]*offset)
                                    head = math.atan2(inward[1], inward[0])
                                    p0 = (start[0] + inward[0]*lead, start[1] + inward[1]*lead)
                                    centre = (p0[0] + math.cos(head + hand*math.pi/2)*radius,
                                              p0[1] + math.sin(head + hand*math.pi/2)*radius)
                                    a0 = math.atan2(p0[1]-centre[1], p0[0]-centre[0])
                                    arc = _arc(centre, radius, a0, hand*theta)
                                    end_head = head + hand*theta
                                    p1 = arc[-1]
                                    p2 = (p1[0] + math.cos(end_head)*tail, p1[1] + math.sin(end_head)*tail)
                                    spine = LineString([start, p0, *arc[1:], p2])
                                    band = spine.buffer(width/2, cap_style=2, join_style=1)
                                    if not site.buffer(EPS).covers(band) or band.intersection(obstacles).area > EPS:
                                        continue
                                    upper = substring(spine, 0, landing).buffer(width/2, cap_style=2, join_style=1)
                                    lower = substring(spine, spine.length-landing, spine.length).buffer(width/2, cap_style=2, join_style=1)
                                    # Use the measured chord path for both XYZ and the grade
                                    # profile. Insert every grade break into the centreline.
                                    fitted = ramp_profile(rules, height, grade=grade, width=width,
                                                          run_length_m=spine.length)
                                    if fitted["length_m"] > spine.length + EPS:
                                        # Chord approximation is slightly shorter than its arc;
                                        # extend the final straight to preserve the grade bound.
                                        extension = fitted["length_m"] - spine.length
                                        p2 = (p2[0]+math.cos(end_head)*extension,
                                              p2[1]+math.sin(end_head)*extension)
                                        spine = LineString([start, p0, *arc[1:], p2])
                                        band = spine.buffer(width/2, cap_style=2, join_style=1)
                                        if not site.buffer(EPS).covers(band) or band.intersection(obstacles).area > EPS:
                                            continue
                                        lower = substring(spine, spine.length-landing, spine.length).buffer(width/2, cap_style=2, join_style=1)
                                    stations = sorted(set([spine.project(Point(p)) for p in spine.coords]
                                                          + fitted["distances"]))
                                    points = [spine.interpolate(d) for d in stations]
                                    centre_line = LineString([(p.x, p.y, _z_at(spine, p, fitted)) for p in points])
                                    candidate={
                                        "polygon": band, "upper_landing": upper, "lower_landing": lower,
                                        "centerline": centre_line, "profile": fitted["profile"], "width_m": width,
                                        "length_m": spine.length, "height_m": height, "orientation": "curved",
                                        "radius_m": round(radius, 3), "inner_radius_m": round(radius - width/2, 3),
                                        "turn_deg": turn_deg}
                                    if accept is not None and not accept(candidate):
                                        continue
                                    candidates.append(candidate)
                                    if len(candidates) >= limit:
                                        return candidates
    return candidates


def _z_at(spine, point, spec):
    """Profile height at the station of `point` along the centreline."""
    d = spine.project(Point(point)) if hasattr(spine, "project") else 0.0
    ds, zs = spec["distances"], spec["zs"]
    for (d0, z0), (d1, z1) in zip(zip(ds, zs), list(zip(ds, zs))[1:]):
        if d <= d1 + EPS:
            span = d1 - d0
            return z0 if span <= EPS else z0 + (z1 - z0)*(d - d0)/span
    return zs[-1]
