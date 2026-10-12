"""Rank the planner's validated candidates and assemble the chosen layout record."""
from __future__ import annotations

import copy
import math
import os

from shapely.geometry import shape

from backend.app.modules.design.generation.maas.masterplan.geometry import digest, union_or_empty
from backend.app.modules.design.generation.maas.masterplan.feedback import build_mass_feedback
from backend.app.modules.design.generation.maas.masterplan.planner_metrics import excavation_cost_units, level_efficiency, module_ideal_m2


def drive_burden(features, provided):
    drives = {}
    for feature in features:
        props = feature.get('properties') or {}
        if props.get('layer') in ('parking_aisle', 'vehicular_access'):
            drives.setdefault(props.get('level', 0), []).append(shape(feature['geometry']))
    return sum(union_or_empty(geoms).area for geoms in drives.values()) / max(provided, 1)


def planning_rank(candidate, *, placement_stage, accessible, planned, surface_target):
    """Feasibility first; construction metrics never choose a planning alternative."""
    return (candidate.get('placement_quality', {}).get('eligible', False) if placement_stage else True,
            candidate['validation']['geometry_status'] == 'passed',
            min(candidate['accessible'], accessible), min(candidate['provided'], planned or 0),
            -abs(sum(v['provided_spaces'] for v in candidate['levels'] if v['level'] == 0)
                 - surface_target) if surface_target is not None else 0,
            -drive_burden(candidate['features'], candidate['provided']),
            candidate.get('ramp_orientation') in ('parallel_to_edge', 'off_aisle'),
            -len(candidate['levels']),
            # Last, between a plan and its own compacted plate (same stalls, aisles and ramp):
            # the declared envelope - the whole parcel when none is authored - is the search
            # domain, not the plan. Measured on 고산 (placement stage): the 22 + 28 rows plan
            # tied with its 1,557 m2 compact twin and `max` kept the first, the 2,500 m2 parcel.
            candidate.get('compact_slab') is not None)


def _rank_and_record(request, candidates, *, rules, options, law, evidence, site, footprint, strategy, planned, required, accessible, target_stalls, surface_target, max_surface, bcr, maxlevels, angle, explicit_angle, placement_stage, search_budget, missing, failures):
    """The tail of `planner._plan_site_fixed`, after every candidate carries its validation."""
    def excavation(c):
        """Excavated area of the deepest basement outline (0 with no basement).  Practice digs the
        plate plus the ramp, not the parcel: the reference scheme's B1 is 1.0-1.3x the footprint."""
        areas=[shape(f["geometry"]).area for f in c["features"]
               if f["properties"]["layer"]=="basement_boundary"]
        return max(areas) if areas else 0.0
    def worst_efficiency(c):
        """The least efficient level of a candidate, as a multiple of the module ideal (0 if none)."""
        eff = level_efficiency(c["features"], rules)
        return max((v["over_module_ideal"] or 0) for v in eff.values()) if eff else 0.0
    def rank(c):
        return planning_rank(c, placement_stage=placement_stage, accessible=accessible,
                             planned=planned, surface_target=surface_target)
    if os.environ.get("MASTERPLAN_EXPLAIN_RANK"):
        # Why THIS candidate: the losing ones are otherwise invisible, and "the objective chose it"
        # is not an answer anybody can check.
        import sys as _sys
        for c in sorted(candidates,key=rank,reverse=True)[:12]:
            surface=sum(v["provided_spaces"] for v in c["levels"] if v["level"]==0)
            print("RANK %-16s %-14s provided %3d surface %3d levels %d worst_eff %5.2f exc %7.1f score %s"
                  % (c.get("strategy"),c.get("pattern","generic_packer"),c["provided"],surface,
                     len(c["levels"]),worst_efficiency(c),excavation(c),c.get("score")),file=_sys.stderr)
    chosen=max(candidates,key=rank)
    missing.extend(chosen.get("pending_reviews") or [])
    for lvl in chosen.get("loop_fallback") or []:
        missing.append(f"circulation_loop_not_achievable:{lvl}: the bounded search did not find a closed aisle loop "
                       f"for the {planned}-stall design target. This is a circulation alternative requiring "
                       f"entry, exit and vehicle maneuver review; aisle width alone establishes no legal or swept-path approval")
    ideal_module=module_ideal_m2(rules)
    chosen_efficiency=level_efficiency(chosen["features"],rules)
    for entry in chosen["levels"]:
        stats=chosen_efficiency.get(entry["level"])
        if stats:
            entry.update({k:stats[k] for k in ("area_per_stall_m2","over_module_ideal","parking_area_m2",
                                               "over_module_ideal_basis")})
            for k in ("plate_area_m2","plate_area_per_stall_m2"):
                if k in stats:
                    entry[k]=stats[k]
    if search_budget.truncated:
        missing.append("basement search truncated by explicit candidate budget; not exhaustive infeasibility")
    validation=chosen["validation"]
    if target_stalls is not None and chosen["provided"] < target_stalls:
        failures.append(f"parking shortfall: {chosen['provided']} of design target {target_stalls} stalls placed "
                        f"(Law minimum {required}); review mass, parking strategy and capacity")
    if surface_target is not None:
        actual_surface=sum(v["provided_spaces"] for v in chosen["levels"] if v["level"]==0)
        if actual_surface != surface_target:
            failures.append(f"surface parking design target is {surface_target}, but {actual_surface} stalls were placed; "
                           "review mass, ramp and parking split before accepting this alternative")
    if validation["geometry_status"]=="passed" or any(
            f["properties"].get("layer")=="ramp" for f in chosen["features"]):
        # A rejected ramp grammar is not evidence that a chosen ramp is absent.
        # The chosen ramp's actual validation failures remain below.
        failures=[f for f in failures if not f.startswith("no straight or curved ramp") and not f.startswith("no straight ramp")]
    failedchecks=[c["id"] for c in validation["checks"] if c["status"]=="failed"]
    missing.extend(validation["pending_reviews"])
    missing.extend((chosen.get("compact_slab") or {}).get("pending_reviews",[]))
    if required is None:
        missing.append("law parking requirement is missing")
        # No requirement means no count feasibility verdict can be formed.
    elif chosen["provided"]<required:
        # A short count is a siting outcome, not an unimplemented feature: say what was
        # tried and what would change it. The trade-off itself is the designer's call.
        # Say WHY in the terms a designer acts on.  The governing fact on a tight parcel is whether
        # a parking module fits across it at all: a double-loaded module is stall + aisle + stall
        # deep, so a parcel narrower than that cannot carry 자주식 rows however they are arranged,
        # and the answer there is 기계식 - which this engine does not draw and must not pretend to.
        module_depth=(2*float(rules["stall_length_m"])+float(rules["aisle_width_m"])
                      if rules.get("stall_length_m") and rules.get("aisle_width_m") else None)
        narrow=None
        if module_depth:
            ring=list(site.minimum_rotated_rectangle.exterior.coords)
            narrow=min(math.dist(ring[i],ring[i+1]) for i in range(4))
        failures.append(f"parking shortfall: {chosen['provided']} of {required} stalls placed under strategy "
                        f"'{strategy}' (basement levels used {len(chosen['levels'])-1} of max {int(maxlevels)}); the rest does not fit "
                        f"beside a {footprint.area:.0f} m2 footprint on a {site.area:.0f} m2 site - a basement/mixed strategy "
                        "or a smaller footprint is a design decision, not a statute")
        single_depth = (float(rules["stall_length_m"])+float(rules["aisle_width_m"])
                        if module_depth else None)
        if narrow is not None and single_depth and narrow < single_depth:
            missing.append(f"parcel narrow dimension {narrow:.1f} m is below the {single_depth:.1f} m "
                           "single-loaded 90-degree module; review a different parking form or mass/access "
                           "arrangement. This search result does not establish site infeasibility")
        elif narrow is not None and module_depth and narrow < module_depth:
            missing.append(f"parcel narrow dimension {narrow:.1f} m permits only a single-loaded "
                           f"90-degree module ({single_depth:.1f} m), not the double-loaded "
                           f"module ({module_depth:.1f} m); verify capacity and end manoeuvres")
        elif narrow is not None and module_depth and narrow < 2*module_depth:
            missing.append(f"the parcel's narrow dimension is {narrow:.1f} m, so only one {module_depth:.1f} m "
                           "module fits across it; the plate and the parking are competing for the same width")
    blocking=list(dict.fromkeys([*failures,*failedchecks,*missing]))
    status="needs_revision" if failures or failedchecks else "needs_evidence" if blocking else "resolved"
    result={"schema_version":"masterplan.layout.v1","type":"FeatureCollection",
        "coordinate_crs":request.get("crs"),"pnu":request.get("pnu"),"status":status,
        "features":chosen["features"],"levels":chosen["levels"],"blocking":blocking,
        "validation":validation,
        "metrics":{"layout_axis":{"mode":"explicit_site_local" if explicit_angle is not None else "frontage_auto",
                   "angle_deg":angle,"source":copy.deepcopy(options.get('layout_axis')),
                   "scope":"generated zones and parking module search; fixed source geometry unchanged; not maneuver validation"},
                   "site_area_m2":site.area,"building_footprint_m2":footprint.area,
                   "coverage_ratio_pct":footprint.area/site.area*100,"bcr_limit_pct":bcr,
                   "required_parking_stalls":required,"planned_parking_stalls":planned,"max_surface_stalls":max_surface,
                   "provided_parking_stalls":chosen["provided"],
                   "required_accessible_stalls":law.get("required_accessible_spaces"),
                   "provided_accessible_stalls":chosen["accessible"],"parking_strategy":chosen["strategy"],
                   "excavation_m2":round(excavation(chosen),2),
                   "excavation_cost_units":excavation_cost_units(excavation(chosen),
                       sum(v["level"]<0 for v in chosen["levels"])),
                   "original_excavation_m2":(chosen.get("compact_slab") or {}).get("original_excavation_m2"),
                   "area_per_stall_m2":round(sum(v["parking_area_m2"] for v in chosen_efficiency.values())
                                             /max(sum(v["stalls"] for v in chosen_efficiency.values()),1),2)
                                        if chosen_efficiency else None,
                   "module_ideal_m2":round(ideal_module["double_loaded"],2) if ideal_module else None,
                   "excavation_over_footprint":round(excavation(chosen)/footprint.area,3) if footprint.area else None,
                   "parking_status":validation["geometry_status"],"layout_pattern":chosen.get("pattern") or "generic_packer",
                   "parking_generation":[{"level":f['properties'].get('level'),**f['properties']['generation']}
                        for f in chosen['features'] if f.get('properties',{}).get('layer')=='parking_aisle'
                        and f['properties'].get('generation')],
                   "layout_score":chosen.get("score"),"layout_terms":chosen.get("terms"),
                   "basement_levels":sum(x["level"]<0 for x in chosen["levels"])},
        "alternatives":[{"strategy":c["strategy"],"pattern":c.get("pattern"),"score":c.get("score"),"provided":c.get("provided"),
                         "pending_reviews":c.get("pending_reviews") or [],
                         "compact_slab":c.get("compact_slab"),
                         "level_counts":{str(v['level']):v['provided_spaces'] for v in c['levels']},
                         "geometry_status":c["validation"]["geometry_status"],
                         "failed_checks":[k["id"] for k in c["validation"]["checks"] if k["status"]=="failed"][:8],
                         "ramp_candidate":c.get("ramp_candidate"),"ramp_orientation":c.get("ramp_orientation"),
                         "provided_spaces":c["provided"],"levels":len(c["levels"])-1,
                         "geometry_status":c["validation"]["geometry_status"],
                         "failed_checks":[x["id"] for x in c["validation"]["checks"] if x["status"]=="failed"],
                         "search_count":c["search_count"]} for c in candidates],
        "provenance":{"law":law,"rules":rules,"evidence":evidence,"compact_slab":chosen.get("compact_slab")}}
    result["handoff"]={"source_agent":"masterplanagent","target_agent":"massagent",
                       "input_hash":digest(request),"geometry_hash":digest(result["features"]),
                       "status":"passed" if status=="resolved" else "failed" if status=="needs_revision" else "needs_evidence",
                       "evaluated":True,"hard_pass":status=="resolved",
                       "scope":validation["scope"]}
    result["search_budget"] = {**search_budget.record(),
        "slab_candidates": "full_host_only" if search_budget.limit is not None else "existing_sized_and_full_host",
        "scope": "per fixed-layout call; invocation cap, not wall-clock or exhaustive feasibility proof"}
    result["entry_policy"] = {"alignment": options.get("entry_alignment", "auto"),
        "scope": "straight full-width longitudinal frontage connectors and single-loaded rows searched on explicit axis; not exhaustive layout feasibility",
        "entrance_approval": "unverified", "swept_path": "unverified"}
    result["mass_feedback"] = build_mass_feedback(request, result)
    return result
