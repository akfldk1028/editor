"""Feasible building-capacity targets for BOOK geometry authors.

This module owns only the capacity contract. Legal envelope construction and
parking remain in their existing hard-gate modules; portfolio orchestration
only passes the resulting immutable dictionaries between stages.
"""

from __future__ import annotations

from copy import deepcopy
from math import isfinite
from typing import Any

from shapely.geometry import Polygon, shape
from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.source_geometry.ir import SourceMass


CAPACITY_AREA_MEASUREMENT_TOLERANCE_M2 = 0.05

from backend.app.modules.design.generation.maas.book_language.legal_floor_field import validate_legal_floor_field


def build_feasible_capacity_contract(
    context: Any,
    *,
    site_local_utm: Polygon,
    height_m: float,
    floors: int,
    target_utilization: float = 0.88,
    minimum_utilization: float = 0.78,
    floor_capacity_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Measure gross floor capacity from the live legal field, BCR and FAR."""
    # Local import keeps the dependency one-way: legal generation does not
    # need to know that an authoring-capacity policy exists.
    from backend.app.modules.design.generation.maas.book_language.downstream_hard_gate import generation_site_at_height

    plan = (
        floor_capacity_plan
        if isinstance(floor_capacity_plan, dict)
        and floor_capacity_plan.get("schema_version")
        == "arr.maas.floor_capacity_plan.v1"
        and floor_capacity_plan.get("status") in {"materialized", "target_unreachable"}
        else None
    )
    if plan is not None:
        embedded_legal_field = plan.get("legal_floor_field")
        authoritative_legal_hash = str(
            plan.get("legal_floor_field_hash") or ""
        )
        embedded_hash = str(
            (embedded_legal_field or {}).get(
                "legal_floor_field_hash"
            )
            or ""
        )
        if (
            not authoritative_legal_hash
            or not validate_legal_floor_field(embedded_legal_field)
            or embedded_hash != authoritative_legal_hash
        ):
            raise ValueError("legal_floor_field_authority_mismatch")
    floor_count = max(
        1,
        int(
            (plan or {}).get("selected_floor_count")
            or floors
        ),
    )
    effective_height = float(
        (plan or {}).get("selected_height_m")
        or height_m
    )
    parcel_area = max(float(site_local_utm.area), 1e-9)
    floor_step = max(0.0, effective_height) / floor_count
    legal_floor_areas = (
        [
            max(0.0, float(value))
            for value in plan.get("legal_floor_section_areas_m2") or ()
        ][:floor_count]
        if plan is not None
        else []
    )
    if len(legal_floor_areas) != floor_count:
        legal_floor_areas = []
        for floor_index in range(floor_count):
            section = generation_site_at_height(context, floor_step * (floor_index + 1))
            legal_floor_areas.append(float(section.area) if section is not None else 0.0)

    bcr_limit = max(0.0, float(context.envelope.bcr_limit))
    far_limit = max(0.0, float(context.envelope.far_limit))
    bcr_adjusted_areas = list(legal_floor_areas)
    if bcr_adjusted_areas:
        bcr_adjusted_areas[0] = min(
            bcr_adjusted_areas[0],
            parcel_area * bcr_limit / 100.0,
        )
    height_field_capacity = sum(bcr_adjusted_areas)
    far_capacity = parcel_area * far_limit / 100.0
    feasible_maximum = (
        max(0.0, float(plan.get("feasible_maximum_gfa_m2") or 0.0))
        if plan is not None
        else max(0.0, min(height_field_capacity, far_capacity))
    )
    target_ratio = max(0.50, min(0.98, float(target_utilization)))
    minimum_ratio = max(0.40, min(target_ratio, float(minimum_utilization)))
    target_floor_area = (
        max(0.0, float(plan.get("target_gfa_m2") or 0.0))
        if plan is not None
        else feasible_maximum * target_ratio
    )
    generation_area = max(float(context.generation_site.area), 1e-9)
    legal_field_yield_ratio = (
        min(1.0, target_floor_area / height_field_capacity)
        if height_field_capacity > 1e-9
        else 0.0
    )
    ground_capacity = (
        float(bcr_adjusted_areas[0])
        if bcr_adjusted_areas
        else generation_area
    )
    plan_floor_targets = (
        [
            max(0.0, float(value))
            for value in plan.get("target_floor_areas_m2") or ()
        ][:floor_count]
        if plan is not None
        else []
    )
    target_ground_plan = (
        min(ground_capacity, plan_floor_targets[0])
        if len(plan_floor_targets) == floor_count and plan_floor_targets
        else ground_capacity * legal_field_yield_ratio
    )
    legal_floor_field = (
        deepcopy(dict(plan.get("legal_floor_field") or {}))
        if plan is not None
        and isinstance(plan.get("legal_floor_field"), dict)
        else {}
    )
    candidate_legal_floor_sections = (
        deepcopy(list(plan.get("legal_floor_sections") or ()))[:floor_count]
        if plan is not None
        else []
    )
    candidate_floor_top_heights = (
        [
            float(value)
            for value in (plan.get("floor_top_heights_m") or ())
        ][:floor_count]
        if plan is not None
        else [
            floor_step * (index + 1)
            for index in range(floor_count)
        ]
    )
    return {
        "schema_version": "arr.maas.feasible_base_capacity.v1",
        "status": "materialized" if feasible_maximum > 0.0 else "infeasible",
        "derivation": "per_floor_legal_section_sum_capped_by_ground_bcr_and_far",
        "parcel_area_m2": round(parcel_area, 3),
        "generation_site_area_m2": round(generation_area, 3),
        "requested_height_m": round(effective_height, 3),
        "requested_floors": floor_count,
        "floor_planning_mode": str(
            (plan or {}).get("planning_mode") or "legacy"
        ),
        "candidate_floor_count_authority": (
            "explicit_clear_span_dimensional_invariant"
            if (plan or {}).get("planning_mode") == "clear_span"
            else "legacy_floor_capacity_plan_compatibility"
        ),
        "candidate_legal_floor_sections": candidate_legal_floor_sections,
        "candidate_floor_top_heights_m": [
            round(value, 3) for value in candidate_floor_top_heights
        ],
        "legal_floor_section_areas_m2": [round(value, 3) for value in legal_floor_areas],
        "bcr_adjusted_floor_areas_m2": [round(value, 3) for value in bcr_adjusted_areas],
        "bcr_limit_pct": round(bcr_limit, 3),
        "far_limit_pct": round(far_limit, 3),
        "height_field_capacity_m2": round(height_field_capacity, 3),
        "far_capacity_m2": round(far_capacity, 3),
        "feasible_maximum_floor_area_m2": round(feasible_maximum, 3),
        "target_utilization": round(target_ratio, 4),
        "minimum_utilization": round(minimum_ratio, 4),
        "target_floor_area_m2": round(target_floor_area, 3),
        "target_floor_areas_m2": [
            round(value, 3) for value in plan_floor_targets
        ],
        "minimum_floor_area_m2": round(feasible_maximum * minimum_ratio, 3),
        "legal_field_target_yield_ratio": round(legal_field_yield_ratio, 4),
        "target_base_plan_area_m2": round(target_ground_plan, 3),
        "target_base_plan_coverage": round(
            min(0.95, target_ground_plan / generation_area),
            4,
        ),
        "statutory_far_is_not_assumed_reachable": True,
        "parking_rechecked_downstream": True,
        "floor_capacity_plan_hash": str(
            (plan or {}).get("floor_capacity_plan_hash") or ""
        ),
        "legal_floor_field_hash": str(
            (plan or {}).get("legal_floor_field_hash")
            or ""
        ),
        "legal_floor_field": legal_floor_field,
        "available_legal_floor_count": int(
            legal_floor_field.get("measured_usable_floor_count") or 0
        ),
        "floor_capacity_plan_status": str((plan or {}).get("status") or ""),
    }


def _plate_projection_coverage(
    plates: Any,
    *,
    capacity_contract: dict[str, Any] | None,
    tolerance_m2: float,
) -> dict[str, Any]:
    """Measure 건축면적 as the union of the plates, against the declared cap.

    The capacity comes from the contract's own parcel area and 건폐율 limit -
    the same product `legal_floor_field` certifies as
    `bcr_footprint_capacity_m2` - so this never invents a threshold. When the
    contract declares neither, there is nothing to measure against and the
    check reports that rather than passing silently.
    """

    contract = capacity_contract if isinstance(capacity_contract, dict) else {}
    try:
        parcel_area_m2 = float(contract.get("parcel_area_m2") or 0.0)
        bcr_limit_pct = float(contract.get("bcr_limit_pct") or 0.0)
    except (TypeError, ValueError):
        parcel_area_m2, bcr_limit_pct = 0.0, 0.0
    capacity_m2 = parcel_area_m2 * bcr_limit_pct / 100.0
    geometries = []
    for plate in plates or ():
        if not isinstance(plate, dict):
            continue
        raw = plate.get("occupied_geometry_utm")
        if not raw:
            continue
        try:
            geometry = shape(raw)
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        if geometry.is_valid and not geometry.is_empty:
            geometries.append(geometry)
    if not geometries or not isfinite(capacity_m2) or capacity_m2 <= 1e-9:
        return {
            "schema_version": "arr.maas.plate_projection_coverage.v1",
            "status": "unmeasurable",
            "measured_plate_count": len(geometries),
            "coverage_capacity_m2": round(capacity_m2, 3),
        }
    projected_area_m2 = float(unary_union(geometries).area)
    return {
        "schema_version": "arr.maas.plate_projection_coverage.v1",
        "status": "measured",
        "measured_plate_count": len(geometries),
        "projected_area_m2": round(projected_area_m2, 3),
        "coverage_capacity_m2": round(capacity_m2, 3),
        "exceeds_capacity": bool(
            projected_area_m2 > capacity_m2 + max(0.0, float(tolerance_m2))
        ),
    }


def evaluate_legal_capacity_authority(
    shared_floor_contract: dict[str, Any] | None,
    source_capacity_measurement: dict[str, Any] | None,
    capacity_contract: dict[str, Any] | None,
) -> dict[str, Any]:
    """Keep legal floor admissibility independent from capacity objectives."""

    from shapely import set_precision

    shared = (
        shared_floor_contract
        if isinstance(shared_floor_contract, dict)
        and shared_floor_contract.get("schema_version")
        == "arr.maas.shared_floor_contract.v1"
        else None
    )
    plates = shared.get("plates") if shared is not None else None
    shared_floor_measured = isinstance(plates, list) and bool(plates)
    failure_reasons = {
        str(reason)
        for reason in (shared.get("failure_reasons") or ())
    } if shared is not None else {"missing_shared_floor_contract"}
    capacity_only_failures = {
        "insufficient_clear_floor_depth",
        "insufficient_floor_area",
    }
    minimum_support_ratio = float(
        (shared or {}).get("minimum_support_ratio") or 0.20
    )

    minimum_positive_area_m2 = 1e-6
    occupied_area_match_tolerance_m2 = 0.002
    constructive_coordinate_grid_m = 1e-6
    minimum_legal_retention_ratio = 0.80
    numeric_comparison_epsilon = 1e-9
    support_threshold_source = (
        "shared_floor_contract.minimum_support_ratio"
        if shared is not None and shared.get("minimum_support_ratio") is not None
        else "legal_capacity_authority.default_minimum_support_ratio"
    )

    def assess_plate_legal_evidence(
        plate: Any,
        index: int,
    ) -> tuple[bool, dict[str, Any]]:
        reasons: list[str] = []
        measured_values: dict[str, Any] = {}
        record = {
            "floor_index": index,
            "reasons": reasons,
            "measured_values": measured_values,
            "thresholds": {
                "minimum_positive_area_m2": minimum_positive_area_m2,
                "occupied_area_match_tolerance_m2": occupied_area_match_tolerance_m2,
                "constructive_coordinate_grid_m": constructive_coordinate_grid_m,
                "minimum_legal_retention_ratio": minimum_legal_retention_ratio,
                "minimum_support_ratio": minimum_support_ratio,
            },
            "threshold_sources": {
                "minimum_positive_area_m2": "legal_capacity_authority.existing_numeric_contract",
                "occupied_area_match_tolerance_m2": "legal_capacity_authority.existing_numeric_contract",
                "constructive_coordinate_grid_m": "shared_floor_contract.intersection_grid_size",
                "minimum_legal_retention_ratio": "legal_capacity_authority.existing_recertification_policy",
                "minimum_support_ratio": support_threshold_source,
            },
        }
        if not isinstance(plate, dict):
            reasons.append("malformed_plate")
            return False, record

        record["floor"] = plate.get("floor")
        plate_failures = {
            str(reason)
            for reason in (plate.get("failure_reasons") or ())
        }
        record["contract_failure_reasons"] = sorted(plate_failures)
        declared_hard_pass = plate.get("hard_pass")
        measured_values["declared_hard_pass"] = declared_hard_pass
        if declared_hard_pass is not (not plate_failures):
            reasons.append("declared_plate_status_mismatch")

        try:
            legal = shape(plate["legal_geometry_utm"])
            occupied = shape(plate["occupied_geometry_utm"])
            gross_area = float(plate["gross_area_m2"])
            legal_retention = float(plate["legal_retention_ratio"])
            support_ratio = float(plate["support_ratio"])
        except (KeyError, TypeError, ValueError):
            reasons.append("malformed_plate")
            return False, record

        measured_values.update({
            "gross_area_m2": gross_area,
            "legal_retention_ratio": legal_retention,
            "support_ratio": support_ratio,
            "legal_polygon_is_empty": bool(legal.is_empty),
            "legal_polygon_is_valid": bool(legal.is_valid),
            "occupied_polygon_is_empty": bool(occupied.is_empty),
            "occupied_polygon_is_valid": bool(occupied.is_valid),
        })
        if not all(
            isfinite(value)
            for value in (gross_area, legal_retention, support_ratio)
        ) or gross_area <= minimum_positive_area_m2:
            reasons.append("malformed_plate")
        if legal.is_empty or not legal.is_valid:
            reasons.append("invalid_legal_polygon")
        if occupied.is_empty or not occupied.is_valid:
            reasons.append("invalid_occupied_polygon")

        if not occupied.is_empty and occupied.is_valid:
            occupied_area = float(occupied.area)
            occupied_area_delta = abs(occupied_area - gross_area)
            measured_values["occupied_area_m2"] = occupied_area
            measured_values["occupied_area_delta_m2"] = occupied_area_delta
            if occupied_area_delta > occupied_area_match_tolerance_m2:
                reasons.append("occupied_area_mismatch")
        if (
            not legal.is_empty
            and legal.is_valid
            and not occupied.is_empty
            and occupied.is_valid
        ):
            canonical_legal = set_precision(
                legal,
                constructive_coordinate_grid_m,
            )
            canonical_occupied = set_precision(
                occupied,
                constructive_coordinate_grid_m,
            )
            outside = canonical_occupied.difference(canonical_legal)
            outside_area = float(outside.area)
            outside_distances = [
                float(canonical_legal.distance(shape({
                    "type": "Point",
                    "coordinates": tuple(coordinate)[:2],
                })))
                for polygon in (
                    canonical_occupied.geoms
                    if hasattr(canonical_occupied, "geoms")
                    else (canonical_occupied,)
                )
                for ring in (
                    (polygon.exterior, *polygon.interiors)
                    if hasattr(polygon, "exterior")
                    else ()
                )
                for coordinate in ring.coords
            ]
            outside_distance = max(outside_distances, default=0.0)
            measured_values["occupied_outside_legal_area_m2"] = outside_area
            measured_values["occupied_outside_legal_distance_m"] = outside_distance
            buffered_legal = canonical_legal.buffer(
                constructive_coordinate_grid_m,
            )
            if not buffered_legal.covers(canonical_occupied):
                reasons.append("occupied_outside_legal_geometry")
        if legal_retention + numeric_comparison_epsilon < minimum_legal_retention_ratio:
            reasons.append("legal_retention_below_threshold")
        if index > 0 and support_ratio + numeric_comparison_epsilon < minimum_support_ratio:
            reasons.append("vertical_support_below_threshold")

        passes = not (plate_failures - capacity_only_failures) and not reasons
        return passes, record

    plate_assessments = [
        assess_plate_legal_evidence(plate, index)
        for index, plate in enumerate(plates or ())
    ]
    plates_recertified = bool(
        shared_floor_measured
        and all(passes for passes, _record in plate_assessments)
    )
    plate_recertification_failures = [
        record for passes, record in plate_assessments if not passes
    ]
    plate_recertification_failure_reasons = sorted({
        reason
        for record in plate_recertification_failures
        for reason in record.get("reasons", ())
    })
    # Every check above reads one plate at a time - its legal geometry, its
    # retention, its support. 건축면적 is not a per-plate quantity: it is the
    # horizontal projection of the *building* (건축법 시행령 제119조 제1항 제2호),
    # the union of the plates. Plates that sit side by side each pass their own
    # check while their union does not, so a mass measured 1.04x over the
    # coverage capacity on PNU 4115011300106840001 still certified with
    # `legal_hard_pass: True`. Measure the union here, against the capacity the
    # contract itself declares.
    coverage_projection = _plate_projection_coverage(
        plates,
        capacity_contract=capacity_contract,
        tolerance_m2=occupied_area_match_tolerance_m2,
    )
    if coverage_projection.get("exceeds_capacity") is True:
        plate_recertification_failure_reasons = sorted({
            *plate_recertification_failure_reasons,
            "coverage_projection_exceeds_capacity",
        })
    declared_hard_pass = (
        shared.get("hard_pass") if shared is not None else None
    )
    certified_contract_pass = bool(
        declared_hard_pass is True and not failure_reasons
    )
    capacity_only_advisory_override = bool(
        declared_hard_pass is False
        and failure_reasons
        and not (failure_reasons - capacity_only_failures)
    )
    legal_hard_pass = bool(
        plates_recertified
        and coverage_projection.get("exceeds_capacity") is not True
        and (certified_contract_pass or capacity_only_advisory_override)
    )

    measurement = (
        source_capacity_measurement
        if isinstance(source_capacity_measurement, dict)
        and source_capacity_measurement.get("schema_version")
        == "arr.maas.source_capacity_measurement.v1"
        else None
    )
    raw_utilization = (
        measurement.get("feasible_capacity_utilization")
        if measurement is not None
        else None
    )
    utilization = (
        float(raw_utilization)
        if isinstance(raw_utilization, (int, float))
        and isfinite(float(raw_utilization))
        else 0.0
    )
    contract = capacity_contract if isinstance(capacity_contract, dict) else {}
    target_utilization = float(contract.get("target_utilization") or 0.0)
    minimum_utilization = float(contract.get("minimum_utilization") or 0.0)
    if measurement is None:
        objective_status = "unavailable"
    elif utilization + 1e-9 < minimum_utilization:
        objective_status = "below"
    elif utilization > target_utilization + 1e-9:
        objective_status = "above"
    else:
        objective_status = "within"

    targets = contract.get("target_floor_areas_m2") or ()
    achieved = (
        tuple(
            float(plate.get("gross_area_m2") or 0.0)
            for plate in plates
            if isinstance(plate, dict)
        )
        if shared_floor_measured
        else ()
    )
    deltas = [
        round((achieved[index] if index < len(achieved) else 0.0) - float(target), 3)
        for index, target in enumerate(targets)
        if isinstance(target, (int, float))
    ]
    return {
        "legal_hard_pass": legal_hard_pass,
        "shared_floor_measured": shared_floor_measured,
        "feasible_capacity_utilization": round(utilization, 4),
        "capacity_objective_status": objective_status,
        "per_floor_target_deltas_m2": deltas,
        "revision_recommended": objective_status in {"below", "above"},
        "plate_recertification_failures": plate_recertification_failures,
        "plate_recertification_failure_reasons": plate_recertification_failure_reasons,
        "plate_projection_coverage": coverage_projection,
    }


def measure_source_capacity(
    source: SourceMass,
    contract: dict[str, Any],
    *,
    site_local_utm: Polygon,
    height_m: float,
    floors: int,
    shared_floor_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare one source graph with the same floorwise capacity contract."""
    shared = (
        shared_floor_contract
        if isinstance(shared_floor_contract, dict)
        and shared_floor_contract.get("schema_version") == "arr.maas.shared_floor_contract.v1"
        else None
    )
    if shared is not None:
        totals = shared.get("totals") if isinstance(shared.get("totals"), dict) else {}
        floor_area = float(totals.get("total_floor_area_m2") or 0.0)
    else:
        floor_count = max(1, int(floors))
        floor_area = 0.0
        for floor_index in range(floor_count):
            fraction = (floor_index + 0.5) / floor_count
            active = [
                volume.footprint
                for volume in source.volumes
                if float(volume.bottom_fraction) <= fraction < float(volume.top_fraction)
            ]
            if active:
                floor_area += float(unary_union(active).area)
    parcel_area = max(float(site_local_utm.area), 1e-9)
    feasible = max(float(contract.get("feasible_maximum_floor_area_m2") or 0.0), 1e-9)
    utilization = floor_area / feasible
    minimum = float(contract.get("minimum_utilization") or 0.0)
    minimum_floor_area = float(
        contract.get("minimum_floor_area_m2")
        or feasible * minimum
    )
    return {
        "schema_version": "arr.maas.source_capacity_measurement.v1",
        "floor_area_m2": round(floor_area, 3),
        "far_pct": round(floor_area / parcel_area * 100.0, 3),
        "feasible_maximum_floor_area_m2": round(feasible, 3),
        "feasible_capacity_utilization": round(utilization, 4),
        "minimum_utilization": round(minimum, 4),
        "area_measurement_tolerance_m2": (
            CAPACITY_AREA_MEASUREMENT_TOLERANCE_M2
        ),
        "floor_contract_hash": str((shared or {}).get("floor_contract_hash") or ""),
        "hard_pass": bool(
            floor_area + CAPACITY_AREA_MEASUREMENT_TOLERANCE_M2
            >= minimum_floor_area
            and (shared is None or shared.get("hard_pass") is True)
        ),
    }


def recursive_plan_coverage_floor(
    building_type: str,
    contract: dict[str, Any] | None = None,
    *,
    host_area_m2: float | None = None,
) -> float:
    """Translate the live capacity contract into a plan-fit floor.

    Program role coverage is already carried by the compiled source union in
    ``source_bridge``.  Keeping a second use-specific floor here enlarged only
    neighborhood forms and made capacity behavior inconsistent across gym,
    cultural and other programs.
    """
    del building_type
    capacity = contract or {}
    target_area = float(capacity.get("target_base_plan_area_m2") or 0.0)
    declared_coverage = float(
        capacity.get("target_base_plan_coverage") or 0.0
    )
    if host_area_m2 and float(host_area_m2) > 0.0 and target_area > 0.0:
        capacity_floor = target_area / float(host_area_m2)
        if declared_coverage > 0.0:
            # Serialized plan areas are rounded to millimetre-square
            # precision. Never let that rounding expand a declared legal
            # coverage (for example 92.638 / 102.930960... > 0.900000).
            capacity_floor = min(capacity_floor, declared_coverage)
    else:
        capacity_floor = declared_coverage
    return max(0.0, min(0.95, capacity_floor))


__all__ = [
    "build_feasible_capacity_contract",
    "measure_source_capacity",
    "recursive_plan_coverage_floor",
]
