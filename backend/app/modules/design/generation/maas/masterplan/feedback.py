"""Evidence-bounded parking demand feedback for MassAgent review.

The planner owns the measured layout. This module only translates its result into
questions and quantitative design targets; it never edits a footprint or claims that
MassAgent, a designer, or a permitting authority accepted a proposal.
"""
from __future__ import annotations

import math
from collections.abc import Mapping


def _mapping(value):
    return value if isinstance(value, Mapping) else {}


def _count(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return int(value) if value >= 0 and int(value) == value else None


def _area(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value) if value >= 0 else None


def _rounded(value):
    return round(value, 2) if value is not None else None


def _rule_snapshot(request, result):
    rules = _mapping(request.get("rules")) or _mapping(_mapping(result.get("provenance")).get("rules"))
    owner = _mapping(rules.get("owner_snapshot"))
    law = _mapping(request.get("law")) or _mapping(_mapping(result.get("provenance")).get("law"))
    return rules.get("source_snapshot") or owner.get("source_snapshot") or law.get("source_snapshot")


def build_mass_feedback(request: Mapping, result: Mapping) -> dict:
    """Return a review contract from an existing layout result and its original request.

    `options.parking_efficiency_ratio` is an explicit, non-statutory multiplier on
    `metrics.module_ideal_m2`. Without it, only the ideal lower area bound is shown.
    Proposed per-level counts retain drawn stalls, remove surplus from the deepest
    level first, then put any shortfall on B1 for *review*. This is not a fit claim.
    """
    request, result = _mapping(request), _mapping(result)
    options = _mapping(request.get("options"))
    ratio = options.get("parking_efficiency_ratio")
    if ratio is not None:
        if isinstance(ratio, bool) or not isinstance(ratio, (int, float)) or not math.isfinite(ratio) or ratio < 1:
            raise ValueError("parking_efficiency_ratio must be a finite number >= 1")
        ratio = float(ratio)

    provenance = _mapping(result.get("provenance"))
    law = _mapping(request.get("law")) or _mapping(provenance.get("law"))
    metrics = _mapping(result.get("metrics"))
    # CARRY THE NUMBER WITH ITS STATUS, DO NOT BLANK IT. Dropping the count whenever anything else in
    # the law block is unresolved - the district-plan overlay, typically - told MassAgent only that
    # something was wrong, never how many cars were missing, so the one party that can act on a
    # parking shortfall got a feedback object with `required_stalls: null` while the planner had
    # designed to 40 and failed `parking_count` against it. The count is Lawagent's answer and it
    # carries a task id; `law_status` travels beside it so the receiver knows it is provisional.
    required = _count(law.get("required_spaces"))
    planned = _count(metrics.get("planned_parking_stalls"))
    target = max(required, planned or 0) if required is not None else planned
    provided = _count(metrics.get("provided_parking_stalls"))
    module_ideal = _area(metrics.get("module_ideal_m2"))
    if module_ideal == 0:
        module_ideal = None
    source_snapshot = _rule_snapshot(request, result)
    snapshot_status = "present" if source_snapshot else "missing"
    law_task_ids = list(law.get("source_task_ids") or [])
    blocking = [str(x) for x in (result.get("blocking") or [])]
    geometry_status = _mapping(result.get("validation")).get("geometry_status")
    no_ramp = any("no straight or curved ramp fits" in x or "no straight ramp fits" in x for x in blocking)

    raw_levels = result.get("levels") or []
    actual = {}
    level_evidence = {}
    for item in raw_levels:
        if not isinstance(item, Mapping):
            continue
        level = item.get("level")
        if isinstance(level, bool) or not isinstance(level, int) or level > 0:
            continue
        if level < -5:
            raise ValueError('observed basement depth exceeds planner maximum 5')
        count = _count(item.get("provided_spaces"))
        if count is not None:
            actual[level] = actual.get(level, 0) + count
        level_evidence[level] = item
    ground = actual.get(0, 0)
    observed = sum(actual.values())
    count_consistent = provided is None or provided == observed

    explicit_depth = _count(options.get("max_basement_levels"))
    if 'max_basement_levels' in options and (explicit_depth is None or explicit_depth > 5):
        raise ValueError('maximum basement levels must be an integer in planner range 0..5')
    max_depth = explicit_depth if explicit_depth is not None else max((abs(k) for k in actual if k < 0), default=1)
    depths = max(max_depth, max((abs(k) for k in actual if k < 0), default=0))
    levels = [0, *(-depth for depth in range(1, depths + 1))]
    proposed = {level: actual.get(level, 0) for level in levels}
    unallocated = None
    if target is not None and count_consistent:
        delta = target - observed
        if delta > 0:
            if depths:
                proposed[-1] += delta
                unallocated = 0
            else:
                unallocated = delta
        else:
            excess = -delta
            for level in reversed(levels):
                removed = min(excess, proposed[level])
                proposed[level] -= removed
                excess -= removed
            unallocated = 0

    basement_target = max(target - ground, 0) if target is not None else None
    ideal_lower_bound = _rounded(basement_target * module_ideal) if basement_target is not None and module_ideal else None
    workable_budget = _rounded(basement_target * module_ideal * ratio) if ideal_lower_bound is not None and ratio is not None else None
    rows = []
    for level in levels:
        evidence = _mapping(level_evidence.get(level))
        current_plate = _area(evidence.get("plate_area_m2")) if level < 0 else None
        proposed_stalls = proposed[level] if target is not None and count_consistent else None
        ideal_area = _rounded(proposed_stalls * module_ideal) if level < 0 and proposed_stalls is not None and module_ideal else None
        budget = _rounded(ideal_area * ratio) if ideal_area is not None and ratio is not None else None
        reduction = _rounded(max(current_plate - budget, 0)) if current_plate is not None and budget is not None else None
        rows.append({"level": level, "actual_stalls": actual.get(level, 0),
                     "proposed_required_stalls": proposed_stalls,
                     "allocation_status": "design_proposal_review_required" if proposed_stalls is not None else "unallocated_needs_evidence",
                     "net_plate_area_m2": _rounded(current_plate),
                     "actual_plate_area_per_stall_m2": _area(evidence.get("plate_area_per_stall_m2")) if level < 0 else None,
                     "ideal_lower_bound_m2": ideal_area,
                     "proposed_net_parking_area_m2": budget,
                     "area_reduction_vs_actual_m2": reduction,
                     "area_basis": evidence.get("over_module_ideal_basis") if level < 0 else None})

    actions = []
    def add(action_id, target_agent, priority, proposal, evidence, *, evidence_status="measured_layout"):
        actions.append({"id": action_id, "target_agent": target_agent, "priority": priority,
                        "review_required": True, "proposal": proposal, "evidence": evidence,
                        "evidence_status": evidence_status,
                        "provenance": {"law_task_ids": law_task_ids,
                                       "rule_source_snapshot": source_snapshot,
                                       "layout_geometry_status": geometry_status}})

    if required is None:
        add("obtain_law_count_evidence", "lawagent", "blocking",
            "Resolve the authoritative integer parking requirement before asking MassAgent to revise area or levels.",
            {"law_status": law.get("status"), "law_required_spaces": law.get("required_spaces"),
             "result_required_parking_stalls": metrics.get("required_parking_stalls")}, evidence_status="missing_law_count")
    elif not source_snapshot:
        add("obtain_rule_snapshot", "lawagent", "blocking",
            "Attach the applicable parking design-rule source snapshot before treating layout dimensions as verified.",
            {"required_spaces": required, "rule_snapshot": None}, evidence_status="missing_rule_snapshot")

    if not count_consistent:
        add("reconcile_layout_counts", "masterplanagent", "blocking",
            "Reconcile measured per-level stalls with the result total before using a floor allocation.",
            {"result_total": provided, "sum_of_levels": observed}, evidence_status="inconsistent_layout")

    if no_ramp and target is not None:
        add("investigate_ramp_fit", "masterplanagent", "high",
            "Review feasible entrance, ramp path, grade profile, clearance and basement-aisle connection on the supplied geometry.",
            {"blocking": [x for x in blocking if "ramp" in x], "ground_stalls": ground,
             "basement_target_stalls": basement_target},
            evidence_status="verified_layout_geometry" if source_snapshot else "preliminary_geometry")

    shortfall = max(target - provided, 0) if target is not None and provided is not None else None
    if shortfall and count_consistent:
        add("review_massing_for_shortfall", "massagent", "high",
            "Review footprint placement, ground access and basement plate options against the remaining parking demand; return an authored revision for replanning.",
            {"planning_target_stalls": target, "provided_stalls": provided,
             "shortfall_stalls": shortfall, "basement_target_stalls": basement_target,
             "ideal_lower_bound_m2": ideal_lower_bound, "workable_area_budget_m2": workable_budget},
            evidence_status="measured_layout_with_rule_snapshot" if source_snapshot else "preliminary_geometry")

    thin = any("thin" in x and "level" in x for x in blocking)
    inefficient = [row for row in rows if row["level"] < 0 and row["area_reduction_vs_actual_m2"] is not None
                   and row["area_reduction_vs_actual_m2"] > 0]
    if inefficient or thin:
        add("review_inefficient_basement_plate", "massagent", "medium",
            "Review the excavated net plate and parking programme per level; resize or reallocate only after checking ramps, structure and stall yield.",
            {"levels": [{"level": row["level"], "actual_stalls": row["actual_stalls"],
                         "proposed_stalls": row["proposed_required_stalls"],
                         "actual_net_plate_m2": row["net_plate_area_m2"],
                         "proposed_net_plate_m2": row["proposed_net_parking_area_m2"],
                         "review_reduction_m2": row["area_reduction_vs_actual_m2"]} for row in (inefficient or rows) if row["level"] < 0],
             "planner_thin_advisory": thin},
            evidence_status="explicit_design_efficiency_assumption" if ratio is not None else "planner_advisory_only")

    eliminated = [row["level"] for row in rows if row["level"] < 0 and row["actual_stalls"] > 0
                  and row["proposed_required_stalls"] == 0]
    if eliminated:
        add("review_eliminating_deep_level", "massagent", "medium",
            "Review whether surplus stalls permit omission of a deep basement level and its excavation; confirm all programme and access obligations.",
            {"candidate_levels": eliminated, "allocation_policy": "remove_surplus_from_deepest_level_first"},
            evidence_status="design_allocation_proposal")

    status = ("needs_evidence" if required is None or source_snapshot is None or not count_consistent
              else "review_required" if actions else "no_change")
    return {
        "schema_version": "masterplan.mass_feedback.v1", "status": status,
        "review_required": bool(actions),
        "demand": {"required_stalls": required, "law_status": law.get("status"),
                   "planned_stalls": planned,
                   "planning_target_stalls": target, "provided_stalls": provided,
                   "legal_shortfall_stalls": max(required - provided, 0) if required is not None and provided is not None else None,
                   "shortfall_stalls": shortfall, "ground_provided_stalls": ground,
                   "basement_required_min_stalls": max(required - ground, 0) if required is not None else None,
                   "basement_target_stalls": basement_target,
                   "unallocated_proposed_stalls": unallocated},
        "levels": rows,
        "area_basis": {"module_ideal_m2": module_ideal, "design_efficiency_ratio": ratio,
                       "assumption_source": "request.options.parking_efficiency_ratio" if ratio is not None else None,
                       "ideal_lower_bound_m2": ideal_lower_bound,
                       "workable_area_budget_m2": workable_budget,
                       "area_scope": "net_basement_parking_plate_excluding_declared_nonparking_programme"},
        "mass_context": {"authored_footprint": bool(request.get("footprint")),
                         "current_footprint_area_m2": _area(metrics.get("building_footprint_m2")),
                         "proposed_footprint_geometry": None,
                         "automatic_mass_change": False},
        "actions": actions,
        "provenance": {"law_status": law.get("status"), "law_task_ids": law_task_ids,
                       "law_snapshot_status": snapshot_status, "rule_source_snapshot": source_snapshot,
                       "layout_geometry_status": geometry_status,
                       "count_consistent": count_consistent,
                       "allocation_policy": "retain_drawn_counts_then_remove_deepest_surplus_or_assign_shortfall_to_B1_for_review"},
    }


__all__ = ["build_mass_feedback"]
