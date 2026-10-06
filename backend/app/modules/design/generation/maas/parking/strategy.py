"""Parking-aware strategy metadata for MAAS candidates.

This module does not decide legal parking compliance. It records deterministic
mass-generation intent so parking can constrain later repairs instead of being
left as a final checklist item.
"""

from __future__ import annotations

import math
from typing import Any

from shapely.geometry import LineString, MultiPolygon, Polygon, mapping, shape

from backend.app.modules.design.generation.services.site_geometry import utm_to_wgs84, wgs84_to_utm

from backend.app.modules.design.generation.maas.parking.layout import evaluate_small_attached_parking_relief, estimate_parking_capacity, generate_parking_layout_candidate


PARKING_STRATEGIES = {
    "none",
    "ground_surface",
    "piloti_ground",
    "basement",
    "semi_basement",
    "mechanical",
    "mixed",
}


def attach_parking_strategy(
    props: dict[str, Any],
    *,
    site_area_m2: float,
    building_type: str,
    footprint_utm: Polygon | None = None,
    site_utm: Polygon | None = None,
    road_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach parking strategy metadata to candidate properties and maas_model."""
    strategy = infer_parking_strategy(
        props,
        site_area_m2=site_area_m2,
        building_type=building_type,
        footprint_utm=footprint_utm,
        site_utm=site_utm,
        road_context=road_context,
    )
    props["parking_strategy"] = strategy["selected_strategy"]
    props["parking_strategy_candidates"] = strategy["strategy_candidates"]
    props["parking_precheck"] = strategy
    model = props.get("maas_model")
    if isinstance(model, dict):
        model["parking_strategy"] = strategy["selected_strategy"]
        model["parking_precheck"] = strategy
    return strategy


def infer_parking_strategy(
    props: dict[str, Any],
    *,
    site_area_m2: float,
    building_type: str,
    footprint_utm: Polygon | None = None,
    site_utm: Polygon | None = None,
    road_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return deterministic parking strategy hints from mass metrics.

    The values here are planning heuristics. Required count still comes from
    the law graph plus floor/use schedule, and layout pass/fail must come from a
    later parking solver.
    """
    footprint_area = _float(props.get("footprint_area"))
    total_floor_area = _float(props.get("floor_area"))
    floors = max(int(_float(props.get("num_floors")) or 0), 0)
    bcr = _float(props.get("bcr"))
    open_area = max(site_area_m2 - footprint_area, 0.0)
    small_lot = site_area_m2 > 0 and site_area_m2 < 330.0
    dense_footprint = bcr >= 55.0 or (site_area_m2 > 0 and open_area / site_area_m2 < 0.35)
    residential_like = _is_residential_like(building_type)

    if floors <= 0 or total_floor_area <= 0:
        candidates = ["none"]
        selected = "none"
    elif small_lot and residential_like:
        candidates = ["piloti_ground", "ground_surface", "mechanical", "semi_basement", "basement", "mixed"]
        selected = "piloti_ground"
    elif dense_footprint:
        candidates = ["piloti_ground", "basement", "mechanical", "mixed"]
        selected = "piloti_ground"
    elif floors >= 5:
        candidates = ["basement", "piloti_ground", "mixed", "mechanical"]
        selected = "basement"
    else:
        candidates = ["ground_surface", "piloti_ground", "semi_basement", "mixed"]
        selected = "ground_surface"

    effective_road_context = _road_context_to_utm(
        road_context or props.get("road_context") or props.get("parking_road_context")
    )
    small_attached_parking = evaluate_small_attached_parking_relief(
        road_context=effective_road_context
    )
    required_spaces = _optional_int(_first_present(
        props.get("required_parking_spaces"),
        props.get("parking_required_spaces"),
        props.get("parking_count_required"),
    ))
    visual_required_spaces = required_spaces
    if visual_required_spaces is None:
        visual_required_spaces = _mass_stage_visual_required_spaces(
            props,
            building_type=building_type,
            total_floor_area=total_floor_area,
            floors=floors,
        )
    accessible_spaces = _optional_int(_first_present(
        props.get("required_accessible_parking_spaces"),
        props.get("accessible_parking_required_spaces"),
    )) or 0
    layout_candidate = None
    if visual_required_spaces is not None and visual_required_spaces >= 0:
        selected, layout_candidate = _select_layout_strategy(
            selected,
            candidates,
            footprint_utm=footprint_utm,
            site_utm=site_utm,
            required_spaces=visual_required_spaces,
            accessible_spaces=accessible_spaces,
            road_context=effective_road_context,
        )
        if required_spaces is None and isinstance(layout_candidate, dict):
            layout_candidate["legal_count_status"] = "unresolved_visual_layout_only"
            layout_candidate["legal_required_spaces"] = None
            layout_candidate["visual_required_spaces"] = visual_required_spaces
            layout_candidate["authority_review"] = True
            layout_candidate["reason"] = (
                "법정 주차대수는 세대/전용면적 입력 후 확정 필요. "
                "현재 주차면은 매스 단계 시각 검토용입니다."
            )
        layout_candidate = _layout_candidate_to_wgs84(layout_candidate)
    layout_precheck = _layout_precheck(
        selected,
        footprint_area=footprint_area,
        open_area=open_area,
        footprint_utm=footprint_utm,
        site_utm=site_utm,
    )

    result = {
        "schema_version": "arr.maas.parking_strategy.v0",
        "status": "has_layout_candidate" if layout_candidate else "needs_parking_requirements",
        "selected_strategy": selected,
        "strategy_candidates": candidates,
        "basis": {
            "site_area_m2": _round(site_area_m2),
            "footprint_area_m2": _round(footprint_area),
            "open_area_m2": _round(open_area),
            "total_floor_area_m2": _round(total_floor_area),
            "num_floors": floors,
            "building_type": building_type,
            "small_lot": small_lot,
            "dense_footprint": dense_footprint,
            "residential_like": residential_like,
        },
        "mass_generation_constraints": _strategy_constraints(selected),
        "layout_precheck": layout_precheck,
        "small_attached_parking_relief": small_attached_parking,
        "required_count": _required_count_summary(props, total_floor_area),
        "repair_request_templates": _repair_templates(selected),
    }
    if layout_candidate:
        result["layout_candidate"] = layout_candidate
    envelope = _parking_envelope(selected, footprint_utm=footprint_utm, site_utm=site_utm)
    if envelope is not None and not envelope.is_empty:
        result["parking_envelope_wgs84"] = _geometry_to_wgs84_mapping(envelope)
    return result


def _mass_stage_visual_required_spaces(
    props: dict[str, Any],
    *,
    building_type: str,
    total_floor_area: float,
    floors: int,
) -> int | None:
    """Return a visual-only stall target when the legal count is unresolved.

    Apartment/common-housing parking count needs household or exclusive-area
    schedules. The massing UI still needs visible stall geometry, but this value
    must not be treated as a computed legal requirement.
    """
    requirement = props.get("parking_required_count")
    status = requirement.get("status") if isinstance(requirement, dict) else None
    if status not in {"needs_external_rule", "needs_metric", "needs_graph_requirement", "needs_pnu"}:
        return None
    if not _is_residential_like(building_type):
        return None
    if floors <= 0 or total_floor_area <= 0:
        return None
    estimated_households = max(1, min(8, floors))
    return estimated_households


def _select_layout_strategy(
    selected: str,
    candidates: list[str],
    *,
    footprint_utm: Polygon | None,
    site_utm: Polygon | None,
    required_spaces: int,
    accessible_spaces: int,
    road_context: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    ordered = [selected, *[candidate for candidate in candidates if candidate != selected]]
    best_strategy = selected
    best_layout: dict[str, Any] | None = None
    best_score: tuple[int, int, int, int, int, int, int] | None = None
    for strategy in ordered:
        if strategy == "none":
            continue
        envelope = _parking_envelope(strategy, footprint_utm=footprint_utm, site_utm=site_utm)
        drive_envelope = _parking_drive_envelope(strategy, footprint_utm=footprint_utm, site_utm=site_utm)
        layout = generate_parking_layout_candidate(
            envelope,
            required_spaces=required_spaces,
            accessible_spaces=accessible_spaces,
            strategy=strategy,
            road_context=road_context,
            drive_envelope=drive_envelope,
        )
        score = _layout_strategy_score(layout)
        if best_score is None or score > best_score:
            best_strategy = strategy
            best_layout = layout
            best_score = score
    if best_layout is None:
        best_layout = generate_parking_layout_candidate(
            None,
            required_spaces=required_spaces,
            accessible_spaces=accessible_spaces,
            strategy=selected,
            road_context=road_context,
        )
    return best_strategy, best_layout


def _layout_strategy_score(layout: dict[str, Any]) -> tuple[int, int, int, int, int, int, int]:
    status = str(layout.get("status") or "")
    unmet = int(layout.get("unmet_spaces") or 0)
    provided = int(layout.get("provided_spaces") or 0)
    required = int(layout.get("required_spaces") or 0)
    status_score = (
        5 if status == "pass"
        else 4 if status == "needs_swept_path_review"
        else 3 if status == "needs_drive_connectivity_review"
        else 2 if status == "needs_aisle_review"
        else 1 if status == "needs_mechanical_parking_review"
        else 1 if unmet == 0
        else 0
    )
    turning = layout.get("turning_clearance") if isinstance(layout.get("turning_clearance"), dict) else {}
    frontage_connected = int(turning.get("frontage_connected_stalls") or 0)
    grid_solver = layout.get("grid_solver") if isinstance(layout.get("grid_solver"), dict) else {}
    entrance_verified = 1 if grid_solver.get("entrance_verified") else 0
    adjacency = layout.get("adjacency") if isinstance(layout.get("adjacency"), dict) else {}
    contiguous = 1 if adjacency.get("contiguous_ok") else 0
    compact_score = 1 if required <= 8 and (provided <= 1 or contiguous) else 0
    return (1 if unmet == 0 else 0, compact_score, status_score, frontage_connected, entrance_verified, contiguous, provided)


def _required_count_summary(props: dict[str, Any], total_floor_area: float) -> dict[str, Any]:
    requirement = props.get("parking_required_count")
    if isinstance(requirement, dict) and requirement:
        return requirement
    return {
        "status": "needs_graph_requirement",
        "reason": "Required parking count depends on local ordinance, use classification, and floor/use area schedule.",
        "facility_area_m2": _round(total_floor_area),
    }


def _road_context_to_utm(road_context: Any) -> dict[str, Any] | None:
    if not isinstance(road_context, dict):
        return None
    converted = dict(road_context)
    for key in ("shared_edge", "sharedEdge", "frontage_geometry", "frontageGeometry", "road_centerline", "roadCenterline"):
        if key in converted:
            converted[key] = _geometry_value_to_utm_mapping(converted[key])
    frontages = converted.get("road_frontages")
    if isinstance(frontages, list):
        converted_frontages = []
        for frontage in frontages:
            if not isinstance(frontage, dict):
                converted_frontages.append(frontage)
                continue
            item = dict(frontage)
            for key in ("geometry", "shared_edge", "sharedEdge", "frontage_geometry", "frontageGeometry", "road_centerline", "roadCenterline"):
                if key in item:
                    item[key] = _geometry_value_to_utm_mapping(item[key])
            converted_frontages.append(item)
        converted["road_frontages"] = converted_frontages
    return converted


def _geometry_value_to_utm_mapping(value: Any) -> Any:
    if isinstance(value, list):
        try:
            if len(value) >= 2 and all(isinstance(point, (list, tuple)) and len(point) >= 2 for point in value):
                geom = LineString([(float(point[0]), float(point[1])) for point in value])
            else:
                return value
        except Exception:
            return value
        if geom.is_empty or not _looks_like_korea_wgs84(geom.bounds):
            return value
        try:
            return mapping(wgs84_to_utm(geom))
        except Exception:
            return value
    if not isinstance(value, dict):
        return value
    try:
        geom = shape(value)
    except Exception:
        return value
    if geom.is_empty or not _looks_like_korea_wgs84(geom.bounds):
        return value
    try:
        return mapping(wgs84_to_utm(geom))
    except Exception:
        return value


def _looks_like_korea_wgs84(bounds: tuple[float, float, float, float]) -> bool:
    minx, miny, maxx, maxy = bounds
    return 120.0 <= minx <= 140.0 and 120.0 <= maxx <= 140.0 and 30.0 <= miny <= 45.0 and 30.0 <= maxy <= 45.0


def _strategy_constraints(strategy: str) -> dict[str, Any]:
    common = {
        "vehicle_access": "needs_driveway_and_aisle_check",
        "pedestrian_access": "separate_from_vehicle_path_where_required",
        "accessible_parking": "needs_accessible_stall_and_route_check",
        "core_placement": "must_not_block_parking_access_or_primary_egress",
    }
    if strategy == "piloti_ground":
        return {
            **common,
            "ground_floor": "reserve_void_or_partial_void_for_parking",
            "column_grid": "needs_usable_bay_width_check",
            "lost_program_area": "deduct_or_reassign_1f_program",
        }
    if strategy in {"basement", "semi_basement"}:
        return {
            **common,
            "ramp": "needs_ramp_slope_width_and_turning_check",
            "excavation": "needs_feasibility_and_cost_review",
        }
    if strategy == "mechanical":
        return {
            **common,
            "equipment": "needs_mechanical_parking_type_and_clearance_check",
            "queueing": "needs_entry_waiting_space_check",
        }
    if strategy == "ground_surface":
        return {
            **common,
            "surface_yard": "use_open_area_before_cutting_mass",
        }
    return common


def _layout_precheck(
    strategy: str,
    *,
    footprint_area: float,
    open_area: float,
    footprint_utm: Polygon | None,
    site_utm: Polygon | None,
) -> dict[str, Any]:
    envelope = _parking_envelope(strategy, footprint_utm=footprint_utm, site_utm=site_utm)
    if envelope is not None:
        return estimate_parking_capacity(envelope, strategy=strategy)

    planning_module_area = 30.0
    if strategy == "ground_surface":
        estimated_capacity = math.floor(max(open_area, 0.0) / planning_module_area)
        envelope_area = open_area
    elif strategy == "piloti_ground":
        envelope_area = max(footprint_area * 0.62, 0.0)
        estimated_capacity = math.floor(envelope_area / planning_module_area)
    elif strategy in {"basement", "semi_basement"}:
        envelope_area = max(footprint_area * 0.75, 0.0)
        estimated_capacity = math.floor(envelope_area / planning_module_area)
    elif strategy == "mechanical":
        envelope_area = max(footprint_area * 0.18, 0.0)
        estimated_capacity = None
    else:
        envelope_area = 0.0
        estimated_capacity = 0
    return {
        "status": "heuristic_only",
        "planning_module_area_m2_per_space": planning_module_area,
        "candidate_parking_envelope_area_m2": _round(envelope_area),
        "estimated_capacity_spaces": estimated_capacity,
        "note": "This is not a legal layout pass. A parking solver must check stalls, aisles, turning, ramps, and accessible route.",
    }


def _parking_envelope(
    strategy: str,
    *,
    footprint_utm: Polygon | None,
    site_utm: Polygon | None,
) -> Polygon | MultiPolygon | None:
    if strategy in {"piloti_ground", "basement", "semi_basement", "mechanical", "mixed"}:
        return footprint_utm
    if strategy == "ground_surface" and site_utm is not None and footprint_utm is not None:
        try:
            return site_utm.difference(footprint_utm)
        except Exception:
            return None
    return None


def _parking_drive_envelope(
    strategy: str,
    *,
    footprint_utm: Polygon | None,
    site_utm: Polygon | None,
) -> Polygon | MultiPolygon | None:
    if strategy == "piloti_ground":
        return site_utm or footprint_utm
    if strategy == "ground_surface" and site_utm is not None and footprint_utm is not None:
        try:
            return site_utm.difference(footprint_utm)
        except Exception:
            return site_utm
    if strategy in {"basement", "semi_basement", "mechanical", "mixed"}:
        return footprint_utm
    return None


def _layout_candidate_to_wgs84(layout_candidate: dict[str, Any]) -> dict[str, Any]:
    stalls = layout_candidate.get("stalls")
    converted_layout = dict(layout_candidate)
    grid_solver = converted_layout.get("grid_solver")
    if isinstance(grid_solver, dict):
        converted_grid = dict(grid_solver)
        connector_polygon = _polygon_from_coords(grid_solver.get("entrance_connector_polygon"))
        if connector_polygon is not None and not connector_polygon.is_empty:
            converted_grid["entrance_connector_polygon_wgs84"] = _polygon_coordinates_wgs84(connector_polygon)
        converted_layout["grid_solver"] = converted_grid
    if not isinstance(stalls, list):
        return converted_layout
    converted_stalls = []
    for stall in stalls:
        if not isinstance(stall, dict):
            converted_stalls.append(stall)
            continue
        converted = dict(stall)
        polygon = _polygon_from_coords(stall.get("polygon"))
        if polygon is not None and not polygon.is_empty:
            converted["polygon_wgs84"] = _polygon_coordinates_wgs84(polygon)
        converted_stalls.append(converted)
    return {**converted_layout, "stalls": converted_stalls}


def _geometry_to_wgs84_mapping(geometry: Polygon | MultiPolygon) -> dict[str, Any] | None:
    try:
        return mapping(utm_to_wgs84(geometry))
    except Exception:
        return None


def _polygon_coordinates_wgs84(polygon: Polygon) -> list[list[float]]:
    try:
        wgs = utm_to_wgs84(polygon)
        return [[round(float(x), 8), round(float(y), 8)] for x, y in wgs.exterior.coords]
    except Exception:
        return []


def _polygon_from_coords(coords: Any) -> Polygon | None:
    if not isinstance(coords, list) or len(coords) < 4:
        return None
    try:
        polygon = Polygon([(float(x), float(y)) for x, y in coords])
        if not polygon.is_valid:
            polygon = polygon.buffer(0)
        return polygon if isinstance(polygon, Polygon) else None
    except Exception:
        return None


def _repair_templates(strategy: str) -> list[dict[str, Any]]:
    templates = [
        {
            "operation": "move_core",
            "reason": "Core blocks parking aisle or accessible route.",
            "target_agent": "maas_geometry_agent",
        },
        {
            "operation": "reduce_or_split_footprint",
            "reason": "Open area or parking aisle is insufficient.",
            "target_agent": "maas_geometry_agent",
        },
    ]
    if strategy == "piloti_ground":
        templates.insert(0, {
            "operation": "reserve_piloti_void",
            "reason": "Ground floor must reserve enough covered parking envelope.",
            "target_agent": "maas_geometry_agent",
        })
    elif strategy in {"basement", "semi_basement"}:
        templates.insert(0, {
            "operation": "add_ramp_and_basement_parking",
            "reason": "Surface or piloti capacity is insufficient.",
            "target_agent": "maas_geometry_agent",
        })
    elif strategy == "mechanical":
        templates.insert(0, {
            "operation": "switch_to_mechanical_parking",
            "reason": "Conventional stall packing is infeasible on the parcel.",
            "target_agent": "maas_geometry_agent",
        })
    return templates


def _is_residential_like(building_type: str) -> bool:
    label = building_type or ""
    return any(token in label for token in ("주택", "공동", "다가구", "다세대", "오피스텔"))


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _optional_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _round(value: float) -> float:
    return round(float(value), 2)


__all__ = ["PARKING_STRATEGIES", "attach_parking_strategy", "infer_parking_strategy"]
