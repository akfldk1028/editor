"""Closed aisle geometry certificates; vehicle swept paths remain separate."""
import math
from shapely.geometry import Polygon, LineString


def full_width_stall_access(drive, stalls, anchors, width):
    """Reconstruct each bay's manoeuvre cell and test full-width reachability.

    This reuses the owner's principal-frame erosion certificate. A connected
    polygon with a core-shaped notch can still fail the required aisle width.
    It certifies clearance geometry, not a steering/swept-path simulation.
    """
    from backend.app.modules.design.generation.maas.masterplan.bounded_packing import _width_connected
    if not stalls:
        return True
    if drive.is_empty or not anchors or not width:
        return False
    cells = []
    for stall in stalls:
        pts = list(stall.minimum_rotated_rectangle.exterior.coords)
        edges = [LineString([a, b]) for a, b in zip(pts, pts[1:])]
        edge = max(edges, key=lambda e: e.intersection(drive.buffer(1e-5)).length)
        mid = edge.interpolate(.5, normalized=True)
        dx, dy = mid.x-stall.centroid.x, mid.y-stall.centroid.y
        norm = math.hypot(dx, dy)
        if norm <= 1e-9:
            return False
        dx, dy = dx/norm*width, dy/norm*width
        a, b = list(edge.coords)
        cell = Polygon([a, b, (b[0]+dx, b[1]+dy), (a[0]+dx, a[1]+dy)])
        if not drive.buffer(1e-5).covers(cell):
            return False
        cells.append({'polygon': stall, 'front': cell})
    return _width_connected({'drive': drive, 'stalls': cells}, anchors, width)


def closed_aisle_loop(drive, width):
    """Find a closed centreline with a full-width corridor inside drawn aisles.

    A connected C/comb or a pinched return leg is not a loop. This conservative
    polygon-offset certificate does not certify steering radius or every bay's
    route to the loop; those require separate path and frontage checks.
    """
    if not isinstance(width,(float,int)) or isinstance(width,bool) or not math.isfinite(width) or width<=0:
        return None
    if drive.is_empty or not drive.is_valid:
        return None
    candidates=[]
    for part in ([drive] if drive.geom_type=='Polygon' else getattr(drive,'geoms',[])):
        if part.geom_type!='Polygon':
            continue
        for interior in part.interiors:
            island=Polygon(interior)
            offset=island.buffer(width/2,join_style=2)
            if offset.geom_type!='Polygon':
                continue
            path=LineString(offset.exterior.coords)
            if path.is_ring and part.buffer(1e-6).covers(path.buffer(width/2,join_style=2)):
                candidates.append(path)
    return max(candidates,key=lambda g:g.length) if candidates else None
