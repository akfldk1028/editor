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
from backend.app.modules.design.generation.maas.masterplan.validation_geometry import (
    LANDING_JOINT_TOL, TOL, _flat_ramp_area, _min_turn_radius, _stacked_flat_access, _turning_space)
from backend.app.modules.design.generation.maas.masterplan.validation_programme import _check_basement_programme
from backend.app.modules.design.generation.maas.masterplan.validation_ramps import _check_ramps
from backend.app.modules.design.generation.maas.masterplan.validation_turning import _check_turning_space


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
    from .pedestrian_routes import check_route_features
    check_route_features(check, request, features)
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
        check("authored_ground_footprint_preserved",drawn_ground.symmetric_difference(ground_occupancy).area<=TOL)
        if request.get("core"):
            check("ground_footprint_contains_core",ground_occupancy.buffer(TOL).covers(shape(request["core"])))
    elif not request.get("footprint") and grouped[(0,"building_ground_footprint")]:
        # The engine's own piloti variant (joint.piloti_ground_variants) draws the enclosed ground
        # floor it planned with. An independent re-validation sends the ORIGINAL request, which has
        # no ground footprint, and used to block the whole footprint: on 고산 the 11 bays under the
        # overhang failed stall_obstructions and the plan the engine had passed became ineligible.
        # Only a GENERATED mass may draw its own ground floor: an authored footprint with no
        # authored ground footprint is enclosed, whatever the plan draws.
        ground_occupancy = unary_union([g for g,p in grouped[(0,"building_ground_footprint")]])
    if ground_occupancy is not None:
        drawn_mass = unary_union([g for g,p in grouped[(0,"building_footprint")]])
        check("ground_footprint_containment",drawn_mass.buffer(TOL).covers(ground_occupancy))
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
            parallel = p.get('type') == 'standard_parallel'
            if parallel:
                from .parallel_parking import WIDTH_M, LENGTH_M
                rw, rl = WIDTH_M, LENGTH_M
                if 'parallel_parking_maneuver_and_applicability_review' not in pending:
                    pending.append('parallel_parking_maneuver_and_applicability_review')
            if rw is not None and rl is not None:
                check(f"stall_dimensions:{sid}",width+TOL>=rw and length+TOL>=rl,
                      measured_width_m=width,measured_length_m=length)
            frontage = g.boundary.intersection(drive.buffer(TOL)).length
            if parallel:
                coords = list(rect.exterior.coords)
                long_edges = [LineString([a,b]) for a,b in zip(coords,coords[1:]) if math.dist(a,b)+TOL>=length]
                frontage = max(edge.intersection(drive.buffer(TOL)).length for edge in long_edges)
            check(f"stall_aisle_frontage:{sid}",frontage+TOL>=(length if parallel else width),contact_m=frontage)
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
        all_stalls = [g for (lvl,layer),items in grouped.items() if layer=="parking_stall" for g,p in items
                      if p.get('type') != 'standard_parallel']
        wide = 0
        for g in all_stalls:
            r = g.minimum_rotated_rectangle; e = [math.dist(a,b) for a,b in zip(r.exterior.coords,list(r.exterior.coords)[1:])]
            if min(e)+TOL >= float(rules.get("expanded_width_m") or 0) and max(e)+TOL >= float(rules.get("expanded_length_m") or 0):
                wide += 1
        basis = len(all_stalls)
        check("expanded_stall_share",wide >= math.ceil(float(rules["expanded_min_share"])*basis)-TOL,expanded=wide,required=math.ceil(float(rules["expanded_min_share"])*basis),total=count,basis_nonparallel=basis)
    _check_basement_programme(check, grouped, request, placement_stage, source_obstacles)
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
    _check_ramps(check, pending, grouped, request, rules, site, source_obstacles, ground_occupancy)
    status = "failed" if any(c["status"]=="failed" for c in checks) else "passed"
    if count:
        _check_turning_space(check, checks, pending, grouped, request, rules)


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

    # Independent circulation geometry validation (approach, landing connection, spur pruning, swept path)
    from backend.app.modules.design.generation.maas.masterplan.validation_circulation import validate_circulation_geometry
    circ_report = validate_circulation_geometry(features, rules, request.get('options'))
    for cc in circ_report.get('checks', []):
        checks.append(cc)

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
    from .planning_scores import score_relationships
    from .siting_relations import measure_siting
    return {"schema_version":"masterplan.validation.v1","geometry_status":status,
            "relationship_scores": score_relationships(features, checks),
            "siting_evidence": measure_siting(request, features, occupied),
            "checks":checks,"pending_reviews":pending,
            "scope":"serialized geometry and design modules; not a permit approval",
            "measured_parking_stalls":count,"measured_accessible_stalls":accessible}
