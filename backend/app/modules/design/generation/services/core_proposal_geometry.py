"""Bounded placement and width-preserving route geometry for an owner proposal."""
import heapq
import math

from shapely.affinity import rotate, translate
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union


def placements(host, width, depth, entry_offset, corridor_width, step, angles):
    minx, miny, maxx, maxy = host.bounds
    nx, ny = math.ceil((maxx - minx) / step), math.ceil((maxy - miny) / step)
    if (nx + 1) * (ny + 1) * len(angles) > 20000:
        raise ValueError('Core placement exceeds 20000-site computational budget')
    safe_ports = host.buffer(-corridor_width / 2)
    result = []
    for angle in angles:
        template = rotate(box(0, 0, width, depth), angle, origin=(0, 0))
        bx, by, _, _ = template.bounds
        radians = math.radians(angle)
        def transformed(point, x, y):
            px, py = point
            return (px * math.cos(radians) - py * math.sin(radians) + x,
                    px * math.sin(radians) + py * math.cos(radians) + y)
        for ix in range(nx + 1):
            for iy in range(ny + 1):
                x, y = minx + ix * step - bx, miny + iy * step - by
                geometry = translate(template, xoff=x, yoff=y)
                if not host.covers(geometry):
                    continue
                for sx, local in [(-1, (0, entry_offset)), (1, (width, entry_offset))]:
                    entry = transformed(local, x, y)
                    normal = sx * math.cos(radians), sx * math.sin(radians)
                    # Additional 10mm proposal clearance avoids placing the route
                    # center on an obstacle's numerical offset boundary; no shrinking.
                    port = tuple(entry[k] + normal[k] * (corridor_width / 2 + .01) for k in (0, 1))
                    if safe_ports.covers(Point(port)):
                        result.append({'geometry': geometry, 'entry': entry, 'port': port,
                            'angle_deg': angle, 'origin': (x, y), 'width_m': width, 'depth_m': depth,
                            'entry_side': sx, 'entry_offset_m': entry_offset})
    return result


def farthest_pair(candidates):
    best = None
    for index, left in enumerate(candidates):
        for right in candidates[index + 1:]:
            distance = math.dist(left['entry'], right['entry'])
            if best is not None and distance <= best[0]:
                continue
            if left['geometry'].intersects(right['geometry']):
                continue
            best = distance, left, right
    return best


def maximum_diagonal(polygon):
    points = list(polygon.convex_hull.exterior.coords)
    return max(math.dist(left, right) for left in points for right in points)


def route(footprint, obstacles, start, end, width):
    """Visibility route in the corridor-center free region; never clip its width."""
    free = footprint.buffer(-width / 2).difference(unary_union(obstacles).buffer(width / 2, join_style=2))
    a, b = start['port'], end['port']
    if not free.covers(Point(a)) or not free.covers(Point(b)):
        return None
    parts = [free] if free.geom_type == 'Polygon' else list(getattr(free, 'geoms', []))
    nodes = [a, b]
    for part in parts:
        if part.geom_type != 'Polygon':
            continue
        nodes.extend(list(part.exterior.coords)[:-1])
        for ring in part.interiors:
            nodes.extend(list(ring.coords)[:-1])
    if len(nodes) > 256:
        raise ValueError('Core route exceeds 256-node computational budget')
    distances, previous, queue = {0: 0.0}, {}, [(0.0, 0)]
    while queue:
        distance, index = heapq.heappop(queue)
        if distance != distances.get(index):
            continue
        if index == 1:
            break
        for target, point in enumerate(nodes):
            proposed = distance + math.dist(nodes[index], point)
            if target == index or proposed >= distances.get(target, math.inf):
                continue
            if free.covers(LineString([nodes[index], point])):
                distances[target] = proposed
                previous[target] = index
                heapq.heappush(queue, (proposed, target))
    if 1 not in distances:
        return None
    path, index = [nodes[1]], 1
    while index:
        index = previous[index]
        path.append(nodes[index])
    path.reverse()
    line = LineString([start['entry'], *path, end['entry']])
    corridor = line.buffer(width / 2, cap_style=2, join_style=1)
    return {'centerline': line, 'geometry': corridor, 'length_m': line.length,
            'outside_m2': corridor.difference(footprint).area,
            'clear_width_m': width, 'width_clipped': False}
