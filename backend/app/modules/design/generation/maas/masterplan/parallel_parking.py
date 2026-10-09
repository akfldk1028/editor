"""Parallel infill beside existing aisles; never changes the drive corridor."""
import math

from shapely.geometry import Polygon
from shapely.ops import unary_union

from .geometry import EPS, parts

# General parallel bays, Art. 3(1)1, edition effective 2026-07-27. The shorter
# residential-road exception is deliberately not assumed for an attached lot.
SOURCE = 'https://law.go.kr/LSW/lsLinkCommonInfo.do?chrClsCd=010202&lsJoLnkSeq=1025436739'
WIDTH_M, LENGTH_M = 2.0, 6.0


def infill(host, drive, existing, required, *, aisle_width):
    if not math.isfinite(aisle_width) or aisle_width <= 0:
        raise ValueError('parallel infill requires a positive aisle width')
    result = list(existing)
    occupied = unary_union([s['polygon'] for s in existing])
    host_b, drive_b = host.buffer(EPS), drive.buffer(EPS)
    for part in parts(drive):
        for ring in (part.exterior, *part.interiors):
            for a, b in zip(ring.coords, list(ring.coords)[1:]):
                length = math.dist(a, b)
                if length + EPS < LENGTH_M:
                    continue
                ux, uy = (b[0]-a[0])/length, (b[1]-a[1])/length
                for sign in (-1, 1):
                    nx, ny = -uy*sign, ux*sign
                    offset = 0.
                    while offset + LENGTH_M <= length + EPS and len(result) < required:
                        x, y = a[0]+ux*offset, a[1]+uy*offset
                        end = (x+ux*LENGTH_M, y+uy*LENGTH_M)
                        bay = Polygon([(x,y),end,(end[0]+nx*WIDTH_M,end[1]+ny*WIDTH_M),
                                       (x+nx*WIDTH_M,y+ny*WIDTH_M)])
                        front = Polygon([(x,y),end,(end[0]-nx*aisle_width,end[1]-ny*aisle_width),
                                         (x-nx*aisle_width,y-ny*aisle_width)])
                        valid = (host_b.covers(bay) and drive_b.covers(front)
                                 and bay.intersection(drive).area <= EPS
                                 and bay.intersection(occupied).area <= EPS)
                        if valid:
                            result.append({'polygon': bay, 'front': front, 'type': 'standard_parallel',
                                           'width_m': WIDTH_M, 'length_m': LENGTH_M})
                            occupied = occupied.union(bay)
                        offset += LENGTH_M if valid else .5
    return result
