"""Ramp clearance against an explicitly declared horizontal slab soffit.

This is a section constraint for concept alternatives. It does not establish
beam, foundation or service clearances absent from the structural input.
"""
from shapely.geometry import LineString, Point
from shapely import get_coordinates
from backend.app.modules.design.generation.maas.masterplan.geometry import EPS, number


def overhead_clearance(ramp, occupied, soffit_z_m, required_height_m):
    width=number(ramp['width_m'],'ramp width',minimum=.1)
    required=number(required_height_m,'required headroom',minimum=.1)
    soffit=float(soffit_z_m)
    coords=list(ramp['centerline'].coords)
    if any(len(p)<3 for p in coords):
        raise ValueError('overhead clearance requires XYZ ramp centreline')
    minimum=None
    def retain(high_z):
        nonlocal minimum
        clearance=soffit-high_z
        minimum=clearance if minimum is None else min(minimum,clearance)
    for a,b in zip(coords,coords[1:]):
        line=LineString([a[:2],b[:2]])
        if line.length<=EPS:
            continue
        overlap=line.buffer(width/2,cap_style=2).intersection(occupied)
        if overlap.area<=EPS:
            continue
        stations=[line.project(Point(x,y))/line.length for x,y in get_coordinates(overlap)]
        retain(max(a[2]+t*(b[2]-a[2]) for t in stations))
    # Round joins between adjacent strips must also clear the slab; no gaps
    # between station ribbons may silently become untested overhead space.
    for p in coords[1:-1]:
        if Point(p[:2]).buffer(width/2).intersection(occupied).area>EPS:
            retain(p[2])
    return {'passed':minimum is None or minimum+EPS>=required,
            'minimum_clearance_m':minimum,'required_height_m':required,
            'soffit_z_m':soffit,'scope':'declared horizontal slab underside; beams/services unverified'}
