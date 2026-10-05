"""One law-derived floor and area authority before MASS authoring.

The planner is deliberately geometry-author agnostic.  It measures the live
legal field, resolves the program's occupiable-floor range, and emits one
content-addressed plan consumed by BOOK/LLM generation and every downstream
gate.  It does not create a building shape.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from shapely.geometry import Polygon, mapping

from backend.app.modules.design.generation.maas.floor_viability import DEFAULT_MINIMUM_CLEAR_DEPTH_M, evaluate_floor_section_viability, minimum_usable_floor_area_m2
from backend.app.modules.design.generation.maas.program_massing.profiles import resolve_program_profile

from backend.app.modules.design.generation.maas.design_space import CoverageBand, coverage_band as resolve_coverage_band, plan_area_for_band

from backend.app.modules.design.generation.maas.book_language.downstream_hard_gate import LegalGenerationContext, generation_site_at_height
from backend.app.modules.design.generation.maas.book_language.legal_floor_field import materialize_legal_floor_field


SCHEMA_VERSION = "arr.maas.floor_capacity_plan.v1"


def derive_program_floor_capacity_plan(
    context: LegalGenerationContext,
    *,
    site_local_utm: Polygon,
    building_type: str,
    target_utilization: float,
    brief_height_cap_m: float | None = None,
    dimensional_context: Mapping[str, Any] | None = None,
    legacy_floor_hint: int | None = None,
    coverage_band: CoverageBand | str | None = None,
    pnu: str = "",
) -> dict[str, Any]:
    """Derive occupiable floors and per-floor GFA targets from the live law field.

    `coverage_band` decides how much ground the proposal takes, and the stack
    follows it: a plate bounded below the 건폐율 ceiling needs more floors to
    carry the same area. Without a band each floor may take the whole ceiling,
    the shortest stack that reaches capacity wins, and every proposal comes out
    at maximum coverage - 86 of 128 within one percent of it on PNU
    4115011300106840001, which is one axis where the portfolio needs two.
    """

    resolved_coverage_band = (
        None if coverage_band is None
        else coverage_band if isinstance(coverage_band, CoverageBand)
        else resolve_coverage_band(coverage_band)
    )
    profile = resolve_program_profile(building_type)
    program_id = str(profile.get("id") or "generic")
    raw_range = profile.get("target_floor_range") or (1, 40)
    profile_min = max(1, int(raw_range[0]))
    profile_max = max(profile_min, int(raw_range[-1]))
    envelope = context.envelope
    legal_floor_field = materialize_legal_floor_field(
        context,
        site_local_utm=site_local_utm,
        pnu=pnu,
    )
    typical_floor_height = max(0.1, float(envelope.floor_height))
    legal_height_cap = max(0.0, float(envelope.height_limit))
    if brief_height_cap_m is not None:
        legal_height_cap = min(legal_height_cap, max(0.0, float(brief_height_cap_m)))

    dimensional = dict(dimensional_context or {})
    clear_span_mode = bool(
        profile.get("dimensional_requirements")
        and dimensional.get("status") in {"adapted", "feasible"}
        and float(dimensional.get("effective_height_m") or 0.0) > 0.0
        and int(dimensional.get("effective_floors") or 0) > 0
    )
    if clear_span_mode:
        selected_count = min(
            profile_max,
            max(profile_min, int(dimensional["effective_floors"])),
        )
        selected_height = min(
            legal_height_cap,
            float(dimensional["effective_height_m"]),
        )
        if selected_height <= 0.0:
            return _infeasible_plan(
                program_id=program_id,
                planning_mode="clear_span",
                typical_floor_height=typical_floor_height,
                legal_height_cap=legal_height_cap,
                profile_range=(profile_min, profile_max),
                legacy_floor_hint=legacy_floor_hint,
                reasons=("clear_span_height_not_legal",),
            )
        floor_tops = tuple(
            selected_height * floor_number / selected_count
            for floor_number in range(1, selected_count + 1)
        )
        allowed_range = (selected_count, selected_count)
        planning_mode = "clear_span"
    else:
        legal_max = int(legal_height_cap / typical_floor_height)
        # A program profile's upper floor range is a design/retrieval hint,
        # not legal or capacity authority.  Capping the measured legal stack
        # here made neighborhood_living's historical [2, 8] range silently
        # declare an eight-storey "feasible maximum" even when live height,
        # floor sections and FAR required more floors.  Ordinary occupiable
        # floors must therefore enumerate the complete lawful height field.
        # Explicit clear-span dimensional programs remain handled above.
        allowed_max = legal_max
        if allowed_max < 1:
            return _infeasible_plan(
                program_id=program_id,
                planning_mode="occupiable_floors",
                typical_floor_height=typical_floor_height,
                legal_height_cap=legal_height_cap,
                profile_range=(profile_min, profile_max),
                legacy_floor_hint=legacy_floor_hint,
                reasons=("legal_height_below_one_occupiable_floor",),
            )
        allowed_range = (1, allowed_max)
        floor_tops = tuple(
            typical_floor_height * floor_number
            for floor_number in range(1, allowed_max + 1)
        )
        selected_height = 0.0
        selected_count = 0
        planning_mode = "occupiable_floors"

    parcel_area = max(float(site_local_utm.area), 1e-9)
    minimum_usable_area = minimum_usable_floor_area_m2(parcel_area)
    sections = []
    section_areas = []
    terminal_floor_exclusion_reasons: list[str] = []
    for top_height in floor_tops:
        if top_height > legal_height_cap + 1e-9:
            break
        section = generation_site_at_height(context, top_height)
        if section is None or section.is_empty:
            break
        viability = evaluate_floor_section_viability(
            section,
            parcel_area_m2=parcel_area,
        )
        if viability["hard_pass"] is not True:
            terminal_floor_exclusion_reasons = list(
                viability["failure_reasons"]
            )
            break
        sections.append(section)
        section_areas.append(float(section.area))

    required_count = allowed_range[0]
    if len(sections) < required_count:
        return _infeasible_plan(
            program_id=program_id,
            planning_mode=planning_mode,
            typical_floor_height=typical_floor_height,
            legal_height_cap=legal_height_cap,
            profile_range=(profile_min, profile_max),
            legacy_floor_hint=legacy_floor_hint,
            reasons=("legal_field_below_program_minimum_floors",),
        )

    bcr_limit = max(0.0, float(envelope.bcr_limit))
    far_limit = max(0.0, float(envelope.far_limit))
    bcr_cap = parcel_area * bcr_limit / 100.0
    far_cap = parcel_area * far_limit / 100.0
    # 건축면적 is the horizontal projection of the *building* - 건축법 시행령
    # 제119조 제1항 제2호, with 제4항 binding every other 수평투영면적 to the same
    # method. It is not the ground floor's area, so an upper plate that
    # overhangs the one below governs the coverage. Capping only index 0 was
    # therefore wrong twice over: it let upper plates exceed the coverage limit
    # outright, and because the capped vector is also the weight vector of a
    # proportional allocator, it shrank the ground floor's *share* instead of
    # its size and handed the difference upward. Measured on PNU
    # 4115011300106840001: caps [499.938, 1922.226, 1922.226] against a 1374.83
    # target produced [158.211, 608.310, 608.310] - a 4x cantilever whose 608
    # exceeds the 499.938 coverage cap - and every mass came out a plate.
    #
    # The 건폐율 cap is a ceiling, not a target. Taking all of it on every floor
    # is one proposal; holding the ground and going up is another, and the two
    # differ in the plate a floor may take. Bounding the plate here is what
    # makes the stack follow: the selection below picks the shortest stack that
    # carries the capacity, so a smaller plate simply needs more floors.
    plate_ceiling = (
        bcr_cap
        if resolved_coverage_band is None
        else plan_area_for_band(bcr_cap, resolved_coverage_band)
    )
    floor_caps = [min(area, plate_ceiling) for area in section_areas]
    feasible_maximum = min(sum(floor_caps), far_cap)
    utilization = max(0.0, min(1.0, float(target_utilization)))
    target_gfa = feasible_maximum * utilization

    if not clear_span_mode:
        # The area target already reserves ``1 - utilization`` of the full
        # legal capacity for voids, courts, terraces and circulation.  Picking
        # the first stack that merely reaches target_gfa consumes that reserve
        # as almost-solid plates (r262: 330.951 / 332.322 m2) and makes every
        # successful VLM carve fail capacity later.  Select the shortest stack
        # that carries the *full feasible capacity* instead; the target area
        # can then use its intended reserve without lowering any hard gate.
        designable_stack_capacity = feasible_maximum
        for count in range(allowed_range[0], len(floor_caps) + 1):
            if (
                min(sum(floor_caps[:count]), far_cap) + 1e-9
                >= designable_stack_capacity
            ):
                selected_count = count
                break
        if selected_count <= 0:
            selected_count = len(floor_caps)
        selected_height = selected_count * typical_floor_height

    selected_sections = sections[:selected_count]
    selected_section_areas = section_areas[:selected_count]
    selected_caps = floor_caps[:selected_count]
    selected_capacity = min(sum(selected_caps), far_cap)
    reachable = selected_capacity + 1e-9 >= target_gfa
    allocated_target = min(target_gfa, selected_capacity)
    target_floor_areas = allocate_floor_targets(selected_caps, allocated_target)
    selected_stack_target_utilization = (
        allocated_target / selected_capacity
        if selected_capacity > 1e-9
        else 0.0
    )

    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "materialized" if reachable else "target_unreachable",
        "derivation": (
            "pnu_legal_height_x_live_floor_sections_capped_by_bcr_far_"
            "with_program_range_as_advisory"
        ),
        "program_id": program_id,
        "building_type": str(building_type or ""),
        "planning_mode": planning_mode,
        "typical_floor_height_m": _round(typical_floor_height),
        "legal_height_cap_m": _round(legal_height_cap),
        "program_floor_range": [profile_min, profile_max],
        "ordinary_program_floor_range_is_authority": False,
        "allowed_floor_range": list(allowed_range),
        "selected_floor_count": selected_count,
        "measured_usable_floor_count": len(sections),
        "minimum_usable_floor_area_m2": _round(minimum_usable_area),
        "minimum_clear_floor_depth_m": DEFAULT_MINIMUM_CLEAR_DEPTH_M,
        "excluded_terminal_floor_count": max(
            0,
            len(floor_tops) - len(sections),
        ),
        "terminal_floor_exclusion_reasons": terminal_floor_exclusion_reasons,
        "selected_height_m": _round(selected_height),
        "floor_top_heights_m": [_round(value) for value in floor_tops[:selected_count]],
        "legal_floor_section_areas_m2": [
            _round(value) for value in selected_section_areas
        ],
        "legal_floor_sections": [
            mapping(section) for section in selected_sections
        ],
        "target_floor_areas_m2": [
            _round(value) for value in target_floor_areas
        ],
        "parcel_area_m2": _round(parcel_area),
        "bcr_limit_pct": _round(bcr_limit),
        "bcr_footprint_capacity_m2": _round(bcr_cap),
        "far_limit_pct": _round(far_limit),
        "statutory_far_capacity_m2": _round(far_cap),
        "feasible_maximum_gfa_m2": _round(feasible_maximum),
        "selected_stack_capacity_m2": _round(selected_capacity),
        "stack_selection_policy": "preserve_capacity_target_design_reserve",
        "target_utilization": round(utilization, 4),
        "design_reserve_ratio": round(1.0 - utilization, 4),
        "selected_stack_target_utilization": round(
            selected_stack_target_utilization,
            4,
        ),
        "target_gfa_m2": _round(allocated_target),
        "target_reachable": reachable,
        "failure_reasons": [] if reachable else ["target_gfa_unreachable"],
        "legacy_floor_hint": (
            int(legacy_floor_hint) if legacy_floor_hint is not None else None
        ),
        "legacy_hint_is_authority": False,
        "legal_floor_field_hash": str(
            legal_floor_field.get("legal_floor_field_hash") or ""
        ),
        "legal_floor_field": legal_floor_field,
        "clear_span_dimensional_context": dimensional if clear_span_mode else {},
    }
    payload["floor_capacity_plan_hash"] = _plan_hash(payload)
    return payload


def allocate_floor_targets(
    capacities: Sequence[float],
    target: float,
) -> list[float]:
    """Allocate target GFA proportionally, retaining reserve on every plate."""

    normalized = [max(0.0, float(value)) for value in capacities]
    total_capacity = sum(normalized)
    if total_capacity <= 1e-9:
        return [0.0 for _ in normalized]
    allocated = max(0.0, min(float(target), total_capacity))
    utilization = allocated / total_capacity
    return [capacity * utilization for capacity in normalized]


def _infeasible_plan(
    *,
    program_id: str,
    planning_mode: str,
    typical_floor_height: float,
    legal_height_cap: float,
    profile_range: tuple[int, int],
    legacy_floor_hint: int | None,
    reasons: Sequence[str],
) -> dict[str, Any]:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "infeasible",
        "derivation": "program_floor_range_x_legal_height_x_live_floor_sections",
        "program_id": program_id,
        "planning_mode": planning_mode,
        "typical_floor_height_m": _round(typical_floor_height),
        "legal_height_cap_m": _round(legal_height_cap),
        "program_floor_range": list(profile_range),
        "allowed_floor_range": [0, 0],
        "selected_floor_count": 0,
        "selected_height_m": 0.0,
        "floor_top_heights_m": [],
        "legal_floor_section_areas_m2": [],
        "legal_floor_sections": [],
        "target_floor_areas_m2": [],
        "target_gfa_m2": 0.0,
        "target_reachable": False,
        "failure_reasons": list(reasons),
        "legacy_floor_hint": (
            int(legacy_floor_hint) if legacy_floor_hint is not None else None
        ),
        "legacy_hint_is_authority": False,
    }
    payload["floor_capacity_plan_hash"] = _plan_hash(payload)
    return payload


def _plan_hash(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _round(value: float) -> float:
    return round(float(value), 3)


__all__ = [
    "SCHEMA_VERSION",
    "allocate_floor_targets",
    "derive_program_floor_capacity_plan",
]
