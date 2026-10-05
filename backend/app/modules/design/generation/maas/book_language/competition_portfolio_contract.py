"""Immutable target-aware constraints for final competition portfolios."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from collections import Counter
from typing import Any, Iterable, Mapping


CAPACITY_BANDS = (
    "spatial_reserve",
    "balanced_yield",
    "brief_target",
    "maximum_feasible",
)
BASE_SCOPES = ("1/1", "1/2", "3/8", "1/4", "1/8", "1/16")


def _counts(**values: int) -> Mapping[str, int]:
    return MappingProxyType(dict(values))


@dataclass(frozen=True)
class CompetitionPortfolioContract:
    target_count: int
    capacity_band_exact_counts: Mapping[str, int]
    capacity_band_minimum_counts: Mapping[str, int]
    capacity_band_maximum_counts: Mapping[str, int]
    base_scopes: tuple[str, ...]
    base_scope_minimum_each: int
    base_scope_maximum_each: int | None
    visible_stepped_minimum: int
    visible_stepped_maximum: int | None
    upper_band_stepped_bands: tuple[str, ...]
    upper_band_stepped_minimum: int
    body_phenotype_minimum_distinct: int
    body_phenotype_maximum_each: int | None
    roof_archetype_minimum_distinct: int
    roof_archetype_maximum_each: int | None
    chassis_family_minimum_distinct: int
    chassis_family_maximum_each: int | None
    plan_family_minimum_distinct: int
    plan_family_maximum_each: int | None
    body_roof_signature_minimum_distinct: int
    body_roof_signature_maximum_each: int | None
    minimum_pair_distance: float
    shared_language_minimum_composite_distance: float


def competition_portfolio_contract(
    target_count: int,
) -> CompetitionPortfolioContract:
    """Return the fail-closed final-set contract for a requested target."""

    target = int(target_count)
    if target <= 0:
        raise ValueError("target_count must be positive")
    empty = MappingProxyType({})
    if target == 3:
        return CompetitionPortfolioContract(
            target_count=3,
            capacity_band_exact_counts=empty,
            capacity_band_minimum_counts=empty,
            capacity_band_maximum_counts=empty,
            base_scopes=(),
            base_scope_minimum_each=0,
            base_scope_maximum_each=None,
            visible_stepped_minimum=0,
            visible_stepped_maximum=1,
            upper_band_stepped_bands=(),
            upper_band_stepped_minimum=0,
            body_phenotype_minimum_distinct=3,
            body_phenotype_maximum_each=1,
            roof_archetype_minimum_distinct=0,
            roof_archetype_maximum_each=None,
            chassis_family_minimum_distinct=0,
            chassis_family_maximum_each=None,
            plan_family_minimum_distinct=0,
            plan_family_maximum_each=None,
            body_roof_signature_minimum_distinct=3,
            body_roof_signature_maximum_each=1,
            # The three-card diagnostic is a representative smoke witness for
            # the final portfolio.  It must not impose a stricter visual-pair
            # threshold than the 20-card acceptance contract, otherwise
            # visibly different legal phenotypes can never reach the stage
            # that is meant to validate them together.
            minimum_pair_distance=0.10,
            shared_language_minimum_composite_distance=0.0,
        )
    if target == 5:
        return CompetitionPortfolioContract(
            target_count=5,
            capacity_band_exact_counts=empty,
            capacity_band_minimum_counts=empty,
            capacity_band_maximum_counts=empty,
            base_scopes=(),
            base_scope_minimum_each=0,
            base_scope_maximum_each=None,
            visible_stepped_minimum=0,
            visible_stepped_maximum=1,
            upper_band_stepped_bands=(),
            upper_band_stepped_minimum=0,
            # MGA_R-inspired islands are assigned from measured final meshes,
            # never authored labels. Four islands keep the bounded five-card
            # proof from converging to one legal wedge language.
            body_phenotype_minimum_distinct=4,
            body_phenotype_maximum_each=2,
            roof_archetype_minimum_distinct=0,
            roof_archetype_maximum_each=None,
            chassis_family_minimum_distinct=0,
            chassis_family_maximum_each=None,
            plan_family_minimum_distinct=0,
            plan_family_maximum_each=None,
            body_roof_signature_minimum_distinct=4,
            body_roof_signature_maximum_each=2,
            minimum_pair_distance=0.10,
            shared_language_minimum_composite_distance=0.0,
        )
    if target == 20:
        return CompetitionPortfolioContract(
            target_count=20,
            # Capacity is a measured lower-bound gate (>= 0.70), not a form
            # author. Requiring five cards in each target band forced five
            # maximum-yield bodies and made legal-fit CSG dominate the visual
            # portfolio. Morphology, BOOK topology and BaseVolume quotas own
            # diversity; capacity bands remain reported evidence only.
            capacity_band_exact_counts=empty,
            capacity_band_minimum_counts=empty,
            capacity_band_maximum_counts=empty,
            base_scopes=BASE_SCOPES,
            base_scope_minimum_each=3,
            base_scope_maximum_each=4,
            visible_stepped_minimum=1,
            visible_stepped_maximum=3,
            upper_band_stepped_bands=(),
            upper_band_stepped_minimum=0,
            body_phenotype_minimum_distinct=5,
            body_phenotype_maximum_each=4,
            roof_archetype_minimum_distinct=7,
            roof_archetype_maximum_each=3,
            chassis_family_minimum_distinct=6,
            chassis_family_maximum_each=4,
            plan_family_minimum_distinct=5,
            plan_family_maximum_each=4,
            body_roof_signature_minimum_distinct=0,
            body_roof_signature_maximum_each=None,
            minimum_pair_distance=0.14,
            shared_language_minimum_composite_distance=0.22,
        )
    if target == 10:
        return CompetitionPortfolioContract(
            target_count=10,
            capacity_band_exact_counts=empty,
            capacity_band_minimum_counts=_counts(
                spatial_reserve=2,
                balanced_yield=2,
                brief_target=2,
                maximum_feasible=2,
            ),
            capacity_band_maximum_counts=_counts(
                spatial_reserve=3,
                balanced_yield=3,
                brief_target=3,
                maximum_feasible=3,
            ),
            base_scopes=BASE_SCOPES,
            base_scope_minimum_each=1,
            base_scope_maximum_each=None,
            visible_stepped_minimum=1,
            visible_stepped_maximum=3,
            upper_band_stepped_bands=(
                "brief_target",
                "maximum_feasible",
            ),
            upper_band_stepped_minimum=1,
            body_phenotype_minimum_distinct=0,
            body_phenotype_maximum_each=3,
            roof_archetype_minimum_distinct=0,
            roof_archetype_maximum_each=3,
            chassis_family_minimum_distinct=0,
            chassis_family_maximum_each=None,
            plan_family_minimum_distinct=0,
            plan_family_maximum_each=None,
            body_roof_signature_minimum_distinct=0,
            body_roof_signature_maximum_each=None,
            minimum_pair_distance=0.10,
            shared_language_minimum_composite_distance=0.0,
        )
    return CompetitionPortfolioContract(
        target_count=target,
        capacity_band_exact_counts=empty,
        capacity_band_minimum_counts=empty,
        capacity_band_maximum_counts=empty,
        base_scopes=(),
        base_scope_minimum_each=0,
        base_scope_maximum_each=None,
        visible_stepped_minimum=0,
        visible_stepped_maximum=None,
        upper_band_stepped_bands=(),
        upper_band_stepped_minimum=0,
        body_phenotype_minimum_distinct=0,
        body_phenotype_maximum_each=None,
        roof_archetype_minimum_distinct=0,
        roof_archetype_maximum_each=None,
        chassis_family_minimum_distinct=0,
        chassis_family_maximum_each=None,
        plan_family_minimum_distinct=0,
        plan_family_maximum_each=None,
        body_roof_signature_minimum_distinct=0,
        body_roof_signature_maximum_each=None,
        minimum_pair_distance=0.10,
        shared_language_minimum_composite_distance=0.0,
    )


def competition_pair_required_distance(
    *,
    target_count: int,
    same_body_phenotype: bool,
    same_roof_archetype: bool,
) -> float:
    """Use one target-aware pair contract in selection and certification."""

    contract = competition_portfolio_contract(target_count)
    if (
        same_body_phenotype or same_roof_archetype
    ) and contract.shared_language_minimum_composite_distance > 0.0:
        return contract.shared_language_minimum_composite_distance
    return contract.minimum_pair_distance


def competition_family_supply_deficits(
    facts: Iterable[Mapping[str, Any]],
    *,
    target_count: int,
    pair_distances: Iterable[float] = (),
) -> dict[str, Any]:
    """Derive bounded supply deficits from the immutable target contract."""

    contract = competition_portfolio_contract(target_count)
    rows = [dict(row) for row in facts][: max(1, int(target_count) * 8)]
    unknown_values = {"", "unknown", "unclassified", "none", "not_available"}
    body_values = [str(row.get("body_phenotype") or "").strip().lower() for row in rows]
    bodies = Counter(value for value in body_values if value not in unknown_values)
    signature_values = []
    unknown_signature_count = 0
    for row, body in zip(rows, body_values):
        roof = str(row.get("roof_archetype") or "").strip().lower()
        if not roof:
            encoded = str(
                row.get("body_roof_signature") or ""
            ).strip().lower()
            components = encoded.split("|")
            if len(components) == 2:
                roof = components[1][:96]
        if body in unknown_values or roof in unknown_values:
            unknown_signature_count += 1
        else:
            signature_values.append(f"{body[:96]}|{roof[:96]}")
    signatures = Counter(signature_values)
    geometry_families = Counter(
        value for row in rows
        if (value := str(row.get("geometry_family") or "").strip().lower())
        not in unknown_values
    )
    distances = [float(value) for value in pair_distances]
    stepped_count = sum(bool(row.get("visible_stepped")) for row in rows)
    return {
        "schema_version": "arr.maas.family_supply_deficits.v1",
        "target_count": contract.target_count,
        "required_body_phenotype_distinct": (
            contract.body_phenotype_minimum_distinct
        ),
        "available_body_phenotype_distinct": len(bodies),
        "unknown_body_phenotype_count": sum(
            value in unknown_values for value in body_values
        ),
        "body_phenotype_shortfall": max(
            0,
            contract.body_phenotype_minimum_distinct - len(bodies),
        ),
        "required_body_roof_signature_distinct": (
            contract.body_roof_signature_minimum_distinct
        ),
        "available_body_roof_signature_distinct": len(signatures),
        "unknown_body_roof_signature_count": unknown_signature_count,
        "body_roof_signature_shortfall": max(
            0,
            contract.body_roof_signature_minimum_distinct - len(signatures),
        ),
        "overrepresented_body_phenotype_counts": dict(sorted(
            (key, count) for key, count in bodies.items()
            if contract.body_phenotype_maximum_each is not None
            and count > contract.body_phenotype_maximum_each
        )),
        "overrepresented_body_roof_signature_counts": dict(sorted(
            (key, count) for key, count in signatures.items()
            if contract.body_roof_signature_maximum_each is not None
            and count > contract.body_roof_signature_maximum_each
        )),
        "overrepresented_geometry_family_counts": dict(sorted(
            (key, count) for key, count in geometry_families.items()
            if count > 1
        )),
        "minimum_pair_distance": contract.minimum_pair_distance,
        "pair_distance_conflict_count": sum(
            value < contract.minimum_pair_distance for value in distances
        ),
        "visible_stepped_count": stepped_count,
        "visible_stepped_maximum": contract.visible_stepped_maximum,
        "visible_stepped_excess": max(
            0,
            stepped_count - (contract.visible_stepped_maximum or stepped_count),
        ),
    }


__all__ = [
    "CompetitionPortfolioContract",
    "competition_family_supply_deficits",
    "competition_portfolio_contract",
]
