"""Non-parking floor area a basement level has to hold, and where it sits.

A basement is not a parking deck.  In the reference scheme (고산동 주민센터 기본계획,
ALT2 지하1층 평면도) the underground floor carries 기계실 195.57, 전기실 77.44,
발전기실 35.20, 통합방재실 40.26, 수방자재보관실 68.40, 창고 34.19 + 23.80,
계단실 22.40 + 21.00, 계단홀 15.36, ELEV.홀 29.71, 펌프실 14.58 m2 - about 578 m2 of
programme against 703 m2 of parking (19 stalls).  Planning the whole excavation as
stalls overstates the count by roughly the programme's share of the floor.

The areas themselves are NOT invented here: they arrive as a declared design input
(``options["basement_program"]``) or from the agent that owns the programme.  This
module only turns declared areas into a reserved band inside the basement outline, so
the parking packer cannot use it, and slices that band into the declared rooms for the
floor-plan handoff.  Practice puts the band along one edge, away from the ramp arrival,
and gives the middle to the parking rows.
"""
from __future__ import annotations

from shapely.affinity import rotate
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

EPS = 1e-9
MIN_BAND_DEPTH_M = 5.0  # legacy import compatibility only; not a room standard or search constraint


def declared_rooms(options: dict) -> list[dict]:
    """The declared basement programme, validated.  [] when nothing was declared."""
    raw = options.get("basement_program") or []
    if not isinstance(raw, list):
        raise ValueError("basement_program must be a list of {name, area_m2} rooms")
    rooms = []
    for item in raw:
        if not isinstance(item, dict) or "area_m2" not in item:
            raise ValueError("each basement_program entry needs an area_m2")
        area = float(item["area_m2"])
        if not (0 < area <= 10000):
            raise ValueError("basement_program area_m2 out of range")
        rooms.append({"name": str(item.get("name") or "unnamed"), "area_m2": area,
                      "kind": str(item.get("kind") or "plant")})
    return rooms


def _band(bounds, side: str, depth: float):
    x0, y0, x1, y1 = bounds
    if side == "west":
        return box(x0, y0, x0 + depth, y1)
    if side == "east":
        return box(x1 - depth, y0, x1, y1)
    if side == "south":
        return box(x0, y0, x1, y0 + depth)
    return box(x0, y1 - depth, x1, y1)


def _depth_for_area(host, bounds, side: str, target: float, span: float) -> float | None:
    """Smallest depth whose band ∩ host reaches `target` (area grows with depth)."""
    lo, hi = 0.0, span
    if host.intersection(_band(bounds, side, hi)).area + EPS < target:
        return None
    for _ in range(40):
        mid = (lo + hi) / 2
        if host.intersection(_band(bounds, side, mid)).area < target:
            lo = mid
        else:
            hi = mid
    return hi


def _slice_rooms(zone, rooms, along_x: bool, angle_deg: float, origin) -> list[dict]:
    """Cut by measured polygon area, not bounding-box length on a tapered band."""
    if zone.is_empty or not zone.is_valid or zone.geom_type!="Polygon" or zone.interiors:
        return []
    minx, miny, maxx, maxy = zone.bounds
    total = sum(r["area_m2"] for r in rooms) or 1.0
    if zone.area+EPS<total:
        return []
    out, cursor = [], (minx if along_x else miny)
    cumulative = 0.0
    for room in sorted(rooms, key=lambda r: -r["area_m2"]):
        cumulative += zone.area * room["area_m2"] / total
        lo, hi = cursor, (maxx if along_x else maxy)
        for _ in range(48):
            mid = (lo+hi)/2
            prefix = box(minx,miny,mid,maxy) if along_x else box(minx,miny,maxx,mid)
            if zone.intersection(prefix).area < cumulative:
                lo = mid
            else:
                hi = mid
        cut = (box(cursor,miny,hi,maxy) if along_x else box(minx,cursor,maxx,hi))
        piece = zone.intersection(cut)
        cursor = hi
        if (piece.is_empty or not piece.is_valid or piece.geom_type!="Polygon" or piece.interiors
                or piece.area+EPS<room["area_m2"]):
            return []
        piece = rotate(piece, angle_deg, origin=origin).buffer(0)
        if (piece.is_empty or not piece.is_valid or piece.geom_type!="Polygon" or piece.interiors
                or piece.area+EPS<room["area_m2"]):
            return []
        out.append({**room, "polygon": piece, "placed_area_m2": piece.area})
    return out


def plant_zone_candidates(basement, rooms: list[dict], *, keep_clear=None, angle_deg: float = 0.0,
                          origin=(0, 0), limit: int = 4) -> list[dict]:
    """Return bounded alternatives reserving the whole programme at distinct edges.

    `angle_deg` is the parking row angle, so the band squares up with the rows.
    `keep_clear` is the caller's union of all occupied structure, ramps and access
    reservations. A candidate cannot overlap it. No room width or depth standard
    is inferred from declared area; detailed room design remains a later task.
    """
    if not isinstance(limit,int) or isinstance(limit,bool) or not 1<=limit<=4:
        raise ValueError("programme candidate limit must be an integer from 1 to 4")
    target = sum(r["area_m2"] for r in rooms)
    if target <= 0 or basement.is_empty:
        return []
    # Difference followed by an inverse rotation can leave coincident edges
    # and zero-area spikes at a shared programme corner. Normalize the area
    # topology before further clipping; no buffer clearance is introduced.
    local = rotate(basement, -angle_deg, origin=origin).buffer(0)
    if local.is_empty:
        return []
    bounds = local.bounds
    clear = rotate(keep_clear, -angle_deg, origin=origin) if keep_clear is not None and not keep_clear.is_empty else None
    candidates = []
    for side in ("west", "east", "south", "north"):
        span = (bounds[2] - bounds[0]) if side in ("west", "east") else (bounds[3] - bounds[1])
        depth = _depth_for_area(local, bounds, side, target, span)
        if depth is None or depth <= EPS or depth > span / 2:
            continue
        zone = local.intersection(_band(bounds, side, depth))
        if zone.geom_type!="Polygon" or not zone.is_valid or zone.interiors:
            continue
        if clear is not None and zone.intersection(clear).area > EPS:
            continue
        rest = local.difference(zone)
        if rest.is_empty:
            continue
        rest = max(getattr(rest, "geoms", [rest]), key=lambda g: g.area)
        # the band may not wall the ramp arrival off from the parking field
        if clear is not None and not rest.buffer(0.05).intersects(clear):
            continue
        # practice: plant away from the ramp arrival, and leave the widest possible field for rows
        far = zone.centroid.distance(clear.centroid) if clear is not None else 0.0
        rx0, ry0, rx1, ry1 = rest.bounds
        score = tuple(round(value,6) for value in (rest.area, min(rx1-rx0,ry1-ry0), far))
        placed = _slice_rooms(zone, rooms, along_x=side in ("south", "north"), angle_deg=angle_deg, origin=origin)
        if len(placed)!=len(rooms):
            continue
        candidates.append({"zone": rotate(zone, angle_deg, origin=origin), "rooms": placed, "side": side,
            "depth_m": round(depth, 2), "area_m2": zone.area,
            "declared_area_m2": target, "rank_score": score})
    return sorted(candidates,key=lambda c:c["rank_score"],reverse=True)[:limit]


def block_plant_zone_candidates(basement, rooms, *, keep_clear=None, angle_deg=0.0,
                                origin=(0,0), limit=4, grid_steps=2):
    """Whole rectangular room groups where full-edge strips hit ramps/cores.

    Dimensions are search alternatives derived from area and host extents, not
    room standards. Every room still needs doors, equipment and egress review.
    """
    if not isinstance(limit,int) or isinstance(limit,bool) or not 1<=limit<=4:
        raise ValueError('block programme limit must be an integer from 1 to 4')
    if type(grid_steps) is not int or not 2<=grid_steps<=8:
        raise ValueError('block placement grid_steps must be 2..8')
    target=sum(room['area_m2'] for room in rooms)
    if target<=0 or basement.is_empty or basement.area+EPS<target:
        return []
    local=rotate(basement,-angle_deg,origin=origin).buffer(0)
    clear=rotate(keep_clear,-angle_deg,origin=origin) if keep_clear is not None else Polygon()
    x0,y0,x1,y1=local.bounds
    widths=(target**.5,(x1-x0)/2,target/((y1-y0)/2))
    candidates=[]
    for width in widths:
        height=target/width
        if width>x1-x0+EPS or height>y1-y0+EPS:
            continue
        for fx in (i/grid_steps for i in range(grid_steps+1)):
            for fy in (i/grid_steps for i in range(grid_steps+1)):
                x,y=x0+(x1-x0-width)*fx,y0+(y1-y0-height)*fy
                zone=box(x,y,x+width,y+height)
                if not local.buffer(EPS).covers(zone) or zone.intersection(clear).area>EPS:
                    continue
                world=rotate(zone,angle_deg,origin=origin).buffer(0)
                if any(world.symmetric_difference(c['zone']).area<EPS for c in candidates):
                    continue
                placed=_slice_rooms(zone,rooms,width>=height,angle_deg,origin)
                if len(placed)!=len(rooms):
                    continue
                far=zone.centroid.distance(clear.centroid) if not clear.is_empty else 0
                # Prefer compact blocks and perimeter locations; actual parking
                # capacity and connectivity determine the solver's final choice.
                rank=(-zone.length,zone.boundary.intersection(local.boundary).length,far)
                candidates.append({'zone':world,'rooms':placed,'side':'block',
                    'aspect_family':round(width,6),
                    'depth_m':min(width,height),'area_m2':world.area,
                    'declared_area_m2':target,'rank_score':rank})
    ordered=sorted(candidates,key=lambda c:c['rank_score'],reverse=True)
    if grid_steps>2:
        families={}
        for c in ordered:
            families.setdefault(c['aspect_family'],c)
        diverse=list(families.values())
        ordered=diverse+[c for c in ordered if all(c is not d for d in diverse)]
    return ordered[:limit]


def plant_zone(basement, rooms: list[dict], *, keep_clear=None, angle_deg: float = 0.0,
               origin=(0, 0)) -> dict | None:
    """Compatibility wrapper selecting the first ranked programme alternative."""
    candidates=plant_zone_candidates(basement,rooms,keep_clear=keep_clear,angle_deg=angle_deg,origin=origin)
    return candidates[0] if candidates else None


def split_plant_zone_candidates(basement, rooms: list[dict], *, keep_clear=None,
                                angle_deg: float = 0.0, origin=(0, 0),
                                limit: int = 8) -> list[dict]:
    """Distribute whole declared rooms between two clear perimeter bands.

    Two deterministic partitions (largest room versus the rest, and greedily
    balanced area) compare edge bands and compact blocks. Individual rooms
    remain connected polygons with their declared area. This is a geometry
    reservation, not certification of room access or equipment clearances.
    """
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 8:
        raise ValueError("split programme limit must be an integer from 1 to 8")
    if len(rooms) < 2 or basement.is_empty:
        return []
    ordered = sorted(range(len(rooms)), key=lambda i: (-rooms[i]["area_m2"], i))
    balanced = [[], []]
    totals = [0.0, 0.0]
    for index in ordered:
        group = 0 if totals[0] <= totals[1] else 1
        balanced[group].append(index)
        totals[group] += rooms[index]["area_m2"]
    partitions = [(ordered[:1], ordered[1:]), tuple(balanced)]
    seen_partitions, seen_geometries, candidates = set(), set(), []
    for groups in partitions:
        partition_key = tuple(sorted(tuple(sorted(g)) for g in groups))
        if partition_key in seen_partitions:
            continue
        seen_partitions.add(partition_key)
        first_rooms, second_rooms = ([rooms[i] for i in g] for g in groups)
        first_choices=plant_zone_candidates(basement,first_rooms,keep_clear=keep_clear,
                                            angle_deg=angle_deg,origin=origin)
        first_choices+=block_plant_zone_candidates(basement,first_rooms,keep_clear=keep_clear,
                                            angle_deg=angle_deg,origin=origin,limit=2)
        for first in first_choices:
            occupied = [first["zone"]]
            if keep_clear is not None and not keep_clear.is_empty:
                occupied.append(keep_clear)
            # Reserve the first wing before generating the second. Two strips
            # cut from the full slab always overlap at an adjacent corner,
            # incorrectly restricting this search to opposite edges only.
            remaining_host = basement.difference(first['zone'])
            second_choices=plant_zone_candidates(remaining_host,second_rooms,
                    keep_clear=unary_union(occupied),angle_deg=angle_deg,origin=origin)
            second_choices+=block_plant_zone_candidates(remaining_host,second_rooms,
                    keep_clear=unary_union(occupied),angle_deg=angle_deg,origin=origin,limit=2)
            for second in second_choices:
                if first["zone"].intersection(second["zone"]).area > EPS:
                    continue
                zone = unary_union([first["zone"], second["zone"]])
                geometry_key = zone.normalize().wkb_hex
                if geometry_key in seen_geometries:
                    continue
                seen_geometries.add(geometry_key)
                remaining = basement.difference(zone)
                local_remaining = rotate(remaining, -angle_deg, origin=origin)
                x0, y0, x1, y1 = local_remaining.bounds
                far = (zone.centroid.distance(keep_clear.centroid)
                       if keep_clear is not None and not keep_clear.is_empty else 0.0)
                score = tuple(round(value, 6) for value in
                              (remaining.area, min(x1-x0, y1-y0), far))
                candidates.append({"zone": zone, "rooms": first["rooms"] + second["rooms"],
                    "side": "+".join(sorted([first["side"], second["side"]])),
                    "depth_m": max(first["depth_m"], second["depth_m"]),
                    "area_m2": zone.area,
                    "declared_area_m2": sum(room["area_m2"] for room in rooms),
                    "rank_score": score, "bands": [first, second]})
    # Keep different edge topologies ahead of second partitions of the same pair.
    ordered_candidates = sorted(candidates, key=lambda c: c["rank_score"], reverse=True)
    preferred, repeated, sides = [], [], set()
    for candidate in ordered_candidates:
        if candidate["side"] in sides:
            repeated.append(candidate)
        else:
            preferred.append(candidate)
            sides.add(candidate["side"])
    return (preferred + repeated)[:limit]


def zone_union(zone: dict | None):
    """The reserved geometry as one polygon for the packer's obstacle list."""
    if not zone:
        return Polygon()
    return unary_union([zone["zone"]])


__all__ = ["declared_rooms", "plant_zone", "plant_zone_candidates", "split_plant_zone_candidates", "block_plant_zone_candidates",
           "zone_union", "MIN_BAND_DEPTH_M"]
