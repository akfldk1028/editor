"""Geometric measurements the validator reads: ramp flats, inscribed turning disc, turn radius."""
from __future__ import annotations

import math

from shapely.geometry import Polygon

from backend.app.modules.design.generation.maas.masterplan.pedestrian import profile_flat_area

TOL = 1e-5
LANDING_JOINT_TOL = 0.01  # m, the ramp landing's construction joint (see drive_obstructions)


def _flat_ramp_area(grouped, ramp, properties, level):
    """Flat profile stations at this level, not an unverified arrival label."""
    profile=properties.get("profile") or []
    if not profile:
        return Polygon()
    if properties.get("from_level")==level:
        elevation=profile[0]["z_m"]
    elif properties.get("to_level")==level:
        elevation=profile[-1]["z_m"]
    else:
        return Polygon()
    center=next((g for (other_level,layer),items in grouped.items() if layer=="ramp_centerline"
        for g,p in items if p.get("from_level")==properties.get("from_level")
        and p.get("to_level")==properties.get("to_level")),None)
    width=properties.get("width_m")
    if center is None or center.geom_type!="LineString" or not width:
        return Polygon()
    return profile_flat_area(ramp,center,profile,width,elevation,tolerance=TOL)


def _stacked_flat_access(grouped, ramp, props, level, options, rules):
    """Only parallel vertically translated runs can share floor landing areas.

    A lower floor may pass under the upper run's flat start only when declared
    storey/slab dimensions meet the supplied headroom rule. The sloping body
    remains reserved. This is not a beam/services clearance certification.
    """
    flat=_flat_ramp_area(grouped,ramp,props,level)
    height,slab,minimum=(options.get('basement_floor_height_m'),options.get('slab_depth_m'),rules.get('min_headroom_m'))
    if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in (height,slab,minimum)):
        return flat
    if height-slab+TOL<minimum:
        return flat
    profile=props.get('profile') or []
    def path(p):
        return next((list(g.coords) for (_,layer),items in grouped.items() if layer=='ramp_centerline'
            for g,gp in items if g.geom_type=='LineString' and gp.get('from_level')==p.get('from_level')
            and gp.get('to_level')==p.get('to_level')),[])
    spine=path(props)
    for (_,layer),items in list(grouped.items()):
        if layer!='ramp':
            continue
        for other,op in items:
            other_profile=op.get('profile') or []
            if op is props or level not in (op.get('from_level'),op.get('to_level')):
                continue
            offset=(op.get('from_level')-props.get('from_level'))*height
            other_spine=path(op)
            if (abs(offset)>TOL and len(profile)==len(other_profile) and profile
                    and spine and len(spine)==len(other_spine)
                    and all(math.dist(a[:2],b[:2])<=TOL for a,b in zip(spine,other_spine))
                    and ramp.symmetric_difference(other).area<=TOL
                    and all(abs(a['distance_m']-b['distance_m'])<=TOL
                            and abs(b['z_m']-a['z_m']-offset)<=TOL for a,b in zip(profile,other_profile))):
                flat=flat.union(_flat_ramp_area(grouped,other,op,level))
    return flat



def _turning_space(drive, radius_m):
    """Largest disc the drive area can contain, and whether the vehicle's turning circle fits.

    A vehicle turning through 180 degrees sweeps the annulus between its inner and outer turning
    radii about a centre.  Requiring the drive to contain a disc of the OUTER radius is the
    conservative form of that test - the annulus is a subset of the disc - and it is exact to
    evaluate: a polygon contains a disc of radius r somewhere iff its negative buffer is non-empty.
    The radii are a declared design input (`options.vehicle`); nothing is assumed when absent.
    """
    if drive.is_empty or not radius_m:
        return None
    lo, hi = 0.0, float(radius_m) * 2
    for _ in range(24):                       # largest inscribed radius by bisection on buffer(-r)
        mid = (lo + hi) / 2
        if drive.buffer(-mid).is_empty:
            hi = mid
        else:
            lo = mid
    return lo


def _min_turn_radius(coords):
    """Sharpest circumradius over consecutive vertex triples; None when the line is straight."""
    # Grade stations may subdivide an existing straight chord. Those collinear
    # points are not new turns and must not shorten adjacent circumradius legs.
    # Douglas-Peucker simplification can retain a station on an arc chord.
    # Remove only forward collinear subdivisions, never a real turn/reversal.
    cleaned = []
    for p in coords:
        while len(cleaned) >= 2:
            a, b = cleaned[-2:]
            ab = (b[0]-a[0], b[1]-a[1])
            bp = (p[0]-b[0], p[1]-b[1])
            cross = abs(ab[0]*bp[1]-ab[1]*bp[0])
            if (cross > 1e-8 * max(math.hypot(*ab)+math.hypot(*bp), 1e-9)
                    or ab[0]*bp[0]+ab[1]*bp[1] < 0):
                break
            cleaned.pop()
        cleaned.append(p)
    coords = cleaned
    best=None
    for (x1,y1),(x2,y2),(x3,y3) in zip(coords,coords[1:],coords[2:]):
        a=math.dist((x1,y1),(x2,y2)); b=math.dist((x2,y2),(x3,y3)); c=math.dist((x1,y1),(x3,y3))
        area2=abs((x2-x1)*(y3-y1)-(x3-x1)*(y2-y1))
        if area2<=1e-12 or a<=1e-9 or b<=1e-9:
            continue
        r=a*b*c/(2*area2)
        best=r if best is None else min(best,r)
    return best
