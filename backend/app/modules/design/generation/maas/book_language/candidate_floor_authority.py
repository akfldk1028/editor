"""Candidate-specific floor authority and capacity measurement.

This module owns trusted legal-floor identity validation. The legacy site
sampler is injected by the compatibility facade so existing monkeypatch seams
remain effective.
"""

from __future__ import annotations

from copy import deepcopy
from math import isfinite
from typing import Any, Callable

from shapely.geometry import Polygon, shape

from backend.app.modules.design.generation.maas.design_space import capacities_under_band, coverage_band as resolve_coverage_band
from backend.app.modules.design.generation.maas.shared_floor_contract import materialize_shared_floor_contract

from backend.app.modules.design.generation.maas.book_language.capacity_contract import measure_source_capacity
from backend.app.modules.design.generation.maas.book_language.legal_floor_field import validate_legal_floor_field

def _capacity_pack_retry_eligible(
    shared_floor_contract: dict[str, Any] | None,
) -> bool:
    """Return whether plan packing can repair the measured floor shortfall."""

    if not isinstance(shared_floor_contract, dict):
        return False
    if shared_floor_contract.get("hard_pass") is True:
        return True
    failures = set(shared_floor_contract.get("failure_reasons") or ())
    if failures - {"insufficient_clear_floor_depth", "insufficient_floor_area"}:
        return False
    plates = shared_floor_contract.get("plates")
    if not isinstance(plates, list) or not plates:
        return False
    return bool(
        all(float(plate.get("gross_area_m2") or 0.0) > 1e-6 for plate in plates)
        and all(
            index == 0 or float(plate.get("support_ratio") or 0.0) >= 0.20
            for index, plate in enumerate(plates)
        )
    )


def _capacity_retry_required(
    *,
    current_plan_coverage: float,
    retry_plan_coverage: float,
    current_floor_targets: Any,
    retry_floor_targets: Any,
) -> bool:
    """Retry when either the plan ratio or authoritative floor targets change."""

    current_targets = tuple(
        round(float(value), 3)
        for value in (current_floor_targets or ())
    )
    derived_targets = tuple(
        round(float(value), 3)
        for value in (retry_floor_targets or ())
    )
    return bool(
        float(retry_plan_coverage) > float(current_plan_coverage) + 1e-6
        or current_targets != derived_targets
    )


def _shared_floor_capacity_measurement(
    source: Any,
    base_capacity_contract: dict[str, Any],
    *,
    generation_context: Any,
    capacity_site: Polygon,
    height: float,
    floors: int,
    pnu: str = "",
    trusted_legal_floor_field: dict[str, Any] | None = None,
    expected_legal_floor_field_hash: str = "",
    trusted_clear_span_floor_plan: dict[str, Any] | None = None,
    generation_site_sampler: Callable[..., Polygon],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Measure candidate/retry capacity from the exact legal floor plates."""

    fallback_sections: tuple[Polygon | None, ...] = ()
    has_trusted_anchor = bool(
        trusted_legal_floor_field is not None
        or expected_legal_floor_field_hash
    )
    if (
        not has_trusted_anchor
        and not (
            base_capacity_contract.get("legal_floor_field")
            or base_capacity_contract.get("legal_floor_field_hash")
        )
    ):
        fallback_sections = tuple(
            generation_site_sampler(
                generation_context,
                float(height) * floor_number / max(1, int(floors)),
            )
            for floor_number in range(1, max(1, int(floors)) + 1)
        )
    floor_context = _candidate_floor_context(
        base_capacity_contract,
        fallback_height=height,
        fallback_floors=floors,
        fallback_legal_sections=fallback_sections,
        trusted_legal_floor_field=trusted_legal_floor_field,
        expected_legal_floor_field_hash=expected_legal_floor_field_hash,
        trusted_clear_span_floor_plan=trusted_clear_span_floor_plan,
    )
    if floor_context.get("hard_pass") is not True:
        return (
            {
                "schema_version": "arr.maas.shared_floor_contract.v1",
                "hard_pass": False,
                "failure_reasons": list(
                    floor_context.get("failure_reasons") or ()
                ),
            },
            {
                "schema_version": "arr.maas.source_capacity_measurement.v1",
                "hard_pass": False,
                "failure_reasons": list(
                    floor_context.get("failure_reasons") or ()
                ),
            },
        )
    candidate_height = float(floor_context["height_m"])
    candidate_floors = int(floor_context["floors"])
    bridge = (
        source.metadata.get("geometry_program_bridge_evidence")
        if isinstance(source.metadata.get("geometry_program_bridge_evidence"), dict)
        else {}
    )
    shared_floor_contract = materialize_shared_floor_contract(
        source,
        site_local_utm=capacity_site,
        legal_sections=tuple(floor_context["legal_sections"]),
        height_m=candidate_height,
        floors=candidate_floors,
        pnu=pnu,
        program_hash=str(bridge.get("program_hash") or ""),
        geometry_hash=str(bridge.get("geometry_hash") or ""),
        floor_capacity_plan_hash=str(
            base_capacity_contract.get("floor_capacity_plan_hash") or ""
        ),
        feasible_capacity_m2=float(
            base_capacity_contract.get("feasible_maximum_floor_area_m2")
            or 0.0
        ),
    )
    measurement = measure_source_capacity(
        source,
        base_capacity_contract,
        site_local_utm=capacity_site,
        height_m=candidate_height,
        floors=candidate_floors,
        shared_floor_contract=shared_floor_contract,
    )
    return shared_floor_contract, measurement


def _candidate_floor_context(
    capacity_contract: dict[str, Any] | None,
    *,
    fallback_height: float,
    fallback_floors: int,
    fallback_legal_sections: tuple[Polygon | None, ...] = (),
    trusted_legal_floor_field: dict[str, Any] | None = None,
    expected_legal_floor_field_hash: str = "",
    trusted_clear_span_floor_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve one candidate's exact legal prefix without height resampling."""

    def reject(reason: str) -> dict[str, Any]:
        return {
            "hard_pass": False,
            "status": reason,
            "failure_reasons": [reason],
        }

    def is_plain_number_type(value: Any) -> bool:
        return type(value) in {int, float}

    def is_plain_number(value: Any) -> bool:
        return is_plain_number_type(value) and isfinite(float(value))

    def is_plain_recursive(value: Any) -> bool:
        value_type = type(value)
        if value_type is dict:
            return all(
                type(key) is str and is_plain_recursive(item)
                for key, item in value.items()
            )
        if value_type in {list, tuple}:
            return all(is_plain_recursive(item) for item in value)
        if value is None or value_type in {str, bool}:
            return True
        return is_plain_number(value)

    def canonical_plain_polygon(value: Any) -> tuple[Any, ...] | None:
        """Return an internal tuple without invoking candidate equality."""

        if (
            type(value) is not dict
            or not all(type(key) is str for key in value)
            or frozenset(value) != {"type", "coordinates"}
            or type(value.get("type")) is not str
            or value.get("type") != "Polygon"
        ):
            return None
        coordinates = value.get("coordinates")
        if type(coordinates) not in {list, tuple} or not coordinates:
            return None
        canonical_rings: list[tuple[Any, ...]] = []
        for ring in coordinates:
            if type(ring) not in {list, tuple} or len(ring) < 4:
                return None
            canonical_points: list[tuple[Any, ...]] = []
            for point in ring:
                if (
                    type(point) not in {list, tuple}
                    or len(point) != 2
                    or not all(is_plain_number(value) for value in point)
                ):
                    return None
                canonical_points.append((
                    "list" if type(point) is list else "tuple",
                    float(point[0]),
                    float(point[1]),
                ))
            canonical_rings.append((
                "list" if type(ring) is list else "tuple",
                tuple(canonical_points),
            ))
        return (
            "Polygon",
            "list" if type(coordinates) is list else "tuple",
            tuple(canonical_rings),
        )

    if capacity_contract is not None and type(capacity_contract) is not dict:
        return reject("invalid_candidate_contract_schema")
    contract = capacity_contract or {}
    legal_field = contract.get("legal_floor_field")
    has_field_identity = bool(
        legal_field or contract.get("legal_floor_field_hash")
    )
    has_trusted_anchor = bool(
        trusted_legal_floor_field is not None
        or expected_legal_floor_field_hash
    )
    if has_trusted_anchor and not has_field_identity:
        return reject("missing_candidate_legal_floor_identity")
    if has_field_identity:
        trusted_field = (
            trusted_legal_floor_field
            if type(trusted_legal_floor_field) is dict
            else None
        )
        trusted_hash = str(expected_legal_floor_field_hash or "")
        if (
            trusted_field is None
            or not trusted_hash
            or not is_plain_recursive(trusted_field)
            or not validate_legal_floor_field(trusted_field)
            or str(
                trusted_field.get("legal_floor_field_hash") or ""
            )
            != trusted_hash
        ):
            return reject("missing_trusted_legal_floor_field_authority")
        if not is_plain_recursive(legal_field):
            return reject("invalid_legal_floor_field_container_schema")
        if not validate_legal_floor_field(legal_field):
            return reject("invalid_legal_floor_field")
        legal_hash = str(legal_field.get("legal_floor_field_hash") or "")
        if legal_hash != trusted_hash:
            return reject("untrusted_legal_floor_field_identity")
        if (
            str(contract.get("legal_floor_field_hash") or "")
            != legal_hash
            or str(
                contract.get("candidate_legal_floor_field_hash") or ""
            )
            != legal_hash
        ):
            return reject("legal_floor_field_identity_mismatch")
        if contract.get("candidate_target_reachable") is not True:
            return reject("candidate_target_unreachable")

        raw_target = contract.get("candidate_target_gfa_m2")
        raw_target_alias = contract.get("target_floor_area_m2")
        if (
            not is_plain_number_type(raw_target)
            or not is_plain_number_type(raw_target_alias)
        ):
            return reject("invalid_candidate_target_gfa_schema")
        target = float(raw_target)
        target_alias = float(raw_target_alias)
        if (
            not isfinite(target)
            or not isfinite(target_alias)
            or target <= 0.0
        ):
            return reject("invalid_candidate_target_gfa")
        if (
            not isfinite(target_alias)
            or abs(target_alias - target) > 0.002
        ):
            return reject("candidate_target_gfa_identity_mismatch")
        raw_floors = contract.get("requested_floors")
        if type(raw_floors) is not int or raw_floors <= 0:
            return reject("invalid_candidate_requested_floors")
        floors = raw_floors
        raw_sections = contract.get("candidate_legal_floor_sections")
        raw_tops = contract.get("candidate_floor_top_heights_m")
        raw_areas = contract.get("legal_floor_section_areas_m2")
        raw_capacities = contract.get("bcr_adjusted_floor_areas_m2")
        target_areas = contract.get("target_floor_areas_m2")
        if (
            floors <= 0
            or type(raw_sections) is not list
            or type(raw_tops) is not list
            or type(raw_areas) is not list
            or type(raw_capacities) is not list
            or type(target_areas) is not list
        ):
            return reject("invalid_candidate_floor_vector_schema")
        if (
            len(raw_sections) != floors
            or len(raw_tops) != floors
            or len(raw_areas) != floors
            or len(raw_capacities) != floors
            or len(target_areas) != floors
        ):
            return reject("candidate_floor_prefix_mismatch")

        clear_span = (
            contract.get("floor_planning_mode") == "clear_span"
            or contract.get("candidate_floor_count_authority")
            == "explicit_clear_span_dimensional_invariant"
        )
        if clear_span:
            trusted_plan = (
                trusted_clear_span_floor_plan
                if type(trusted_clear_span_floor_plan) is dict
                else None
            )
            if trusted_plan is None:
                return reject("missing_trusted_clear_span_floor_plan")
            trusted_sections = trusted_plan.get(
                "legal_floor_sections"
            )
            trusted_tops = trusted_plan.get("floor_top_heights_m")
            trusted_areas = trusted_plan.get(
                "legal_floor_section_areas_m2"
            )
            if (
                type(trusted_sections) is not list
                or type(trusted_tops) is not list
                or type(trusted_areas) is not list
            ):
                return reject("invalid_trusted_clear_span_floor_plan")
            raw_expected_floors = trusted_plan.get(
                "selected_floor_count"
            )
            raw_expected_height = trusted_plan.get(
                "selected_height_m"
            )
            raw_bcr_cap = trusted_plan.get(
                "bcr_footprint_capacity_m2"
            )
            if (
                type(raw_expected_floors) is not int
                or raw_expected_floors <= 0
                or not is_plain_number(raw_expected_height)
                or not is_plain_number(raw_bcr_cap)
            ):
                return reject("invalid_trusted_clear_span_floor_plan")
            expected_floors = raw_expected_floors
            expected_height = float(raw_expected_height)
            bcr_cap = float(raw_bcr_cap)
            if not all(is_plain_number(value) for value in trusted_areas):
                return reject("invalid_trusted_clear_span_floor_plan")
            trusted_capacities = [
                # Coverage bounds every plate, not only the ground one: it is
                # the building's horizontal projection (건축법 시행령 제119조
                # 제1항 제2호).
                # Coverage bounds every plate, not only the ground one: it is
                # the building's horizontal projection (건축법 시행령 제119조
                # 제1항 제2호).
                min(float(value), bcr_cap)
                for value in trusted_areas
            ]
        else:
            trusted_sections = trusted_field.get(
                "legal_floor_sections"
            )
            trusted_tops = trusted_field.get(
                "legal_floor_top_heights_m"
            )
            trusted_areas = trusted_field.get(
                "legal_floor_section_areas_m2"
            )
            trusted_capacities = trusted_field.get(
                "bcr_adjusted_floor_capacities_m2"
            )
            # A candidate may declare how much ground it takes, and the prefix
            # it is then held to is the minimum one *under that ground take*.
            # This stays fail-closed: the band is one of a fixed set of legal
            # fractions, the capacity it scales is the trusted field's own
            # 건폐율 capacity, and the prefix is still recomputed here rather
            # than believed. Without this, holding the ground made every
            # candidate's honest prefix disagree with the one authority that
            # re-derives it, and 24 of 30 masses died before compiling with
            # candidate_floor_count_not_minimum_legal_prefix.
            declared_band_id = contract.get("coverage_band_id")
            if declared_band_id is not None:
                if type(declared_band_id) is not str:
                    return reject("invalid_candidate_coverage_band_schema")
                try:
                    declared_band = resolve_coverage_band(declared_band_id)
                except KeyError:
                    return reject("unknown_candidate_coverage_band")
                raw_ground_capacity = trusted_field.get(
                    "bcr_footprint_capacity_m2"
                )
                if (
                    not is_plain_number(raw_ground_capacity)
                    or float(raw_ground_capacity) <= 0.0
                ):
                    return reject("invalid_trusted_coverage_capacity")
                if type(trusted_capacities) not in {list, tuple}:
                    return reject("invalid_trusted_floor_capacity_vector")
                trusted_capacities = capacities_under_band(
                    trusted_capacities,
                    ground_capacity_m2=float(raw_ground_capacity),
                    band=declared_band,
                )
            reserve_stack_authority = bool(
                contract.get("candidate_floor_count_authority")
                == "full_lawful_design_reserve_stack_for_spatial_reserve"
                and contract.get("capacity_alternative_id")
                == "spatial_reserve"
            )
            if reserve_stack_authority:
                expected_floors = (
                    len(trusted_capacities)
                    if sum(
                        float(capacity)
                        for capacity in trusted_capacities
                    ) + 1e-9 >= target
                    else 0
                )
            else:
                cumulative = 0.0
                expected_floors = 0
                for index, capacity in enumerate(trusted_capacities):
                    cumulative += float(capacity)
                    if cumulative + 1e-9 >= target:
                        expected_floors = index + 1
                        break
            expected_height = (
                float(trusted_tops[expected_floors - 1])
                if expected_floors > 0
                else 0.0
            )
        if expected_floors <= 0 or floors != expected_floors:
            return reject(
                "candidate_floor_count_not_minimum_legal_prefix"
            )
        expected_sections = trusted_sections[:floors]
        expected_tops = [float(value) for value in trusted_tops[:floors]]
        expected_areas = [float(value) for value in trusted_areas[:floors]]
        expected_capacities = [
            float(value) for value in trusted_capacities[:floors]
        ]
        raw_claimed_prefix_capacity = contract.get(
            "candidate_prefix_capacity_m2"
        )
        if not is_plain_number(raw_claimed_prefix_capacity):
            return reject(
                "candidate_prefix_capacity_identity_mismatch"
            )
        claimed_prefix_capacity = float(
            raw_claimed_prefix_capacity
        )
        if (
            not isfinite(claimed_prefix_capacity)
            or abs(
                claimed_prefix_capacity - sum(expected_capacities)
            )
            > 0.002
        ):
            return reject(
                "candidate_prefix_capacity_identity_mismatch"
            )
        if (
            len(expected_sections) != floors
            or len(expected_tops) != floors
            or len(expected_areas) != floors
            or len(expected_capacities) != floors
        ):
            return reject("candidate_legal_floor_prefix_mismatch")
        candidate_section_identity: list[tuple[Any, ...]] = []
        trusted_section_identity: list[tuple[Any, ...]] = []
        for raw_section, expected_section in zip(
            raw_sections,
            expected_sections,
        ):
            candidate_identity = canonical_plain_polygon(raw_section)
            if candidate_identity is None:
                return reject("invalid_candidate_legal_section_schema")
            trusted_identity = canonical_plain_polygon(expected_section)
            if trusted_identity is None:
                return reject("invalid_trusted_legal_section_schema")
            candidate_section_identity.append(candidate_identity)
            trusted_section_identity.append(trusted_identity)
        if candidate_section_identity != trusted_section_identity:
            return reject("candidate_legal_floor_prefix_mismatch")
        if not all(
            is_plain_number_type(value) for value in raw_tops
        ):
            return reject("invalid_candidate_floor_top_schema")
        if not all(
            is_plain_number_type(value) for value in raw_areas
        ):
            return reject("invalid_candidate_floor_area_schema")
        if not all(
            is_plain_number_type(value) for value in raw_capacities
        ):
            return reject("invalid_candidate_floor_capacity_schema")
        if not all(
            is_plain_number_type(value) for value in target_areas
        ):
            return reject("invalid_candidate_floor_target_schema")
        raw_height = contract.get("requested_height_m")
        if not is_plain_number_type(raw_height):
            return reject("invalid_candidate_requested_height_schema")
        try:
            sections: list[Polygon] = []
            for raw_section in expected_sections:
                section = shape(raw_section)
                if (
                    not isinstance(section, Polygon)
                    or section.is_empty
                    or not section.is_valid
                    or float(section.area) <= 1e-9
                ):
                    raise ValueError("invalid candidate legal section")
                sections.append(section)
            tops = tuple(float(value) for value in raw_tops)
            areas = tuple(float(value) for value in raw_areas)
            capacities = tuple(
                float(value) for value in raw_capacities
            )
            targets = tuple(float(value) for value in target_areas)
            height = float(raw_height)
        except (TypeError, ValueError):
            return reject("invalid_candidate_floor_prefix")
        if (
            not all(isfinite(value) for value in tops)
            or not isfinite(height)
        ):
            return reject("invalid_candidate_floor_heights")
        if not all(isfinite(value) for value in areas):
            return reject("invalid_candidate_floor_area_vector")
        if not all(isfinite(value) for value in capacities):
            return reject("invalid_candidate_floor_capacity_vector")
        if not all(isfinite(value) for value in targets):
            return reject("invalid_candidate_floor_target_vector")
        if any(
            abs(actual - expected) > 0.002
            for actual, expected in zip(tops, expected_tops)
        ):
            return reject("candidate_floor_top_prefix_mismatch")
        if any(
            abs(actual - expected) > 0.002
            for actual, expected in zip(areas, expected_areas)
        ):
            return reject("candidate_floor_area_prefix_mismatch")
        if any(
            abs(actual - expected) > 0.002
            for actual, expected in zip(
                capacities,
                expected_capacities,
            )
        ):
            return reject("candidate_floor_capacity_prefix_mismatch")
        if (
            not all(isfinite(value) and value > 0.0 for value in tops)
            or any(right <= left for left, right in zip(tops, tops[1:]))
            or not isfinite(height)
            or height <= 0.0
            or abs(height - expected_height) > 0.002
        ):
            return reject("invalid_candidate_floor_heights")
        if not all(
            isfinite(value) and value > 0.0 for value in targets
        ):
            return reject("invalid_candidate_floor_target_vector")
        if any(
            value > capacity + 0.002
            for value, capacity in zip(targets, expected_capacities)
        ):
            return reject(
                "candidate_floor_target_exceeds_trusted_capacity"
            )
        if abs(sum(targets) - target) > 0.002:
            return reject("candidate_floor_target_sum_mismatch")
        return {
            "hard_pass": True,
            "status": "materialized",
            "height_m": height,
            "floors": floors,
            "legal_sections": tuple(sections),
            # Keep the ground-floor legal area on the same candidate-specific
            # authority as the polygons. Recursive BOOK compilation may use a
            # smaller upper section as its temporary host; that host area is
            # not a valid denominator for final ground coverage.
            "legal_floor_section_areas_m2": areas,
            "floor_top_heights_m": tops,
            "upper_legal_section": sections[-1],
            "legal_floor_field_hash": legal_hash,
            "authority": str(
                contract.get("candidate_floor_count_authority") or ""
            ),
        }

    fallback_count = max(1, int(fallback_floors))
    fallback_sections = tuple(fallback_legal_sections)
    if len(fallback_sections) != fallback_count:
        return {
            "hard_pass": False,
            "status": "legacy_floor_context_missing",
            "failure_reasons": ["legacy_floor_context_missing"],
        }
    return {
        "hard_pass": True,
        "status": "legacy_fallback",
        "height_m": float(fallback_height),
        "floors": fallback_count,
        "legal_sections": fallback_sections,
        "legal_floor_section_areas_m2": tuple(
            float(section.area)
            if isinstance(section, Polygon) and not section.is_empty
            else 0.0
            for section in fallback_sections
        ),
        "floor_top_heights_m": tuple(
            float(fallback_height) * (index + 1) / fallback_count
            for index in range(fallback_count)
        ),
        "upper_legal_section": fallback_sections[-1],
        "legal_floor_field_hash": "",
        "authority": "legacy_resampled_floor_context",
    }


def _compact_candidate_capacity_evidence(
    capacity_contract: dict[str, Any] | None,
) -> dict[str, Any]:
    """Keep candidate identity without duplicating the full legal polygon field."""

    contract = (
        capacity_contract
        if isinstance(capacity_contract, dict)
        else {}
    )
    return {
        key: deepcopy(value)
        for key, value in contract.items()
        if key not in {
            "legal_floor_field",
            "candidate_legal_floor_sections",
        }
    }
