"""Siting terms the ranking reads: how many road openings a plan cuts, and what frontage the building takes.

Two statutory facts make these generic rather than one parcel's answer:

- 주차장법 시행규칙 제5조제6호, applied to 부설주차장 by 제11조제1항: where the lot connects to two or
  more roads, the entrance and exit go on the road with less traffic impact. The front road
  (`front_frontage`, the widest, `road_context`) is therefore the last place for a gate.
- 제6조제1항제4호: at 50 or more spaces one entrance of 5.5 m suffices (or a separated entry and exit),
  and below that a single 3.5 m entrance does. A surface lot and its basement ramp need not cut two
  openings; a second opening is a cost to the street (FHWA-HRT-14-057 access management), never a
  benefit to the plan.

So the building gains where it takes frontage no vehicle may use (the front road, 차량출입불허구간)
and loses where it takes frontage a gate could use. No corner rule: a corner placement follows when
the main road and the gate road meet there.
"""
from __future__ import annotations

from shapely.geometry import shape
from shapely.ops import unary_union

# A building held back by a 건축한계선 or 대지 안의 공지 still faces that road.
FACING_M = 3.0
# Pieces shorter than this where drive meets frontage are coordinate noise, not an opening.
MIN_OPENING_M = 0.05


def road_openings(request, features):
    """Separate places where the ground drive meets the road frontage (validator `entrance_width`)."""
    if not request.get('frontage'):
        return 0
    drive = unary_union([shape(f['geometry']) for f in features
                         if f['properties'].get('layer') in ('parking_aisle', 'vehicular_access')
                         and f['properties'].get('level', 0) == 0])
    if drive.is_empty:
        return 0
    contact = drive.buffer(0.01).intersection(shape(request['frontage']))
    return sum(1 for g in getattr(contact, 'geoms', [contact]) if not g.is_empty and g.length > MIN_OPENING_M)


def gates_on_front(request, features):
    """Openings on the front road while some other road frontage is available (제5조제6호)."""
    if not request.get('frontage') or not request.get('front_frontage'):
        return 0
    road, front = shape(request['frontage']), shape(request['front_frontage'])
    if road.difference(front.buffer(0.05)).length <= MIN_OPENING_M:
        return 0  # the front road is the only road: nothing to prefer
    drive = unary_union([shape(f['geometry']) for f in features
                         if f['properties'].get('layer') in ('parking_aisle', 'vehicular_access')
                         and f['properties'].get('level', 0) == 0])
    if drive.is_empty:
        return 0
    contact = drive.buffer(0.01).intersection(road)
    return sum(1 for g in getattr(contact, 'geoms', [contact])
               if not g.is_empty and g.length > MIN_OPENING_M
               and g.intersection(front.buffer(0.05)).length > 0.5 * g.length)


def building_frontage_score(request, footprint):
    """Metres of no-vehicle frontage the building faces minus metres of gate frontage it faces.

    No-vehicle frontage: the front road where another road exists, and declared 차량출입불허구간.
    Gate frontage: the rest of `frontage`. Measured within FACING_M of the footprint.
    """
    if footprint is None or footprint.is_empty or not request.get('frontage'):
        return 0.0
    near = footprint.buffer(FACING_M)
    road = shape(request['frontage'])
    blocked = [shape(request['vehicle_prohibited'])] if request.get('vehicle_prohibited') else []
    if request.get('front_frontage'):
        front = shape(request['front_frontage'])
        if road.difference(front.buffer(0.05)).length > MIN_OPENING_M:
            blocked.append(front)
    unusable = unary_union(blocked) if blocked else None
    gate_supply = road.difference(unusable.buffer(0.05)) if unusable is not None else road
    taken_unusable = near.intersection(unusable).length if unusable is not None else 0.0
    return taken_unusable - near.intersection(gate_supply).length


__all__ = ['FACING_M', 'building_frontage_score', 'gates_on_front', 'road_openings']
