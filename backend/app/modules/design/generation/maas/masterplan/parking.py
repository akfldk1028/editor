"""Bounded aisle-and-spine parking search using supplied ARR/Lawagent dimensions.

Every retained stall has its full manoeuvring cell and a connected drive spine.
This is a geometric search, not a parking-count area heuristic.
"""
from __future__ import annotations

import math
from shapely.affinity import rotate
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.masterplan.geometry import EPS, parts


def _connected_component(drive, anchors):
    polygons = parts(drive)
    if not anchors:
        return max(polygons, key=lambda p:p.area, default=Polygon())
    touched = [p for p in polygons if any(p.distance(a) < EPS for a in anchors)]
    return max(touched, key=lambda p:p.area, default=Polygon())


def _principal_angles(envelope):
    """Orientation (degrees) of the envelope's minimum rotated rectangle and its normal."""
    rect = envelope.minimum_rotated_rectangle
    coords = list(getattr(rect, "exterior", rect).coords) if not rect.is_empty else []
    if len(coords) < 3:
        return []
    (x0, y0), (x1, y1) = coords[0], coords[1]
    angle = round(math.degrees(math.atan2(y1-y0, x1-x0)), 6)
    return [angle, angle+90]


def pack_level(envelope, anchors, rules, required, accessible=0, *, preferred_angle=0, require_full_width=False, allowed_angles=None, preserve_banks=False):
    if required <= 0 or envelope.is_empty:
        return {"stalls": [], "drive": Polygon(), "provided": 0, "accessible": 0, "search_count": 0}
    aisle = float(rules["aisle_width_m"])
    stall_w, stall_l = float(rules["stall_width_m"]), float(rules["stall_length_m"])
    accessible_w = float(rules["accessible_width_m"])
    accessible_l = float(rules["accessible_length_m"])
    best = None
    trials = 0
    # A real parcel is never axis-aligned in its UTM frame; the spine/strip
    # boxes span the host's bounding box, so the host must be rotated square
    # first. Try the envelope's own principal orientation as well as the
    # frontage angle and the world axes.
    angles = list(dict.fromkeys(allowed_angles if allowed_angles is not None else
                               [preferred_angle, preferred_angle+90, 0, 90, *_principal_angles(envelope)]))
    for angle in angles:
        host = rotate(envelope,-angle,origin=(0,0))
        if not host.is_valid:
            # A residual ground polygon (site minus an authored plate, front strip and ramp) can
            # carry a self-touching ring after rotation; GEOS then raises "side location conflict"
            # on the first box intersection. buffer(0) heals the ring without moving any edge.
            host = host.buffer(0)
        entrances = [rotate(a,-angle,origin=(0,0)) for a in anchors]
        minx,miny,maxx,maxy = host.bounds
        if maxx-minx < aisle+stall_w or maxy-miny < aisle+stall_l:
            continue
        xchoices = [minx, maxx-aisle]
        for anchor in entrances:
            xchoices.extend([anchor.bounds[0]-aisle,anchor.bounds[2]])
        for sx in dict.fromkeys(round(x,6) for x in xchoices if minx-EPS <= x <= maxx-aisle+EPS):
            # The spine is the part of the full-height corridor that lies in the
            # host. A real parcel is never an exact rectangle, so requiring the
            # whole bounding-box corridor to be covered produced zero trials on
            # every surveyed site. Each stall and its manoeuvring cell are still
            # required to lie entirely inside the host below.
            spine = box(sx,miny,sx+aisle,maxy).intersection(host)
            if spine.is_empty or spine.geom_type != "Polygon" or spine.area < aisle*stall_w:
                continue
            for offset in (0,stall_l,stall_l+aisle):
                trials += 1
                aisles = []
                cells = []
                y = miny+offset
                while y+aisle <= maxy+EPS:
                    strip = box(minx,y,maxx,y+aisle).intersection(host)
                    aisles.extend(parts(strip))
                    for side in (-1,1):
                        x = minx
                        while x+stall_w <= maxx+EPS:
                            # Wider bays are generated as alternatives; regular
                            # bays resume after the accessible quota, not overlap.
                            want_accessible = sum(c["type"]=="accessible" for c in cells) < accessible
                            w = accessible_w if want_accessible else stall_w
                            length = accessible_l if want_accessible else stall_l
                            if x+w > maxx+EPS:
                                break
                            sy = y-length if side == -1 else y+aisle
                            stall = box(x,sy,x+w,sy+length)
                            manoeuvre = box(x,y,x+w,y+aisle)
                            if (host.buffer(EPS).covers(stall) and host.buffer(EPS).covers(manoeuvre)
                                    and stall.intersection(spine).area <= EPS
                                    and all(stall.intersection(c["polygon"]).area <= EPS for c in cells)):
                                cells.append({"polygon":stall,"front":manoeuvre,
                                              "type":"accessible" if want_accessible else "standard_90deg",
                                              "width_m":w,"length_m":length})
                            x += w
                    y += 2*max(stall_l,accessible_l)+aisle
                drive = unary_union([spine,*aisles])
                # The spine may run beside a ramp landing; add only corridors
                # whose complete width lies in the supplied driving envelope.
                for entrance in entrances:
                    if drive.distance(entrance) < EPS:
                        continue
                    ax,ay = entrance.centroid.x,entrance.centroid.y
                    corridor = box(min(ax,sx+aisle/2)-aisle/2,ay-aisle/2,
                                   max(ax,sx+aisle/2)+aisle/2,ay+aisle/2)
                    if host.buffer(EPS).covers(corridor):
                        drive = drive.union(corridor)
                connected = _connected_component(drive, entrances)
                if connected.is_empty:
                    continue
                valid = [c for c in cells if connected.buffer(EPS).covers(c["front"])]
                valid.sort(key=lambda c:(c["type"] != "accessible",
                                         min((c["polygon"].distance(a) for a in entrances),default=0),
                                         c["polygon"].centroid.y,c["polygon"].centroid.x))
                if preserve_banks:
                    from backend.app.modules.design.generation.maas.masterplan.stall_banks import select_complete_banks
                    selected=select_complete_banks(valid,required)
                else:
                    selected = valid[:required]
                # Keep aisles/spine clear of every selected parked vehicle.
                if any(connected.intersection(c["polygon"]).area > EPS for c in selected):
                    continue
                acc = sum(c["type"] == "accessible" for c in selected)
                score = (min(acc,accessible),len(selected),-connected.area)
                if best is None or score > best[0]:
                    world_stalls = [{**c,"polygon":rotate(c["polygon"],angle,origin=(0,0)),
                                     "front":rotate(c["front"],angle,origin=(0,0))} for c in selected]
                    world_drive = rotate(connected,angle,origin=(0,0))
                    if require_full_width:
                        from backend.app.modules.design.generation.maas.masterplan.bounded_packing import _width_connected
                        if not _width_connected({'stalls':world_stalls, 'drive':world_drive}, anchors, aisle):
                            continue
                    best = (score,{"stalls":world_stalls,"drive":world_drive,
                                   "provided":len(selected),"accessible":acc,
                                   "available_spaces":len(valid),"angle_deg":angle})
    result = best[1] if best else {"stalls":[],"drive":Polygon(),"provided":0,"accessible":0}
    return {**result,"search_count":trials}
