"""Conservative full-width road-to-stall certificates, separately for each ground lot."""
import math
from shapely.geometry import LineString, Point, Polygon, box
from shapely.affinity import rotate, translate
from shapely.ops import linemerge

from .geometry import parts


def certify_ground_access(drive, stalls, road, width):
    result = {'id': 'placement_full_width_drive:0', 'status': 'unknown',
              'required_width_m': width, 'certified_stalls': 0, 'total_stalls': len(stalls),
              'scope': 'Conservative road-to-ground-stall full-width certificate; no steering, ramp or permit approval'}
    if not stalls:
        return {**result, 'status': 'not_applicable'}
    if (not isinstance(width, (int, float)) or isinstance(width, bool) or not math.isfinite(width)
            or width <= 0 or road is None or road.is_empty or drive.is_empty or not drive.is_valid):
        return {**result, 'reason': 'missing_or_unsupported_inputs'}
    origin = drive.centroid
    drive = translate(drive, xoff=-origin.x, yoff=-origin.y)
    road = translate(road, xoff=-origin.x, yoff=-origin.y)
    stalls = [translate(stall, xoff=-origin.x, yoff=-origin.y) for stall in stalls]
    certified = set()
    for component in parts(drive):
        contact = road.intersection(component.buffer(1e-5))
        if contact.geom_type == 'MultiLineString':
            contact = linemerge(contact)
        lines = [contact] if isinstance(contact, LineString) else list(getattr(contact, 'geoms', ()))
        runs = []
        for line in lines:
            if isinstance(line, LineString):
                coords = list(line.simplify(1e-8).coords)
                runs.extend(LineString([a, b]) for a, b in zip(coords, coords[1:])
                            if math.dist(a, b) >= width - 1e-5)
        local = [(i, stall) for i, stall in enumerate(stalls) if stall.distance(component) <= 1e-5]
        radius = width / 2
        # Every certificate belongs to one eroded component: proximity to a
        # different core or to a portal endpoint does not establish a route.
        offset = max(0, radius - 1e-5)
        cores = parts(component.buffer(-offset))
        rectangle = component.minimum_rotated_rectangle
        if component.symmetric_difference(rectangle).area <= 1e-9:
            coords = list(rectangle.exterior.coords)
            a, b = coords[:2]
            angle = math.degrees(math.atan2(b[1]-a[1], b[0]-a[0]))
            origin = component.centroid
            aligned = rotate(translate(component, xoff=-origin.x, yoff=-origin.y), -angle, origin=(0, 0))
            x0, y0, x1, y1 = aligned.bounds
            if x1-x0 > 2*offset and y1-y0 > 2*offset:
                core = box(x0+offset, y0+offset, x1-offset, y1-offset)
                cores = [translate(rotate(core, angle, origin=(0, 0)), xoff=origin.x, yoff=origin.y)]
        for core in cores:
            served = False
            for run in runs:
                a, b = list(run.coords)
                tx, ty = (b[0]-a[0])/run.length, (b[1]-a[1])/run.length
                positions = {radius, run.length-radius, run.length/2,
                             max(radius, min(run.length-radius, run.project(core.centroid)))}
                for station in positions:
                    portal = run.interpolate(station)
                    for sign in (-1, 1):
                        nx, ny = -ty*sign, tx*sign
                        left = (portal.x-tx*radius, portal.y-ty*radius)
                        right = (portal.x+tx*radius, portal.y+ty*radius)
                        cell = Polygon([left, right,
                            (right[0]+nx*width, right[1]+ny*width),
                            (left[0]+nx*width, left[1]+ny*width)])
                        center = Point(portal.x+nx*radius, portal.y+ny*radius)
                        if component.buffer(1e-5).covers(cell) and core.buffer(1e-5).covers(center):
                            served = True
                            break
                    if served:
                        break
                if served:
                    break
            if not served:
                continue
            reachable = core.buffer(radius+1e-5).intersection(component.buffer(1e-5))
            for i, stall in local:
                coords = list(stall.minimum_rotated_rectangle.exterior.coords)
                edges = [LineString([a, b]) for a, b in zip(coords, coords[1:])]
                edge = max(edges, key=lambda e: e.intersection(component.buffer(1e-5)).length)
                mid = edge.interpolate(.5, normalized=True)
                dx, dy = mid.x-stall.centroid.x, mid.y-stall.centroid.y
                norm = math.hypot(dx, dy)
                if norm <= 1e-9:
                    continue
                dx, dy = dx/norm*width, dy/norm*width
                a, b = list(edge.coords)
                cell = Polygon([a, b, (b[0]+dx, b[1]+dy), (a[0]+dx, a[1]+dy)])
                if reachable.covers(cell):
                    certified.add(i)
    return {**result, 'status': 'passed' if len(certified) == len(stalls) else 'unknown',
            'certified_stalls': len(certified),
            'reason': 'all_ground_stalls_certified' if len(certified) == len(stalls) else 'conservative_certificate_incomplete'}
