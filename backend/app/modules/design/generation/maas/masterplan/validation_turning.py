"""Turning-space measurements for `validation.validate_plan`."""
from __future__ import annotations

import math

from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.masterplan.validation_geometry import TOL, _turning_space


def _check_turning_space(check, checks, pending, grouped, request, rules):
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
