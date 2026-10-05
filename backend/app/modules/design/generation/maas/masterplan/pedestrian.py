"""One owner for declared ground pedestrian reservations; no inferred widths."""
import math
from shapely.geometry import Polygon, LineString, shape
from shapely.ops import substring
from backend.app.modules.design.generation.maas.masterplan.geometry import EPS, number, polygon, union_or_empty


def pedestrian_reservation(request):
    site=polygon(request['site'],'site')
    pieces=[]
    pending=['pedestrian_route_design_review']
    evidence=request.get('evidence') or {}
    if request.get('pedestrian_reserved_area') is not None:
        pieces.append(polygon(request['pedestrian_reserved_area'],'pedestrian reserved area'))
        source=evidence.get('pedestrian_reserved_area')
        if not source or (isinstance(source,dict) and source.get('authored_source_missing')):
            pending.append('pedestrian_reserved_area_source_review')
    width=(request.get('options') or {}).get('front_reservation_width_m')
    if width is not None:
        width=number(width,'front reservation width')
        front=shape(request['front_frontage']) if request.get('front_frontage') else None
        if front is None or front.is_empty or front.geom_type not in ('LineString','MultiLineString'):
            raise ValueError('front_reservation_width_m requires explicit front_frontage')
        if width:
            pieces.append(front.buffer(width,cap_style=2).intersection(site))
    reserved=union_or_empty(pieces) if pieces else Polygon()
    if not reserved.is_empty and not site.buffer(EPS).covers(reserved):
        raise ValueError('pedestrian reserved area extends outside site')
    if not pieces and width is None:
        pending.append('pedestrian_reservation_geometry_missing')
    crossing=Polygon()
    if request.get('pedestrian_vehicle_crossing_area') is not None:
        crossing=polygon(request['pedestrian_vehicle_crossing_area'],'pedestrian vehicle crossing area')
        if not reserved.buffer(EPS).covers(crossing):
            raise ValueError('pedestrian vehicle crossing must be within reserved area')
        if not evidence.get('pedestrian_vehicle_crossing_area'):
            raise ValueError('pedestrian vehicle crossing requires explicit source evidence')
        pending.append('pedestrian_vehicle_crossing_safety_review')
    return {'reserved':reserved,'vehicle_blocked':reserved.difference(crossing),
            'crossing':crossing,'pending_reviews':pending}


def exclude_reserved_stalls(plan, reserved):
    """An allowed vehicle crossing is still not a parking bay."""
    if reserved.is_empty:
        return plan
    stalls=[s for s in plan['stalls'] if s['polygon'].intersection(reserved).area<=EPS]
    return {**plan,'stalls':stalls,'provided':len(stalls),
            'accessible':sum(s['type']=='accessible' for s in stalls)}


def profile_flat_area(ramp, centerline, profile, width, elevation, *, tolerance=EPS):
    """Measure flat plan area from profile stations, never a landing label."""
    if centerline is None or centerline.geom_type != 'LineString' or not width:
        return Polygon()
    spine = LineString([p[:2] for p in centerline.coords])
    flats = []
    for a, b in zip(profile, profile[1:]):
        if (abs(a['z_m']-elevation) <= tolerance and abs(b['z_m']-elevation) <= tolerance
                and b['distance_m'] > a['distance_m']):
            segment = substring(spine, a['distance_m'], b['distance_m'])
            coords = []
            for point in segment.coords:
                if not coords or math.dist(coords[-1], point) > 1e-9:
                    coords.append(point)
            if len(coords) >= 2:
                # Buffer the flat run the way the ramp band itself was buffered (round joins at
                # quad_segs=32). At shapely's default 8 the two curved edges disagree by slivers, and
                # on a turning ramp those slivers - 0.01 m2 of them - made `drive_obstructions` fail a
                # drive that sat entirely on the landings. The band is the authority; this measures
                # into it, so matching its resolution is a correction, not a tolerance.
                flats.append(LineString(coords).buffer(float(width)/2, cap_style=2,
                                                       join_style=1, quad_segs=32))
    return union_or_empty(flats).intersection(ramp)


def ramp_reservation_conflicts(ramp, pedestrian, *, ground_flat=None, tolerance=EPS):
    """No implied pedestrian deck above a ramp; only authored flat crossings.

    All area outside the profile's ground-level flat conflicts with any reserved
    pedestrian area. A flat ground crossing may use only the explicit crossing
    area. This also checks a generated road connector where present.
    """
    if pedestrian['reserved'].is_empty:
        return {'passed': True, 'overlap_m2': 0.}
    if ground_flat is None:
        profile = ramp.get('profile') or []
        ground_flat = profile_flat_area(ramp['polygon'], ramp.get('centerline'), profile,
            ramp.get('width_m'), profile[0]['z_m'] if profile else 0., tolerance=tolerance)
    blocked = pedestrian['vehicle_blocked']
    body = ramp['polygon'].difference(ground_flat.buffer(tolerance))
    overlap = (body.intersection(pedestrian['reserved']).area + ground_flat.intersection(blocked).area
               + ramp.get('ground_connector', Polygon()).intersection(blocked).area)
    return {'passed': overlap <= tolerance, 'overlap_m2': overlap}
