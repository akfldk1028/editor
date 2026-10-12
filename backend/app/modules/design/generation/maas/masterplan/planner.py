"""Deterministic site, surface and multilevel basement design orchestration."""
from __future__ import annotations

import copy
import math
import os

from backend.app.modules.design.generation.maas.masterplan.search_budget import BasementSearchBudget

from shapely.geometry import LineString, Point, Polygon, mapping, shape
from shapely.affinity import translate

from backend.app.modules.design.generation.maas.masterplan.geometry import EPS, digest, feature, footprint_inside, number, parts, polygon, union_or_empty
from backend.app.modules.design.generation.maas.masterplan.bounded_packing import pack_level
from backend.app.modules.design.generation.maas.masterplan.basement_layout import solve_basement_level, slab_envelopes
from backend.app.modules.design.generation.maas.masterplan.aisle_ramps import aisle_ramp_candidates
from backend.app.modules.design.generation.maas.masterplan.compact_slab import compact_slab_candidate
from backend.app.modules.design.generation.maas.masterplan.feedback import build_mass_feedback
from backend.app.modules.design.generation.maas.masterplan.program import declared_rooms, plant_zone
from backend.app.modules.design.generation.maas.masterplan.ramps import curved_ramp_candidates, ramp_candidates, ramp_profile
from backend.app.modules.design.generation.maas.masterplan.rows import row_candidates
from backend.app.modules.design.generation.maas.masterplan.validation import validate_plan
from backend.app.modules.design.generation.maas.masterplan.pedestrian import pedestrian_reservation, exclude_reserved_stalls, ramp_reservation_conflicts
from backend.app.modules.design.generation.maas.masterplan.core_repair import core_obstacle
from backend.app.modules.design.generation.maas.masterplan.planner_metrics import (
    SERVED_LAYERS, excavation_cost_units, level_efficiency, module_ideal_m2, parking_entrance_feature,
    program_features)
from backend.app.modules.design.generation.maas.masterplan.planner_rank import _rank_and_record
from backend.app.modules.design.generation.maas.masterplan.parking_targets import target_mode



def plan_site(request):
    refusal = _placement_target_refusal(request)
    if refusal is not None:
        return refusal
    from backend.app.modules.design.generation.maas.masterplan.joint import select_joint_layout
    result = select_joint_layout(request, _plan_site_fixed)
    if request.get('options', {}).get('planning_stage') == 'placement':
        from backend.app.modules.design.generation.maas.masterplan.placement_quality import review_placement
        result['placement_quality'] = review_placement(request, result)
        result['planning_stage'] = 'placement'
        result['next_stage'] = 'Mass studies use the selected building zone; detailed Plan follows'
        if not result['placement_quality']['eligible']:
            result['status'] = ('needs_evidence' if result['placement_quality'].get('status') == 'needs_evidence'
                and result.get('status') != 'needs_revision' else 'needs_revision')
            result['blocking'].extend('placement quality: '+v for v in result['placement_quality']['failures'])
            result['handoff'].update(hard_pass=False,
                status='needs_evidence' if result['status'] == 'needs_evidence' else 'failed')
    return result


def _off_prohibited(candidates, prohibited):
    """차량출입불허구간: a ramp whose body or road connector touches a prohibited interval is no candidate.

    Portals are generated on the permitted frontage, but the ramp and its connector corridor are
    full-width strips and can still reach the interval's end; the agent's frame tolerance is 0.05 m.
    """
    if prohibited is None:
        return candidates
    kept=[]
    for candidate in candidates:
        pieces=[candidate.get("polygon"),candidate.get("ground_connector")]
        if any(g is not None and not g.is_empty and g.distance(prohibited)<=0.05 for g in pieces):
            continue
        kept.append(candidate)
    return kept


def _placement_target_refusal(request):
    options = request.get('options') or {}
    if (options.get('planning_stage') != 'placement' or request.get('footprint')
            or options.get('target_footprint_m2') is not None):
        return None
    code = 'building_zone_target_unconfirmed'
    pending = list(dict.fromkeys([*((request.get('law') or {}).get('blocking') or []), code]))
    return {'schema_version':'masterplan.layout.v1','type':'FeatureCollection',
        'pnu':request.get('pnu'),'coordinate_crs':request.get('crs'),
        'status':'needs_evidence','code':code,'planner_invoked':False,
        'features':[],'levels':[],'metrics':{},'blocking':pending,
        'validation':{'geometry_status':'needs_evidence','checks':[],
            'pending_reviews':pending,'scope':'No layout search: an explicit building-zone design target is missing'},
        'provenance':{'law':copy.deepcopy(request.get('law') or {}),
            'rules':copy.deepcopy(request.get('rules') or {}),'evidence':copy.deepcopy(request.get('evidence') or {})},
        'handoff':{'status':'needs_evidence','evaluated':False,'hard_pass':False,
            'input_hash':digest(request),'geometry_hash':digest([])}}


def _plan_site_fixed(request):
    from backend.app.modules.design.generation.maas.masterplan.layout_axis import layout_axis_angle
    refusal = _placement_target_refusal(request)
    if refusal is not None:
        return refusal
    request=copy.deepcopy(request)
    site=polygon(request["site"],"site")
    if site.area>1_000_000:
        raise ValueError("site exceeds bounded planner area (1 km2); subdivide the design")
    law=request.get("law") or {}
    options=request.setdefault("options",{})
    search_budget = BasementSearchBudget(options.get('max_basement_solves'))
    placement_stage = options.get('planning_stage') == 'placement'
    explicit_angle = layout_axis_angle(request)
    common_axis = placement_stage or explicit_angle is not None
    straight_entry = options.get('entry_alignment') == 'straight'
    if options.get('entry_alignment') not in (None, 'auto', 'straight'):
        raise ValueError('entry_alignment must be auto or straight')
    if straight_entry and explicit_angle is None:
        raise ValueError('straight entry requires an explicit source-attributed layout_axis')
    # A common module axis is a placement decision, not a Mass/Plan input.
    def plan_rows(*args, **kwargs):
        if kwargs.get('ramp') is not None and search_budget.limit is not None and search_budget.invoked >= search_budget.limit:
            search_budget.truncated = True
            return []
        if common_axis:
            kwargs['allowed_angles'] = [angle] if straight_entry else [angle, angle+90]
            kwargs['preserve_banks'] = True
        if straight_entry:
            kwargs['straight_entry'] = True
        kwargs.setdefault('prohibited', prohibited)
        return row_candidates(*args, **kwargs)
    def plan_pack(*args, **kwargs):
        if common_axis:
            kwargs.update(allowed_angles=[angle, angle+90], require_full_width=True, preserve_banks=True)
        return pack_level(*args, **kwargs)
    evidence=request.get("evidence") or {}
    rules=dict(request.get("rules") or {})
    mix = options.get('parking_mix', 'perpendicular')
    if mix not in ('perpendicular', 'parallel_infill'):
        raise ValueError('unsupported parking mix')
    if mix == 'parallel_infill':
        rules['parking_mix'] = mix
    missing=list(law.get("blocking") or [])
    source_reviews=request.get('mass_source_pending_reviews') or []
    if not isinstance(source_reviews,list) or not all(isinstance(item,str) for item in source_reviews):
        raise ValueError('mass source pending reviews must be a list of strings')
    missing.extend(source_reviews)
    pedestrian=pedestrian_reservation(request)
    missing.extend(pedestrian['pending_reviews'])
    failures=[]
    if law.get("status")!="resolved":
        missing.append("law evidence is incomplete")
    for name in (("buildable","frontage") if placement_stage else ("buildable","frontage","core","columns")):
        if not evidence.get(name):
            missing.append(f"{name} source evidence is missing")
    required=law.get("required_spaces")
    if required is not None:
        number(required,"required spaces",maximum=1000)
        if int(required)!=required:
            missing.append("law parking requirement needs an authoritative integer count")
            required=None
    bcr=law.get("bcr_pct")
    if bcr is not None:
        number(bcr,"BCR",maximum=100)
    else:
        missing.append("BCR evidence is missing")
    # Design inputs on top of the law's minimum: plan for more stalls than required
    # (target_parking_stalls) and cap how many sit on the surface (max_surface_stalls).
    target_stalls=options.get("target_parking_stalls")
    if target_stalls is not None:
        number(target_stalls,"target parking stalls",maximum=1000)
        if required is not None and target_stalls<required and target_mode(request) == 'required':
            failures.append("target_parking_stalls is below the law's required count")
            target_stalls=None
    planned=int(max(required or 0,target_stalls or 0)) if (required is not None or target_stalls is not None) else None
    max_surface=options.get("max_surface_stalls")
    if max_surface is not None:
        number(max_surface,"max surface stalls",maximum=1000)
    surface_target=options.get("target_surface_stalls")
    if surface_target is not None:
        number(surface_target,"target surface stalls",maximum=1000)
        if int(surface_target)!=surface_target:
            raise ValueError("target_surface_stalls must be an integer")
        if (max_surface is not None and surface_target>max_surface) or (planned is not None and surface_target>planned):
            raise ValueError("target_surface_stalls exceeds the surface cap or total planning target")
    def surface_quota():
        return int(min(v for v in (planned or 0,max_surface,surface_target) if v is not None))
    field=options.get("parking_field","auto")
    # A basement aisle graph should be strongly connected so a driver who misses a space can come
    # round again (IStructE, Design Recommendations for Multi-Storey and Underground Car Parks 4th
    # ed. 3.2.6/4.4, which also caps a dead-end aisle at six bins). That is NOT forced here, and
    # forcing it was wrong: a loop spends its return leg on pavement, so on a dense plate a comb
    # legitimately carries more cars. Measured on this fixture, same slab:
    #   40 required   ring 40 stalls in ONE basement at 19.4 m2 of aisle each
    #                 comb 21 stalls, no loop, and a second basement on top
    #   150 required  comb 150 and passes; ring 131 and falls short
    # Neither wins everywhere, which is why the choice belongs to the objective. What was broken is
    # that the objective never saw the loop: `rows.row_candidates` sorts by a score that penalises
    # aisle LENGTH, a loop always runs more aisle than the comb it beats, so the loop sorted last
    # and `limit` truncated it away. It now keeps a seat for one, and `auto` picks correctly in both
    # cases above.
    # CIRCULATION IS SCORED, NOT FORCED. Forcing a loop was measured on 고산 and it moved the plan
    # AWAY from practice: the loop only closes on a plate big enough for it, so the whole-parcel dig
    # won and the basement came out 2,500 m2 at 64.1/108.7 m2 per stall with a straight ramp. Left to
    # choose, the engine takes a practice-sized 1,468 m2 plate at 44.5/50.6 with the curved ramp and
    # dead-end aisles - which is also what the reference drawing does (ALT1's aisle dead-ends at the
    # west). So the loop earns points instead: `rows.WEIGHTS["w_loop"]` prices it in cars, and the
    # basement ranking takes the loop at equal cars. No statute requires 회차 (시행규칙 제6조·제11조
    # have no such clause); what the law does draw at 50 stalls is the two-lane aisle or separated
    # entry/exit ramps (제6조제1항제5호사목1)·제11조제1항) and the 5.5 m entrance (제4호), both of which
    # the 6 m two-way aisle already meets. An explicit basement_parking_field still wins.
    basement_field=options.get('basement_parking_field') or field
    if basement_field not in ('auto','single','comb','ring'):
        raise ValueError('invalid basement_parking_field')
    if field not in {"auto","single","comb","ring"}:
        raise ValueError("unsupported parking field")
    # A DECLARED FIELD IS NOT A PREFERENCE. When the caller names `ring`, falling back to `auto` the
    # moment one slab cannot close a loop hands back the comb from the FIRST slab tried and never
    # reaches the slab that could have carried the loop - measured on 고산 at 40 cars, the 1,539 m2
    # module plate solves ring at 28 stalls with a 94 m loop while the 37x37 grown plate solves comb
    # at 39 and wins by arriving first. So a named field is strict: it either produces a loop or it
    # produces nothing for that slab, and the search moves on. Only the engine's own `auto` may trade.
    strict_field=bool(options.get('basement_parking_field'))
    def solve_level(*args, level, field, **kwargs):
        """Solve one basement level; when a loop was ASKED FOR and cannot be built, say so.

        Only a caller that names `ring` takes this path - the default decides circulation by
        comparison in `rank`, not by asking for it. A plate too small or too pinched to close a loop
        still gets built, because refusing would hand back no basement at all, but the compromise
        travels with the candidate and reaches the record as
        `circulation_loop_not_achievable:{level}` if that candidate is the one chosen.
        """
        kwargs['require_full_width'] = common_axis or bool(options.get('core_vehicle_clearance_m'))
        kwargs['orthogonal_layout'] = common_axis
        kwargs['module_family'] = options.get('basement_module')
        kwargs['module_axis'] = options.get('module_axis', 'both')
        out=search_budget.run(solve_basement_level,*args,field=field,**kwargs)
        if out is not None or field!='ring' or strict_field:
            return out
        out=search_budget.run(solve_basement_level,*args,field='auto',**kwargs)
        if out is not None:
            out={**out,'loop_fallback_level':level}
        return out

    turn_radius=(options.get("vehicle") or {}).get("turning_radius_outer_m")
    # the 회전로 at a closed aisle end is a declared design input at the practice width (2.5 m);
    # no statute requires it, so nothing is assumed when it is absent
    turn_lane=options.get("turn_lane_m")
    def expanded_total():
        # 확장형 share (제11조④ -> 제6조①14) counts over the whole lot; None when the rules set no share
        share=rules.get("expanded_min_share")
        return int(math.ceil(float(share)*planned)) if (share and planned) else None
    buildable=polygon(request.get("buildable") or request["site"],"buildable")
    if not site.buffer(EPS).covers(buildable):
        failures.append("buildable boundary extends outside parcel")
    target=options.get("target_footprint_m2")
    if target is None:
        # The binding footprint ceiling is the law's stated capacity when it
        # exists (Lawagent reports it rounded); site area x BCR is the fallback.
        # Generating to the unrounded product overshot the stated cap by
        # 0.0003 m2 on a real parcel and failed the validator's footprint_area.
        ceilings=[x for x in (law.get("ground_capacity_m2"), site.area*bcr/100 if bcr is not None else None) if x is not None]
        target=min(number(x,"footprint ceiling") for x in ceilings) if ceilings else None
    frontage=shape(request["frontage"]) if request.get("frontage") else None
    if frontage is not None and frontage.geom_type not in {"LineString","MultiLineString"}:
        raise ValueError("frontage must be a line geometry")
    if frontage is None:
        missing.append("verified road frontage is missing")
    elif frontage.difference(site.boundary.buffer(.05)).length>EPS:
        # Source line must represent actual shared frontage, not a nearby road centreline.
        missing.append("frontage is not a verified shared parcel boundary")
    front=shape(request["front_frontage"]) if request.get("front_frontage") else None
    # 차량출입불허구간 registered in the district plan: the frontage already excludes it, and the
    # intervals travel too so no generated vehicle entrance may touch them.
    prohibited=shape(request["vehicle_prohibited"]) if request.get("vehicle_prohibited") else None
    if prohibited is not None and prohibited.geom_type not in {"LineString","MultiLineString"}:
        raise ValueError("vehicle_prohibited must be a line geometry")
    if request.get("footprint"):
        footprint=polygon(request["footprint"],"footprint")
    else:
        if front is None and frontage is not None:
            # No declared front: align to the longest road edge and say the hierarchy is unverified.
            segs=[LineString(pair) for line in ([frontage] if isinstance(frontage,LineString) else list(getattr(frontage,"geoms",()))) for pair in zip(line.coords,list(line.coords)[1:])]
            front=max(segs,key=lambda l:l.length,default=None)
            if front is not None:
                missing.append("front road hierarchy unverified - footprint aligned to the longest vehicle frontage")
        # the parking module is the unit the plate is sized in: stall + aisle + stall
        module_depth=(2*float(rules["stall_length_m"])+float(rules["aisle_width_m"])
                      if rules.get("stall_length_m") and rules.get("aisle_width_m") else None)
        footprint=(footprint_inside(buildable.difference(pedestrian['reserved']),target or 0,align_to=front,module_depth_m=module_depth)
                   if explicit_angle is None else Polygon())
        if explicit_angle is not None or (placement_stage and options.get('placement_variant') is not None):
            from backend.app.modules.design.generation.maas.masterplan.joint import footprint_candidates
            variants=footprint_candidates(buildable.difference(pedestrian['reserved']),target or 0,front,module_depth,
                angle_deg=explicit_angle)
            variant=options.get('placement_variant',0)
            if type(variant) is not int or not 0<=variant<len(variants):
                raise ValueError('placement_variant is outside generated building-zone candidates')
            footprint=variants[variant]
        missing.append("generated building zone awaits downstream Mass development" if placement_stage else
                       "generated mass footprint requires MassAgent/architect acceptance")
    core=polygon(request["core"],"core") if request.get("core") else Polygon()
    if not core.is_empty and not footprint.buffer(EPS).covers(core):
        failures.append("core lies outside authored footprint")
    authored_ground=request.get("ground_footprint") is not None
    ground_footprint=polygon(request["ground_footprint"],"ground footprint") if authored_ground else footprint
    if authored_ground:
        if not footprint.buffer(EPS).covers(ground_footprint):
            raise ValueError("ground footprint lies outside building footprint")
        if not core.is_empty and not ground_footprint.buffer(EPS).covers(core):
            raise ValueError("ground footprint must contain the building core")
        if footprint.difference(ground_footprint).area>EPS:
            missing.append("partial piloti structural grid and clear height require review")
    columns=[polygon(x,"column") for x in request.get("columns",[])]
    # Reserve the declared preliminary access/vehicle clearance before packing;
    # subtracting only the core polygon leaves a pinched aisle touching its wall.
    obstacles=union_or_empty([core_obstacle(request),*columns])
    base=[feature("site_boundary",site,area_m2=site.area),feature("buildable_boundary",buildable)]
    from .pedestrian_routes import route_features
    base.extend(route_features(pedestrian['route']))
    if not pedestrian['reserved'].is_empty:
        base.append(feature('pedestrian_reserved_area',pedestrian['reserved']))
    if not pedestrian['crossing'].is_empty:
        base.append(feature('pedestrian_vehicle_crossing_area',pedestrian['crossing']))
    if not footprint.is_empty:
        base.append(feature("building_footprint",footprint,area_m2=footprint.area,
                            coverage_pct=footprint.area/site.area*100,
                            ground_occupancy_separate=authored_ground))
    if authored_ground:
        base.append(feature("building_ground_footprint",ground_footprint,area_m2=ground_footprint.area,
                            source="authored ground occupancy"))
    if not core.is_empty:
        base.append(feature("building_core",core,area_m2=core.area))
    base.extend(feature("column",c) for c in columns)
    if frontage is not None:
        base.append(feature("road_frontage",frontage))
    required_keys=("stall_width_m","stall_length_m","accessible_width_m","accessible_length_m","aisle_width_m")
    rules_ready=all(rules.get(k) is not None for k in required_keys)
    if not rules_ready:
        missing.append("parking design dimensions are missing from Lawagent")
    else:
        for key in required_keys:
            number(rules[key],key,minimum=.1,maximum=30)
    accessible=law.get("required_accessible_spaces")
    if accessible is None:
        missing.append("accessible parking requirement is unconfirmed")
        accessible=0
    else:
        number(accessible,"accessible spaces",maximum=1000)
        if int(accessible)!=accessible:
            raise ValueError("accessible spaces must be an integer")
    if required is not None and accessible>required:
        failures.append("accessible count exceeds total requirement")
    maxlevels=number(options.get("max_basement_levels",1),"maximum basement levels",minimum=0,maximum=5)  # also read before the basement block for the shortfall message
    strategy=options.get("parking_strategy","auto")
    if strategy not in {"auto","surface","ground_surface","piloti","piloti_and_surface","basement","mixed"}:
        raise ValueError("unsupported parking strategy")
    candidates=[]
    angle=0
    if isinstance(frontage,LineString) and len(frontage.coords)>1:
        a,b=frontage.coords[0],frontage.coords[-1]
        angle=math.degrees(math.atan2(b[1]-a[1],b[0]-a[0]))
    if explicit_angle is not None:
        angle=explicit_angle
    def add_parking(plan,level,z):
        feats=[]
        # The entrance is clipped geometry; a clip can leave line or point slivers beside the strip
        # (a GeometryCollection), which compact_slab and the validator rightly refuse. Only its
        # area is a drivable entrance.
        entrance=union_or_empty(parts(plan['entrance'])) if plan.get('entrance') is not None else None
        if entrance is not None and not entrance.is_empty:
            feats.append(parking_entrance_feature(entrance,level,z))
        for i,stall in enumerate(plan["stalls"],1):
            feats.append(feature("parking_stall",stall["polygon"],level,
                         stall_id=f"{'G' if level==0 else 'B'+str(-level)}-P{i:03d}",
                         type=stall["type"],width_m=stall["width_m"],length_m=stall["length_m"],z_m=z))
        # the drive is a union of manoeuvring rectangles; touching edges can leave a
        # self-intersecting ring, which buffer(0) normalises without moving the boundary
        drive=plan["drive"].buffer(0) if not plan["drive"].is_valid else plan["drive"]
        if not drive.is_empty:
            # How the field was laid out travels with the aisle so the validator can report it
            # without re-deriving it from pixels: how many whole modules were tiled, how many
            # cross aisles join them, and how many stalls sit past the last crossover.
            shape_keys={k:plan[k] for k in ("bands","cross_aisles","dead_end_stalls","generation") if plan.get(k) is not None}
            feats.append(feature("parking_aisle",drive,level,width_m=rules["aisle_width_m"],z_m=z,**shape_keys))
        return feats
    # A design target may produce an unapproved surface proposal while the
    # legal minimum remains unknown. The missing-law verdict below is retained.
    if planned is not None and rules_ready:
        if strategy in {"auto","surface","ground_surface","piloti","piloti_and_surface","mixed"}:
            piloti=strategy in {"piloti","piloti_and_surface"}
            ground=site.difference(obstacles if piloti and not authored_ground else union_or_empty([ground_footprint,obstacles]))
            ground=ground.difference(pedestrian['vehicle_blocked'])
            if piloti:
                missing.append("piloti structural grid and clear height require review")
            parking=({'stalls':[],'drive':Polygon(),'provided':0,'accessible':0,'search_count':0} if straight_entry else
                     plan_pack(ground,[frontage] if frontage is not None else [],rules,surface_quota(),int(accessible),preferred_angle=angle))
            parking=exclude_reserved_stalls(parking,pedestrian['reserved'])
            feats=base+add_parking(parking,0,0)
            candidates.append({"strategy":"piloti_and_surface" if piloti else "ground_surface",
                "features":feats,"levels":[{"level":0,"z_m":0,"provided_spaces":parking["provided"]}],
                "provided":parking["provided"],"accessible":parking["accessible"],"search_count":parking["search_count"]})
            if not piloti and frontage is not None:
                # Row-and-aisle candidates chosen by objective (rows.py): one through aisle, rows both sides.
                for rc in plan_rows(site,ground,footprint,obstacles,frontage,front,rules,surface_quota(),int(accessible),
                                         occupied_footprint=ground_footprint if authored_ground else None,
                                         expanded_needed=expanded_total(),turn_radius_m=turn_radius,turn_lane_m=turn_lane,field=field):
                    rc=exclude_reserved_stalls(rc,pedestrian['reserved'])
                    feats=base+add_parking({"stalls":rc["stalls"],"drive":rc["drive"],"entrance":rc.get("entrance"),"bands":rc.get("bands"),"cross_aisles":rc.get("cross_aisles"),"dead_end_stalls":(rc.get("terms") or {}).get("dead_end_stalls")},0,0)
                    candidates.append({"strategy":"ground_surface","pattern":"rows","score":rc["score"],"terms":rc["terms"],
                        "features":feats,"levels":[{"level":0,"z_m":0,"provided_spaces":rc["provided"]}],
                        "provided":rc["provided"],"accessible":rc["accessible"],"search_count":1})
        if strategy in {"auto","basement","mixed"} and planned>0:
            # A basement floor is not a parking deck: the declared plant/storage programme
            # (기계실·전기실·발전기실·방재실·창고·계단실·ELEV홀 ...) takes its area first.
            prog=declared_rooms(options)
            if not prog:
                missing.append("basement programme (기계실·전기실 등 비주차 실) is not declared - "
                               "the stall count below grade assumes the whole floor is parking")
            basement=polygon(request.get("basement_boundary") or request["site"],"basement boundary")
            if not evidence.get("basement_boundary"):
                missing.append("basement excavation boundary evidence is missing")
            if not site.buffer(EPS).covers(basement):
                failures.append("basement boundary lies outside parcel")
            ramp_keys=("ramp_width_m","ramp_max_slope","transition_length_m","transition_slope","min_headroom_m")
            if not all(rules.get(k) is not None for k in ramp_keys):
                missing.append("ramp rules are missing")
            elif options.get("basement_floor_height_m") is None or options.get("slab_depth_m") is None:
                missing.append("basement floor height and slab depth are required design inputs")
            elif frontage is not None:
                height=number(options["basement_floor_height_m"],"floor height",minimum=.5,maximum=10)
                number(options["slab_depth_m"],"slab depth",maximum=height)
                maxlevels=number(options.get("max_basement_levels",1),"maximum basement levels",minimum=1,maximum=5)
                if int(maxlevels)!=maxlevels:
                    raise ValueError("maximum basement levels must be an integer")
                # THE BUILDING BLOCKS THE GROUND, NOT THE BASEMENT. Passing the footprint as a ramp
                # obstruction forbade the one arrangement practice actually draws - ALT1 runs its
                # curved ramp along the building's west face and down - and pushed every ramp into
                # the yard, where it cut the surface rows to nothing: measured on 고산, the yard
                # carries 23 stalls and 0 once a ramp is laid across it, which is why "지상 60 %"
                # came back as 3 cars. Below grade the ramp may pass under the plate (that is what
                # `share_under_footprint` measures); at grade only its flat UPPER LANDING is a
                # conflict, because a car stands on it before it starts down.
                blocked=union_or_empty([obstacles])
                requested_turn=options.get('ramp_turn_deg')
                if requested_turn is not None:
                    requested_turn=number(requested_turn,'ramp turn',minimum=1,maximum=180)
                def accept_ramp(ramp):
                    if not ramp_reservation_conflicts(ramp,pedestrian)['passed']:
                        return False
                    if not isinstance(ramp,dict):
                        # rows.py hands the band polygon alone and applies its own at-grade landing
                        # rule before it ever gets here; only the dict form carries the landings.
                        return True
                    if requested_turn is not None:
                        from .ramp_intent import matches_turn
                        if not matches_turn(ramp,requested_turn):
                            return False
                    entry_app = options.get("entry_approach")
                    if entry_app in ("corner_clear", "straight_6m", "straight_10m"):
                        corner_clearance = 6.0 if entry_app == "straight_6m" else (10.0 if entry_app == "straight_10m" else 3.0)
                        if isinstance(frontage, LineString) and len(frontage.coords) >= 2:
                            p0, p1 = Point(frontage.coords[0]), Point(frontage.coords[-1])
                            upper = ramp.get("upper_landing")
                            if upper is not None:
                                if upper.distance(p0) < corner_clearance or upper.distance(p1) < corner_clearance:
                                    return False
                    upper=ramp.get("upper_landing")
                    if upper is not None and not ground_footprint.is_empty:
                        if upper.intersection(ground_footprint).area>EPS:
                            return False
                    if not ground_footprint.is_empty and rules.get("min_headroom_m") is not None:
                        # Passing under the plate is only allowed where the declared slab leaves the
                        # headroom the rules require; otherwise the ramp would drive through the
                        # ground floor. Same test the aisle-ramp path already applies.
                        from backend.app.modules.design.generation.maas.masterplan.ramp_overhead import overhead_clearance
                        if not overhead_clearance(ramp,ground_footprint,-float(options["slab_depth_m"]),
                                                  rules["min_headroom_m"])["passed"]:
                            return False
                    return True
                shape_opt=options.get("ramp_shape","any")
                # THE RAMP IS NOT CONFINED TO THE DECLARED SLAB. A ramp to a 3.3 m basement runs
                # about 37 m - two 6 m landings, two 3 m transitions and ~19 m of slope - and the
                # upper half of that is at or near ground level, which is why practice lets it run
                # past the plate and counts it as part of the dig (reference ALT1: the curved ramp
                # leaves the basement outline and its band is excavated with it). Testing it against
                # the plate alone rejected every ramp on any slab shorter than the run: on the 38 x
                # 34 m fixture slab, 0 candidates against the slab and 5 against the parcel. The
                # plan then reported "no ramp fits" and placed no basement parking at all.
                ramp_host=union_or_empty([basement,site]).intersection(site).buffer(0)
                ramps=ramp_candidates(ramp_host,frontage,blocked,rules,height,accept=accept_ramp) if shape_opt!="curved" else []
                # practice turns the ramp where a straight run will not fit beside the plate
                if shape_opt!="straight":
                    ramps+=curved_ramp_candidates(ramp_host,frontage,blocked,rules,height,accept=accept_ramp,
                        **({'turns':(requested_turn,)} if requested_turn is not None else {}))
                ramps=_off_prohibited(ramps,prohibited)
                if not ramps:
                    spec_len=(ramp_profile(rules,height) or {}).get("length_m")
                    reach=max(basement.bounds[2]-basement.bounds[0],basement.bounds[3]-basement.bounds[1]) if not basement.is_empty else 0
                    failures.append("no straight or curved ramp fits the supplied site/frontage and obstructions"
                                    + (f": the ramp needs {spec_len:.1f} m of run for a {height:g} m drop and the "
                                       f"widest dimension available is {reach:.1f} m" if spec_len else ""))
                ground_candidate=next((c for c in candidates if c["strategy"]=="ground_surface"),None)
                # SIZE THE DIG HERE TOO. This branch excavated the whole authorized envelope for every
                # candidate, so excavation was identical across them and could not separate a scheme
                # that parks 23 cars in the yard and digs for 17 from one that buries all 40 - both
                # read 2,500 m2 on 고산. The rows branch has sized its slab since this morning; the
                # generic packer never did, and mixed schemes only ever reach this branch.
                module=2*float(rules["stall_length_m"])+float(rules["aisle_width_m"])
                ideal=(module_ideal_m2(rules) or {}).get("double_loaded") or 20.0
                # DEDUPE THE RAMPS BEFORE MULTIPLYING BY SLABS. Sub-branch 2 already drops ramps that
                # differ by less than 10 m2 at the same angle (see the `selected` loop below); this
                # branch did not, so 12 straight + 8 curved candidates - many of them the same band
                # shifted half a stall - each dragged a full multi-level basement solve through four
                # slabs. Identical work, four times over per duplicate.
                deduped=[]
                for ramp in ramps:
                    if any(ramp["polygon"].symmetric_difference(old["polygon"]).area < 10.0 for old in deduped):
                        continue
                    deduped.append(ramp)
                ramps=deduped
                if placement_stage:
                    # Placement studies need a small set of distinct access
                    # arrangements, not every ramp times every excavation cut.
                    # Detailed slab sizing follows the solved geometry below.
                    if len(ramps)>4:
                        ramps=[ramps[round(i*(len(ramps)-1)/3)] for i in range(4)]
                ramp_slabs=[]
                for ramp in ramps:
                    if placement_stage or search_budget.limit is not None:
                        ramp_slabs.append((ramp, basement))
                        continue
                    mandatory=union_or_empty([obstacles,ramp["polygon"]]).intersection(basement).buffer(0)
                    budget=sum(room["area_m2"] for room in prog)+mandatory.area+(planned or 0)*ideal
                    sized=slab_envelopes(mandatory if not mandatory.is_empty else basement,basement,mandatory,
                                         budget,module,aisle_width=rules["aisle_width_m"],angle_deg=angle or 0.,
                                         required=planned,stall_width=rules["stall_width_m"])
                    # THE DECLARED ENVELOPE STAYS ON THE TABLE. `slab_envelopes` returns the full host
                    # LAST, so truncating its list to three dropped it - and with it the behaviour
                    # this branch had before sizing existed. When every sized plate then failed to
                    # pack, the basement came back with zero stalls instead of the plan it used to
                    # produce. Sizing may only add options.
                    for slab in [*(sized or [])[:3], basement]:
                        ramp_slabs.append((ramp,slab))
                # KEEP ONE BASEMENT SOLVE FOR THE ROW-AND-AISLE FAMILY. It runs after this loop on the same
                # budget, so a capped run (the alternatives door requires max_basement_solves 1..3) used to
                # spend every solve here: on 고산 the row scheme sharing the surface gate (22 + 28, ramp
                # off the aisle) was generated and never got a basement, and 0 + 50 won. With a cap of
                # two or more and a frontage the rows can reach, the last solve is theirs.
                rows_reserve=1 if (frontage is not None and search_budget.limit is not None
                                   and search_budget.limit>=2) else 0
                for rindex,(ramp,basement_plate) in enumerate(ramp_slabs):
                    if search_budget.limit is not None and search_budget.invoked >= search_budget.limit-rows_reserve:
                        search_budget.truncated = True
                        break
                    feats=list(base)
                    candidate_reviews=[]
                    # WHAT IS DUG INCLUDES THE RAMP. The declared boundary is the parking plate;
                    # the excavation is that plate plus the ramp that reaches it, which is how
                    # practice draws and prices it. Keeping them equal made the validator reject
                    # its own ramp (ramp_containment) and the drive that ends on its landing
                    # (drive_containment). Parking still gets only the declared plate - a ramp is
                    # not floor area - so area per stall is unaffected by this.
                    dug=union_or_empty([basement_plate,ramp["polygon"]]).intersection(site).buffer(0)
                    connector=ramp.get("ground_connector",Polygon())
                    if not connector.is_empty:
                        feats.append(feature("vehicular_access",connector,0,z_m=0,
                                             role="road_to_ramp_connector"))
                    provided=0
                    acc=0
                    levels=[{"level":0,"z_m":0,"provided_spaces":0}]
                    search_count=0
                    loop_fallback=[]
                    # Mixed ground parking must reserve the ramp before packing.
                    if strategy=="mixed":
                        free=site.difference(union_or_empty([ground_footprint,obstacles,ramp["polygon"],connector]))
                        free=free.difference(pedestrian['vehicle_blocked'])
                        gp=({'stalls':[],'drive':Polygon(),'provided':0,'accessible':0,'search_count':0} if straight_entry else
                            plan_pack(free,[frontage],rules,surface_quota(),int(accessible),preferred_angle=angle))
                        # THE SURFACE OF A MIXED SCHEME IS STILL A ROW-AND-AISLE FIELD. Packing it with
                        # the generic packer put 3 cars on ground that the row engine fills with 23 -
                        # the same ground, the same ramp already reserved - so "지상 60 %" came back as
                        # 3 + 37 and the split it names was fiction. The row engine is tried on the
                        # identical free area and kept only when it carries more; the ramp's road
                        # connector joins the drive so the level stays one piece, and if it does not
                        # touch, `drive_connected:0` says so rather than this guessing.
                        if frontage is not None:
                            rows_surface=plan_rows(site,free,footprint,obstacles,frontage,front,rules,
                                surface_quota(),int(accessible),expanded_needed=expanded_total(),
                                turn_radius_m=turn_radius,turn_lane_m=turn_lane,field=field)
                            best_rows=max(rows_surface,key=lambda c:c["provided"],default=None)
                            if best_rows is None and gp["provided"]*4 < surface_quota():
                                # THE SPLIT DOES NOT FIT THIS FOOTPRINT, AND THAT IS THE ANSWER. A
                                # surface field needs a contiguous 16.0 m module strip; the ramp has to
                                # cross the yard to reach the road, and at this coverage the yard is a
                                # ring that the crossing breaks. Measured on 고산: yard 1,002 m2 carries
                                # 23 cars, 795 m2 after the ramp carries none, and the packer's 3 is a
                                # token, not a scheme. The footprint is MassAgent's, so this travels as
                                # a finding rather than being dressed up as a split.
                                candidate_reviews.append(
                                    "surface/basement split does not fit this footprint: the yard is "
                                    f"{(site.area-ground_footprint.area):.0f} m2 at {100*ground_footprint.area/site.area:.1f} % "
                                    f"coverage, the ramp corridor takes {ramp['polygon'].intersection(site).area:.0f} m2 of it, "
                                    f"and the {free.area:.0f} m2 left cannot hold a "
                                    f"{2*float(rules['stall_length_m'])+float(rules['aisle_width_m']):.1f} m parking module - "
                                    "a smaller footprint is a design decision, not a statute")
                            if best_rows is not None and best_rows["provided"]>gp["provided"]:
                                gp={**gp,"stalls":best_rows["stalls"],"entrance":best_rows.get("entrance"),
                                    "drive":union_or_empty([best_rows["drive"],best_rows.get("entrance"),connector]).buffer(0),
                                    "provided":best_rows["provided"],"accessible":best_rows["accessible"],
                                    "bands":best_rows.get("bands"),"cross_aisles":best_rows.get("cross_aisles")}
                        gp=exclude_reserved_stalls(gp,pedestrian['reserved'])
                        feats+=add_parking(gp,0,0)
                        provided=gp["provided"];acc=gp["accessible"]
                        levels[0]["provided_spaces"]=provided
                    for depth in range(1,int(maxlevels)+1):
                        if provided>=planned:
                            break
                        level=-depth
                        expanded_done=sum(f['properties'].get('type')=='expanded' for f in feats
                                          if f['properties'].get('layer')=='parking_stall')
                        solved=solve_level(basement_plate,ramp,obstacles,prog if depth==1 else [],rules,
                            int(planned-provided),int(max(0,accessible-acc)),angle=angle or 0.,
                            expanded_needed=max(0,expanded_total()-expanded_done) if expanded_total() is not None else None,
                            turn_radius_m=turn_radius,turn_lane_m=turn_lane,field=basement_field,level=level)
                        if solved is not None and depth<int(maxlevels) and provided+solved['parking']['provided']<planned:
                            # This level falls short, so try again leaving room for a ramp down to the
                            # NEXT level. THE RETRY MUST NOT DESTROY THE ANSWER WE ALREADY HAVE: it
                            # was overwriting `solved` unconditionally, so whenever the stacked-ramp
                            # variant failed the perfectly good level above it was discarded and the
                            # whole plan came back with zero stalls. Measured on the 38 x 34 m slab:
                            # solve returned 28 stalls, the retry returned None, and the plan reported
                            # 0 - which is a large part of why basements were not appearing at all.
                            stacked=solve_level(basement_plate,ramp,obstacles,prog if depth==1 else [],rules,
                                int(planned-provided),int(max(0,accessible-acc)),angle=angle or 0.,
                                expanded_needed=max(0,expanded_total()-expanded_done) if expanded_total() is not None else None,
                                turn_radius_m=turn_radius,turn_lane_m=turn_lane,field=basement_field,level=level,
                                departure_landing=ramp['upper_landing'])
                            if stacked is not None:
                                solved=stacked
                        if solved is None:
                            break
                        zone,bp=solved['zone'],solved['parking']
                        if solved.get('loop_fallback_level') is not None:
                            loop_fallback.append(solved['loop_fallback_level'])
                        search_count+=bp["search_count"]
                        feats.append(feature("basement_boundary",dug,level,z_m=level*height))
                        feats.extend(program_features(zone,level,level*height))
                        if not core.is_empty:
                            feats.append(feature("building_core",core,level,z_m=level*height))
                        feats.extend(feature("column",c,level,z_m=level*height) for c in columns)
                        profile=[{"distance_m":p["distance_m"],"z_m":p["z_m"]+(level+1)*height} for p in ramp["profile"]]
                        feats.append(feature("ramp",ramp["polygon"],level,from_level=level+1,to_level=level,
                            profile=profile,width_m=ramp["width_m"],length_m=ramp["length_m"],
                            layout_type="curved_arc_with_grade_transitions" if ramp.get("orientation")=="curved"
                                        else "straight_with_grade_transitions",
                            **({"radius_m":ramp["radius_m"],"inner_radius_m":ramp["inner_radius_m"],
                                "turn_deg":ramp["turn_deg"]} if ramp.get("orientation")=="curved" else {})))
                        center=translate(ramp["centerline"],zoff=(level+1)*height)
                        feats.append(feature("ramp_centerline",center,level,from_level=level+1,to_level=level))
                        # Vertical translation preserves the profile's XY start.
                        # The intermediate floor must actually connect back to it.
                        departure=ramp["upper_landing"]
                        feats.append(feature("vehicular_access",departure,level+1,z_m=(level+1)*height,
                                             role="ramp_departure",from_level=level+1,to_level=level))
                        feats.append(feature("vehicular_access",ramp["lower_landing"],level,z_m=level*height,
                                             role="ramp_arrival",from_level=level+1,to_level=level))
                        feats+=add_parking(bp,level,level*height)
                        provided+=bp["provided"];acc+=bp["accessible"]
                        levels.append({"level":level,"z_m":level*height,"provided_spaces":bp["provided"]})
                        if bp["provided"]==0:
                            break
                    candidates.append({"strategy":"mixed" if strategy=="mixed" else "basement",
                        "ramp_candidate":rindex,"ramp_orientation":ramp.get("orientation"),"features":feats,"levels":levels,"provided":provided,
                        "accessible":acc,"search_count":search_count,"loop_fallback":loop_fallback,
                        "pending_reviews":candidate_reviews})
                # Row-and-aisle candidates with the ramp leaving the aisle; the basement is the plate + ramp hull.
                # A 'basement' strategy keeps the ground clear: the aisle only carries the entrance to the ramp (quota 0).
                ground_r=site.difference(union_or_empty([ground_footprint,obstacles]))
                ground_r=ground_r.difference(pedestrian['vehicle_blocked'])
                # ramp_shape is a design decision, not something the objective should settle silently:
                # Both supplied practice alternatives use a curved western ramp.
                shape_opt=options.get("ramp_shape","any")
                if shape_opt not in {"any","straight","curved"}:
                    raise ValueError("ramp_shape must be any, straight or curved")
                curved_spec=(ramp_profile(rules,height,grade=rules["curved_ramp_max_slope"],width=rules["curved_ramp_width_m"])
                             if shape_opt in {"any","curved"} and rules.get("curved_ramp_max_slope")
                             and rules.get("curved_ramp_width_m") else None)
                spec=ramp_profile(rules,height) if options.get("ramp_shape","any")!="curved" else curved_spec
                ground_ok=strategy in {"auto","mixed"}
                row_layouts=(plan_rows(site,ground_r,footprint,obstacles,frontage,front,rules,surface_quota(),int(accessible),
                                          occupied_footprint=ground_footprint if authored_ground else None,
                                          ramp=spec,curved=curved_spec,curve_min_radius=rules.get("curve_min_inner_radius_m"),
                                          expanded_needed=expanded_total(),ground_stalls=ground_ok,
                                          turn_radius_m=turn_radius,turn_lane_m=turn_lane,field=field,
                                          accept_ramp=accept_ramp,ramp_shape=shape_opt) if spec else [])
                if ground_ok and shape_opt!='straight' and curved_spec is not None:
                    # Reserve capacity before fitting a ramp. Capping the first
                    # row at the final demand discards usable bays prematurely.
                    reserve_bays=2*math.ceil(curved_spec['width_m']/float(rules['stall_width_m']))
                    seeds=plan_rows(site,ground_r,footprint,obstacles,frontage,front,rules,
                        surface_quota()+reserve_bays,int(accessible),expanded_needed=expanded_total(),
                        occupied_footprint=ground_footprint if authored_ground else None,
                        turn_radius_m=turn_radius,turn_lane_m=turn_lane,field=field)
                    attached=aisle_ramp_candidates(site,seeds,obstacles,frontage,rules,height,
                        footprint=footprint,occupied=ground_footprint,
                        slab_soffit_z_m=-float(options['slab_depth_m']),
                        required_height_m=rules.get('min_headroom_m'),accept_ramp=accept_ramp)
                    attached=_off_prohibited(attached,prohibited)
                    for rc in attached:
                        if placement_stage:
                            from backend.app.modules.design.generation.maas.masterplan.stall_banks import select_complete_banks
                            stalls=select_complete_banks(rc['stalls'],surface_quota())
                        else:
                            stalls=sorted(rc['stalls'],key=lambda s:(s['type']!='accessible',s['type']!='expanded'))[:surface_quota()]
                        rc={**rc,'stalls':stalls,'provided':len(stalls),
                            'accessible':sum(s['type']=='accessible' for s in stalls)}
                        row_layouts.append(rc)
                if os.environ.get("MASTERPLAN_EXPLAIN_RANK"):
                    import sys as _sys
                    print("ROWS strategy=%s raw=%d with_ramp=%d accepted=%d"
                          % (strategy,len(row_layouts),
                             sum(1 for rc in row_layouts if rc.get('ramp') is not None),
                             sum(1 for rc in row_layouts if rc.get('ramp') is not None and accept_ramp(rc['ramp']))),
                          file=_sys.stderr)
                row_layouts=[rc for rc in row_layouts if rc.get('ramp') is not None and accept_ramp(rc['ramp'])]
                # Grow demand-sized alternatives from the mass hull inside the
                # authorized underground envelope; area alone never proves fit.
                # This ran only when the caller declared target_surface_stalls, so every other
                # scheme excavated the whole authorized envelope and paid for it: on 고산 the plate
                # came out 2,499.69 m2 for 62 cars (43.9 m2/stall against 실무 ALT1's 30.3) because
                # nothing ever asked for a smaller dig. The sizing is a search dimension, not a
                # caller preference - slab_envelopes returns the full host among its candidates, so
                # the undug-to-the-boundary option is still on the table and the objective chooses.
                if row_layouts:
                    expanded_rows=[]
                    selected=[]
                    for rc in sorted(row_layouts,key=lambda c:(-c['provided'],-c['score'])):
                        if rc.get('ramp') is None or rc.get('basement') is None:
                            continue
                        if any(abs(rc['angle_deg']-old['angle_deg'])<1 and
                               rc['ramp']['polygon'].symmetric_difference(old['ramp']['polygon']).area<10
                               for old in selected):
                            continue
                        selected.append(rc)
                        if len(selected)>=4:
                            break
                    ideal=module_ideal_m2(rules)['double_loaded']
                    efficiency=number(options.get('parking_efficiency_ratio',1),'parking efficiency ratio',minimum=1)
                    module=2*float(rules['stall_length_m'])+float(rules['aisle_width_m'])
                    for rc in selected:
                        if placement_stage:
                            expanded_rows.append({**rc,'basement':basement})
                            continue
                        mandatory=union_or_empty([obstacles,rc['ramp']['polygon']])
                        budget=sum(room['area_m2'] for room in prog)+mandatory.area+max(0,planned-rc['provided'])*ideal*efficiency
                        for slab in slab_envelopes(rc['basement'],basement,mandatory,budget,module,
                                                   aisle_width=rules['aisle_width_m'],angle_deg=rc['angle_deg'],
                                                   required=max(0,planned-rc['provided']) if planned else None,
                                                   stall_width=rules['stall_width_m']):
                            expanded_rows.append({**rc,'basement':slab})
                    # A host that cannot carry a sized slab keeps the layouts it already had;
                    # sizing must not be able to empty the candidate set.
                    row_layouts=expanded_rows or row_layouts
                _drop={"no_ramp":0,"no_basement":0,"outside_envelope":0,"zone_fail":0,"kept":0}
                for rc in row_layouts:
                    rc=exclude_reserved_stalls(rc,pedestrian['reserved'])
                    if rc["ramp"] is None or rc["basement"] is None or not basement.buffer(EPS).covers(rc["basement"]):
                        _drop["no_ramp" if rc["ramp"] is None else
                              "no_basement" if rc["basement"] is None else "outside_envelope"]+=1
                        continue
                    ramp=rc["ramp"]; basement_r=rc["basement"]; zone_fail=False
                    feats=list(base); provided=rc["provided"]; acc=rc["accessible"]
                    levels=[{"level":0,"z_m":0,"provided_spaces":provided}]
                    loop_fallback=[]
                    feats+=add_parking({"stalls":rc["stalls"],"drive":rc["drive"],"entrance":rc.get("entrance"),"bands":rc.get("bands"),"cross_aisles":rc.get("cross_aisles"),"dead_end_stalls":(rc.get("terms") or {}).get("dead_end_stalls")},0,0)
                    search_count=0
                    for depth in range(1,int(maxlevels)+1):
                        if provided>=planned:
                            break
                        level=-depth
                        # The lower landing is flat drive: keep it in the packer's host so the basement aisle can
                        # reach it (a ramp beside the plate lands in the hull's tip), then keep stalls off it.
                        exp_done=sum(f['properties'].get('type')=='expanded' for f in feats
                                     if f['properties'].get('layer')=='parking_stall')
                        exp_left=(max(0,expanded_total()-exp_done) if expanded_total() is not None else None)
                        solved=solve_level(basement_r,ramp,obstacles,prog if depth==1 else [],rules,
                            int(planned-provided),int(max(0,accessible-acc)),angle=rc['angle_deg'],
                            expanded_needed=exp_left,turn_radius_m=turn_radius,turn_lane_m=turn_lane,field=basement_field,level=level)
                        if solved is not None and depth<int(maxlevels) and provided+solved['parking']['provided']<planned:
                            # Same rule as the other branch: A RETRY MUST NOT DESTROY A SOLVED LEVEL.
                            stacked=solve_level(basement_r,ramp,obstacles,prog if depth==1 else [],rules,
                                int(planned-provided),int(max(0,accessible-acc)),angle=rc['angle_deg'],
                                expanded_needed=exp_left,turn_radius_m=turn_radius,turn_lane_m=turn_lane,field=basement_field,
                                level=level,departure_landing=ramp['upper_landing'])
                            if stacked is not None:
                                solved=stacked
                        if solved is None:
                            zone_fail=True
                            break
                        zone,bp=solved['zone'],solved['parking']
                        if solved.get('loop_fallback_level') is not None:
                            loop_fallback.append(solved['loop_fallback_level'])
                        search_count+=bp["search_count"]
                        feats.append(feature("basement_boundary",basement_r,level,z_m=level*height))
                        feats.extend(program_features(zone,level,level*height))
                        if not core.is_empty:
                            feats.append(feature("building_core",core,level,z_m=level*height))
                        feats.extend(feature("column",c,level,z_m=level*height) for c in columns)
                        profile=[{"distance_m":p["distance_m"],"z_m":p["z_m"]+(level+1)*height} for p in ramp["profile"]]
                        feats.append(feature("ramp",ramp["polygon"],level,from_level=level+1,to_level=level,
                            profile=profile,width_m=ramp["width_m"],length_m=ramp["length_m"],
                            layout_type=("curved_arc_with_grade_transitions" if ramp.get("shape")=="curved"
                                         else "straight_with_grade_transitions"),
                            share_under_footprint=ramp["share_under_footprint"],
                            **({'overhead_soffit_z_m':ramp['overhead_soffit_z_m']}
                               if depth==1 and ramp.get('overhead_soffit_z_m') is not None else {}),
                            **({"radius_m":round(ramp["radius_m"],3),"inner_radius_m":round(ramp["inner_radius_m"],3)}
                               if ramp.get("shape")=="curved" else {})))
                        center=translate(ramp["centerline"],zoff=(level+1)*height)
                        feats.append(feature("ramp_centerline",center,level,from_level=level+1,to_level=level))
                        # Vertical translation preserves the profile's XY start.
                        # The intermediate floor must actually connect back to it.
                        departure=ramp["upper_landing"]
                        feats.append(feature("vehicular_access",departure,level+1,z_m=(level+1)*height,
                                             role="ramp_departure",from_level=level+1,to_level=level))
                        feats.append(feature("vehicular_access",ramp["lower_landing"],level,z_m=level*height,
                                             role="ramp_arrival",from_level=level+1,to_level=level))
                        feats+=add_parking(bp,level,level*height)
                        provided+=bp["provided"];acc+=bp["accessible"]
                        levels.append({"level":level,"z_m":level*height,"provided_spaces":bp["provided"]})
                        if bp["provided"]==0:
                            break
                    if zone_fail:
                        _drop["zone_fail"]+=1
                        continue  # this basement outline cannot hold the declared programme
                    _drop["kept"]+=1
                    candidates.append({"strategy":"mixed" if strategy=="mixed" else "basement","pattern":"rows","score":rc["score"],
                        "terms":rc["terms"],"ramp_orientation":"off_aisle","features":feats,"levels":levels,
                        "provided":provided,"accessible":acc,"search_count":search_count,"loop_fallback":loop_fallback})
    if os.environ.get("MASTERPLAN_EXPLAIN_RANK") and 'strategy' in dir():
        import sys as _sys
        print("ROWS-BASEMENT drops %s" % (_drop if '_drop' in dir() else None),file=_sys.stderr)
    # Compact slabs by default: without them every candidate's plate is the declared envelope (the
    # whole site when none is authored), excavation reads equal across schemes, and the next key -
    # stalls per basement area - always favours burying everything. 고산: 0 + 50 over 22 + 28.
    if options.get("compact_basement_search",True):
        envelope=polygon(request.get("basement_boundary") or request["site"],"excavation envelope")
        for original_index,original in enumerate(list(candidates)):
            compact=copy.deepcopy(original)
            proposals=[]
            for f in compact["features"]:
                if f["properties"].get("layer")!="basement_boundary":
                    continue
                try:
                    proposal=compact_slab_candidate(original["features"],level=f["properties"]["level"],
                        envelope=envelope,wall_clearance_m=options.get("basement_wall_clearance_m"))
                except ValueError:
                    # A compact slab is an optional saving on a candidate that already exists. One
                    # candidate with a degenerate basement feature must not abort the whole plan: the
                    # original stays in the pool and the validator reports its geometry.
                    continue
                if proposal["status"]!="concept_candidate" or (proposal["saved_area_m2"] or 0)<=EPS:
                    continue
                f["geometry"]=mapping(proposal["polygon"])
                f["properties"].update(compact_candidate=True,area_m2=proposal["area_m2"],
                    original_area_m2=proposal["original_area_m2"])
                proposals.append({k:v for k,v in proposal.items() if k!="polygon"})
            if proposals:
                compact["compact_slab"]={"source_candidate_index":original_index,"levels":proposals,
                    "saved_area_m2":sum(p["saved_area_m2"] for p in proposals),
                    "original_excavation_m2":max(shape(f["geometry"]).area for f in original["features"]
                        if f["properties"].get("layer")=="basement_boundary"),
                    "pending_reviews":sorted({r for p in proposals for r in p["pending_reviews"]})}
                candidates.append(compact)
    if not candidates:
        candidates=[{"strategy":strategy,"features":base,"levels":[{"level":0,"z_m":0,"provided_spaces":0}],
                     "provided":0,"accessible":0,"search_count":0}]
    for candidate in candidates:
        candidate["validation"]=validate_plan(request,candidate)
        if placement_stage:
            from backend.app.modules.design.generation.maas.masterplan.placement_quality import review_placement
            candidate['placement_quality']=review_placement(request, {**candidate,
                'metrics':{'planned_parking_stalls':planned,'required_parking_stalls':required}})
    return _rank_and_record(request, candidates, rules=rules, options=options, law=law, evidence=evidence,
        site=site, footprint=footprint, strategy=strategy, planned=planned, required=required,
        accessible=accessible, target_stalls=target_stalls, surface_target=surface_target,
        max_surface=max_surface, bcr=bcr, maxlevels=maxlevels, angle=angle, explicit_angle=explicit_angle,
        placement_stage=placement_stage, search_budget=search_budget, missing=missing, failures=failures)
