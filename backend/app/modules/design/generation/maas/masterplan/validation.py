"""Independent checks of serialized geometry, not trust in solver status strings."""
from __future__ import annotations

import math
from collections import defaultdict

from shapely.geometry import LineString, Point, Polygon, shape
from shapely.ops import unary_union, substring

from backend.app.modules.design.generation.maas.masterplan.compact_slab import REQUIRED_LAYERS
from backend.app.modules.design.generation.maas.masterplan.ramp_overhead import overhead_clearance
from backend.app.modules.design.generation.maas.masterplan.pedestrian import pedestrian_reservation, profile_flat_area, ramp_reservation_conflicts
from backend.app.modules.design.generation.maas.masterplan.circulation import closed_aisle_loop, full_width_stall_access
from backend.app.modules.design.generation.maas.masterplan.core_repair import clearance as core_clearance_requirement

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


def validate_plan(request, result):
    checks = []
    pending = []
    def check(key, ok, **measurements):
        # ok=None records a MEASUREMENT with no verdict: used where the rule's datum is unsettled
        # or where the thing measured is lawful but worth a reviewer's eye.
        checks.append({"id":key,"status":"measured" if ok is None else ("passed" if ok else "failed"),
                       **measurements})
    site = shape(request["site"])
    buildable = shape(request.get("buildable") or request["site"])
    basement = shape(request.get("basement_boundary") or request["site"])
    rules = request.get("rules") or {}
    law = request.get("law") or {}
    features = result.get("features",[])
    core_clearance = core_clearance_requirement(request)
    pedestrian=pedestrian_reservation(request)
    pending.extend(pedestrian['pending_reviews'])
    source_obstacles = [shape(x) for x in request.get("columns",[])]
    if request.get("core"):
        source_obstacles.append(shape(request["core"]))
    grouped = defaultdict(list)
    for f in features:
        p = f["properties"]
        if f.get("geometry"):
            try:
                g = shape(f["geometry"])
                check(f"geometry_valid:{p.get('layer')}:{p.get('stall_id','')}",g.is_valid and not g.is_empty)
                grouped[(p.get("level",0),p["layer"])].append((g,p))
            except Exception:
                check("geometry_parse",False)
    occupied=shape(request['ground_footprint']) if request.get('ground_footprint') else (
        shape(request['footprint']) if request.get('footprint') else unary_union(
            [g for g,p in grouped[(0,'building_ground_footprint')] or grouped[(0,'building_footprint')]]))
    check('pedestrian_reservation_ground_building',occupied.intersection(pedestrian['reserved']).area<=TOL)
    for layer in ('parking_stall','parking_aisle','vehicular_access'):
        forbidden=pedestrian['reserved'] if layer=='parking_stall' else pedestrian['vehicle_blocked']
        overlap=sum(g.intersection(forbidden).area for g,p in grouped[(0,layer)])
        check(f'pedestrian_reservation:{layer}',overlap<=TOL,overlap_m2=overlap)
    ramp_overlap=0.
    for (ramp_level,layer),items in list(grouped.items()):
        if layer!='ramp':
            continue
        for geom,props in items:
            if props.get('from_level')==0 or props.get('to_level')==0:
                flat=_flat_ramp_area(grouped,geom,props,0)
                conflict=ramp_reservation_conflicts({'polygon':geom},pedestrian,ground_flat=flat,tolerance=TOL)
                ramp_overlap+=conflict['overlap_m2']
    check('pedestrian_reservation:ramp',ramp_overlap<=TOL,overlap_m2=ramp_overlap)
    for g,p in grouped[(0,"building_footprint")]:
        check("footprint_containment",buildable.buffer(TOL).covers(g),outside_m2=g.difference(buildable).area)
        limit = law.get("ground_capacity_m2")
        if limit is None and law.get("bcr_pct") is not None:
            limit = site.area*law["bcr_pct"]/100
        if limit is not None:
            check("footprint_area",g.area <= limit+TOL,area_m2=g.area,limit_m2=limit)
    if request.get("footprint"):
        drawn = unary_union([g for g,p in grouped[(0,"building_footprint")]])
        check("authored_footprint_preserved",drawn.symmetric_difference(shape(request["footprint"])).area<=TOL)
    ground_occupancy = None
    if request.get("ground_footprint") is not None:
        ground_occupancy = shape(request["ground_footprint"])
        drawn_ground = unary_union([g for g,p in grouped[(0,"building_ground_footprint")]])
        drawn_mass = unary_union([g for g,p in grouped[(0,"building_footprint")]])
        check("authored_ground_footprint_preserved",drawn_ground.symmetric_difference(ground_occupancy).area<=TOL)
        check("ground_footprint_containment",drawn_mass.buffer(TOL).covers(ground_occupancy))
        if request.get("core"):
            check("ground_footprint_contains_core",ground_occupancy.buffer(TOL).covers(shape(request["core"])))
        if drawn_mass.difference(ground_occupancy).area>TOL:
            pending.append("piloti_structural_clearance_review")
        ground_drive = unary_union([g for g,p in grouped[(0,"parking_aisle")]+grouped[(0,"vehicular_access")]])
        check("drive_ground_footprint_collision:0",ground_drive.intersection(ground_occupancy).area<=TOL)
    for (level,layer),items in list(grouped.items()):
        if layer!="basement_boundary":
            continue
        slab=unary_union([g for g,p in items])
        required_geometry=unary_union([g for (other_level,other_layer),objects in grouped.items()
            if other_level==level and other_layer in REQUIRED_LAYERS for g,p in objects])
        check(f"basement_boundary_preserves_programme:{level}",slab.buffer(TOL).covers(required_geometry))
        # The declared boundary is the PARKING PLATE; what is dug is that plate plus the ramp that
        # reaches it, because a ramp to a 3.3 m basement runs about 37 m and practice lets it pass
        # the plate rather than shortening the plate to hold it (reference ALT1 draws exactly that).
        # So the guard keeps its teeth - nothing may be dug that is not the plate or a ramp, and
        # nothing outside the parcel - instead of forbidding the ramp outright, which rejected every
        # basement on a slab shorter than the run.
        ramps_here=unary_union([g for (other_level,other_layer),objects in grouped.items()
            if other_layer=="ramp" for g,p in objects
            if level in (p.get("from_level"),p.get("to_level"))])
        dug_envelope=unary_union([basement,ramps_here]).intersection(site).buffer(0)
        check(f"basement_boundary_envelope:{level}",dug_envelope.buffer(TOL).covers(slab),
              declared_m2=round(basement.area,2),dug_m2=round(slab.area,2))
        if any(p.get("compact_candidate") for g,p in items):
            check(f"compact_slab_preserves_programme:{level}",slab.buffer(TOL).covers(required_geometry))
            check(f"compact_slab_envelope:{level}",basement.buffer(TOL).covers(slab))
    count = 0
    accessible = 0
    levels = sorted({level for (level,layer),items in grouped.items()
                     if items and layer in {"parking_stall","parking_aisle","vehicular_access"}})
    placement_stage = (request.get('options') or {}).get('planning_stage') == 'placement'
    for level in levels:
        plates=[g for g,p in grouped[(level,"basement_boundary")]]
        host = unary_union(plates) if level<0 and plates else basement if level<0 else site
        stalls = grouped[(level,"parking_stall")]
        drive_geoms = [g for g,p in grouped[(level,"parking_aisle")]+grouped[(level,"vehicular_access")]]
        drive = unary_union(drive_geoms)
        forbidden = [*source_obstacles,*[g for g,p in grouped[(level,"building_core")]+grouped[(level,"column")]]]
        for g,p in grouped[(level,"ramp")]:
            forbidden.append(g)
        if level==0:
            if ground_occupancy is not None:
                forbidden.append(ground_occupancy)
            elif request.get("options",{}).get("parking_strategy") not in {"piloti","piloti_and_surface"}:
                forbidden.extend(g for g,p in grouped[(0,"building_footprint")])
        blocked = unary_union(forbidden)
        check(f"drive_containment:{level}",host.buffer(TOL).covers(drive),outside_m2=drive.difference(host).area)
        drive_blockers=[*source_obstacles,*[g for g,p in grouped[(level,"building_core")]
            +grouped[(level,"column")]+grouped[(level,"basement_plant_zone")]+grouped[(level,"basement_room")]]]
        if level==0:
            if ground_occupancy is not None:
                drive_blockers.append(ground_occupancy)
            elif request.get("options",{}).get("parking_strategy") not in {"piloti","piloti_and_surface"}:
                drive_blockers.extend(g for g,p in grouped[(0,"building_footprint")])
        for (ramp_level,ramp_layer),items in list(grouped.items()):
            if ramp_layer!="ramp":
                continue
            for ramp_geom,ramp_props in items:
                if level in {ramp_props.get("from_level"),ramp_props.get("to_level")}:
                    flat=_stacked_flat_access(grouped,ramp_geom,ramp_props,level,request.get('options',{}),rules)
                    # The landing edge is a construction joint, not a knife edge, and a turning ramp's
                    # band and its landing are two polygon approximations of the same arc: they
                    # disagree by slivers (measured 0.0094 m2 on the 고산 curved scheme, which was the
                    # ONLY thing failing an otherwise clean 62/62 plan with both levels' loops
                    # certified). 1 cm past the landing the ramp has fallen 1.4 mm at the statutory
                    # 14 % curve grade, so this cannot hide a drive drawn up a slope - that is square
                    # metres, and the area test below stays at TOL to catch it.
                    drive_blockers.append(ramp_geom.difference(flat.buffer(LANDING_JOINT_TOL)))
        # Record the overlap, not just the verdict: a failure of 0.01 m2 on a turning ramp and one of
        # 150 m2 on a drive drawn up the slope are different problems, and the id alone cannot tell them apart.
        drive_conflict=drive.intersection(unary_union(drive_blockers)).area
        check(f"drive_obstructions:{level}",drive_conflict<=TOL,overlap_m2=round(drive_conflict,4))
        if request.get('core') and core_clearance:
            core_geom = shape(request['core'])
            ramps = [g for (lv, layer), items in grouped.items() if layer == 'ramp'
                     for g, p in items if level in (p.get('from_level'), p.get('to_level'))]
            vehicle_geom = unary_union([drive, *[g for g, p in stalls], *ramps])
            distance = core_geom.distance(vehicle_geom) if not vehicle_geom.is_empty else None
            check(f'core_vehicle_clearance:{level}', distance is None or distance+TOL >= core_clearance,
                  distance_m=distance, required_m=core_clearance,
                  scope='declared preliminary design clearance, not a certified door or pedestrian route')
        count += len(stalls)
        for index,(g,p) in enumerate(stalls):
            sid = p.get("stall_id",str(index))
            check(f"stall_containment:{sid}",host.buffer(TOL).covers(g),outside_m2=g.difference(host).area)
            check(f"stall_obstructions:{sid}",g.intersection(blocked).area <= TOL)
            check(f"stall_drive_collision:{sid}",g.intersection(drive).area <= TOL)
            overlap = sum(g.intersection(other).area for other,_ in stalls[index+1:])
            check(f"stall_overlap:{sid}",overlap<=TOL,overlap_m2=overlap)
            rect = g.minimum_rotated_rectangle
            edges = [math.dist(a,b) for a,b in zip(rect.exterior.coords,list(rect.exterior.coords)[1:])]
            width,length = min(edges),max(edges)
            is_accessible = p.get("type")=="accessible"
            accessible += int(is_accessible)
            rw = rules.get("accessible_width_m" if is_accessible else "stall_width_m")
            rl = rules.get("accessible_length_m" if is_accessible else "stall_length_m")
            if rw is not None and rl is not None:
                check(f"stall_dimensions:{sid}",width+TOL>=rw and length+TOL>=rl,
                      measured_width_m=width,measured_length_m=length)
            frontage = g.boundary.intersection(drive.buffer(TOL)).length
            check(f"stall_aisle_frontage:{sid}",frontage+TOL>=width,contact_m=frontage)
        # Drive aisles must be one component, except at ground where a surface
        # lot and a ramp departure may each meet the road on their own: there
        # every component must touch the road. Tiny coordinate noise is not a road.
        components = list(drive.buffer(TOL).geoms) if hasattr(drive.buffer(TOL),"geoms") else [drive]
        if level==0:
            road = shape(request["frontage"]) if request.get("frontage") else None
            if road is not None:
                check(f"drive_connected:{level}",all(c.distance(road)<=TOL for c in components) if not drive.is_empty else True,
                      components=len(components))
                check("road_connection",drive.distance(road)<=TOL)
            else:
                check(f"drive_connected:{level}",len(components)==1)
        else:
            check(f"drive_connected:{level}",len(components)==1)
            # Measure every basement; enforce closure only for an explicitly
            # requested ring layout. Topology does not certify vehicle maneuvers.
            navigable=drive.difference(unary_union(drive_blockers)).buffer(0)
            loop=closed_aisle_loop(navigable,rules.get('aisle_width_m'))
            ok = (loop is not None) if (request.get('options') or {}).get('basement_parking_field') == 'ring' else None
            check(f'closed_aisle_loop:{level}', ok,
                  closed=loop is not None,
                  width_m=rules.get('aisle_width_m'),
                  loop_length_m=round(loop.length,3) if loop is not None else None,
                  maneuver_status='needs_evidence',
                  note=('closed full-width corridor measured; actual vehicle maneuver unverified'
                        if loop is not None else
                        'no closed full-width corridor certified; end access and recovery require review'),
                  scope='closed full-width aisle geometry; steering/swept path remains separate')
            arrivals = [g for g,p in grouped[(level,"vehicular_access")] if p.get("role")=="ramp_arrival"]
            if (core_clearance or placement_stage) and rules.get('aisle_width_m'):
                check(f'{"placement_full_width_drive" if placement_stage else "core_repair_full_width_drive"}:{level}',
                      full_width_stall_access(navigable, [g for g,p in stalls], arrivals, rules['aisle_width_m']),
                      required_width_m=rules['aisle_width_m'],
                      scope='full-width connection from ramp to every stall manoeuvre cell; not swept path')
            check(f"ramp_to_aisle_connection:{level}",bool(arrivals) and all(g.distance(drive)<=TOL for g in arrivals))
    required = law.get("required_spaces")
    if required is not None:
        check("parking_count",count>=required,required=required,provided=count)
    elif count==0:
        # NOTHING DRAWN IS NOT NOTHING WRONG. With no stalls there is nothing for the geometry checks
        # to catch, so `geometry_status` comes back `passed` on a plan that contains no parking at
        # all - two benchmark parcels did exactly that. The demand is Lawagent's to state and it did
        # not, so this is not a violation to fail; it is an absence to record, and a reader who takes
        # `passed` for "this parcel worked" needs to see it.
        check("parking_designed",None,provided=0,
              note="no stalls drawn and no required count from Lawagent: nothing here can be affirmed")
    # Entrance width where the ground drive meets the road (제6조①4 via 제11조①): one opening of the
    # required width, or two separate openings (entry/exit) for large lots.
    if rules.get("entrance_width_m") is not None and request.get("frontage"):
        road = shape(request["frontage"])
        ground_drive = unary_union([gg for gg,pp in grouped[(0,"parking_aisle")]+grouped[(0,"vehicular_access")]])
        contact = ground_drive.buffer(TOL).intersection(road)
        openings = sorted((c.length for c in getattr(contact,"geoms",[contact]) if not c.is_empty), reverse=True)
        need = float(rules["entrance_width_m"])
        # a 50-stall lot may instead split the opening in two (제6조제1항제4호); keep this a real
        # boolean - `rules.get(...)` returning None would otherwise make the verdict None
        ok = bool((openings and openings[0]+TOL >= need)
                  or (rules.get("entrance_large_lot") and len(openings) >= 2
                      and all(o+TOL >= 3.5 for o in openings[:2])))
        check("entrance_width",ok if not ground_drive.is_empty else True,openings_m=[round(o,2) for o in openings],required_m=need)
    # 확장형 share for lots the rules flag (제11조④ -> 제6조①14): counted over all perpendicular stalls.
    if rules.get("expanded_min_share") and count:
        all_stalls = [g for (lvl,layer),items in grouped.items() if layer=="parking_stall" for g,p in items]
        wide = 0
        for g in all_stalls:
            r = g.minimum_rotated_rectangle; e = [math.dist(a,b) for a,b in zip(r.exterior.coords,list(r.exterior.coords)[1:])]
            if min(e)+TOL >= float(rules.get("expanded_width_m") or 0) and max(e)+TOL >= float(rules.get("expanded_length_m") or 0):
                wide += 1
        check("expanded_stall_share",wide >= math.ceil(float(rules["expanded_min_share"])*count)-TOL,expanded=wide,required=math.ceil(float(rules["expanded_min_share"])*count),total=count)
    # The declared basement programme keeps its area: stalls may not stand in the reserved zone and
    # the zone must hold what was declared (제6조 dimensions are checked elsewhere; this is the brief).
    declared_program=(request.get("options") or {}).get("basement_program") or []
    basement_levels={level for (level,layer),items in grouped.items() if level<0 and items and layer=="basement_boundary"}
    used_basement_levels={level for (level,layer),items in grouped.items() if level<0 and items and layer in REQUIRED_LAYERS}
    for level in sorted(used_basement_levels):
        check(f"basement_boundary_present:{level}",level in basement_levels)
    basement_levels |= used_basement_levels
    if declared_program and basement_levels:
        programme_level=max(basement_levels)
        if placement_stage:
            check(f"basement_programme_present:{programme_level}",bool(grouped[(programme_level,"basement_plant_zone")]))
        else:
            check(f"basement_programme_present:{programme_level}",bool(grouped[(programme_level,"basement_plant_zone")])
                  and bool(grouped[(programme_level,"basement_room")]))
    programme_levels={level for (level,layer),items in grouped.items() if items
                      and layer in {"basement_plant_zone","basement_room"}}
    for level in sorted(programme_levels):
        items=grouped[(level,"basement_plant_zone")]
        zone=unary_union([g for g,p in items]); declared=sum(float(p.get("declared_area_m2") or 0) for g,p in items)
        clash=[p.get("stall_id") for g,p in grouped[(level,"parking_stall")] if g.intersection(zone).area>TOL]
        check(f"plant_zone_clear:{level}",not clash,stalls_in_zone=clash[:5],level=level)
        check(f"plant_zone_area:{level}",zone.area+TOL>=declared,reserved_m2=round(zone.area,2),declared_m2=round(declared,2))
        programme_blockers=unary_union([*source_obstacles,*[g for g,p in grouped[(level,"building_core")]
            +grouped[(level,"column")]+grouped[(level,"ramp")]]])
        check(f"plant_zone_obstructions:{level}",zone.intersection(programme_blockers).area<=TOL)
        individual_rooms=grouped[(level,"basement_room")]
        for index,(room,props) in enumerate(individual_rooms):
            check(f"basement_room_zone_containment:{level}:{index}",zone.buffer(TOL).covers(room))
            if props.get("declared_area_m2") is not None:
                check(f"basement_room_declared_area:{level}:{index}",room.area+TOL>=props["declared_area_m2"])
            check(f"basement_room_overlap:{level}:{index}",all(room.intersection(other).area<=TOL
                for other,_ in individual_rooms[index+1:]))
            check(f"basement_room_connected:{level}:{index}",room.geom_type=="Polygon" and not room.interiors)
            check(f"basement_room_obstructions:{level}:{index}",room.intersection(programme_blockers).area<=TOL)
        if not placement_stage:
            requested = {}
            for room in (request.get("options") or {}).get("basement_program") or []:
                name=str(room.get("name") or "unnamed")
                requested[name]=requested.get(name,0)+float(room["area_m2"])
            for name, area in requested.items():
                pieces=[g for g,p in grouped[(level,"basement_room")] if p.get("name")==name]
                actual=unary_union(pieces)
                check(f"basement_room_area:{level}:{name}",actual.area+TOL>=area,
                      placed_m2=round(actual.area,2),declared_m2=area)
                check(f"basement_room_containment:{level}:{name}",zone.buffer(TOL).covers(actual))
    max_spaces = law.get("max_spaces")
    if max_spaces is not None:
        check("parking_cap",count<=max_spaces,maximum=max_spaces,provided=count)
    req_acc = law.get("required_accessible_spaces")
    if req_acc is not None:
        check("accessible_count",accessible>=req_acc,required=req_acc,provided=accessible)
    elif count:
        # Serialized designs can bypass planner missing-evidence propagation.
        # Do not calculate a count or treat absent applicability as exemption.
        pending.append("accessible_space_count_requires_facility_and_local_ordinance_evidence")
    if accessible or (req_acc is not None and req_acc > 0):
        pending.append("accessible_pedestrian_route_review")
    ramps = [(g,p) for (level,layer),items in grouped.items() if layer=="ramp" for g,p in items]
    for g,p in ramps:
        rid = f"{p.get('from_level')}:{p.get('to_level')}"
        profile = p.get("profile",[])
        if p.get('from_level',0)<0:
            pending.append('stacked_ramp_soffit_beams_services_review')
        center=next((c for c,cp in grouped[(p.get("to_level"),"ramp_centerline")]
            if cp.get("from_level")==p.get("from_level") and cp.get("to_level")==p.get("to_level")),None)
        for endpoint,role,level in ((0,"ramp_departure",p.get("from_level")),
                                    (-1,"ramp_arrival",p.get("to_level"))):
            access=unary_union([a for a,ap in grouped[(level,"vehicular_access")]
                if ap.get("role")==role and ap.get("from_level",p.get("from_level"))==p.get("from_level")
                and ap.get("to_level",p.get("to_level"))==p.get("to_level")])
            flat=_flat_ramp_area(grouped,g,p,level)
            valid_endpoint=False
            if center is not None and center.geom_type=="LineString" and profile:
                point=center.coords[endpoint]
                valid_endpoint=(len(point)>=3 and abs(point[2]-profile[endpoint]["z_m"])<=TOL
                    and access.buffer(TOL).covers(Point(point[:2]))
                    and access.intersection(flat).area>TOL)
            check(f"{role}_profile_endpoint:{rid}",valid_endpoint)
        # A ramp is only partly below grade: its upper landing and the top of its slope sit at or
        # near ground level and legitimately lie beyond the parking plate. The binding limit is the
        # PARCEL, and that the dig drawn for the level contains it - which the envelope check above
        # enforces from the other side.
        check(f"ramp_containment:{rid}",site.buffer(TOL).covers(g))
        curved = str(p.get("layout_type","")).startswith("curved")
        if curved:
            # A turning ramp is not its bounding rectangle: measure the run along the centreline
            # the plan actually carries, the band width as area over that run, and the sharpest
            # turn from the centreline itself (제6조제1항제5호나목·다목).
            spine = next((c for c,cp in grouped[(p.get("to_level"),"ramp_centerline")]
                          if cp.get("from_level")==p.get("from_level")),None)
            run = spine.length if spine is not None else 0.0
            measured_width = g.area/run if run > TOL else 0.0
            check(f"ramp_profile_length:{rid}",bool(profile) and abs(profile[0]["distance_m"])<=TOL and
                  run > TOL and abs(profile[-1]["distance_m"]-run)<=0.5,centreline_run_m=round(run,2))
            need_w = rules.get("curved_ramp_width_m") or rules.get("ramp_width_m")
            if need_w:
                # the band is a polygonal approximation of an arc, so its area is a few parts in
                # 10,000 under the true annulus: 10 mm of tolerance, not the geometric TOL
                check(f"ramp_width:{rid}",measured_width+0.01>=need_w,measured_width_m=round(measured_width,3),required_m=need_w)
            inner_min = rules.get("curve_min_inner_radius_m")
            if inner_min is not None and spine is not None:
                turn = _min_turn_radius([(c[0],c[1]) for c in spine.coords])
                inner = (turn - measured_width/2) if turn is not None else None
                check(f"ramp_curve_radius:{rid}",inner is not None and inner+TOL>=float(inner_min),
                      measured_centreline_radius_m=None if turn is None else round(turn,2),
                      measured_inner_radius_m=None if inner is None else round(inner,2),required_inner_m=inner_min)
        else:
            rectangular = g.minimum_rotated_rectangle
            edges = [math.dist(a,b) for a,b in zip(rectangular.exterior.coords,list(rectangular.exterior.coords)[1:])]
            check(f"ramp_profile_length:{rid}",bool(profile) and abs(profile[0]["distance_m"])<=TOL and
                  abs(profile[-1]["distance_m"]-max(edges))<=TOL)
            if rules.get("ramp_width_m"):
                check(f"ramp_width:{rid}",min(edges)+TOL>=rules["ramp_width_m"])
        valid = len(profile)>=2
        grades=[]
        for a,b in zip(profile,profile[1:]):
            dx=b["distance_m"]-a["distance_m"]
            if dx<=0:
                valid=False
            else:
                grades.append(abs(b["z_m"]-a["z_m"])/dx)
        maximum=(rules.get("curved_ramp_max_slope") if curved else None) or rules.get("ramp_max_slope")
        if curved and grades and p.get("radius_m") and p.get("width_m"):
            # On an arc the rise is fixed and the path at radius r is r*theta, so the grade scales
            # as 1/r. IStructE measures a curved ramp's gradient ON THE CENTRE LINE; Weant measures
            # it along the outer edge; 시행규칙 제6조제1항제5호라목 does not say. The profile here is
            # the centre line, so the kerb figures are reported, not judged.
            R=float(p["radius_m"]); half=float(p["width_m"])/2
            worst=max(grades)
            pending.append(f"curved_ramp_grade_datum:{rid}")
            check(f"ramp_grade_kerbs:{rid}",None,note="the datum is unsettled: IStructE measures on the "
                  "centre line, Weant on the outer edge, and 시행규칙 제6조제1항제5호라목 is silent",
                  centreline_grade=round(worst,4),
                  inner_kerb_grade=round(worst*R/(R-half),4) if R>half else None,
                  outer_kerb_grade=round(worst*R/(R+half),4))
        check(f"ramp_grade:{rid}",valid and maximum is not None and max(grades,default=0)<=maximum+TOL,
              max_grade=max(grades,default=None))
        floor_h=request.get("options",{}).get("basement_floor_height_m")
        if floor_h is not None and profile:
            check(f"ramp_level_rise:{rid}",abs(profile[0]["z_m"]-p["from_level"]*floor_h)<=TOL and
                  abs(profile[-1]["z_m"]-p["to_level"]*floor_h)<=TOL)
        headroom = (floor_h or 0)-request.get("options",{}).get("slab_depth_m",0)
        if rules.get("min_headroom_m"):
            check(f"ramp_stacking_headroom:{rid}",headroom+TOL>=rules["min_headroom_m"],clear_height_m=headroom)
        cores = unary_union(source_obstacles)
        check(f"ramp_obstructions:{rid}",g.intersection(cores).area<=TOL)
        if p.get("overhead_soffit_z_m") is not None:
            slab_depth=request.get("options",{}).get("slab_depth_m")
            soffit=p["overhead_soffit_z_m"]
            source_ok=(isinstance(slab_depth,(int,float)) and not isinstance(slab_depth,bool)
                and math.isfinite(slab_depth) and isinstance(soffit,(int,float))
                and math.isfinite(soffit) and abs(soffit+slab_depth)<=TOL)
            check(f"ramp_overhead_soffit_source:{rid}",source_ok)
            center=next((c for c,cp in grouped[(p.get("to_level"),"ramp_centerline")]
                if cp.get("from_level")==p.get("from_level") and cp.get("to_level")==p.get("to_level")),None)
            occupied=ground_occupancy if ground_occupancy is not None else unary_union(
                [geometry for geometry,props in grouped[(0,"building_footprint")]])
            clearance=None
            profile_matches=False
            if center is not None and center.geom_type=="LineString" and profile:
                coords=list(center.coords)
                station=0.0
                profile_matches=all(len(c)>=3 and math.isfinite(c[2]) for c in coords)
                for index,c in enumerate(coords):
                    if index:
                        station+=math.dist(coords[index-1][:2],c[:2])
                    segment=next(((a,b) for a,b in zip(profile,profile[1:])
                        if a["distance_m"]-TOL<=station<=b["distance_m"]+TOL
                        and b["distance_m"]>a["distance_m"]),None)
                    if segment is None or len(c)<3:
                        profile_matches=False
                        break
                    a,b=segment
                    z=a["z_m"]+(station-a["distance_m"])/(b["distance_m"]-a["distance_m"])*(b["z_m"]-a["z_m"])
                    profile_matches=profile_matches and abs(c[2]-z)<=TOL
            check(f"ramp_overhead_xyz_profile:{rid}",profile_matches)
            if source_ok and profile_matches and rules.get("min_headroom_m") and p.get("width_m"):
                try:
                    clearance=overhead_clearance({"centerline":center,"width_m":p["width_m"]},
                        occupied,-slab_depth,rules["min_headroom_m"])
                except (ValueError,TypeError):
                    clearance=None
            check(f"ramp_overhead_clearance:{rid}",bool(clearance and clearance["passed"]),
                  minimum_clearance_m=clearance["minimum_clearance_m"] if clearance else None)
            pending.append("structural_soffit_beams_services_review")
        if p.get("from_level")==0 and request.get("frontage"):
            # The ramp reaches the road directly, or through the ground drive it departs from
            # (row-and-aisle plans: the ramp leaves the through aisle), which must itself meet the road.
            road=shape(request["frontage"])
            ground_drive=unary_union([gg for gg,pp in grouped[(0,"parking_aisle")]+grouped[(0,"vehicular_access")]])
            via_drive=(not ground_drive.is_empty and g.distance(ground_drive)<=TOL and ground_drive.distance(road)<=TOL)
            check("ramp_road_connection",g.distance(road)<=TOL or via_drive)
    status = "failed" if any(c["status"]=="failed" for c in checks) else "passed"
    if count:
        # Disc clearance is a geometric measurement, not proof of a maneuver.
        # A full-circle engineering requirement is enforced only when requested.
        vehicle = request.get("options", {}).get("vehicle") or {}
        # Preserve declared radius data; do not infer a body envelope or legal
        # requirement from a wheel-centre radius or a mechanical-device forecourt.
        turn_r = vehicle.get("minimum_turning_radius_m") or vehicle.get("turning_radius_outer_m")
        full_circle_required = vehicle.get('require_full_turning_circle') is True
        if full_circle_required:
            # The minimum alias may describe a wheel-centre radius, not the
            # swept body's outer radius. Never substitute it for this criterion.
            turn_r = vehicle.get('turning_radius_outer_m')
            if type(turn_r) not in (int,float) or not math.isfinite(turn_r) or turn_r <= 0:
                turn_r = None
        for (level, layer), items in sorted(grouped.items()):
            if layer != "parking_aisle":
                continue
            drive_here = unary_union([g for g, _ in items])
            if full_circle_required and turn_r is None and items:
                checks.append({'id':f'turning_circle_design_requirement:{level}',
                    'status':'needs_evidence','level':level,'required_outer_radius_m':None,
                    'basis':'explicit_conservative_design_requirement_not_law',
                    'reason':'finite_positive_outer_turning_radius_required'})
                pending.append('finite_positive_outer_turning_radius_required')
            if turn_r is None:
                check(f"turning_space:{level}", None, level=level,
                      maneuver_status="needs_evidence",
                      note="vehicle turning radii are not declared (options.vehicle); actual maneuver unverified")
                continue
            got = _turning_space(drive_here, turn_r)
            if vehicle.get('require_full_turning_circle') is True and items:
                check(f"turning_circle_design_requirement:{level}",
                      got is not None and got + TOL >= float(turn_r), level=level,
                      largest_inscribed_radius_m=None if got is None else round(got,2),
                      required_outer_radius_m=turn_r,
                      basis='explicit_conservative_design_requirement_not_law',
                      scope='full disc clearance only; exact swept path remains unverified')
            check(f"turning_space:{level}", None, level=level,
                  largest_inscribed_radius_m=None if got is None else round(got, 2),
                  minimum_turning_radius_m=turn_r, source=vehicle.get("source"),
                  maneuver_status="needs_evidence",
                  note="inscribed-disc measurement only; actual entrance, bay-entry and recovery maneuvers unverified")
        pending.extend(["vehicle_swept_path_review", "structural_and_excavation_review"])
        if rules.get("ev_min_share"):
            pending.append("ev_charging_stalls_marking")  # 제6조①14 5 %: a marking/equipment item for the drawing stage
        if rules.get("stall_max_grade") is not None:
            pending.append("stall_surface_grade_review")  # 제6조①13: needs the DEM/표고 profile, not planned here


    # Measure dead-end exposure without claiming an unverified universal bay
    # limit or absence of applicable law. Turning and end-bay usability require
    # the declared vehicle and an actual path check.
    for feat in features:
        prop = feat["properties"]
        if prop.get("layer") != "parking_aisle" or prop.get("dead_end_stalls") is None:
            continue
        level = prop.get("level", 0)
        run = int(prop["dead_end_stalls"])
        check(f"dead_end_run:{level}", None, level=level, stalls_past_last_crossover=run,
              bands=prop.get("bands"), cross_aisles=prop.get("cross_aisles"),
              maneuver_status="needs_evidence",
              note="measured dead-end exposure only; end-bay access and recovery maneuvers require an actual path check")

    # Optional collision evidence never closes steering/trajectory feasibility.
    from backend.app.modules.design.generation.maas.masterplan.swept_path import layout_maneuver_result
    maneuver = layout_maneuver_result(request, features)
    if maneuver is not None:
        checks.append({'id': 'vehicle_body_envelope',
                       'status': ('measured' if maneuver['status'] == 'clear_conservative_envelope'
                                  else 'needs_evidence'), 'evidence': maneuver})
        pending.extend(x for x in maneuver.get('pending_reviews', []) if x not in pending)
    status = "failed" if any(c["status"]=="failed" for c in checks) else "passed"
    if status == 'passed' and any(c['status']=='needs_evidence' for c in checks):
        status = 'needs_evidence'
    return {"schema_version":"masterplan.validation.v1","geometry_status":status,
            "checks":checks,"pending_reviews":pending,
            "scope":"serialized geometry and design modules; not a permit approval",
            "measured_parking_stalls":count,"measured_accessible_stalls":accessible}
