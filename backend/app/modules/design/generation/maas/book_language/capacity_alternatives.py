"""Site-derived FAR alternatives between program projection and hard gates.

The alternatives in this module are not additional building typologies and do
not author parcel geometry.  They derive several utilization targets from one
measured feasible-capacity contract, then ask the existing geometry compiler
to fit the same typed form language to the corresponding plan-area target.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from math import isfinite
from typing import Any

from backend.app.modules.design.generation.maas.design_space import CoverageBand, capacities_under_band, coverage_band as resolve_coverage_band, plan_area_for_band

from backend.app.modules.design.generation.maas.book_language.floor_capacity_plan import allocate_floor_targets
from backend.app.modules.design.generation.maas.book_language.legal_floor_field import validate_legal_floor_field


CAPACITY_ALTERNATIVE_SCHEMA = "arr.maas.capacity_alternative.v1"


@dataclass(frozen=True)
class CapacityAlternativeSpec:
    alternative_id: str
    label: str
    intent: str
    target_rule: str

    def to_manifest_item(self) -> dict[str, Any]:
        return {
            "id": self.alternative_id,
            "label": self.label,
            "intent": self.intent,
            "target_rule": self.target_rule,
            "generation_scope": "post_program_pre_hard_gate",
        }


CAPACITY_ALTERNATIVE_SPECS = (
    CapacityAlternativeSpec(
        "spatial_reserve",
        "Spatial reserve",
        "retain the feasible minimum while preserving void and public-space capacity",
        "feasible_minimum",
    ),
    CapacityAlternativeSpec(
        "balanced_yield",
        "Balanced yield",
        "split the interval between feasible minimum and the program brief target",
        "midpoint_of_minimum_and_brief_target",
    ),
    CapacityAlternativeSpec(
        "brief_target",
        "Brief target",
        "fit the typed form to the program-aware target utilization",
        "program_brief_target",
    ),
    CapacityAlternativeSpec(
        "maximum_feasible",
        "Maximum feasible",
        "test the upper design-yield band while retaining exact legal, parking and public-space gates",
        "midpoint_of_program_target_and_feasible_ceiling",
    ),
)

_SPEC_BY_ID = {spec.alternative_id: spec for spec in CAPACITY_ALTERNATIVE_SPECS}


def _resolve_band(
    coverage_band: CoverageBand | str | None,
) -> CoverageBand | None:
    if coverage_band is None:
        return None
    if isinstance(coverage_band, CoverageBand):
        return coverage_band
    return resolve_coverage_band(coverage_band)


def coverage_band_of_alternative(
    alternative: dict[str, Any] | None,
) -> CoverageBand | None:
    """Recover the ground take an alternative was built with.

    The band travels inside the alternative it produced, so every consumer of
    that alternative reads the same ground take without a second cursor and
    without a wider signature.
    """

    evidence = (alternative or {}).get("coverage_band")
    if not isinstance(evidence, dict):
        return None
    band_id = str(evidence.get("band_id") or "")
    if not band_id:
        return None
    try:
        return resolve_coverage_band(band_id)
    except KeyError:
        return None


def _lawful_stack_under_band(
    contract: dict[str, Any],
    band: CoverageBand,
) -> tuple[list[float], float] | None:
    """Return the plates and total GFA the lawful stack carries under one band.

    The whole lawful stack is read here, not the prefix the run happened to
    select: holding the ground is answered by going up, and that answer only
    exists if the floors above the run's own selection are still on the table.
    """

    field = contract.get("legal_floor_field")
    if not isinstance(field, dict):
        return None
    capacities = field.get("bcr_adjusted_floor_capacities_m2")
    if not isinstance(capacities, (list, tuple)) or not capacities:
        return None
    ground_capacity = max(
        0.0,
        float(field.get("bcr_footprint_capacity_m2") or 0.0),
    )
    if ground_capacity <= 1e-9:
        return None
    bounded = capacities_under_band(
        capacities,
        ground_capacity_m2=ground_capacity,
        band=band,
    )
    total = sum(bounded)
    far_capacity = max(0.0, float(field.get("statutory_far_capacity_m2") or 0.0))
    if far_capacity > 1e-9:
        total = min(total, far_capacity)
    return bounded, total


def capacity_alternative_catalog() -> list[dict[str, Any]]:
    return [spec.to_manifest_item() for spec in CAPACITY_ALTERNATIVE_SPECS]


def capacity_alternative_for_lattice_index(index: int) -> CapacityAlternativeSpec:
    """Stratify the existing variation lattice without multiplying live VLM calls."""

    return CAPACITY_ALTERNATIVE_SPECS[int(index) % len(CAPACITY_ALTERNATIVE_SPECS)]


def capacity_alternative_for_host(
    index: int,
    base_contract: dict[str, Any] | None,
    *,
    host_area_m2: float,
    floor_count: int,
) -> CapacityAlternativeSpec:
    """Cycle only targets that the current legal generation host can reach.

    Some variations are intentionally born in a smaller sunlight-safe upper
    section. Assigning the near-maximum parcel target to that host by raw index
    creates a mathematically impossible candidate before geometry language is
    considered. This upper bound uses only host area, floor count and the
    measured feasible-capacity denominator; exact mesh capacity remains a
    downstream hard gate.
    """

    contract = base_contract or {}
    feasible_maximum = max(
        0.0,
        float(contract.get("feasible_maximum_floor_area_m2") or 0.0),
    )
    if feasible_maximum <= 1e-9:
        return capacity_alternative_for_lattice_index(index)
    host_capacity_upper_bound = (
        max(0.0, float(host_area_m2))
        * max(1, int(floor_count))
        / feasible_maximum
    )
    reachable = tuple(
        spec
        for spec in CAPACITY_ALTERNATIVE_SPECS
        if float(build_capacity_alternative(contract, spec)["target_utilization"])
        <= host_capacity_upper_bound + 1e-9
    )
    choices = reachable or (CAPACITY_ALTERNATIVE_SPECS[0],)
    return choices[int(index) % len(choices)]


def build_capacity_alternative(
    base_contract: dict[str, Any] | None,
    alternative: CapacityAlternativeSpec | str,
    *,
    coverage_band: CoverageBand | str | None = None,
) -> dict[str, Any]:
    """Derive one target from measured site capacity, never a freehand ratio.

    `coverage_band` chooses how much ground the proposal takes. Without one the
    plan stays a consequence of the floor-area target, which is what made every
    delivered mass fill the plan to the legal ceiling - 86 of 128 within one
    percent of it - and gave the portfolio one axis where it needs two.
    """

    spec = _SPEC_BY_ID[str(alternative)] if isinstance(alternative, str) else alternative
    contract = base_contract or {}
    minimum = max(0.0, min(0.98, float(contract.get("minimum_utilization") or 0.0)))
    brief_target = max(
        minimum,
        min(0.98, float(contract.get("target_utilization") or minimum)),
    )
    # The upper design band is derived from the live program target and the
    # measured feasible ceiling.  A fixed 0.98 target made virtually every
    # expressive/voided form fail and left only legal-envelope-shaped boxes.
    # Taking the remaining interval's midpoint keeps the alternative truly
    # above the brief while leaving a measured design reserve for the same
    # public threshold, void and parking gates used by every other band.
    maximum_design_yield = brief_target + (1.0 - brief_target) * 0.5
    # Spatial reserve is the release floor itself.  Raising it even slightly can
    # cross a discrete floor-capacity boundary: on the live Gangnam parcel,
    # 60% fits in two lawful plates while 62.5% adds a third sunlight-setback
    # plate and overwrites authored courts, wings and bars with one wedge.
    # Public-space operations remain measured downstream; they must fit inside
    # this target instead of silently increasing the target that names itself
    # ``feasible_minimum``.
    spatial_reserve_target = minimum
    targets = {
        "spatial_reserve": spatial_reserve_target,
        "balanced_yield": minimum + (brief_target - minimum) * 0.5,
        "brief_target": brief_target,
        "maximum_feasible": maximum_design_yield,
    }
    target = max(minimum, min(0.98, targets[spec.alternative_id]))
    unbounded_feasible_maximum = max(
        0.0,
        float(contract.get("feasible_maximum_floor_area_m2") or 0.0),
    )
    resolved_band = _resolve_band(coverage_band)
    # A band that holds the ground lowers what the lawful stack can carry, and
    # the height field is finite: on a low-rise parcel, 45% of the ground simply
    # cannot reach the same GFA however many lawful floors are used. Holding the
    # utilization against the *maximal* capacity would therefore make every
    # dispersed proposal unreachable and quietly delete that corner of the grid.
    # Holding it against this band's own capacity keeps the corner and states the
    # honest consequence instead: a scheme that takes less ground is a smaller
    # building, which is exactly the trade an architect is choosing between.
    bounded_stack = (
        None if resolved_band is None
        else _lawful_stack_under_band(contract, resolved_band)
    )
    feasible_maximum = (
        unbounded_feasible_maximum
        if bounded_stack is None
        else min(unbounded_feasible_maximum, bounded_stack[1])
    )
    floor_count = max(1, int(contract.get("requested_floors") or 1))
    generation_area = max(
        0.0,
        float(contract.get("generation_site_area_m2") or 0.0),
    )
    target_floor_area = feasible_maximum * target
    height_field_capacity = max(
        0.0,
        float(contract.get("height_field_capacity_m2") or feasible_maximum),
    )
    legal_field_yield_ratio = (
        min(1.0, target_floor_area / height_field_capacity)
        if height_field_capacity > 1e-9
        else 0.0
    )
    bcr_floor_areas = contract.get("bcr_adjusted_floor_areas_m2")
    ground_capacity = (
        max(0.0, float(bcr_floor_areas[0]))
        if isinstance(bcr_floor_areas, list) and bcr_floor_areas
        else generation_area
    )
    # Without a band the plan follows the floor-area target and lands on the
    # 건폐율 ceiling whenever that target is demanding. With one it is chosen,
    # and the band is a fraction of the same certified capacity, so a smaller
    # plate is legal by the same evidence as a full one.
    derived_plan_area = ground_capacity * legal_field_yield_ratio
    target_plan_area = (
        derived_plan_area
        if resolved_band is None
        else plan_area_for_band(ground_capacity, resolved_band)
    )
    target_plan_coverage = (
        min(0.95, target_plan_area / generation_area)
        if generation_area > 1e-9
        else 0.0
    )
    return {
        "schema_version": CAPACITY_ALTERNATIVE_SCHEMA,
        "alternative_id": spec.alternative_id,
        "label": spec.label,
        "intent": spec.intent,
        "target_rule": spec.target_rule,
        "stage": "post_program_pre_hard_gate",
        "feasible_minimum_utilization": round(minimum, 4),
        "program_brief_target_utilization": round(brief_target, 4),
        "target_utilization": round(target, 4),
        "feasible_maximum_floor_area_m2": round(feasible_maximum, 3),
        "target_floor_area_m2": round(target_floor_area, 3),
        "legal_field_target_yield_ratio": round(legal_field_yield_ratio, 4),
        "target_base_plan_area_m2": round(target_plan_area, 3),
        "target_base_plan_coverage": round(target_plan_coverage, 4),
        "coverage_band": (
            resolved_band.evidence() if resolved_band is not None else None
        ),
        "ground_take_bounds_the_stack": bounded_stack is not None,
        "unbounded_feasible_maximum_floor_area_m2": round(
            unbounded_feasible_maximum,
            3,
        ),
        "floor_area_derived_plan_area_m2": round(derived_plan_area, 3),
        "projection_mode": "typed_form_plan_fit",
        "hard_gates_remain_downstream": True,
        "legal_floor_field_hash": str(
            contract.get("legal_floor_field_hash") or ""
        ),
    }


def capacity_contract_for_alternative(
    base_contract: dict[str, Any] | None,
    alternative: dict[str, Any],
) -> dict[str, Any]:
    """Return a projected copy consumable by the existing source bridge."""

    projected = deepcopy(base_contract or {})
    _apply_candidate_floor_prefix(
        projected,
        target=float(alternative.get("target_floor_area_m2") or 0.0),
        coverage_band=coverage_band_of_alternative(alternative),
        # Spatial reserve intentionally distributes the minimum total GFA over
        # the complete lawful design stack. Packing the same 60% aggregate
        # into the minimum two-floor prefix demanded roughly 97% of each live
        # plate on the Gangnam parcel, leaving no room for courts, wings or a
        # continuous section and forcing every survivor toward the envelope.
        # Higher-yield alternatives still use their minimum required prefix.
        preserve_full_lawful_stack=(
            str(alternative.get("alternative_id") or "")
            == "spatial_reserve"
        ),
    )
    target_floor_areas = _alternative_floor_targets(
        projected,
        target=float(alternative.get("target_floor_area_m2") or 0.0),
    )
    projected.update({
        "target_utilization": alternative.get("target_utilization", 0.0),
        "target_floor_area_m2": alternative.get("target_floor_area_m2", 0.0),
        "target_floor_areas_m2": target_floor_areas,
        "target_base_plan_area_m2": alternative.get(
            "target_base_plan_area_m2", 0.0
        ),
        "target_base_plan_coverage": alternative.get(
            "target_base_plan_coverage", 0.0
        ),
        "capacity_alternative_id": alternative.get("alternative_id", ""),
        "floor_target_distribution": (
            "proportional_across_candidate_prefix_for_authored_fit"
        ),
    })
    return projected


def _apply_candidate_floor_prefix(
    contract: dict[str, Any],
    *,
    target: float,
    preserve_full_lawful_stack: bool = False,
    coverage_band: CoverageBand | None = None,
) -> None:
    """Select the minimum lawful prefix that can carry one candidate target.

    `coverage_band` bounds every plate before the prefix is chosen, so a scheme
    that holds the ground asks the stack for the difference. The plates written
    back are what the candidate is certified against and what the geometry fit
    reads as its floor targets, which is why bounding them here - rather than
    only recording the intended plan area - is what moves the delivered form.
    """

    requested = float(target)
    original_requested_floors = contract.get("requested_floors")
    if not isfinite(requested) or requested <= 0.0:
        contract["candidate_floor_count_authority"] = (
            "invalid_candidate_target"
        )
        contract["candidate_target_reachable"] = False
        contract["candidate_target_gfa_m2"] = requested
        return

    # A clear-span program fixes its floor count as a dimensional invariant, so
    # the stack cannot answer a ground take by growing and bounding the plates
    # would only shrink the building against a count it may not change. The
    # ground-take axis therefore applies to ordinary occupiable floors only.
    if contract.get("floor_planning_mode") == "clear_span":
        capacities = [
            max(0.0, float(value))
            for value in (
                contract.get("bcr_adjusted_floor_areas_m2") or ()
            )
        ]
        legal_hash = str(
            contract.get("legal_floor_field_hash") or ""
        )
        contract["candidate_floor_count_authority"] = (
            "explicit_clear_span_dimensional_invariant"
        )
        contract["candidate_target_reachable"] = bool(
            sum(capacities)
            + 1e-9
            >= requested
        )
        contract["candidate_target_gfa_m2"] = round(requested, 3)
        contract["candidate_prefix_capacity_m2"] = round(
            sum(capacities),
            3,
        )
        contract["candidate_legal_floor_field_hash"] = legal_hash
        return

    legal_field = contract.get("legal_floor_field")
    if not validate_legal_floor_field(legal_field):
        contract["candidate_floor_count_authority"] = (
            "legacy_contract_without_validated_legal_floor_field"
        )
        return
    legal_hash = str(legal_field.get("legal_floor_field_hash") or "")
    if (
        not legal_hash
        or str(contract.get("legal_floor_field_hash") or "") != legal_hash
    ):
        contract["candidate_floor_count_authority"] = (
            "invalid_legal_floor_field_identity"
        )
        contract["candidate_target_reachable"] = False
        return

    capacities = [
        max(0.0, float(value))
        for value in (
            legal_field.get("bcr_adjusted_floor_capacities_m2") or ()
        )
    ]
    ground_capacity = max(
        0.0,
        float(legal_field.get("bcr_footprint_capacity_m2") or 0.0),
    )
    if coverage_band is not None and ground_capacity > 1e-9:
        capacities = capacities_under_band(
            capacities,
            ground_capacity_m2=ground_capacity,
            band=coverage_band,
        )
        # Declared, not implied. The candidate floor authority re-derives this
        # prefix from the trusted field and will only agree if it is told the
        # same ground take; leaving it implicit is what made every banded
        # candidate look like an invented prefix.
        contract["coverage_band_id"] = coverage_band.band_id
    sections = list(legal_field.get("legal_floor_sections") or ())
    areas = [
        max(0.0, float(value))
        for value in (
            legal_field.get("legal_floor_section_areas_m2") or ()
        )
    ]
    tops = [
        max(0.0, float(value))
        for value in (
            legal_field.get("legal_floor_top_heights_m") or ()
        )
    ]
    count = len(capacities)
    if (
        count <= 0
        or len(sections) != count
        or len(areas) != count
        or len(tops) != count
    ):
        contract["candidate_floor_count_authority"] = (
            "invalid_legal_floor_field_vectors"
        )
        contract["candidate_target_reachable"] = False
        return

    preserve_design_reserve = bool(
        preserve_full_lawful_stack
        and type(original_requested_floors) is int
        and original_requested_floors == count
    )
    cumulative = 0.0
    selected_count = count if preserve_design_reserve else 0
    if not preserve_design_reserve:
        for index, capacity in enumerate(capacities):
            cumulative += capacity
            if cumulative + 1e-9 >= requested:
                selected_count = index + 1
                break
    reachable = bool(
        selected_count > 0
        and sum(capacities[:selected_count]) + 1e-9 >= requested
    )
    if not reachable:
        selected_count = count

    contract.update({
        "requested_floors": selected_count,
        "requested_height_m": round(tops[selected_count - 1], 3),
        "legal_floor_section_areas_m2": [
            round(value, 3) for value in areas[:selected_count]
        ],
        "bcr_adjusted_floor_areas_m2": [
            round(value, 3) for value in capacities[:selected_count]
        ],
        "candidate_legal_floor_sections": deepcopy(
            sections[:selected_count]
        ),
        "candidate_floor_top_heights_m": [
            round(value, 3) for value in tops[:selected_count]
        ],
        "candidate_floor_count_authority": (
            "full_lawful_design_reserve_stack_for_spatial_reserve"
            if preserve_design_reserve
            else "minimum_legal_capacity_prefix_for_candidate_target"
        ),
        "candidate_target_reachable": reachable,
        "candidate_target_gfa_m2": round(requested, 3),
        "candidate_prefix_capacity_m2": round(
            sum(capacities[:selected_count]),
            3,
        ),
        "candidate_legal_floor_field_hash": legal_hash,
    })


def _alternative_floor_targets(
    contract: dict[str, Any],
    *,
    target: float,
) -> list[float]:
    """Project one alternative total onto the same exact legal floor stack."""

    floor_count = max(1, int(contract.get("requested_floors") or 1))
    capacities = contract.get("bcr_adjusted_floor_areas_m2")
    if not isinstance(capacities, (list, tuple)) or len(capacities) != floor_count:
        return []
    normalized = [max(0.0, float(value)) for value in capacities]
    raw = allocate_floor_targets(normalized, target)
    rounded = [round(value, 3) for value in raw]
    desired = round(min(max(0.0, float(target)), sum(normalized)), 3)
    residual = round(desired - sum(rounded), 3)
    if abs(residual) > 1e-9:
        for index in range(len(rounded) - 1, -1, -1):
            adjusted = rounded[index] + residual
            if -1e-9 <= adjusted <= normalized[index] + 1e-9:
                rounded[index] = round(max(0.0, adjusted), 3)
                break
    return rounded


def evaluate_capacity_alternative(
    alternative: dict[str, Any],
    measurement: dict[str, Any] | None,
) -> dict[str, Any]:
    measured = measurement or {}
    achieved = max(
        0.0,
        float(measured.get("feasible_capacity_utilization") or 0.0),
    )
    target = max(0.0, float(alternative.get("target_utilization") or 0.0))
    minimum = max(
        0.0,
        float(alternative.get("feasible_minimum_utilization") or 0.0),
    )
    brief_target = max(
        minimum,
        float(alternative.get("program_brief_target_utilization") or minimum),
    )
    measured_band_targets = {
        "spatial_reserve": minimum,
        "balanced_yield": minimum + (brief_target - minimum) * 0.5,
        "brief_target": brief_target,
        "maximum_feasible": brief_target + (1.0 - brief_target) * 0.5,
    }
    achieved_bands = [
        (alternative_id, band_target)
        for alternative_id, band_target in measured_band_targets.items()
        if (
            achieved + 1e-9 >= band_target
            or (
                alternative_id == "spatial_reserve"
                and measured.get("hard_pass") is True
            )
        )
    ]
    selectable_alternative_id, selectable_target = (
        max(achieved_bands, key=lambda item: item[1])
        if achieved_bands
        else ("", 0.0)
    )
    return {
        **alternative,
        "achieved_utilization": round(achieved, 4),
        "target_gap": round(achieved - target, 4),
        "target_hard_pass": bool(
            achieved + 1e-9 >= target
            or (
                target <= minimum + 1e-9
                and measured.get("hard_pass") is True
            )
        ),
        "requested_capacity_alternative_id": str(
            alternative.get("alternative_id") or ""
        ),
        "requested_target_utilization": round(target, 4),
        "selectable_capacity_alternative_id": selectable_alternative_id,
        "selectable_capacity_target_utilization": round(selectable_target, 4),
        "selectable_capacity_hard_pass": bool(selectable_alternative_id),
        "capacity_band_resolution": (
            "highest_measured_achieved_band"
            if selectable_alternative_id
            else "below_feasible_minimum"
        ),
        "measurement_schema_version": measured.get("schema_version"),
    }


def capacity_fit_score(
    alternative: dict[str, Any],
    measurement: dict[str, Any] | None,
) -> float:
    """Balance requested-target fit with absolute feasible-capacity yield."""

    measured = measurement or {}
    achieved = min(
        1.0,
        max(0.0, float(measured.get("feasible_capacity_utilization") or 0.0)),
    )
    target = max(1e-9, float(alternative.get("target_utilization") or 0.0))
    target_fit = min(1.0, achieved / target)
    return round(target_fit * 0.70 + achieved * 0.30, 6)


def capacity_retry_floor_targets(
    contract: dict[str, Any] | None,
    alternative: dict[str, Any] | None,
    measurement: dict[str, Any] | None,
) -> tuple[float, ...]:
    """Compensate one measured fit shortfall without exceeding legal plates."""

    contract = contract or {}
    alternative = alternative or {}
    measurement = measurement or {}
    raw_targets = contract.get("target_floor_areas_m2")
    caps = contract.get("bcr_adjusted_floor_areas_m2")
    if (
        not isinstance(raw_targets, (list, tuple))
        or not raw_targets
        or not isinstance(caps, (list, tuple))
        or len(caps) != len(raw_targets)
    ):
        return ()
    current_targets = tuple(
        round(max(0.0, float(value)), 3)
        for value in raw_targets
    )
    design_target_utilization = max(
        0.0,
        float(alternative.get("target_utilization") or 0.0),
    )
    target_utilization = max(
        0.0,
        float(
            alternative.get("feasible_minimum_utilization")
            or design_target_utilization
        ),
    )
    achieved_utilization = max(
        0.0,
        float(measurement.get("feasible_capacity_utilization") or 0.0),
    )
    if (
        target_utilization <= 1e-9
        or achieved_utilization <= 1e-9
        or achieved_utilization + 1e-9 >= target_utilization
    ):
        return current_targets
    compensated_total = min(
        sum(max(0.0, float(value)) for value in caps),
        sum(current_targets) * target_utilization / achieved_utilization,
    )
    return tuple(_alternative_floor_targets(
        {
            **contract,
            "requested_floors": len(current_targets),
        },
        target=compensated_total,
    ))


def capacity_contract_with_retry_targets(
    contract: dict[str, Any],
    retry_targets: tuple[float, ...],
) -> dict[str, Any]:
    """Bind a recompiled target vector to every finalization identity alias."""

    rebound = deepcopy(contract)
    targets = [round(float(value), 3) for value in retry_targets]
    total = round(sum(targets), 3)
    rebound.update({
        "target_floor_areas_m2": targets,
        "target_floor_area_m2": total,
        "candidate_target_gfa_m2": total,
    })
    return rebound


def capacity_retry_plan_coverage(
    current_coverage: float,
    alternative: dict[str, Any],
    measurement: dict[str, Any] | None,
) -> float:
    """Derive one bounded plan-fit retry from measured target shortfall.

    Floor area scales approximately with plan area for the same typed vertical
    profile. The ratio is therefore evidence-derived, not a use-specific shape
    macro. A caller may retry once; exact capacity, legal and retention gates
    still decide whether the widened materialization survives.
    """

    coverage = max(0.0, min(0.95, float(current_coverage or 0.0)))
    measured = measurement or {}
    achieved = max(
        0.0,
        float(measured.get("feasible_capacity_utilization") or 0.0),
    )
    target = max(0.0, float(alternative.get("target_utilization") or 0.0))
    if achieved <= 1e-9 or achieved + 1e-9 >= target:
        return round(coverage, 6)
    return round(min(0.95, coverage * target / achieved), 6)


__all__ = [
    "CAPACITY_ALTERNATIVE_SCHEMA",
    "CAPACITY_ALTERNATIVE_SPECS",
    "CapacityAlternativeSpec",
    "build_capacity_alternative",
    "capacity_fit_score",
    "capacity_retry_plan_coverage",
    "capacity_contract_with_retry_targets",
    "capacity_alternative_catalog",
    "capacity_alternative_for_host",
    "capacity_alternative_for_lattice_index",
    "capacity_contract_for_alternative",
    "capacity_retry_floor_targets",
    "evaluate_capacity_alternative",
]
