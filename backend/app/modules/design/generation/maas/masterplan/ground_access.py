"""Conservative full-width road-to-stall certificates, separately for each ground lot."""
import math
from shapely.geometry import LineString, Polygon
from shapely.affinity import translate
from shapely.ops import linemerge, nearest_points, substring

from .geometry import parts

# A drive drawn exactly as wide as the rule (the common case: the generator draws aisle_width_m)
# eroded by a hair under half its width leaves a 2e-5 m core; floating-point noise then fails
# every stall and the certificate is always unknown on standard layouts. One centimetre is
# below any drawing precision and is not a width relaxation: a 5.98 m drive still fails.
SLACK = 0.01


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
                            if math.dist(a, b) >= width - SLACK)
        if not runs:
            continue
        local = [(i, stall) for i, stall in enumerate(stalls) if stall.distance(component) <= 1e-5]
        radius = width / 2
        offset = max(0, radius - SLACK)
        # Every certificate belongs to one eroded core: proximity to a different core or to a
        # portal endpoint does not establish a route. The core is where a full-width body can
        # be centred inside the drive.
        cores = parts(component.buffer(-offset))
        # A car enters across a width-long opening along one of the drive's own edge
        # directions: the entry strip may meet the road at any angle (고산: the rows run 28 deg
        # off the road), so a road-normal probe is not required and not sufficient. Its body,
        # from beyond the road to the core, must lie inside the drive where it is past the
        # road, and must cross the road line inside the opening.
        directions = []
        for polygon in parts(component):
            for ring in (polygon.exterior, *polygon.interiors):
                coords = list(ring.coords)
                for a, b in zip(coords, coords[1:]):
                    length = math.dist(a, b)
                    if length <= 1e-6:
                        continue
                    d = ((b[0]-a[0])/length, (b[1]-a[1])/length)
                    if all(abs(d[0]*e[0]+d[1]*e[1]) < math.cos(math.radians(0.5)) for e in directions):
                        directions.append(d)
        def served_by(core, run):
            # the far side of the road near the opening: the body's outside part lives there;
            # the opening itself is enforced by the crossing test below
            a, b = run.coords[0], run.coords[-1]
            tx, ty = (b[0]-a[0])/run.length, (b[1]-a[1])/run.length
            longer = LineString([(a[0]-tx*width, a[1]-ty*width), (b[0]+tx*width, b[1]+ty*width)])
            # 2*width deep: the outside body is width long and its corners reach past that
            sides = [LineString(list(longer.coords)[::step]).buffer(2*width, single_sided=True) for step in (1, -1)]
            far = min(sides, key=lambda side: side.intersection(component).area)
            for station in (run.length/2, radius, run.length-radius):
                portal = run.interpolate(station)
                for dx, dy in directions:
                    for sign in (1, -1):
                        ux, uy = dx*sign, dy*sign
                        line = LineString([(portal.x-ux*width, portal.y-uy*width),
                                           (portal.x+ux*2*width, portal.y+uy*2*width)])
                        hit = line.intersection(core.buffer(SLACK))
                        if hit.is_empty:
                            continue
                        # the body stops where its centre reaches the core: beyond that the
                        # core itself certifies the width
                        reach = line.project(nearest_points(line.interpolate(0), hit)[1])
                        body = substring(line, 0, reach).buffer(offset, cap_style=2)
                        # area tests: `covers` trips on zero-area slivers that a rotated
                        # difference leaves on shared boundaries
                        if (body.difference(far).difference(component.buffer(1e-5)).area <= 1e-6
                                and body.intersection(road).difference(run.buffer(SLACK)).length <= 1e-6):
                            return True
            return False
        for core in cores:
            if not any(served_by(core, run) for run in runs):
                continue
            reachable = core.buffer(radius+SLACK, cap_style=3, join_style=2).intersection(component.buffer(1e-5))
            for i, stall in local:
                stall_rectangle = stall.minimum_rotated_rectangle
                if stall_rectangle.geom_type != 'Polygon' or stall_rectangle.is_empty:
                    continue
                coords = list(stall_rectangle.exterior.coords)
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
