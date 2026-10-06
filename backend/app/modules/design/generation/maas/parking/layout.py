"""Deterministic parking layout precheck helpers for MAAS.

This is a conservative capacity estimator, not a final parking layout solver.
It uses statutory/design module dimensions to decide whether a candidate mass
has a plausible parking envelope before a later solver places exact stalls,
aisles, ramps, turning paths, columns, and accessible routes.
"""

from __future__ import annotations

import math
from itertools import combinations
from typing import Any

from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon, shape
from shapely.ops import nearest_points


DEFAULT_STALL_WIDTH_M = 2.5
DEFAULT_STALL_LENGTH_M = 5.0
DEFAULT_PARALLEL_STALL_WIDTH_M = 2.0
DEFAULT_PARALLEL_STALL_LENGTH_M = 6.0
RESIDENTIAL_UNDIVIDED_ROAD_PARALLEL_LENGTH_M = 5.0
DEFAULT_AISLE_WIDTH_M = 6.0
DEFAULT_PARALLEL_AISLE_WIDTH_M = 3.0
DEFAULT_ACCESSIBLE_WIDTH_M = 3.3
DEFAULT_ACCESSIBLE_LENGTH_M = 5.0
SMALL_ATTACHED_PARKING_MAX_SPACES = 8
TANDEM_ALLOWED_MAX_SPACES = 5
ATTACHED_PARKING_ENTRANCE_WIDTH_M = 3.0
ATTACHED_PARKING_DEAD_END_APPROVAL_ENTRANCE_WIDTH_M = 2.5
ROAD_AS_AISLE_UNDIVIDED_MAX_ROAD_WIDTH_M = 12.0
ROAD_AS_AISLE_PERPENDICULAR_REQUIRED_WIDTH_M = 6.0
ROAD_AS_AISLE_PARALLEL_REQUIRED_WIDTH_M = 4.0
GRID_SOLVER_STEP_M = 0.5
PILOTI_ASSUMED_COLUMN_SIZE_M = 0.45
PILOTI_MIN_CLEAR_BAY_MARGIN_M = 0.3


def estimate_parking_capacity(
    envelope: Polygon | MultiPolygon | None,
    *,
    strategy: str,
    include_accessible: bool = True,
) -> dict[str, Any]:
    """Estimate 90-degree self-parking capacity in a candidate envelope."""
    polygon = _largest_polygon(envelope)
    if polygon is None or polygon.is_empty or polygon.area <= 0:
        return _empty("missing_or_empty_envelope", strategy)

    long_side, short_side = _oriented_rect_dimensions(polygon)
    usable_factor = _usable_factor(strategy)
    effective_area = polygon.area * usable_factor

    double_loaded = _module_capacity(
        length=long_side,
        depth=short_side,
        module_depth=DEFAULT_STALL_LENGTH_M * 2 + DEFAULT_AISLE_WIDTH_M,
        rows_per_module=2,
    )
    single_loaded = _module_capacity(
        length=long_side,
        depth=short_side,
        module_depth=DEFAULT_STALL_LENGTH_M + DEFAULT_AISLE_WIDTH_M,
        rows_per_module=1,
    )
    area_capacity = math.floor(effective_area / _planning_module_area(strategy))
    estimated = max(0, min(max(double_loaded, single_loaded), area_capacity))
    if strategy == "mechanical":
        estimated = None

    return {
        "status": "heuristic_only",
        "strategy": strategy,
        "envelope_area_m2": round(polygon.area, 2),
        "effective_area_m2": round(effective_area, 2),
        "oriented_rect": {
            "long_side_m": round(long_side, 2),
            "short_side_m": round(short_side, 2),
        },
        "module_dimensions": {
            "stall_width_m": DEFAULT_STALL_WIDTH_M,
            "stall_length_m": DEFAULT_STALL_LENGTH_M,
            "aisle_width_m": DEFAULT_AISLE_WIDTH_M,
            "double_loaded_depth_m": DEFAULT_STALL_LENGTH_M * 2 + DEFAULT_AISLE_WIDTH_M,
            "single_loaded_depth_m": DEFAULT_STALL_LENGTH_M + DEFAULT_AISLE_WIDTH_M,
            "accessible_width_m": DEFAULT_ACCESSIBLE_WIDTH_M if include_accessible else None,
            "accessible_length_m": DEFAULT_ACCESSIBLE_LENGTH_M if include_accessible else None,
        },
        "capacity_estimates": {
            "single_loaded_spaces": single_loaded,
            "double_loaded_spaces": double_loaded,
            "area_limited_spaces": area_capacity,
            "estimated_capacity_spaces": estimated,
        },
        "limitations": [
            "does_not_place_exact_stalls",
            "does_not_model_columns_or_core_obstructions",
            "does_not_check_ramp_slope_or_turning_swept_path",
            "does_not_verify_accessible_route",
        ],
    }


def generate_parking_layout_candidate(
    envelope: Polygon | MultiPolygon | None,
    *,
    required_spaces: int,
    strategy: str = "ground_surface",
    accessible_spaces: int = 0,
    road_context: dict[str, Any] | None = None,
    drive_envelope: Polygon | MultiPolygon | None = None,
) -> dict[str, Any]:
    """Generate deterministic stall coordinates for early MAAS parking review.

    This is a coordinate placer, not an optimizer. It creates a legally
    explainable first candidate that a later grid/MIP solver can improve.
    """
    polygon = _largest_polygon(envelope)
    drive_polygon = _largest_polygon(drive_envelope) or polygon
    if polygon is None or polygon.is_empty or polygon.area <= 0:
        return _layout_result(
            status="fail",
            strategy=strategy,
            placement_mode="none",
            required_spaces=required_spaces,
            accessible_spaces=accessible_spaces,
            stalls=[],
            reason="missing_or_empty_envelope",
        )

    if strategy == "mechanical":
        return _mechanical_parking_review_candidate(
            polygon,
            required_spaces=required_spaces,
            accessible_spaces=accessible_spaces,
        )

    relief = evaluate_small_attached_parking_relief(
        required_spaces=required_spaces,
        road_context=road_context,
    )
    road_as_aisle = any(option["available"] for option in relief["road_as_aisle_options"])
    if road_as_aisle:
        candidate = _place_road_as_aisle_stalls(
            polygon,
            required_spaces=required_spaces,
            accessible_spaces=accessible_spaces,
            allow_tandem=bool(relief["tandem_parking"]["available"]),
        )
        candidate["small_attached_parking_relief"] = relief
        _attach_authority_review_check(candidate, relief)
        if candidate["provided_spaces"] >= required_spaces:
            _attach_basement_ramp_review(candidate, strategy, road_context)
            return candidate

    candidate = _place_internal_90_degree_stalls(
        polygon,
        required_spaces=required_spaces,
        accessible_spaces=accessible_spaces,
        strategy=strategy,
        drive_polygon=drive_polygon,
    )
    rejected_module = (candidate if candidate.get('drive_envelope_check', {}).get('satisfied') is False else None)
    if (
        candidate["provided_spaces"] < required_spaces
        and required_spaces <= SMALL_ATTACHED_PARKING_MAX_SPACES
    ):
        compact_candidate = _place_single_row_aisle_review_stalls(
            polygon,
            required_spaces=required_spaces,
            accessible_spaces=accessible_spaces,
            strategy=strategy,
        )
        if _layout_rank(compact_candidate) > _layout_rank(candidate):
            candidate = compact_candidate
    if candidate["provided_spaces"] < required_spaces or candidate.get("status") != "pass":
        grid_candidate = _solve_grid_parking_layout(
            polygon,
            drive_polygon=drive_polygon,
            required_spaces=required_spaces,
            accessible_spaces=accessible_spaces,
            strategy=strategy,
            road_context=road_context,
        )
        if _layout_rank(grid_candidate) > _layout_rank(candidate):
            candidate = grid_candidate
    if (
        accessible_spaces == 0
        and required_spaces <= SMALL_ATTACHED_PARKING_MAX_SPACES
        and (candidate["provided_spaces"] < required_spaces or candidate.get("status") != "pass")
    ):
        parallel_candidate = _solve_connected_parallel_parking_layout(
            polygon,
            drive_polygon=drive_polygon,
            required_spaces=required_spaces,
            strategy=strategy,
            road_context=road_context,
        )
        if _layout_rank(parallel_candidate) > _layout_rank(candidate):
            candidate = parallel_candidate
    candidate["small_attached_parking_relief"] = relief
    if rejected_module is not None and candidate is not rejected_module:
        candidate['rejected_layouts'] = [rejected_module]
    _attach_authority_review_check(candidate, relief)
    _attach_basement_ramp_review(candidate, strategy, road_context)
    return candidate


def evaluate_small_attached_parking_relief(
    *,
    required_spaces: int | None = None,
    road_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate small attached-parking layout exceptions without approving them."""
    context = road_context or {}
    road_width = _optional_float(context.get("road_width_m"))
    has_sidewalk_separation = _optional_bool(context.get("has_sidewalk_separation"))
    is_dead_end = bool(context.get("is_dead_end_road"))
    required_known = required_spaces is not None
    within_8 = required_spaces <= SMALL_ATTACHED_PARKING_MAX_SPACES if required_known else None
    within_5 = required_spaces <= TANDEM_ALLOWED_MAX_SPACES if required_known else None

    undivided_road_possible = (
        road_width is not None
        and road_width < ROAD_AS_AISLE_UNDIVIDED_MAX_ROAD_WIDTH_M
        and has_sidewalk_separation is False
        and (within_8 is not False)
    )
    wide_road_perpendicular_possible = (
        road_width is not None
        and road_width >= ROAD_AS_AISLE_UNDIVIDED_MAX_ROAD_WIDTH_M
        and has_sidewalk_separation is not False
        and (within_5 is not False)
    )

    return {
        "status": "evaluated" if required_known else "needs_required_count",
        "source": "Parking Lot Act Enforcement Rule Article 11(5)",
        "applies_to": "attached_self_parking_total_spaces_8_or_less",
        "required_spaces": required_spaces,
        "road_context": {
            "road_width_m": road_width,
            "has_sidewalk_separation": has_sidewalk_separation,
            "is_dead_end_road": is_dead_end,
        },
        "road_as_aisle_options": [
            {
                "key": "undivided_road_under_12m",
                "available": bool(undivided_road_possible),
                "condition": "No sidewalk/roadway separation, road width under 12m, total attached self-parking spaces 8 or less.",
                "aisle_width_counting_road_m": ROAD_AS_AISLE_PERPENDICULAR_REQUIRED_WIDTH_M,
                "parallel_aisle_width_counting_road_m": ROAD_AS_AISLE_PARALLEL_REQUIRED_WIDTH_M,
                "road_inclusion_scope": "to_centerline_or_opposite_boundary_if_no_centerline",
            },
            {
                "key": "sidewalk_separated_road_12m_or_more_perpendicular",
                "available": bool(wide_road_perpendicular_possible),
                "condition": "Sidewalk/roadway separated road 12m or wider, total spaces 5 or less, no obstruction to parking use.",
                "parking_angle": "perpendicular_only",
                "needs_authority_review": True,
                "sidewalk_separation_evidence": (
                    "confirmed" if has_sidewalk_separation is True else "unknown_needs_site_or_road_evidence"
                ),
            },
        ],
        "tandem_parking": {
            "available": within_5 is not False,
            "condition": "For 5 or fewer stalls, up to two stalls may be placed in tandem from the aisle.",
            "max_depth_from_aisle": 2,
        },
        "entrance_width": {
            "min_width_m": ATTACHED_PARKING_ENTRANCE_WIDTH_M,
            "dead_end_road_approval_min_width_m": (
                ATTACHED_PARKING_DEAD_END_APPROVAL_ENTRANCE_WIDTH_M if is_dead_end else None
            ),
        },
        "limitations": [
            "does_not_replace_required_stall_count",
            "needs_actual_road_geometry_and_centerline",
            "needs_local_authority_no_traffic_obstruction_review",
        ],
    }


def _attach_authority_review_check(candidate: dict[str, Any], relief: dict[str, Any]) -> None:
    placement_mode = str(candidate.get("placement_mode") or "")
    if not placement_mode.startswith("road_as_aisle"):
        return
    stalls = candidate.get("stalls") if isinstance(candidate.get("stalls"), list) else []
    adjacency = candidate.get("adjacency") if isinstance(candidate.get("adjacency"), dict) else {}
    turning = candidate.get("turning_clearance") if isinstance(candidate.get("turning_clearance"), dict) else {}
    road_options = relief.get("road_as_aisle_options") if isinstance(relief.get("road_as_aisle_options"), list) else []
    available_options = [
        option for option in road_options
        if isinstance(option, dict) and option.get("available")
    ]
    sidewalk_unknown = any(
        option.get("sidewalk_separation_evidence") == "unknown_needs_site_or_road_evidence"
        for option in available_options
        if isinstance(option, dict)
    )
    provided_spaces = int(candidate.get("provided_spaces") or len(stalls))
    required_spaces = int(candidate.get("required_spaces") or 0)
    within_small_limit = provided_spaces <= SMALL_ATTACHED_PARKING_MAX_SPACES
    tandem_ok = (
        not placement_mode.endswith("tandem")
        or (
            provided_spaces <= TANDEM_ALLOWED_MAX_SPACES
            and bool(relief.get("tandem_parking", {}).get("available"))
            and bool(adjacency.get("contiguous_ok"))
        )
    )
    road_option_ok = bool(available_options)
    count_ok = required_spaces > 0 and provided_spaces >= required_spaces
    blockers = []
    if not count_ok:
        blockers.append("required_stall_count_not_placed")
    if not within_small_limit:
        blockers.append("exceeds_8_space_small_attached_limit")
    if not tandem_ok:
        blockers.append("tandem_depth_or_count_not_satisfied")
    if not road_option_ok:
        blockers.append("road_as_aisle_option_unavailable")
    if not adjacency.get("contiguous_ok"):
        blockers.append("stalls_not_contiguous")
    evidence_needed = []
    if sidewalk_unknown:
        evidence_needed.append("sidewalk_or_roadway_separation_evidence")
    if road_option_ok:
        evidence_needed.append("authority_no_traffic_obstruction_confirmation")
    review = {
        "schema_version": "arr.maas.parking_authority_review.v1",
        "status": (
            "blocked"
            if blockers
            else "prechecked_needs_external_evidence"
            if evidence_needed
            else "prechecked"
        ),
        "basis": "Parking Lot Act Enforcement Rule Article 11(5) small attached self-parking road-as-aisle/tandem precheck",
        "checks": {
            "required_count_placed": count_ok,
            "within_8_space_small_attached_limit": within_small_limit,
            "road_as_aisle_option_available": road_option_ok,
            "tandem_depth_count_ok": tandem_ok,
            "stalls_contiguous": bool(adjacency.get("contiguous_ok")),
            "v1_turning_status_ok": turning.get("status") == "v1_pass",
        },
        "available_road_as_aisle_options": [
            option.get("key") for option in available_options if isinstance(option, dict)
        ],
        "external_evidence_needed": evidence_needed,
        "blockers": blockers,
        "authority_review": bool(evidence_needed or blockers),
    }
    candidate["authority_review_check"] = review
    turning["authority_review_check"] = review
    turning["authority_review"] = review["authority_review"]
    candidate["turning_clearance"] = turning


def _attach_basement_ramp_review(
    candidate: dict[str, Any],
    strategy: str,
    road_context: dict[str, Any] | None,
) -> None:
    """Do not turn a stall-only basement diagram into a final parking pass."""

    if strategy not in {"basement", "semi_basement"}:
        return
    context = road_context if isinstance(road_context, dict) else {}
    ramp = context.get("basement_ramp")
    ramp_verified = bool(context.get("basement_ramp_verified")) or (
        isinstance(ramp, dict) and ramp.get("status") == "pass"
    )
    if ramp_verified:
        return

    evidence_key = "basement_ramp_slope_width_and_turning_geometry"
    existing = (
        dict(candidate.get("authority_review_check") or {})
        if isinstance(candidate.get("authority_review_check"), dict)
        else {}
    )
    evidence_needed = list(existing.get("external_evidence_needed") or ())
    if evidence_key not in evidence_needed:
        evidence_needed.append(evidence_key)
    candidate["authority_review_check"] = {
        **existing,
        "schema_version": "arr.maas.basement_parking_review.v1",
        "status": "prechecked_needs_external_evidence",
        "basis": (
            "Placed stalls do not prove a basement ramp's width, slope, "
            "frontage connection or swept turning path."
        ),
        "external_evidence_needed": evidence_needed,
        "authority_review": True,
    }
    if candidate.get("status") == "pass":
        candidate["status"] = "needs_basement_ramp_review"
    limitations = list(candidate.get("limitations") or ())
    limitation = "basement_ramp_geometry_not_verified"
    if limitation not in limitations:
        limitations.append(limitation)
    candidate["limitations"] = limitations


def _place_road_as_aisle_stalls(
    polygon: Polygon,
    *,
    required_spaces: int,
    accessible_spaces: int,
    allow_tandem: bool,
) -> dict[str, Any]:
    origin, u, v, length, depth = _oriented_frame(polygon)
    max_depth_rows = 2 if allow_tandem else 1
    depth_rows = min(max_depth_rows, max(0, math.floor(depth / DEFAULT_STALL_LENGTH_M)))
    if depth_rows <= 0:
        return _layout_result(
            status="fail",
            strategy="ground_surface",
            placement_mode="road_as_aisle",
            required_spaces=required_spaces,
            accessible_spaces=accessible_spaces,
            stalls=[],
            reason="insufficient_depth_for_stall",
        )

    stalls = _fill_rows(
        polygon,
        origin=origin,
        u=u,
        v=v,
        length=length,
        row_depth=DEFAULT_STALL_LENGTH_M,
        row_offsets=[i * DEFAULT_STALL_LENGTH_M for i in range(depth_rows)],
        required_spaces=required_spaces,
        accessible_spaces=accessible_spaces,
        mode="road_as_aisle_tandem" if depth_rows > 1 else "road_as_aisle_single_row",
    )
    if len(stalls) < required_spaces:
        parallel_stalls = _fill_parallel_row(
            polygon,
            origin=origin,
            u=u,
            v=v,
            length=length,
            depth=depth,
            stall_length=DEFAULT_PARALLEL_STALL_LENGTH_M,
            required_spaces=required_spaces,
            accessible_spaces=accessible_spaces,
            mode="road_as_aisle_parallel",
        )
        if len(parallel_stalls) > len(stalls):
            stalls = parallel_stalls
            depth_rows = 1
    if len(stalls) < required_spaces:
        compact_parallel_stalls = _fill_parallel_row(
            polygon,
            origin=origin,
            u=u,
            v=v,
            length=length,
            depth=depth,
            stall_length=RESIDENTIAL_UNDIVIDED_ROAD_PARALLEL_LENGTH_M,
            required_spaces=required_spaces,
            accessible_spaces=accessible_spaces,
            mode="road_as_aisle_residential_parallel_authority_review",
        )
        if len(compact_parallel_stalls) > len(stalls):
            stalls = compact_parallel_stalls
            depth_rows = 1
    return _layout_result(
        status="pass" if len(stalls) >= required_spaces else "fail",
        strategy="ground_surface",
        placement_mode=(
            "road_as_aisle_residential_parallel_authority_review"
            if stalls and stalls[0].get("mode") == "road_as_aisle_residential_parallel_authority_review"
            else
            "road_as_aisle_parallel"
            if stalls and stalls[0].get("mode") == "road_as_aisle_parallel"
            else "road_as_aisle_tandem"
            if depth_rows > 1
            else "road_as_aisle_single_row"
        ),
        required_spaces=required_spaces,
        accessible_spaces=accessible_spaces,
        stalls=stalls,
        reason=None if len(stalls) >= required_spaces else "insufficient_frontage_or_depth",
    )


def _place_internal_90_degree_stalls(
    polygon: Polygon,
    *,
    required_spaces: int,
    accessible_spaces: int,
    strategy: str,
    drive_polygon: Polygon | None = None,
) -> dict[str, Any]:
    origin, u, v, length, depth = _oriented_frame(polygon)
    row_offsets: list[float] = []
    if depth >= DEFAULT_STALL_LENGTH_M * 2 + DEFAULT_AISLE_WIDTH_M:
        row_offsets = [0.0, DEFAULT_STALL_LENGTH_M + DEFAULT_AISLE_WIDTH_M]
        mode = "internal_double_loaded_90"
    elif depth >= DEFAULT_STALL_LENGTH_M + DEFAULT_AISLE_WIDTH_M:
        row_offsets = [0.0]
        mode = "internal_single_loaded_90"
    else:
        mode = "internal_90"

    stalls = _fill_rows(
        polygon,
        origin=origin,
        u=u,
        v=v,
        length=length,
        row_depth=DEFAULT_STALL_LENGTH_M,
        row_offsets=row_offsets,
        required_spaces=required_spaces,
        accessible_spaces=accessible_spaces,
        mode=mode,
    )
    drive_cells = []
    drive_area = drive_polygon if drive_polygon is not None else polygon
    if stalls and row_offsets:
        # The exact unrounded row intervals define the full shared 6 m aisle.
        # Check the same full polygon that the result's operability owner sees;
        # never clip it around an obstruction and retain the width claim.
        intervals = [(stall.pop('_frame_start_u_m'), stall['width_m']) for stall in stalls]
        start = min(offset for offset, width in intervals)
        stop = max(offset + width for offset, width in intervals)
        drive_cells = [_rect_from_frame(origin=origin, u=u, v=v,
            start_u=start, start_v=DEFAULT_STALL_LENGTH_M,
            width_u=stop-start, width_v=DEFAULT_AISLE_WIDTH_M)]
    drive_satisfied = all(drive_area.buffer(1e-7).contains(cell) for cell in drive_cells)
    result = _layout_result(
        status="pass" if len(stalls) >= required_spaces else "fail",
        strategy=strategy,
        placement_mode=mode,
        required_spaces=required_spaces,
        accessible_spaces=accessible_spaces,
        stalls=stalls,
        drive_cells=drive_cells,
        reason=None if len(stalls) >= required_spaces else "insufficient_internal_module_capacity",
    )
    result['drive_geometry_basis'] = 'existing_internal_module_frame; full_aisle_checked_before_ranking'
    result['drive_envelope_check'] = {'satisfied':drive_satisfied,
        'outside_envelope_m2':sum(cell.difference(drive_area).area for cell in drive_cells),
        'basis':'same polygon.buffer(1e-7).contains as existing stall and grid drive checks'}
    if not drive_satisfied:
        result['status'] = 'fail'
        result['reason'] = 'internal_aisle_outside_envelope'
        result['drive_aisle_clearance']['status'] = 'fail'
        result['turning_clearance']['status'] = 'needs_swept_path_review'
        result['turning_clearance']['reason'] = 'internal_aisle_outside_envelope'
    return result


def _place_single_row_aisle_review_stalls(
    polygon: Polygon,
    *,
    required_spaces: int,
    accessible_spaces: int,
    strategy: str,
) -> dict[str, Any]:
    origin, u, v, length, depth = _oriented_frame(polygon)
    if depth < DEFAULT_STALL_LENGTH_M:
        return _layout_result(
            status="fail",
            strategy=strategy,
            placement_mode="single_row_aisle_review",
            required_spaces=required_spaces,
            accessible_spaces=accessible_spaces,
            stalls=[],
            reason="insufficient_depth_for_single_row_stall",
        )

    stalls = _fill_rows(
        polygon,
        origin=origin,
        u=u,
        v=v,
        length=length,
        row_depth=DEFAULT_STALL_LENGTH_M,
        row_offsets=[0.0],
        required_spaces=required_spaces,
        accessible_spaces=accessible_spaces,
        mode="single_row_aisle_review",
    )
    enough = len(stalls) >= required_spaces
    compact = _stalls_are_compact(stalls[:required_spaces], required_spaces=required_spaces)
    return _layout_result(
        status="needs_aisle_review" if enough and compact else "fail",
        strategy=strategy,
        placement_mode="single_row_aisle_review",
        required_spaces=required_spaces,
        accessible_spaces=accessible_spaces,
        stalls=stalls,
        reason=(
            "single_row_stalls_need_drive_aisle_or_road_as_aisle_review"
            if enough and compact else
            "single_row_stalls_are_not_adjacent"
            if enough else "insufficient_single_row_frontage_or_depth"
        ),
    )


def _solve_grid_parking_layout(
    polygon: Polygon,
    *,
    drive_polygon: Polygon | None = None,
    required_spaces: int,
    accessible_spaces: int,
    strategy: str,
    road_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    drive_area = drive_polygon or polygon
    origin, u, v, length, depth = _oriented_frame(polygon)
    candidates: list[dict[str, Any]] = []
    candidates.extend(_grid_stall_candidates(
        polygon,
        origin=origin,
        u=u,
        v=v,
        length=length,
        depth=depth,
        drive_area=drive_area,
        required_accessible=accessible_spaces,
        orientation="u",
    ))
    candidates.extend(_grid_stall_candidates(
        polygon,
        origin=origin,
        u=v,
        v=u,
        length=depth,
        depth=length,
        drive_area=drive_area,
        required_accessible=accessible_spaces,
        orientation="v",
    ))
    access_edges = _road_access_edges(road_context)
    if not access_edges:
        access_edges = _site_boundary_edges(drive_area)
    selected = _select_compact_grid_candidates(
        candidates,
        required_spaces=required_spaces,
        accessible_spaces=accessible_spaces,
        access_edges=access_edges,
    )
    drive_polygons = _connect_grid_row_aisles(selected[:required_spaces], drive_area)

    stalls = []
    for index, item in enumerate(selected[:required_spaces], start=1):
        stalls.append({
            "stall_id": f"P{index:02d}",
            "type": item["type"],
            "width_m": item["width_m"],
            "length_m": item["length_m"],
            "row": item["row"],
            "mode": "grid_connected_90",
            "orientation": item["orientation"],
            "polygon": _polygon_coordinates(item["stall_polygon"]),
        })
    connected = _drive_components_connected(drive_polygons)
    access = _drive_entrance_access(drive_polygons, drive_area, road_context=road_context)
    entrance_verified = access["connected"] and access["method"] == "road_frontage_geometry"
    enough = len(stalls) >= required_spaces
    accessible_enough = sum(1 for stall in stalls if stall["type"] == "accessible") >= accessible_spaces
    status = (
        "pass"
        if enough and accessible_enough and connected and entrance_verified
        else "needs_drive_connectivity_review"
        if enough and accessible_enough
        else "fail"
    )
    result = _layout_result(
        status=status,
        strategy=strategy,
        placement_mode="grid_connected_90",
        required_spaces=required_spaces,
        accessible_spaces=accessible_spaces,
        stalls=stalls,
        drive_cells=drive_polygons[:required_spaces],
        entrance_access=access,
        reason=None if status == "pass" else (
            "grid_solver_insufficient_accessible_stall_candidates"
            if enough and not accessible_enough else
            "grid_drive_cells_need_entrance_connection_review"
            if enough else "grid_solver_insufficient_stall_candidates"
        ),
    )
    result["grid_solver"] = {
        "schema_version": "arr.maas.parking_grid_solver.v0",
        "cell_step_m": GRID_SOLVER_STEP_M,
        "candidate_stalls": len(candidates),
        "selected_stalls": len(stalls),
        "drive_components_connected": connected,
        "entrance_connected": access["connected"],
        "entrance_verified": entrance_verified,
        "entrance_connection_method": access["method"],
        "entrance_connection_type": access["connection_type"],
        "entrance_edge_count": access["edge_count"],
        "entrance_min_distance_m": access["min_distance_m"],
        "entrance_connector_length_m": access["connector_length_m"],
        "entrance_connector_width_m": access["connector_width_m"],
        "entrance_connector_polygon": (
            _polygon_coordinates(access["connector_polygon"])
            if isinstance(access.get("connector_polygon"), Polygon) and not access["connector_polygon"].is_empty
            else None
        ),
        "drive_cells": [_polygon_coordinates(poly) for poly in drive_polygons[:required_spaces]],
        "variable_mapping": {
            "x": "selected stall candidates",
            "y": "drive aisle cells adjacent to selected stalls",
            "connectivity": "drive cells must touch into one component and connect to road/frontage or site access boundary",
        },
    }
    result["limitations"] = [
        "grid_solver_first_feasible_not_global_mip_optimum",
        "does_not_model_swept_path_columns_or_core_obstructions",
    ]
    if access["method"] == "site_boundary_inferred":
        result["limitations"].append("entrance_edge_inferred_from_site_boundary_without_road_frontage_geometry")
    return result


def _solve_connected_parallel_parking_layout(
    polygon: Polygon,
    *,
    drive_polygon: Polygon | None = None,
    required_spaces: int,
    strategy: str,
    road_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Place a compact internal parallel row with its own 3 m aisle."""

    drive_area = drive_polygon or polygon
    candidates: list[dict[str, Any]] = []
    for (
        frame_origin,
        frame_u,
        frame_v,
        frame_length,
        frame_depth,
        orientation,
    ) in _parallel_candidate_frames(polygon, road_context=road_context):
        for side in (1, -1):
            row = 1 if side == 1 else 2
            stall_start_v = (
                0.0
                if side == 1
                else max(0.0, frame_depth - DEFAULT_PARALLEL_STALL_WIDTH_M)
            )
            drive_start_v = (
                DEFAULT_PARALLEL_STALL_WIDTH_M
                if side == 1
                else max(
                    0.0,
                    stall_start_v - DEFAULT_PARALLEL_AISLE_WIDTH_M,
                )
            )
            cursor = 0.0
            while cursor + DEFAULT_PARALLEL_STALL_LENGTH_M <= frame_length + 1e-9:
                stall_polygon = _rect_from_frame(
                    origin=frame_origin,
                    u=frame_u,
                    v=frame_v,
                    start_u=cursor,
                    start_v=stall_start_v,
                    width_u=DEFAULT_PARALLEL_STALL_LENGTH_M,
                    width_v=DEFAULT_PARALLEL_STALL_WIDTH_M,
                )
                aisle_polygon = _rect_from_frame(
                    origin=frame_origin,
                    u=frame_u,
                    v=frame_v,
                    start_u=cursor,
                    start_v=drive_start_v,
                    width_u=DEFAULT_PARALLEL_STALL_LENGTH_M,
                    width_v=DEFAULT_PARALLEL_AISLE_WIDTH_M,
                )
                if (
                    polygon.buffer(1e-7).contains(stall_polygon)
                    and drive_area.buffer(1e-7).contains(aisle_polygon)
                ):
                    candidates.append({
                        "type": "standard",
                        "width_m": DEFAULT_PARALLEL_STALL_WIDTH_M,
                        "length_m": DEFAULT_PARALLEL_STALL_LENGTH_M,
                        "row": row,
                        "orientation": f"parallel_{orientation}",
                        "start_u": round(cursor, 6),
                        "start_v": round(stall_start_v, 6),
                        "stall_polygon": stall_polygon,
                        "drive_polygon": aisle_polygon,
                    })
                cursor += GRID_SOLVER_STEP_M

    access_edges = _road_access_edges(road_context) or _site_boundary_edges(drive_area)
    selected = _select_compact_grid_candidates(
        candidates,
        required_spaces=required_spaces,
        accessible_spaces=0,
        access_edges=access_edges,
    )
    selected = selected[:required_spaces]
    drive_cells = [candidate["drive_polygon"] for candidate in selected]
    stalls = [
        {
            "stall_id": f"P{index:02d}",
            "type": "standard",
            "width_m": candidate["width_m"],
            "length_m": candidate["length_m"],
            "row": candidate["row"],
            "mode": "grid_connected_parallel",
            "orientation": candidate["orientation"],
            "polygon": _polygon_coordinates(candidate["stall_polygon"]),
        }
        for index, candidate in enumerate(selected, start=1)
    ]
    connected = _drive_components_connected(drive_cells)
    access = _drive_entrance_access(
        drive_cells,
        drive_area,
        road_context=road_context,
    )
    entrance_verified = access["connected"] and access["method"] == "road_frontage_geometry"
    enough = len(stalls) >= required_spaces
    status = (
        "pass"
        if enough and connected and entrance_verified
        else "needs_drive_connectivity_review"
        if enough
        else "fail"
    )
    result = _layout_result(
        status=status,
        strategy=strategy,
        placement_mode="grid_connected_parallel",
        required_spaces=required_spaces,
        accessible_spaces=0,
        stalls=stalls,
        drive_cells=drive_cells,
        entrance_access=access,
        reason=(
            None
            if status == "pass"
            else "parallel_drive_cells_need_entrance_connection_review"
            if enough
            else "parallel_solver_insufficient_stall_candidates"
        ),
    )
    result["grid_solver"] = {
        "schema_version": "arr.maas.parking_grid_solver.v1",
        "module": "connected_internal_parallel",
        "cell_step_m": GRID_SOLVER_STEP_M,
        "candidate_stalls": len(candidates),
        "selected_stalls": len(stalls),
        "drive_components_connected": connected,
        "entrance_connected": access["connected"],
        "entrance_verified": entrance_verified,
        "entrance_connection_method": access["method"],
        "entrance_connection_type": access["connection_type"],
        "entrance_edge_count": access["edge_count"],
        "entrance_min_distance_m": access["min_distance_m"],
        "drive_cells": [_polygon_coordinates(cell) for cell in drive_cells],
    }
    return result


def _parallel_candidate_frames(
    polygon: Polygon,
    *,
    road_context: dict[str, Any] | None,
) -> list[
    tuple[
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
        float,
        float,
        str,
    ]
]:
    """Return principal and real-boundary frames for parallel modules."""

    origin, u, v, length, depth = _oriented_frame(polygon)
    frames = [
        (origin, u, v, length, depth, "principal_u"),
        (origin, v, u, depth, length, "principal_v"),
    ]
    representative = polygon.representative_point()
    lines = [*_road_access_edges(road_context)]
    exterior = tuple(polygon.exterior.coords)
    lines.extend(
        LineString((exterior[index], exterior[index + 1]))
        for index in range(len(exterior) - 1)
    )
    seen: set[tuple[float, float, float, float]] = set()
    all_outer_points = tuple(
        (float(x), float(y))
        for x, y in tuple(polygon.exterior.coords)[:-1]
    )
    for index, line in enumerate(lines):
        coordinates = tuple(line.coords)
        if len(coordinates) < 2:
            continue
        p0 = coordinates[0]
        p1 = coordinates[-1]
        edge_length = math.dist(p0, p1)
        if edge_length + 1e-9 < DEFAULT_PARALLEL_STALL_LENGTH_M:
            continue
        ux = (float(p1[0]) - float(p0[0])) / edge_length
        uy = (float(p1[1]) - float(p0[1])) / edge_length
        vx, vy = -uy, ux
        toward = (
            (float(representative.x) - float(p0[0])) * vx
            + (float(representative.y) - float(p0[1])) * vy
        )
        if toward < 0.0:
            vx, vy = -vx, -vy
        projected_depth = max(
            0.0,
            max(
                (x - float(p0[0])) * vx + (y - float(p0[1])) * vy
                for x, y in all_outer_points
            ),
        )
        key = (
            round(float(p0[0]), 6),
            round(float(p0[1]), 6),
            round(ux, 6),
            round(uy, 6),
        )
        if key in seen:
            continue
        seen.add(key)
        frames.append((
            (float(p0[0]), float(p0[1])),
            (ux, uy),
            (vx, vy),
            edge_length,
            projected_depth,
            f"boundary_{index}",
        ))
    return frames


def _grid_stall_candidates(
    polygon: Polygon,
    *,
    origin: tuple[float, float],
    u: tuple[float, float],
    v: tuple[float, float],
    length: float,
    depth: float,
    drive_area: Polygon,
    required_accessible: int,
    orientation: str,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    widths = [("accessible", DEFAULT_ACCESSIBLE_WIDTH_M)] if required_accessible > 0 else []
    widths.append(("standard", DEFAULT_STALL_WIDTH_M))
    row_index = 0
    for side in (1, -1):
        row_index += 1
        stall_start_v = 0.0 if side == 1 else max(0.0, depth - DEFAULT_STALL_LENGTH_M)
        drive_start_v = DEFAULT_STALL_LENGTH_M if side == 1 else max(0.0, stall_start_v - DEFAULT_AISLE_WIDTH_M)
        for stall_type, stall_width in widths:
            cursor = 0.0
            while cursor + stall_width <= length + 1e-9:
                stall_polygon = _rect_from_frame(
                    origin=origin,
                    u=u,
                    v=v,
                    start_u=cursor,
                    start_v=stall_start_v,
                    width_u=stall_width,
                    width_v=DEFAULT_STALL_LENGTH_M,
                )
                drive_polygon = _rect_from_frame(
                    origin=origin,
                    u=u,
                    v=v,
                    start_u=cursor,
                    start_v=drive_start_v,
                    width_u=stall_width,
                    width_v=DEFAULT_AISLE_WIDTH_M,
                )
                if polygon.buffer(1e-7).contains(stall_polygon) and drive_area.buffer(1e-7).contains(drive_polygon):
                    candidates.append({
                        "type": stall_type,
                        "width_m": stall_width,
                        "length_m": DEFAULT_STALL_LENGTH_M,
                        "row": row_index,
                        "orientation": orientation,
                        "start_u": round(cursor, 6),
                        "start_v": round(stall_start_v, 6),
                        "stall_polygon": stall_polygon,
                        "drive_polygon": drive_polygon,
                    })
                cursor += GRID_SOLVER_STEP_M
    return candidates


def _grid_candidate_sort_key(candidate: dict[str, Any]) -> tuple[int, float, float]:
    centroid = candidate["stall_polygon"].centroid
    type_rank = 0 if candidate["type"] == "accessible" else 1
    return type_rank, round(centroid.y, 3), round(centroid.x, 3)


def _connect_grid_row_aisles(
    selected: list[dict[str, Any]], drive_area: Polygon | MultiPolygon,
) -> list[Polygon]:
    """Pave full-width gaps between neighboring aisle cells in the same row.

    Keep one aisle polygon per stall so downstream frontage checks retain their
    index correspondence. The convex corridor is actual generated material,
    admitted only inside the drive envelope and clear of every selected stall.
    This does not infer a connection between unrelated rows or around obstacles.
    """
    cells = [candidate["drive_polygon"] for candidate in selected]
    rows: dict[tuple[Any, ...], list[int]] = {}
    for index, candidate in enumerate(selected):
        rows.setdefault((candidate.get("orientation"), candidate.get("row"),
                         candidate.get("start_v")), []).append(index)
    for indices in rows.values():
        indices.sort(key=lambda index: float(selected[index].get("start_u") or 0.0))
        for left, right in zip(indices, indices[1:]):
            a = selected[left]["drive_polygon"]
            b = selected[right]["drive_polygon"]
            if a.intersects(b):
                continue
            corridor = a.union(b).convex_hull
            # Use the same containment tolerance as candidate construction;
            # never change the connectivity checker to hide missing pavement.
            if not drive_area.buffer(1e-7).covers(corridor):
                continue
            if any(_stall_polygons_overlap(corridor, item["stall_polygon"]) for item in selected):
                continue
            cells[left] = cells[left].union(corridor)
    return cells


def _select_compact_grid_candidates(
    candidates: list[dict[str, Any]],
    *,
    required_spaces: int,
    accessible_spaces: int,
    access_edges: list[LineString] | None = None,
) -> list[dict[str, Any]]:
    ordered = sorted(candidates, key=_grid_candidate_sort_key)
    if required_spaces <= 0 or not ordered:
        return []
    contiguous_row = _select_contiguous_row_candidates(
        ordered,
        required_spaces=required_spaces,
        accessible_spaces=accessible_spaces,
        access_edges=access_edges,
    )
    if len(contiguous_row) >= required_spaces:
        return contiguous_row[:required_spaces]

    exact_small_group = _select_exact_small_grid_group(
        ordered,
        required_spaces=required_spaces,
        accessible_spaces=accessible_spaces,
        access_edges=access_edges,
    )
    if len(exact_small_group) >= required_spaces:
        return exact_small_group[:required_spaces]

    # Preserve feasible partial searches too: an unmet request is exactly when
    # throwing away a better partial count conceals available capacity.
    def score_group(group: list[dict[str, Any]]) -> tuple[Any, ...]:
        return _grid_group_score(
            group, required_spaces=required_spaces,
            accessible_spaces=accessible_spaces, access_edges=access_edges,
        )
    # Vectorized GEOS keeps the exact area gate; bitsets preserve every seed
    # and stable tie while avoiding millions of repeated Python pair scans.
    import numpy as np
    import shapely

    polygons = np.asarray([item["stall_polygon"] for item in ordered], dtype=object)
    centroids = shapely.centroid(polygons)
    sort_keys = [_grid_candidate_sort_key(item) for item in ordered]
    blocked_rows: dict[int, int] = {}
    distance_rows: dict[int, Any] = {}
    accessible_mask = sum(1 << i for i, item in enumerate(ordered) if item["type"] == "accessible")
    all_candidates = (1 << len(ordered)) - 1

    def blocked_row(index: int) -> int:
        if index not in blocked_rows:
            hit = np.flatnonzero(shapely.intersects(polygons[index], polygons))
            conflicts = hit[shapely.area(shapely.intersection(polygons[index], polygons[hit])) > 1e-6]
            mask = sum(1 << int(i) for i in conflicts)
            # Preserve dict equality for duplicate and tiny-area candidates.
            for other, candidate in enumerate(ordered):
                if candidate == ordered[index]:
                    mask |= 1 << other
            blocked_rows[index] = mask
        return blocked_rows[index]

    def distances(index: int):
        if index not in distance_rows:
            distance_rows[index] = shapely.distance(centroids[index], centroids)
        return distance_rows[index]

    best = max((contiguous_row, exact_small_group), key=score_group)
    best_score = score_group(best)
    for seed_index, seed in enumerate(ordered):
        if accessible_spaces > 0 and seed["type"] != "accessible":
            continue
        group: list[dict[str, Any]] = []
        available = all_candidates
        nearest = np.full(len(ordered), np.inf)
        orientations = set()
        rows = set()
        remaining_accessible = max(0, min(accessible_spaces, required_spaces))

        def add(index: int) -> bool:
            nonlocal remaining_accessible, available, nearest
            candidate = ordered[index]
            if not (available & (1 << index)):
                return False
            if remaining_accessible > 0 and candidate["type"] != "accessible":
                return False
            group.append(candidate)
            available &= ~blocked_row(index)
            nearest = np.minimum(nearest, distances(index))
            orientations.add(candidate["orientation"])
            rows.add((candidate["orientation"], candidate["row"]))
            if candidate["type"] == "accessible":
                remaining_accessible -= 1
            return True

        add(seed_index)
        while len(group) < required_spaces:
            eligible_bits = available & (accessible_mask if remaining_accessible > 0 else all_candidates)
            eligible = []
            while eligible_bits:
                bit = eligible_bits & -eligible_bits
                eligible.append(bit.bit_length() - 1)
                eligible_bits ^= bit
            if not eligible:
                break
            # min keeps the first tied entry, matching stable sort then [0].
            chosen = min(eligible, key=lambda index: (
                0 if remaining_accessible > 0 or ordered[index]["type"] == "standard" else 1,
                (0 if ordered[index]["orientation"] in orientations else 1,
                 0 if (ordered[index]["orientation"], ordered[index]["row"]) in rows else 1,
                 round(float(nearest[index]), 3), sort_keys[index]),
            ))
            if not add(chosen):
                break

        score = _grid_group_score(
            group,
            required_spaces=required_spaces,
            accessible_spaces=accessible_spaces,
            access_edges=access_edges,
        )
        if best_score is None or score > best_score:
            best = group
            best_score = score

    if len(best) >= required_spaces:
        return best[:required_spaces]

    selected: list[dict[str, Any]] = []
    occupied: list[Polygon] = []
    remaining_accessible = max(0, min(accessible_spaces, required_spaces))
    for candidate in ordered:
        if len(selected) >= required_spaces:
            break
        if remaining_accessible > 0 and candidate["type"] != "accessible":
            continue
        if any(_stall_polygons_overlap(candidate["stall_polygon"], existing) for existing in occupied):
            continue
        selected.append(candidate)
        occupied.append(candidate["stall_polygon"])
        if candidate["type"] == "accessible":
            remaining_accessible -= 1
    if len(selected) < required_spaces:
        for candidate in ordered:
            if len(selected) >= required_spaces:
                break
            if candidate in selected:
                continue
            if any(_stall_polygons_overlap(candidate["stall_polygon"], existing) for existing in occupied):
                continue
            selected.append(candidate)
            occupied.append(candidate["stall_polygon"])
    return max((best, selected), key=score_group)[:required_spaces]


def _select_exact_small_grid_group(
    candidates: list[dict[str, Any]],
    *,
    required_spaces: int,
    accessible_spaces: int,
    access_edges: list[LineString] | None = None,
) -> list[dict[str, Any]]:
    """Exhaustively select a compact small-lot group.

    This mirrors the MIP objective order at a tiny scale: satisfy the stall
    count, prevent overlaps, then prefer row-contiguous or adjacent/tandem
    clusters before weaker scattered layouts.
    """
    if required_spaces <= 1 or required_spaces > SMALL_ATTACHED_PARKING_MAX_SPACES:
        return []
    # Exhaustive search is useful only while the combination space is truly
    # small.  The previous ``len(candidates) <= 90`` guard still allowed
    # 90C5 (43,949,268) groups and made one small-lot parking check take tens
    # of seconds.  Above this deterministic budget the caller continues with
    # the bounded seed/greedy selector below.
    combination_budget = 5_000
    try:
        combination_count = math.comb(len(candidates), required_spaces)
    except (TypeError, ValueError):
        return []
    if combination_count > combination_budget:
        return []
    best: list[dict[str, Any]] = []
    best_score: tuple[Any, ...] | None = None
    for combo in combinations(candidates, required_spaces):
        group = list(combo)
        if sum(1 for candidate in group if candidate["type"] == "accessible") < accessible_spaces:
            continue
        if _grid_group_has_overlaps(group):
            continue
        adjacency = _candidate_group_adjacency(group)
        score = (
            1 if adjacency["row_contiguous_ok"] else 0,
            1 if adjacency["cluster_contiguous_ok"] else 0,
            -adjacency["connected_components"],
            adjacency["touching_pairs"],
            *_grid_group_score(
                group,
                required_spaces=required_spaces,
                accessible_spaces=accessible_spaces,
                access_edges=access_edges,
            ),
        )
        if best_score is None or score > best_score:
            best = group
            best_score = score
    return best


def _grid_group_has_overlaps(group: list[dict[str, Any]]) -> bool:
    for index, candidate in enumerate(group):
        for other in group[index + 1:]:
            if _stall_polygons_overlap(candidate["stall_polygon"], other["stall_polygon"]):
                return True
    return False


def _candidate_group_adjacency(group: list[dict[str, Any]]) -> dict[str, Any]:
    stalls = []
    for index, candidate in enumerate(group, start=1):
        stalls.append({
            "stall_id": f"C{index:02d}",
            "row": candidate.get("row"),
            "polygon": _polygon_coordinates(candidate["stall_polygon"]),
        })
    adjacency = _stall_adjacency_metrics(stalls)
    return {
        "touching_pairs": int(adjacency.get("touching_pairs") or 0),
        "connected_components": int(adjacency.get("connected_components") or len(group)),
        "row_contiguous_ok": bool(adjacency.get("row_contiguous_ok")),
        "cluster_contiguous_ok": bool(adjacency.get("cluster_contiguous_ok")),
    }


def _stall_polygons_overlap(a: Polygon, b: Polygon) -> bool:
    return a.intersection(b).area > 1e-6


def _select_contiguous_row_candidates(
    candidates: list[dict[str, Any]],
    *,
    required_spaces: int,
    accessible_spaces: int,
    access_edges: list[LineString] | None = None,
) -> list[dict[str, Any]]:
    best: list[dict[str, Any]] = []
    best_score: tuple[Any, ...] | None = None
    groups: dict[tuple[str, int, float], list[dict[str, Any]]] = {}
    for candidate in candidates:
        groups.setdefault(
            (
                str(candidate.get("orientation")),
                int(candidate.get("row") or 0),
                float(candidate.get("start_v") or 0.0),
            ),
            [],
        ).append(candidate)

    for group in groups.values():
        ordered = sorted(group, key=lambda item: (float(item.get("start_u") or 0.0), _grid_candidate_sort_key(item)))
        for start_index in range(len(ordered)):
            selected: list[dict[str, Any]] = []
            occupied: list[Polygon] = []
            cursor_u: float | None = None
            remaining_accessible = max(0, min(accessible_spaces, required_spaces))
            for candidate in ordered[start_index:]:
                if len(selected) >= required_spaces:
                    break
                if remaining_accessible > 0 and candidate["type"] != "accessible":
                    continue
                start_u = float(candidate.get("start_u") or 0.0)
                if cursor_u is not None:
                    if start_u < cursor_u - GRID_SOLVER_STEP_M * 0.55:
                        continue
                    if start_u > cursor_u + GRID_SOLVER_STEP_M * 0.55:
                        break
                if any(_stall_polygons_overlap(candidate["stall_polygon"], existing) for existing in occupied):
                    continue
                if selected and selected[-1]["stall_polygon"].distance(candidate["stall_polygon"]) > 0.05:
                    break
                selected.append(candidate)
                occupied.append(candidate["stall_polygon"])
                cursor_u = start_u + float(candidate["width_m"])
                if candidate["type"] == "accessible":
                    remaining_accessible -= 1
            score = _grid_group_score(
                selected,
                required_spaces=required_spaces,
                accessible_spaces=accessible_spaces,
                access_edges=access_edges,
            )
            if best_score is None or score > best_score:
                best = selected
                best_score = score
    return best[:required_spaces]


def _grid_candidate_compact_sort_key(
    candidate: dict[str, Any],
    group: list[dict[str, Any]],
) -> tuple[int, int, float, tuple[int, float, float]]:
    if not group:
        return 0, 0, 0.0, _grid_candidate_sort_key(candidate)
    same_orientation = any(candidate["orientation"] == item["orientation"] for item in group)
    same_row = any(
        candidate["orientation"] == item["orientation"] and candidate["row"] == item["row"]
        for item in group
    )
    distance = min(
        candidate["stall_polygon"].centroid.distance(item["stall_polygon"].centroid)
        for item in group
    )
    return (
        0 if same_orientation else 1,
        0 if same_row else 1,
        round(float(distance), 3),
        _grid_candidate_sort_key(candidate),
    )


def _grid_group_score(
    group: list[dict[str, Any]],
    *,
    required_spaces: int,
    accessible_spaces: int,
    access_edges: list[LineString] | None = None,
) -> tuple[Any, ...]:
    if not group:
        return (0, 0, 0, 0, 0, 0, float("-inf"), 0, float("-inf"), float("-inf"))
    provided_accessible = sum(1 for candidate in group if candidate["type"] == "accessible")
    enough = len(group) >= required_spaces
    accessible_enough = provided_accessible >= accessible_spaces
    drive_polygons = [candidate["drive_polygon"] for candidate in group]
    connected = _drive_components_connected(drive_polygons)
    access = _drive_access_score(drive_polygons, access_edges or [])
    frontage_connected = _grid_group_frontage_connected_count(group)
    row_groups = len({(candidate["orientation"], candidate["row"]) for candidate in group})
    centroids = [candidate["stall_polygon"].centroid for candidate in group]
    max_distance = 0.0
    for i, a in enumerate(centroids):
        for b in centroids[i + 1:]:
            max_distance = max(max_distance, float(a.distance(b)))
    return (
        1 if enough and accessible_enough else 0,
        1 if accessible_enough else 0,
        min(len(group), required_spaces),
        1 if connected else 0,
        1 if access["connected"] else 0,
        frontage_connected,
        -round(float(access["min_distance_m"]), 3),
        -row_groups,
        -round(max_distance, 3),
        -round(float(group[0]["stall_polygon"].centroid.distance(group[-1]["stall_polygon"].centroid)), 3),
    )


def _grid_group_frontage_connected_count(group: list[dict[str, Any]]) -> int:
    if not group:
        return 0
    drive_union = group[0]["drive_polygon"]
    for candidate in group[1:]:
        drive_union = drive_union.union(candidate["drive_polygon"])
    connected_count = 0
    for candidate in group:
        try:
            width = float(candidate.get("width_m") or DEFAULT_STALL_WIDTH_M)
        except Exception:
            width = DEFAULT_STALL_WIDTH_M
        required_frontage = max(2.0, width * 0.75)
        try:
            frontage_m = float(candidate["stall_polygon"].boundary.intersection(drive_union).length)
        except Exception:
            frontage_m = 0.0
        if frontage_m + 1e-7 >= required_frontage:
            connected_count += 1
    return connected_count


def _drive_components_connected(drive_polygons: list[Polygon]) -> bool:
    if len(drive_polygons) <= 1:
        return bool(drive_polygons)
    seen = {0}
    stack = [0]
    while stack:
        idx = stack.pop()
        current = drive_polygons[idx].buffer(1e-7)
        for other_idx, other in enumerate(drive_polygons):
            if other_idx in seen:
                continue
            if current.intersects(other.buffer(1e-7)):
                seen.add(other_idx)
                stack.append(other_idx)
    return len(seen) == len(drive_polygons)


def _stalls_are_compact(stalls: list[dict[str, Any]], *, required_spaces: int) -> bool:
    if required_spaces <= 1:
        return len(stalls) >= required_spaces
    if len(stalls) < required_spaces:
        return False
    centroids = [Polygon(stall["polygon"]).centroid for stall in stalls[:required_spaces]]
    max_distance = 0.0
    for i, a in enumerate(centroids):
        for b in centroids[i + 1:]:
            max_distance = max(max_distance, float(a.distance(b)))
    allowed_span = DEFAULT_STALL_WIDTH_M * max(1, required_spaces) + GRID_SOLVER_STEP_M
    return max_distance <= allowed_span


def _drive_entrance_access(
    drive_polygons: list[Polygon],
    drive_area: Polygon,
    *,
    road_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not drive_polygons:
        return {
            "connected": False,
            "method": "missing_drive_cells",
            "connection_type": "none",
            "edge_count": 0,
            "min_distance_m": None,
            "connector_length_m": None,
            "connector_width_m": None,
            "connector_polygon": None,
        }
    access_edges = _road_access_edges(road_context)
    method = "road_frontage_geometry" if access_edges else "site_boundary_inferred"
    if not access_edges:
        access_edges = _site_boundary_edges(drive_area)
    if not access_edges:
        return {
            "connected": False,
            "method": "missing_access_edge",
            "connection_type": "none",
            "edge_count": 0,
            "min_distance_m": None,
            "connector_length_m": None,
            "connector_width_m": None,
            "connector_polygon": None,
        }
    access = _drive_access_score(drive_polygons, access_edges)
    connection_type = "direct" if access["connected"] else "none"
    connector_length_m: float | None = None
    if not access["connected"]:
        connector = _drive_access_connector(drive_polygons, access_edges, drive_area)
        if connector["connected"]:
            access = {"connected": True, "min_distance_m": access["min_distance_m"]}
            connection_type = "site_connector_v1"
            connector_length_m = connector["length_m"]
            connector_width_m = connector.get("width_m")
            connector_polygon = connector.get("polygon")
        else:
            connector_width_m = None
            connector_polygon = None
    else:
        connector_width_m = None
        connector_polygon = None
    return {
        "connected": access["connected"],
        "method": method,
        "connection_type": connection_type,
        "edge_count": len(access_edges),
        "min_distance_m": round(float(access["min_distance_m"]), 3),
        "connector_length_m": round(float(connector_length_m), 3) if connector_length_m is not None else None,
        "connector_width_m": round(float(connector_width_m), 3) if connector_width_m is not None else None,
        "connector_polygon": connector_polygon,
    }


def _drive_access_score(drive_polygons: list[Polygon], access_edges: list[LineString]) -> dict[str, Any]:
    if not drive_polygons or not access_edges:
        return {"connected": False, "min_distance_m": float("inf")}
    min_distance = min(
        drive.distance(edge)
        for drive in drive_polygons
        for edge in access_edges
    )
    access_tolerance = max(0.25, GRID_SOLVER_STEP_M + 1e-7)
    connected = any(
        drive.buffer(1e-7).intersects(edge.buffer(access_tolerance))
        for drive in drive_polygons
        for edge in access_edges
    )
    return {"connected": connected, "min_distance_m": float(min_distance)}


def _drive_access_connector(
    drive_polygons: list[Polygon],
    access_edges: list[LineString],
    drive_area: Polygon,
) -> dict[str, Any]:
    if not drive_polygons or not access_edges or not isinstance(drive_area, Polygon) or drive_area.is_empty:
        return {"connected": False, "length_m": None}
    best_line: LineString | None = None
    best_length = float("inf")
    for drive in drive_polygons:
        for edge in access_edges:
            try:
                a, b = nearest_points(drive, edge)
                line = LineString([(a.x, a.y), (b.x, b.y)])
            except Exception:
                continue
            if line.is_empty:
                continue
            length = float(line.length)
            if length < best_length:
                best_line = line
                best_length = length
    if best_line is None:
        return {"connected": False, "length_m": None}
    if best_length <= max(0.25, GRID_SOLVER_STEP_M + 1e-7):
        return {"connected": True, "length_m": best_length}
    half_width = ATTACHED_PARKING_ENTRANCE_WIDTH_M * 0.5
    connector_corridor = best_line.buffer(half_width, cap_style=2, join_style=2)
    covered_by_site = drive_area.buffer(1e-7).covers(connector_corridor)
    return {
        "connected": bool(covered_by_site),
        "length_m": best_length if covered_by_site else None,
        "width_m": ATTACHED_PARKING_ENTRANCE_WIDTH_M if covered_by_site else None,
        "polygon": connector_corridor if covered_by_site else None,
    }


def _road_access_edges(road_context: dict[str, Any] | None) -> list[LineString]:
    if not isinstance(road_context, dict):
        return []
    candidates: list[Any] = []
    for key in ("shared_edge", "sharedEdge", "frontage_geometry", "frontageGeometry", "road_centerline", "roadCenterline"):
        if road_context.get(key):
            candidates.append(road_context.get(key))
    frontages = road_context.get("road_frontages")
    if isinstance(frontages, list):
        for frontage in frontages:
            if not isinstance(frontage, dict):
                continue
            for key in ("shared_edge", "sharedEdge", "frontage_geometry", "frontageGeometry", "road_centerline", "roadCenterline", "geometry"):
                if frontage.get(key):
                    candidates.append(frontage.get(key))
                    break
    edges: list[LineString] = []
    for candidate in candidates:
        geom = _line_geometry(candidate)
        if geom is None:
            continue
        if isinstance(geom, LineString):
            edges.append(geom)
        elif isinstance(geom, MultiLineString):
            edges.extend(line for line in geom.geoms if isinstance(line, LineString) and not line.is_empty)
    return edges


def _line_geometry(value: Any) -> LineString | MultiLineString | None:
    if isinstance(value, list):
        try:
            if len(value) >= 2 and all(isinstance(point, (list, tuple)) and len(point) >= 2 for point in value):
                return LineString([(float(point[0]), float(point[1])) for point in value])
        except Exception:
            return None
    try:
        geom = shape(value) if isinstance(value, dict) else value
    except Exception:
        return None
    if isinstance(geom, (LineString, MultiLineString)) and not geom.is_empty:
        return geom
    if isinstance(geom, Polygon) and not geom.is_empty:
        return LineString(geom.exterior.coords)
    return None


def _site_boundary_edges(drive_area: Polygon) -> list[LineString]:
    if not isinstance(drive_area, Polygon) or drive_area.is_empty:
        return []
    try:
        return [LineString(drive_area.exterior.coords)]
    except Exception:
        return []


def _layout_rank(layout: dict[str, Any]) -> tuple[int, int, int, int, int]:
    status = str(layout.get("status") or "")
    unmet = int(layout.get("unmet_spaces") or 0)
    provided = int(layout.get("provided_spaces") or 0)
    required = int(layout.get("required_spaces") or 0)
    adjacency = layout.get("adjacency") if isinstance(layout.get("adjacency"), dict) else {}
    compact_score = (
        1
        if required <= SMALL_ATTACHED_PARKING_MAX_SPACES
        and (provided <= 1 or adjacency.get("contiguous_ok"))
        else 0
    )
    status_score = (
        4 if status == "pass"
        else 3 if status in {"needs_drive_connectivity_review", "needs_swept_path_review"}
        else 2 if status == "needs_aisle_review"
        else 0
    )
    spatially_clear = layout.get('drive_envelope_check', {}).get('satisfied') is not False
    return (1 if spatially_clear else 0, 1 if unmet == 0 else 0, compact_score, status_score, provided)


def _fill_rows(
    polygon: Polygon,
    *,
    origin: tuple[float, float],
    u: tuple[float, float],
    v: tuple[float, float],
    length: float,
    row_depth: float,
    row_offsets: list[float],
    required_spaces: int,
    accessible_spaces: int,
    mode: str,
) -> list[dict[str, Any]]:
    stalls: list[dict[str, Any]] = []
    remaining_accessible = max(0, min(accessible_spaces, required_spaces))
    for row_index, offset in enumerate(row_offsets):
        cursor = 0.0
        while len(stalls) < required_spaces:
            is_accessible = remaining_accessible > 0
            width = DEFAULT_ACCESSIBLE_WIDTH_M if is_accessible else DEFAULT_STALL_WIDTH_M
            if cursor + width > length + 1e-9:
                break
            stall_polygon = _rect_from_frame(
                origin=origin,
                u=u,
                v=v,
                start_u=cursor,
                start_v=offset,
                width_u=width,
                width_v=row_depth,
            )
            if polygon.buffer(1e-7).contains(stall_polygon):
                stalls.append({
                    "stall_id": f"P{len(stalls) + 1:02d}",
                    "type": "accessible" if is_accessible else "standard",
                    "width_m": width,
                    "length_m": row_depth,
                    "row": row_index + 1,
                    "mode": mode,
                    "polygon": _polygon_coordinates(stall_polygon),
                })
                if mode.startswith('internal_'):
                    stalls[-1]['_frame_start_u_m'] = cursor
                if is_accessible:
                    remaining_accessible -= 1
            cursor += width
    return stalls


def _fill_parallel_row(
    polygon: Polygon,
    *,
    origin: tuple[float, float],
    u: tuple[float, float],
    v: tuple[float, float],
    length: float,
    depth: float,
    stall_length: float,
    required_spaces: int,
    accessible_spaces: int,
    mode: str,
) -> list[dict[str, Any]]:
    if accessible_spaces > 0:
        return []
    best: list[dict[str, Any]] = []
    row_offsets = [0.0]
    far_offset = max(0.0, depth - DEFAULT_PARALLEL_STALL_WIDTH_M)
    if far_offset > 0.05:
        row_offsets.append(far_offset)
    start_offsets = [i * GRID_SOLVER_STEP_M for i in range(max(1, int(stall_length / GRID_SOLVER_STEP_M)))]
    for row_index, row_offset in enumerate(row_offsets, start=1):
        for start_offset in start_offsets:
            stalls: list[dict[str, Any]] = []
            cursor = start_offset
            while len(stalls) < required_spaces:
                if cursor + stall_length > length + 1e-9:
                    break
                stall_polygon = _rect_from_frame(
                    origin=origin,
                    u=u,
                    v=v,
                    start_u=cursor,
                    start_v=row_offset,
                    width_u=stall_length,
                    width_v=DEFAULT_PARALLEL_STALL_WIDTH_M,
                )
                if polygon.buffer(1e-7).contains(stall_polygon):
                    stalls.append({
                        "stall_id": f"P{len(stalls) + 1:02d}",
                        "type": "standard",
                        "width_m": DEFAULT_PARALLEL_STALL_WIDTH_M,
                        "length_m": stall_length,
                        "row": row_index,
                        "mode": mode,
                        "orientation": "parallel",
                        "polygon": _polygon_coordinates(stall_polygon),
                    })
                cursor += stall_length
            if len(stalls) > len(best):
                best = stalls
            if len(best) >= required_spaces:
                return best
    return best


def _layout_result(
    *,
    status: str,
    strategy: str,
    placement_mode: str,
    required_spaces: int,
    accessible_spaces: int,
    stalls: list[dict[str, Any]],
    reason: str | None,
    drive_cells: list[Polygon] | None = None,
    entrance_access: dict[str, Any] | None = None,
) -> dict[str, Any]:
    unmet = max(0, required_spaces - len(stalls))
    provided_accessible = sum(1 for stall in stalls if stall["type"] == "accessible")
    unmet_accessible = max(0, accessible_spaces - provided_accessible)
    adjacency = _stall_adjacency_metrics(stalls)
    canonical_drive_cells = []
    for cell in drive_cells or ():
        try:
            canonical_drive_cells.append(
                Polygon(_polygon_coordinates(cell))
            )
        except (TypeError, ValueError):
            canonical_drive_cells.append(cell)
    operability = _parking_operability_checks(
        stalls,
        strategy=strategy,
        placement_mode=placement_mode,
        drive_cells=canonical_drive_cells,
        entrance_access=entrance_access,
    )
    result = {
        "schema_version": "arr.maas.parking_layout_candidate.v0",
        "status": status,
        "strategy": strategy,
        "placement_mode": placement_mode,
        "required_spaces": required_spaces,
        "required_accessible_spaces": accessible_spaces,
        "provided_spaces": len(stalls),
        "provided_accessible_spaces": provided_accessible,
        "unmet_spaces": unmet,
        "unmet_accessible_spaces": unmet_accessible,
        "stalls": stalls,
        "drive_cells": [_polygon_coordinates(cell) for cell in canonical_drive_cells],
        "entrance_connector_polygon": (_polygon_coordinates(entrance_access['connector_polygon'])
            if entrance_access and isinstance(entrance_access.get('connector_polygon'), Polygon) else None),
        "coordinate_precision_m": 10.0 ** -LAYOUT_COORDINATE_DECIMAL_PLACES,
        "layout_formula": _layout_formula_metadata(placement_mode, required_spaces=required_spaces),
        "adjacency": adjacency,
        "column_clearance": operability["column_clearance"],
        "drive_aisle_clearance": operability["drive_aisle_clearance"],
        "turning_clearance": operability["turning_clearance"],
        "limitations": [
            "deterministic_first_candidate_not_global_optimum",
            "column_core_check_deferred_until_structural_grid_or_core_polygons_are_supplied",
            "turning_check_uses_v1_stall_frontage_and_entrance_connector_not_vehicle_swept_path_simulation",
            "does_not_replace_grid_mip_solver",
        ],
    }
    if result["status"] == "pass" and operability["turning_clearance"].get("status") != "v1_pass":
        result["status"] = "needs_swept_path_review"
        result["reason"] = operability["turning_clearance"].get("reason") or "turning_clearance_requires_review"
    if (
        result["status"] == "pass"
        and placement_mode == "grid_connected_90"
        and required_spaces > 1
        and required_spaces <= SMALL_ATTACHED_PARKING_MAX_SPACES
        and not adjacency.get("contiguous_ok")
    ):
        result["status"] = "needs_aisle_review"
        result["reason"] = "multiple parking stalls should be grouped in one contiguous row for this mass-stage layout."
    if reason:
        result["reason"] = reason
    if unmet > 0 or unmet_accessible > 0:
        result["repair_requests"] = [
            {
                "operation": "increase_parking_envelope_or_switch_strategy",
                "reason": (
                    f"{unmet} required parking spaces are not placed."
                    if unmet > 0
                    else f"{unmet_accessible} required accessible parking spaces are not placed."
                ),
                "target_agent": "maas_geometry_agent",
            }
        ]
    else:
        result["repair_requests"] = []
    result["mass_stage_parking"] = _mass_stage_parking_summary(result)
    return result


def _mechanical_parking_review_candidate(
    polygon: Polygon,
    *,
    required_spaces: int,
    accessible_spaces: int,
) -> dict[str, Any]:
    area = float(polygon.area or 0.0)
    long_side, short_side = _oriented_rect_dimensions(polygon)
    module_area = 18.0
    area_capacity = max(0, math.floor(area / module_area))
    bay_capacity = max(0, math.floor(long_side / 2.7) * max(1, math.floor(short_side / 5.6)) * 2)
    conceptual_capacity = max(area_capacity, bay_capacity)
    provided = min(required_spaces, conceptual_capacity)
    unmet = max(0, required_spaces - provided)
    status = "needs_mechanical_parking_review" if unmet == 0 else "fail"
    result = {
        "schema_version": "arr.maas.parking_layout_candidate.v0",
        "status": status,
        "strategy": "mechanical",
        "placement_mode": "mechanical_conceptual_stack",
        "required_spaces": required_spaces,
        "required_accessible_spaces": accessible_spaces,
        "provided_spaces": provided,
        "provided_accessible_spaces": 0,
        "unmet_spaces": unmet,
        "unmet_accessible_spaces": accessible_spaces,
        "stalls": [],
        "layout_formula": {
            "schema_version": "arr.maas.parking_formula.v1",
            "mode": "mechanical_conceptual_stack",
            "required_spaces": required_spaces,
            "module": {
                "conceptual_module_area_m2_per_space": module_area,
                "oriented_long_side_m": round(long_side, 2),
                "oriented_short_side_m": round(short_side, 2),
                "area_capacity_spaces": area_capacity,
                "bay_capacity_spaces": bay_capacity,
                "conceptual_capacity_spaces": conceptual_capacity,
            },
        },
        "adjacency": {
            "contiguous_ok": True,
            "row_contiguous_ok": True,
            "cluster_contiguous_ok": True,
            "basis": "mechanical_stack_capacity_review_not_stall_row_geometry",
        },
        "column_clearance": {
            "status": "needs_review",
            "reason": "mechanical equipment bay, pit, and structural grid are not modeled.",
        },
        "drive_aisle_clearance": {
            "status": "authority_review",
            "reason": "mechanical parking uses equipment access/queueing rather than standard 6m stall aisle.",
        },
        "turning_clearance": {
            "status": "authority_review",
            "entrance_connected": True,
            "frontage_connected_stalls": provided,
            "reason": "entry queueing, turntable, and manufacturer equipment specification require review.",
        },
        "authority_review_check": {
            "schema_version": "arr.maas.mechanical_parking_review.v0",
            "status": "prechecked_needs_external_evidence" if unmet == 0 else "blocked",
            "basis": "Mechanical parking conceptual capacity unlock for high-FAR MAAS candidates.",
            "external_evidence_needed": [
                "mechanical_parking_equipment_type",
                "pit_or_lift_clearance",
                "entry_queueing_space",
                "manufacturer_turning_and_safety_clearance",
                "local_authority_acceptance",
            ],
        },
        "limitations": [
            "conceptual_capacity_only_not_final_parking_approval",
            "does_not_place_standard_stall_polygons",
            "requires_mechanical_equipment_and_local_authority_review",
        ],
        "repair_requests": [] if unmet == 0 else [{
            "operation": "increase_mechanical_parking_capacity_or_switch_strategy",
            "reason": f"{unmet} required parking spaces remain unmet even with conceptual mechanical parking.",
            "target_agent": "maas_geometry_agent",
        }],
    }
    result["mass_stage_parking"] = _mass_stage_parking_summary(result)
    return result


def _mass_stage_parking_summary(layout: dict[str, Any]) -> dict[str, Any]:
    """Separate mass-stage feasibility from final parking approval.

    A deterministic early massing run should not pretend to be a permit-grade
    swept-path/structural/core review. It still needs a clear signal when the
    required stall count, accessible count, row grouping, and generated 6m
    aisle module are plausible enough for design comparison.
    """
    required = int(layout.get("required_spaces") or 0)
    provided = int(layout.get("provided_spaces") or 0)
    accessible_required = int(layout.get("required_accessible_spaces") or 0)
    accessible_provided = int(layout.get("provided_accessible_spaces") or 0)
    unmet = int(layout.get("unmet_spaces") or 0)
    unmet_accessible = int(layout.get("unmet_accessible_spaces") or 0)
    if required <= 0:
        return {
            "status": "needs_requirement",
            "reason": "No required parking count is attached to this candidate.",
        }
    if layout.get("strategy") == "mechanical":
        count_ok = provided >= required and unmet == 0
        return {
            "schema_version": "arr.maas.parking_mass_stage.v0",
            "status": "pass" if count_ok else "fail",
            "count_ok": count_ok,
            "accessible_ok": accessible_required == 0,
            "row_or_cluster_ok": True,
            "aisle_module_ok": True,
            "frontage_or_relief_ok": True,
            "entrance_ok": True,
            "authority_review_required": True,
            "final_layout_status": layout.get("status"),
            "reason": None if count_ok else "Mechanical parking conceptual capacity is below required count.",
        }
    count_ok = provided >= required and unmet == 0
    accessible_ok = accessible_provided >= accessible_required and unmet_accessible == 0
    adjacency = layout.get("adjacency") if isinstance(layout.get("adjacency"), dict) else {}
    row_ok = bool(
        adjacency.get("row_contiguous_ok")
        or adjacency.get("cluster_contiguous_ok")
        or adjacency.get("contiguous_ok")
        or provided <= 1
    )
    aisle = layout.get("drive_aisle_clearance") if isinstance(layout.get("drive_aisle_clearance"), dict) else {}
    aisle_status = aisle.get("status")
    aisle_ok = aisle_status in {"pass", "authority_review"} or layout.get("placement_mode") in {
        "internal_double_loaded_90",
        "internal_single_loaded_90",
        "grid_connected_90",
        "grid_connected_parallel",
    }
    turning = layout.get("turning_clearance") if isinstance(layout.get("turning_clearance"), dict) else {}
    row_relief = turning.get("contiguous_row_frontage_relief") if isinstance(turning.get("contiguous_row_frontage_relief"), dict) else {}
    tandem_relief = turning.get("small_attached_tandem_relief") if isinstance(turning.get("small_attached_tandem_relief"), dict) else {}
    frontage_ok = (
        turning.get("status") == "v1_pass"
        or bool(row_relief.get("available"))
        or bool(tandem_relief.get("available"))
        or provided <= 1
    )
    entrance_ok = turning.get("entrance_connected") is not False
    status = "pass" if count_ok and accessible_ok and row_ok and aisle_ok and frontage_ok and entrance_ok else "fail"
    reason = None
    if not count_ok:
        reason = "Required parking spaces are not fully placed."
    elif not accessible_ok:
        reason = "Required accessible parking spaces are not fully placed."
    elif not row_ok:
        reason = "Placed stalls are not grouped as a contiguous mass-stage parking row or cluster."
    elif not aisle_ok:
        reason = "Generated aisle module is not sufficient for mass-stage review."
    elif not frontage_ok:
        reason = "Stalls need a frontage or small-attached relief check before mass-stage pass."
    elif not entrance_ok:
        reason = "Generated parking aisle is not connected to road/frontage access."
    return {
        "schema_version": "arr.maas.parking_mass_stage.v0",
        "status": status,
        "count_ok": count_ok,
        "accessible_ok": accessible_ok,
        "row_or_cluster_ok": row_ok,
        "aisle_module_ok": aisle_ok,
        "frontage_or_relief_ok": frontage_ok,
        "entrance_ok": entrance_ok,
        "authority_review_required": layout.get("status") != "pass",
        "final_layout_status": layout.get("status"),
        "reason": reason,
    }


def _layout_formula_metadata(placement_mode: str, *, required_spaces: int) -> dict[str, Any]:
    single_depth = DEFAULT_STALL_LENGTH_M + DEFAULT_AISLE_WIDTH_M
    double_depth = DEFAULT_STALL_LENGTH_M * 2 + DEFAULT_AISLE_WIDTH_M
    mode_labels = {
        "internal_double_loaded_90": "double_loaded_90",
        "internal_single_loaded_90": "single_loaded_90",
        "grid_connected_90": "grid_connected_90",
        "grid_connected_parallel": "grid_connected_parallel",
        "single_row_aisle_review": "single_row_90_requires_aisle_review",
        "road_as_aisle_single_row": "road_as_aisle_single_row",
        "road_as_aisle_tandem": "road_as_aisle_tandem",
        "road_as_aisle_parallel": "road_as_aisle_parallel",
        "road_as_aisle_residential_parallel_authority_review": "road_as_aisle_residential_parallel_authority_review",
    }
    return {
        "schema_version": "arr.maas.parking_formula.v1",
        "mode": mode_labels.get(placement_mode, placement_mode),
        "required_spaces": required_spaces,
        "stall": {
            "standard_width_m": DEFAULT_STALL_WIDTH_M,
            "standard_length_m": DEFAULT_STALL_LENGTH_M,
            "parallel_width_m": DEFAULT_PARALLEL_STALL_WIDTH_M,
            "parallel_length_m": DEFAULT_PARALLEL_STALL_LENGTH_M,
            "residential_undivided_road_parallel_length_m": RESIDENTIAL_UNDIVIDED_ROAD_PARALLEL_LENGTH_M,
            "accessible_width_m": DEFAULT_ACCESSIBLE_WIDTH_M,
            "accessible_length_m": DEFAULT_ACCESSIBLE_LENGTH_M,
        },
        "aisle": {
            "two_way_90deg_width_m": DEFAULT_AISLE_WIDTH_M,
            "small_attached_parallel_width_m": DEFAULT_PARALLEL_AISLE_WIDTH_M,
        },
        "module": {
            "single_loaded_90_depth_m": single_depth,
            "single_loaded_90_formula": "stall_length + aisle_width",
            "double_loaded_90_depth_m": double_depth,
            "double_loaded_90_formula": "stall_length + aisle_width + stall_length",
            "parallel_stall_formula": "parallel_length 6.0m x parallel_width 2.0m",
        },
        "small_attached_parking": {
            "max_spaces": SMALL_ATTACHED_PARKING_MAX_SPACES,
            "tandem_allowed_max_spaces": TANDEM_ALLOWED_MAX_SPACES,
            "entrance_width_m": ATTACHED_PARKING_ENTRANCE_WIDTH_M,
        },
    }


def _parking_operability_checks(
    stalls: list[dict[str, Any]],
    *,
    strategy: str,
    placement_mode: str,
    drive_cells: list[Polygon] | None = None,
    entrance_access: dict[str, Any] | None = None,
) -> dict[str, Any]:
    drive_cell_count = len(drive_cells or [])
    exact_90_module = placement_mode in {
        "internal_double_loaded_90",
        "internal_single_loaded_90",
        "grid_connected_90",
    }
    exact_parallel_module = placement_mode == "grid_connected_parallel"
    has_drive_cells = drive_cell_count > 0
    aisle_status = (
        "pass"
        if exact_90_module or exact_parallel_module
        else "needs_review"
    )
    aisle_source = "generated_drive_cells" if has_drive_cells else "module_formula"
    if placement_mode.startswith("road_as_aisle"):
        aisle_status = "authority_review"
        aisle_source = "road_as_aisle_exception"
    elif placement_mode == "single_row_aisle_review":
        aisle_status = "needs_review"
        aisle_source = "single_row_requires_road_or_drive_aisle_confirmation"

    row_span = _largest_row_span(stalls)
    required_depth = (
        DEFAULT_PARALLEL_STALL_WIDTH_M + DEFAULT_PARALLEL_AISLE_WIDTH_M
        if exact_parallel_module
        else DEFAULT_STALL_LENGTH_M + (DEFAULT_AISLE_WIDTH_M if exact_90_module else 0.0)
    )
    column_clearance = _column_clearance_check(
        stalls,
        strategy=strategy,
        required_clear_bay_width_m=row_span,
        required_clear_depth_m=required_depth,
    )
    turning_clearance = _turning_clearance_check(
        stalls,
        placement_mode=placement_mode,
        aisle_status=aisle_status,
        drive_cells=drive_cells or [],
        entrance_access=entrance_access,
    )
    return {
        "column_clearance": column_clearance,
        "drive_aisle_clearance": {
            "status": aisle_status,
            "source": aisle_source,
            "required_width_m": (
                DEFAULT_PARALLEL_AISLE_WIDTH_M
                if exact_parallel_module
                else DEFAULT_AISLE_WIDTH_M
            ),
            "provided_width_m": (
                DEFAULT_PARALLEL_AISLE_WIDTH_M
                if exact_parallel_module
                else DEFAULT_AISLE_WIDTH_M
                if exact_90_module or has_drive_cells
                else None
            ),
            "drive_cell_count": drive_cell_count,
        },
        "turning_clearance": turning_clearance,
    }


def _turning_clearance_check(
    stalls: list[dict[str, Any]],
    *,
    placement_mode: str,
    aisle_status: str,
    drive_cells: list[Polygon],
    entrance_access: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = {
        "required_aisle_width_m": (
            DEFAULT_PARALLEL_AISLE_WIDTH_M
            if placement_mode == "grid_connected_parallel"
            else DEFAULT_AISLE_WIDTH_M
        ),
        "note": "This is a mass-stage v1 frontage/aisle/entrance check, not a vehicle swept-path simulation.",
    }
    if placement_mode.startswith("road_as_aisle"):
        return {
            **base,
            "status": "v1_pass" if stalls else "needs_swept_path_review",
            "method": "road_as_aisle_exception_v1",
            "frontage_checked": False,
            "authority_review": True,
            "reason": (
                None
                if stalls
                else "No parking stalls are placed for road-as-aisle review."
            ),
        }
    if aisle_status != "pass":
        return {
            **base,
            "status": "needs_swept_path_review",
            "method": "aisle_status_requires_review",
            "reason": f"drive aisle status is {aisle_status}.",
        }
    if not drive_cells:
        return {
            **base,
            "status": "v1_pass",
            "method": "minimum_90deg_aisle_module",
            "frontage_checked": False,
            "reason": "No explicit drive cells were generated for this deterministic module layout.",
        }

    drive_union = drive_cells[0]
    for drive in drive_cells[1:]:
        drive_union = drive_union.union(drive)

    frontage_checks = []
    connected_count = 0
    for index, stall in enumerate(stalls):
        try:
            stall_polygon = Polygon(stall["polygon"])
        except Exception:
            continue
        try:
            width = float(stall.get("width_m") or DEFAULT_STALL_WIDTH_M)
        except Exception:
            width = DEFAULT_STALL_WIDTH_M
        required_frontage = max(2.0, width * 0.75)
        try:
            frontage_m = float(stall_polygon.boundary.intersection(drive_union).length)
        except Exception:
            frontage_m = 0.0
        if index < len(drive_cells):
            try:
                paired_frontage = float(
                    stall_polygon.boundary.intersection(drive_cells[index].buffer(1e-7)).length
                )
                frontage_m = max(frontage_m, min(width, paired_frontage))
            except Exception:
                pass
        connected = frontage_m + 0.05 >= required_frontage
        if connected:
            connected_count += 1
        frontage_checks.append({
            "stall_id": stall.get("stall_id"),
            "required_frontage_m": round(required_frontage, 3),
            "provided_frontage_m": round(frontage_m, 3),
            "connected": connected,
        })

    entrance_connected = None
    entrance_type = None
    if isinstance(entrance_access, dict):
        entrance_connected = bool(entrance_access.get("connected"))
        entrance_type = entrance_access.get("connection_type")
    tandem_relief = _small_attached_tandem_frontage_relief(
        stalls,
        frontage_checks,
        placement_mode=placement_mode,
    )
    row_frontage_relief = _contiguous_row_drive_cell_frontage_relief(
        stalls,
        drive_cells,
        placement_mode=placement_mode,
    )
    frontage_ok = connected_count >= len(stalls) if stalls else False
    if not frontage_ok and row_frontage_relief["available"]:
        frontage_ok = True
    if not frontage_ok and tandem_relief["available"]:
        frontage_ok = True
    entrance_ok = entrance_connected is not False
    status = "v1_pass" if frontage_ok and entrance_ok else "needs_swept_path_review"
    reason = None
    if not frontage_ok:
        reason = (
            "One or more stalls do not have enough frontage on the generated "
            f"{base['required_aisle_width_m']:g}m drive aisle."
        )
    elif not entrance_ok:
        reason = "Generated drive aisle is not connected to a road/frontage entrance."
    result = {
        **base,
        "status": status,
        "method": "stall_frontage_and_entrance_connector_v1",
        "frontage_checked": True,
        "frontage_connected_stalls": connected_count,
        "frontage_total_stalls": len(stalls),
        "frontage_checks": frontage_checks,
        "contiguous_row_frontage_relief": row_frontage_relief,
        "small_attached_tandem_relief": tandem_relief,
        "entrance_connected": entrance_connected,
        "entrance_connection_type": entrance_type,
    }
    if reason:
        result["reason"] = reason
    return result


def _contiguous_row_drive_cell_frontage_relief(
    stalls: list[dict[str, Any]],
    drive_cells: list[Polygon],
    *,
    placement_mode: str,
) -> dict[str, Any]:
    if placement_mode not in {
        "grid_connected_90",
        "grid_connected_parallel",
    } or len(stalls) <= 1:
        return {"available": False, "reason": "Only grid-connected multi-stall rows use this frontage relief."}
    if len(drive_cells) < len(stalls):
        return {"available": False, "reason": "Generated drive cell count is lower than stall count."}
    adjacency = _stall_adjacency_metrics(stalls)
    row_ok = bool(adjacency.get("row_contiguous_ok", adjacency.get("contiguous_ok")))
    small_attached_cluster_ok = (
        len(stalls) <= TANDEM_ALLOWED_MAX_SPACES
        and bool(adjacency.get("cluster_contiguous_ok"))
    )
    return {
        "available": row_ok or small_attached_cluster_ok,
        "basis": (
            "contiguous grid row with one generated drive cell per stall"
            if row_ok
            else "small attached parking cluster: adjacent/tandem stalls share a generated 6m drive-cell group"
        ),
        "row_groups": adjacency.get("row_groups"),
        "touching_pairs": adjacency.get("touching_pairs"),
        "connected_components": adjacency.get("connected_components"),
        "cluster_contiguous_ok": adjacency.get("cluster_contiguous_ok"),
        "small_attached_cluster_relief": small_attached_cluster_ok,
        "drive_cell_count": len(drive_cells),
    }


def _small_attached_tandem_frontage_relief(
    stalls: list[dict[str, Any]],
    frontage_checks: list[dict[str, Any]],
    *,
    placement_mode: str,
) -> dict[str, Any]:
    if not placement_mode.startswith("road_as_aisle"):
        return {
            "available": False,
            "max_spaces": TANDEM_ALLOWED_MAX_SPACES,
            "reason": "Tandem relief is only applied to explicit road-as-aisle tandem layouts.",
        }
    if len(stalls) == 0 or len(stalls) > TANDEM_ALLOWED_MAX_SPACES:
        return {
            "available": False,
            "max_spaces": TANDEM_ALLOWED_MAX_SPACES,
            "reason": "Tandem relief only applies to five or fewer stalls.",
        }
    connected_ids = {
        check.get("stall_id")
        for check in frontage_checks
        if check.get("connected")
    }
    if len(connected_ids) == len(stalls):
        return {
            "available": False,
            "max_spaces": TANDEM_ALLOWED_MAX_SPACES,
            "reason": "All stalls already have direct aisle frontage.",
        }
    polygons = []
    for stall in stalls:
        try:
            polygons.append((stall.get("stall_id"), Polygon(stall["polygon"])))
        except Exception:
            return {
                "available": False,
                "max_spaces": TANDEM_ALLOWED_MAX_SPACES,
                "reason": "Stall polygon is missing or invalid.",
            }
    reachable = set(connected_ids)
    for stall_id, polygon in polygons:
        if stall_id in reachable:
            continue
        touches_front_stall = any(
            front_id in connected_ids and polygon.buffer(1e-7).intersects(front_polygon.buffer(1e-7))
            for front_id, front_polygon in polygons
        )
        if touches_front_stall:
            reachable.add(stall_id)
    return {
        "available": len(reachable) == len(stalls),
        "max_spaces": TANDEM_ALLOWED_MAX_SPACES,
        "max_depth_from_aisle": 2,
        "direct_frontage_stalls": len(connected_ids),
        "reachable_stalls": len(reachable),
        "basis": "Parking Lot Act Enforcement Rule Article 11(5): for five or fewer stalls, up to two stalls may be placed in tandem from the aisle.",
    }


def _column_clearance_check(
    stalls: list[dict[str, Any]],
    *,
    strategy: str,
    required_clear_bay_width_m: float,
    required_clear_depth_m: float,
) -> dict[str, Any]:
    if strategy != "piloti_ground":
        return {
            "status": "not_applicable",
            "reason": "Column clearance is only evaluated for piloti parking in this precheck.",
        }
    if not stalls:
        return {
            "status": "fail",
            "reason": "No parking stalls are placed, so piloti column clearance cannot pass.",
        }
    assumed_clear_bay_width = required_clear_bay_width_m + PILOTI_MIN_CLEAR_BAY_MARGIN_M * 2
    return {
        "status": "deferred_structural_review",
        "method": "clear_bay_record_only",
        "assumed_column_size_m": PILOTI_ASSUMED_COLUMN_SIZE_M,
        "required_clear_bay_width_m": round(required_clear_bay_width_m, 2),
        "assumed_clear_bay_width_m": round(assumed_clear_bay_width, 2),
        "required_clear_depth_m": round(required_clear_depth_m, 2),
        "margin_each_side_m": PILOTI_MIN_CLEAR_BAY_MARGIN_M,
        "reason": "No explicit column/core polygons are supplied; structural column/core clearance is deferred.",
    }


def _largest_row_span(stalls: list[dict[str, Any]]) -> float:
    spans: dict[Any, float] = {}
    for stall in stalls:
        try:
            width = float(stall.get("width_m") or DEFAULT_STALL_WIDTH_M)
        except Exception:
            width = DEFAULT_STALL_WIDTH_M
        row = stall.get("row")
        spans[row] = spans.get(row, 0.0) + width
    return max(spans.values(), default=0.0)


def _stall_adjacency_metrics(stalls: list[dict[str, Any]]) -> dict[str, Any]:
    polygons = []
    for stall in stalls:
        try:
            polygons.append((stall["stall_id"], stall.get("row"), Polygon(stall["polygon"])))
        except Exception:
            continue
    if len(polygons) <= 1:
        return {
            "status": "single_or_none",
            "touching_pairs": 0,
            "gap_pairs": 0,
            "max_gap_m": 0.0,
            "row_groups": len({stall.get("row") for stall in stalls}) if stalls else 0,
            "connected_components": len(polygons),
            "row_contiguous_ok": True,
            "cluster_contiguous_ok": True,
            "contiguous_ok": True,
        }
    row_touching_pairs = 0
    gap_pairs = 0
    max_neighbor_gap = 0.0
    min_neighbor_gap = float("inf")
    row_groups = len({row for _stall_id, row, _polygon in polygons})
    for row in sorted({row for _stall_id, row, _polygon in polygons}, key=lambda value: str(value)):
        row_polygons = [item for item in polygons if item[1] == row]
        row_polygons.sort(key=lambda item: (round(item[2].centroid.x, 3), round(item[2].centroid.y, 3)))
        for index in range(len(row_polygons) - 1):
            a = row_polygons[index][2]
            b = row_polygons[index + 1][2]
            distance = float(a.distance(b))
            min_neighbor_gap = min(min_neighbor_gap, distance)
            max_neighbor_gap = max(max_neighbor_gap, distance)
            if distance <= 0.05:
                row_touching_pairs += 1
            else:
                gap_pairs += 1
    expected_neighbor_pairs = max(0, len(polygons) - 1)
    row_contiguous_ok = row_groups == 1 and gap_pairs == 0 and row_touching_pairs >= expected_neighbor_pairs

    graph: dict[str, set[str]] = {stall_id: set() for stall_id, _row, _polygon in polygons}
    cluster_touching_pairs = 0
    for index, (stall_id, _row, polygon) in enumerate(polygons):
        for other_id, _other_row, other_polygon in polygons[index + 1:]:
            if polygon.distance(other_polygon) <= 0.05:
                cluster_touching_pairs += 1
                graph[stall_id].add(other_id)
                graph[other_id].add(stall_id)
    seen: set[str] = set()
    components = 0
    for stall_id in graph:
        if stall_id in seen:
            continue
        components += 1
        stack = [stall_id]
        seen.add(stall_id)
        while stack:
            current = stack.pop()
            for next_id in graph[current]:
                if next_id in seen:
                    continue
                seen.add(next_id)
                stack.append(next_id)
    cluster_contiguous_ok = components == 1 and cluster_touching_pairs >= expected_neighbor_pairs
    contiguous_ok = row_contiguous_ok or cluster_contiguous_ok
    return {
        "status": (
            "row_contiguous"
            if row_contiguous_ok
            else "cluster_contiguous"
            if cluster_contiguous_ok
            else "has_gaps"
        ),
        "touching_pairs": cluster_touching_pairs,
        "row_touching_pairs": row_touching_pairs,
        "gap_pairs": gap_pairs,
        "min_gap_m": round(0.0 if min_neighbor_gap == float("inf") else min_neighbor_gap, 3),
        "max_gap_m": round(max_neighbor_gap, 3),
        "row_groups": row_groups,
        "connected_components": components,
        "row_contiguous_ok": row_contiguous_ok,
        "cluster_contiguous_ok": cluster_contiguous_ok,
        "contiguous_ok": contiguous_ok,
    }


def _oriented_frame(polygon: Polygon) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float], float, float]:
    rect = polygon.minimum_rotated_rectangle
    coords = list(rect.exterior.coords)
    edges: list[tuple[float, int]] = []
    for i in range(min(4, len(coords) - 1)):
        edges.append((math.dist(coords[i], coords[i + 1]), i))
    if not edges:
        return (0.0, 0.0), (1.0, 0.0), (0.0, 1.0), 0.0, 0.0
    long_len, long_idx = max(edges, key=lambda item: item[0])
    short_len = min(length for length, _idx in edges)
    p0 = coords[long_idx]
    p1 = coords[long_idx + 1]
    ux = (p1[0] - p0[0]) / long_len if long_len else 1.0
    uy = (p1[1] - p0[1]) / long_len if long_len else 0.0
    vx, vy = -uy, ux
    centroid = polygon.centroid
    test = (p0[0] + vx * short_len * 0.5, p0[1] + vy * short_len * 0.5)
    if math.dist((centroid.x, centroid.y), test) > math.dist((centroid.x, centroid.y), (p0[0] - vx * short_len * 0.5, p0[1] - vy * short_len * 0.5)):
        vx, vy = -vx, -vy
    return (p0[0], p0[1]), (ux, uy), (vx, vy), long_len, short_len


def _rect_from_frame(
    *,
    origin: tuple[float, float],
    u: tuple[float, float],
    v: tuple[float, float],
    start_u: float,
    start_v: float,
    width_u: float,
    width_v: float,
) -> Polygon:
    corners = [
        _frame_point(origin, u, v, start_u, start_v),
        _frame_point(origin, u, v, start_u + width_u, start_v),
        _frame_point(origin, u, v, start_u + width_u, start_v + width_v),
        _frame_point(origin, u, v, start_u, start_v + width_v),
    ]
    return Polygon(corners)


def _frame_point(
    origin: tuple[float, float],
    u: tuple[float, float],
    v: tuple[float, float],
    offset_u: float,
    offset_v: float,
) -> tuple[float, float]:
    return (
        origin[0] + u[0] * offset_u + v[0] * offset_v,
        origin[1] + u[1] * offset_u + v[1] * offset_v,
    )


LAYOUT_COORDINATE_DECIMAL_PLACES = 4


def _polygon_coordinates(polygon: Polygon) -> list[list[float]]:
    return [[round(x, LAYOUT_COORDINATE_DECIMAL_PLACES), round(y, LAYOUT_COORDINATE_DECIMAL_PLACES)]
            for x, y in polygon.exterior.coords]


def _module_capacity(*, length: float, depth: float, module_depth: float, rows_per_module: int) -> int:
    modules = math.floor(depth / module_depth)
    stalls_per_row = math.floor(length / DEFAULT_STALL_WIDTH_M)
    return max(0, modules * rows_per_module * stalls_per_row)


def _oriented_rect_dimensions(polygon: Polygon) -> tuple[float, float]:
    rect = polygon.minimum_rotated_rectangle
    coords = list(rect.exterior.coords)
    if len(coords) < 4:
        return 0.0, 0.0
    lengths = [
        math.dist(coords[i], coords[i + 1])
        for i in range(min(4, len(coords) - 1))
    ]
    if not lengths:
        return 0.0, 0.0
    unique = sorted(lengths)
    short_side = unique[0]
    long_side = unique[-1]
    return long_side, short_side


def _largest_polygon(geometry: Polygon | MultiPolygon | None) -> Polygon | None:
    if geometry is None:
        return None
    if isinstance(geometry, Polygon):
        return geometry
    if isinstance(geometry, MultiPolygon):
        polygons = [g for g in geometry.geoms if isinstance(g, Polygon) and not g.is_empty]
        if not polygons:
            return None
        return max(polygons, key=lambda g: g.area)
    return None


def _usable_factor(strategy: str) -> float:
    if strategy == "piloti_ground":
        return 0.62
    if strategy in {"basement", "semi_basement"}:
        return 0.75
    if strategy == "ground_surface":
        return 0.85
    if strategy == "mixed":
        return 0.70
    return 0.0


def _planning_module_area(strategy: str) -> float:
    if strategy in {"basement", "semi_basement"}:
        return 32.0
    if strategy == "piloti_ground":
        return 34.0
    return 30.0


def _empty(reason: str, strategy: str) -> dict[str, Any]:
    return {
        "status": "heuristic_only",
        "strategy": strategy,
        "reason": reason,
        "envelope_area_m2": 0.0,
        "capacity_estimates": {
            "single_loaded_spaces": 0,
            "double_loaded_spaces": 0,
            "area_limited_spaces": 0,
            "estimated_capacity_spaces": 0,
        },
    }


def _optional_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    return None


__all__ = [
    "DEFAULT_ACCESSIBLE_LENGTH_M",
    "DEFAULT_ACCESSIBLE_WIDTH_M",
    "DEFAULT_AISLE_WIDTH_M",
    "DEFAULT_STALL_LENGTH_M",
    "DEFAULT_STALL_WIDTH_M",
    "evaluate_small_attached_parking_relief",
    "estimate_parking_capacity",
    "generate_parking_layout_candidate",
]
