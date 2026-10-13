"""Bounded visibility search with full-width geometry checks."""
import heapq
import math
from shapely.geometry import LineString, Point
from .geometry import EPS, parts, union_or_empty

MAX_NODES = 192


def corridor_for(spine, width):
    coords = list(spine.coords)
    # Preserve the terminal full-width caps when GEOS simplifies short final turns.
    return union_or_empty([
        *[LineString([a,b]).buffer(width/2, cap_style=2) for a,b in zip(coords, coords[1:])],
        *[Point(p).buffer(width/2) for p in coords[1:-1]],
    ])


def clear(corridor, site, obstacles):
    return site.buffer(EPS).covers(corridor) and corridor.intersection(obstacles).area <= EPS


def ports(point, boundary, radius, site, obstacles):
    lines = [boundary] if boundary.geom_type in ('LineString', 'LinearRing') else list(boundary.geoms)
    result = []
    for line in lines:
        coords = list(line.coords)
        for a, b in zip(coords, coords[1:]):
            segment = LineString([a, b])
            if segment.length <= EPS or segment.distance(point) > EPS:
                continue
            dx, dy = (b[0]-a[0])/segment.length, (b[1]-a[1])/segment.length
            for sign in (-1, 1):
                p = Point(point.x-sign*dy*radius, point.y+sign*dx*radius)
                if clear(LineString([point, p]).buffer(radius-1e-4, cap_style=2), site, obstacles):
                    result.append(p)
    return result


def route_spine(arrival, entrance, front, ground, site, obstacles, width):
    direct = LineString([arrival, entrance])
    if direct.length <= EPS:
        raise ValueError('no external approach length; direct boundary entrances require separate design')
    if clear(direct.buffer(width/2, cap_style=2), site, obstacles):
        return direct, 2
    radius = width/2 + 1e-4
    starts = ports(arrival, front, radius, site, obstacles)
    ends = ports(entrance, ground.boundary, radius, site, obstacles)
    if not starts or not ends:
        raise ValueError('full-width pedestrian arrival or entrance is obstructed')
    nodes = starts + ends
    for geometry in (obstacles.buffer(radius, join_style=2), site.buffer(-radius, join_style=2)):
        for piece in parts(geometry):
            for ring in [piece.exterior, *piece.interiors]:
                nodes.extend(Point(x, y) for x,y in list(ring.coords)[:-1])
    if len(nodes) > MAX_NODES:
        raise ValueError('pedestrian route search node budget exceeded; explicit route design required')
    # Round caps ensure each turn has clearance, not just each segment's flat rectangle.
    nodes = nodes[:len(starts)+len(ends)] + [p for p in nodes[len(starts)+len(ends):]
        if clear(p.buffer(width/2), site, obstacles)]
    destinations = set(range(len(starts), len(starts)+len(ends)))
    queue = [(arrival.distance(p), i, [i]) for i,p in enumerate(starts)]
    heapq.heapify(queue)
    distances = {i:d for d,i,_ in queue}
    visited = set()
    while queue:
        distance, index, path = heapq.heappop(queue)
        if index in visited:
            continue
        visited.add(index)
        if index in destinations:
            spine = LineString([arrival, *[nodes[i] for i in path], entrance])
            if clear(corridor_for(spine, width), site, obstacles):
                return spine, len(nodes)
        for other, point in enumerate(nodes):
            if other in visited or nodes[index].distance(point) <= EPS:
                continue
            segment = LineString([nodes[index], point])
            candidate = distance + segment.length
            if candidate >= distances.get(other, math.inf):
                continue
            if clear(segment.buffer(width/2), site, obstacles):
                distances[other] = candidate
                heapq.heappush(queue, (candidate, other, path+[other]))
    raise ValueError('no full-width pedestrian route found within bounded search')
