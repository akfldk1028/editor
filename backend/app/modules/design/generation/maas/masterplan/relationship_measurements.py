"""Continuous geometric observations, separate from gate compliance percentages."""
import math
from shapely.geometry import LineString, Point, shape
from shapely.ops import unary_union, linemerge, nearest_points

TOL = 1e-6


def _longest_line(g):
    lines = [g] if g.geom_type in ('LineString', 'LinearRing') else [
        line for part in getattr(g, 'geoms', []) for line in _lines(part)]
    if not lines:
        return 0.0
    merged = unary_union(lines)
    if merged.geom_type == 'MultiLineString':
        merged = linemerge(merged)
    return max((line.length for line in _lines(merged)), default=0.0)


def _lines(g):
    if g.geom_type in ('LineString', 'LinearRing'):
        return [g]
    return [line for part in getattr(g, 'geoms', []) for line in _lines(part)]


def _area(g):
    return g.is_valid and not g.is_empty and g.geom_type in ('Polygon', 'MultiPolygon')


def _frontage(grouped, request):
    key = 'front_frontage' if request.get('front_frontage') else 'frontage'
    result = {'source_field': key, 'boundary_contact_m': None, 'facing_facade_length_m': None,
              'distance_m': None, 'scope': 'Outer facades facing the supplied road segment by orientation; not doors, visibility or usable frontage.'}
    buildings = [g for g, _ in grouped.get((0, 'building_footprint'), []) if _area(g)]
    if not request.get(key) or not buildings:
        return result
    road = shape(request[key])
    if not road.is_valid or road.is_empty or road.geom_type not in ('LineString', 'MultiLineString'):
        return result
    building = unary_union(buildings)
    facing = []
    for polygon in ([building] if building.geom_type == 'Polygon' else building.geoms):
        # Ring orientation, not the centroid, determines outward on concave footprints.
        sign = 1 if polygon.exterior.is_ccw else -1
        coordinates = list(polygon.exterior.coords)
        for a, b in zip(coordinates, coordinates[1:]):
            edge = LineString([a, b])
            if edge.length <= TOL:
                continue
            facing.extend(_lines(edge.intersection(road)))
            nx, ny = sign*(b[1]-a[1])/edge.length, sign*(a[0]-b[0])/edge.length
            midpoint = edge.interpolate(.5, normalized=True)
            for road_line in _lines(road):
                for c, d in zip(road_line.coords, list(road_line.coords)[1:]):
                    length = math.dist(c[:2], d[:2])
                    if length <= TOL:
                        continue
                    ux, uy = (d[0]-c[0])/length, (d[1]-c[1])/length
                    target = nearest_points(midpoint, LineString([c, d]))[1]
                    if nx*(target.x-midpoint.x)+ny*(target.y-midpoint.y) <= TOL:
                        continue
                    pa, pb = [(p[0]-c[0])*ux+(p[1]-c[1])*uy for p in (a, b)]
                    if abs(pb-pa) <= TOL:
                        continue
                    t0, t1 = sorted((-pa/(pb-pa), (length-pa)/(pb-pa)))
                    lo, hi = max(0., t0), min(1., t1)
                    if hi > lo:
                        facing.append(LineString([edge.interpolate(lo, normalized=True), edge.interpolate(hi, normalized=True)]))
    result.update(boundary_contact_m=round(building.boundary.intersection(road).length, 6),
                  facing_facade_length_m=round(unary_union(facing).length, 6),
                  distance_m=round(building.distance(road), 6))
    return result


def measure_relationships(grouped, request):
    """Reuse the validator's parsed geometry; no new rule or preferred shape."""
    records = []
    for (level, layer), items in grouped.items():
        if layer != 'ramp_centerline':
            continue
        for center, props in items:
            pair = (props.get('from_level'), props.get('to_level'))
            row = {'from_level': pair[0], 'to_level': pair[1], 'status': 'unknown',
                   'outlet_width_m': None, 'landing_end_width_m': None, 'contact_fraction': None,
                   'reason': 'missing or ambiguous centreline, landing or aisle'}
            records.append(row)
            matching = [c for c, p in items if (p.get('from_level'), p.get('to_level')) == pair]
            landings = [g for g, p in grouped.get((level, 'vehicular_access'), [])
                        if p.get('role') == 'ramp_arrival' and
                        (p.get('from_level'), p.get('to_level')) == pair]
            aisles = [g for g, _ in grouped.get((level, 'parking_aisle'), [])]
            if (level != pair[1] or len(matching) != 1 or len(landings) != 1 or not aisles
                    or center.geom_type != 'LineString' or not center.is_valid
                    or not _area(landings[0]) or not all(_area(g) for g in aisles)):
                continue
            points = list(center.coords)
            if len(points) < 2:
                continue
            b = points[-1]
            a = next((p for p in reversed(points[:-1]) if math.dist(p[:2], b[:2]) > TOL), None)
            if a is None or not landings[0].buffer(TOL).covers(Point(b[:2])):
                continue
            length = math.dist(a[:2], b[:2])
            nx, ny = -(b[1]-a[1])/length, (b[0]-a[0])/length
            x0, y0, x1, y1 = landings[0].bounds
            reach = math.hypot(x1-x0, y1-y0)+1
            section = LineString([(b[0]-nx*reach, b[1]-ny*reach), (b[0]+nx*reach, b[1]+ny*reach)])
            port = section.intersection(landings[0].buffer(TOL))
            span = _longest_line(port)
            width = min(span, _longest_line(port.intersection(unary_union(aisles).buffer(TOL))))
            row.update(status='measured', outlet_width_m=round(width, 6), landing_end_width_m=round(span, 6),
                       contact_fraction=round(width/span, 6) if span > TOL else None,
                       reason='Longest continuous aisle contact across the terminal normal section; lateral exits and downstream bottlenecks are not measured.')
    return {'schema_version': 'masterplan.relationship-measurements.v1',
            'ramp_landings': records, 'building_frontage': _frontage(grouped, request),
            'scope': 'Raw geometry, no quality weight, legality verdict or vehicle trajectory certificate.'}
