"""Bounded search for an interior straight ramp with a real road connection.

This is a geometric fallback, not a vehicle swept-path or approval check. It
uses only dimensions passed in the caller's rules/profile and refuses any band
or ground connector outside the site, across an obstruction, or across the
descending part of its own ramp.
"""
from __future__ import annotations

import math

from shapely.geometry import LineString, Point, Polygon
from shapely.prepared import prep

from backend.app.modules.design.generation.maas.masterplan.geometry import EPS, number, parts


def _unit(dx, dy):
    length = math.hypot(dx, dy)
    return (dx / length, dy / length) if length > EPS else None


def _segments(geometry):
    for line in ([geometry] if isinstance(geometry, LineString) else getattr(geometry, "geoms", ())):
        if not isinstance(line, LineString):
            continue
        coordinates = list(line.coords)
        for a, b in zip(coordinates, coordinates[1:]):
            if math.dist(a[:2], b[:2]) > EPS:
                yield a[:2], b[:2]


def _vertices(geometry, cap=256):
    """Keep all useful contour vertices on normal parcels, a bounded sample on huge ones."""
    coordinates = []
    for polygon in parts(geometry):
        coordinates.extend(list(polygon.exterior.coords)[:-1])
        for ring in polygon.interiors:
            coordinates.extend(list(ring.coords)[:-1])
    if len(coordinates) <= cap:
        return coordinates
    stride = max(1, math.ceil(len(coordinates) / cap))
    return coordinates[::stride][:cap]


def _orientations(site, frontage, max_axes=16):
    """Prioritize the frontage normal, then frontage and parcel contour axes."""
    primary = []
    for a, b in _segments(frontage):
        tangent = _unit(b[0] - a[0], b[1] - a[1])
        if tangent is None:
            continue
        left = (-tangent[1], tangent[0])
        midpoint = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        probe = max(0.1, min(1.0, site.minimum_clearance / 4 if site.minimum_clearance else 1.0))
        inward = left if site.buffer(EPS).covers(Point(midpoint[0] + left[0] * probe, midpoint[1] + left[1] * probe)) else (-left[0], -left[1])
        primary.extend((inward, tangent))

    secondary = []
    for polygon in parts(site):
        for a, b in _segments(polygon.exterior):
            unit = _unit(b[0] - a[0], b[1] - a[1])
            if unit is not None:
                secondary.append((math.dist(a, b), unit))
    secondary.sort(key=lambda item: -item[0])
    axes = []
    for axis in [*primary, *(unit for _, unit in secondary)]:
        if all(abs(axis[0] * old[0] + axis[1] * old[1]) < 0.999 for old in axes):
            axes.append(axis)
        if len(axes) >= max_axes:
            break
    return [signed for axis in axes for signed in (axis, (-axis[0], -axis[1]))]


def _critical_positions(values, item_size, lower, upper, focus, cap=24):
    maximum = upper - item_size
    if maximum < lower - EPS:
        return []
    anchors = [lower, maximum, (lower + maximum) / 2]
    anchors.extend(value for raw in values for value in (raw, raw - item_size))
    distinct = {}
    for value in anchors:
        if lower - EPS <= value <= maximum + EPS:
            distinct[round(value, 6)] = min(max(value, lower), maximum)
    ordered = sorted(distinct.values(), key=lambda value: (abs(value + item_size / 2 - focus), value))
    return ordered[:cap]


def _road_portals(frontage, width):
    for a, b in _segments(frontage):
        span = math.dist(a, b)
        if span + EPS < width:
            continue
        tangent = ((b[0] - a[0]) / span, (b[1] - a[1]) / span)
        left = (-tangent[1], tangent[0])
        distances = [span / 2, width / 2, span - width / 2, span / 4, 3 * span / 4]
        for distance in dict.fromkeys(round(d, 6) for d in distances):
            if distance < width / 2 - EPS or distance > span - width / 2 + EPS:
                continue
            portal = (a[0] + tangent[0] * distance, a[1] + tangent[1] * distance)
            yield portal, tangent, left
            yield portal, tangent, (-left[0], -left[1])


def _connector(site, frontage, obstacles, ramp, upper, width, landing):
    """Test straight and orthogonal full-width corridors to the flat landing."""
    permitted = prep(site.buffer(EPS))
    descending = ramp.difference(upper)
    target = upper.centroid
    for portal, tangent, normal in _road_portals(frontage, width):
        if not permitted.covers(Point(portal)):
            continue
        delta = (target.x - portal[0], target.y - portal[1])
        along = delta[0] * normal[0] + delta[1] * normal[1]
        across = delta[0] * tangent[0] + delta[1] * tangent[1]
        if along < -EPS:
            continue
        starts = [
            [portal, (target.x, target.y)],
        ]
        for departure in (width / 2, width, 1.5 * width, 2 * width, along):
            if departure < 0 or departure > along + width:
                continue
            first = (portal[0] + normal[0] * departure, portal[1] + normal[1] * departure)
            corner = (first[0] + tangent[0] * across, first[1] + tangent[1] * across)
            starts.append([portal, first, corner, (target.x, target.y)])
        for vertices in starts:
            points = [vertices[0]]
            for point in vertices[1:]:
                if math.dist(point, points[-1]) > EPS:
                    points.append(point)
            if len(points) < 2:
                continue
            corridor = LineString(points).buffer(width / 2, cap_style=2, join_style=1)
            if (corridor.is_empty or not corridor.is_valid or not permitted.covers(corridor)
                    or corridor.intersection(obstacles).area > EPS
                    or corridor.intersection(descending).area > EPS
                    or corridor.distance(frontage) > EPS
                    or corridor.intersection(upper).area <= EPS):
                continue
            return corridor
    return None


def interior_ramp_candidates(site, frontage, obstacles, rules, height, spec, *, limit=12, accept=None):
    """Find contained interior ramps whose upper landing has a drivable road band.

    Candidate axes come from the verified frontage and actual parcel edges. A
    finite set of free-space/obstacle vertices and boundary extrema provides
    placement positions. The fallback stops after 2,400 ramp placements or
    `limit` connected proposals, whichever comes first.
    """
    if limit <= 0 or frontage is None or frontage.is_empty or site.is_empty:
        return []
    width = number(spec["width_m"], "ramp width", minimum=.1)
    run = number(spec["length_m"], "ramp run", minimum=.1)
    landing = number(spec["landing_m"], "ramp landing", minimum=.1)
    height = number(height, "basement floor height", minimum=.1)
    if run <= 2 * landing or width <= 0:
        return []
    # Import only after ramps.py has defined its geometry helpers; this module
    # is intentionally loaded lazily by that module's fallback branch.
    from backend.app.modules.design.generation.maas.masterplan.ramps import rectangle

    site_cover = prep(site.buffer(EPS))
    free = site.difference(obstacles)
    if free.is_empty:
        return []
    vertices = [*_vertices(site), *_vertices(obstacles), *_vertices(free)]
    road_segments = list(_segments(frontage))
    if not road_segments:
        return []
    road_midpoints = [((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) for a, b in road_segments]
    candidates = []
    tested = 0
    max_placements = 2400

    for along in _orientations(site, frontage):
        across = (-along[1], along[0])
        projected = [(x * across[0] + y * across[1], x * along[0] + y * along[1]) for x, y, *_ in vertices]
        if not projected:
            continue
        u_values = [p[0] for p in projected]
        v_values = [p[1] for p in projected]
        min_u, max_u = min(u_values), max(u_values)
        min_v, max_v = min(v_values), max(v_values)
        midpoint = min(road_midpoints, key=lambda p: math.hypot(p[0] - free.centroid.x, p[1] - free.centroid.y))
        road_u = midpoint[0] * across[0] + midpoint[1] * across[1]
        road_v = midpoint[0] * along[0] + midpoint[1] * along[1]
        u_positions = _critical_positions(u_values, width, min_u, max_u, road_u)
        v_positions = _critical_positions(v_values, run, min_v, max_v, road_v)
        for v0 in v_positions:
            for u0 in u_positions:
                tested += 1
                if tested > max_placements:
                    return candidates
                origin = (across[0] * u0 + along[0] * v0, across[1] * u0 + along[1] * v0)
                area = rectangle(origin, along, across, 0, 0, width, run)
                if not site_cover.covers(area) or area.intersection(obstacles).area > EPS:
                    continue
                upper = rectangle(origin, along, across, 0, 0, width, landing)
                connector = _connector(site, frontage, obstacles, area, upper, width, landing)
                if connector is None:
                    continue
                lower = rectangle(origin, along, across, 0, run - landing, width, run)
                center = LineString([
                    (origin[0] + across[0] * width / 2 + along[0] * d,
                     origin[1] + across[1] * width / 2 + along[1] * d, z)
                    for d, z in zip(spec["distances"], spec["zs"])
                ])
                candidate={
                    "polygon": area, "upper_landing": upper, "lower_landing": lower,
                    "centerline": center, "profile": spec["profile"],
                    "width_m": width, "length_m": run, "height_m": height,
                    "orientation": "interior_straight", "ground_connector": connector,
                }
                if accept is not None and not accept(candidate):
                    continue
                candidates.append(candidate)
                if len(candidates) >= limit:
                    return candidates
    return candidates
