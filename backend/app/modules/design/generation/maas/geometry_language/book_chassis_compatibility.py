"""Topology-preserving compatibility between chassis and BOOK operations.

BOOK defines operations independently of a host.  Once a host already carries
an architectural relation, however, a second operation can erase rather than
develop it.  These rules protect only measured spatial invariants; they do not
encode parcel coordinates, completed forms, or aesthetic templates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from backend.app.modules.design.generation.maas.grammar.parameter_schema import PARAMETER_BOUNDS


@dataclass(frozen=True)
class ChassisRelationInvariant:
    chassis_operator: str
    protected_relation: str
    incompatible_book_verbs: frozenset[str]
    rationale: str


CHASSIS_RELATION_INVARIANTS = (
    ChassisRelationInvariant(
        chassis_operator="split_wing",
        protected_relation="continuous_public_gap_between_two_legible_wings",
        incompatible_book_verbs=frozenset({
            "interlock", "intersect", "join", "merge", "overlap", "rotate",
        }),
        rationale=(
            "full-span crossing or union relations bridge the split seam with a "
            "second dominant body, so the two-wing chassis reads as one scalloped box"
        ),
    ),
)


@dataclass(frozen=True)
class SplitWingRelationContract:
    minimum_public_gap_ratio: float = 0.22
    maximum_public_gap_ratio: float = 0.30
    default_public_gap_ratio: float = 0.24
    measurement_basis: str = "live_solid_span_perpendicular_to_wings"
    evidence: str = "r149b_base_vlm_requested_gap_ratio_0.24_to_0.26"


SPLIT_WING_RELATION_CONTRACT = SplitWingRelationContract()


def split_wing_gap_ratio_from_unit(unit: float) -> float:
    """Sample the shared public-gap range from a normalized design variable."""
    contract = SPLIT_WING_RELATION_CONTRACT
    bounded = max(0.0, min(1.0, float(unit)))
    return round(
        contract.minimum_public_gap_ratio
        + (contract.maximum_public_gap_ratio - contract.minimum_public_gap_ratio) * bounded,
        6,
    )


def project_book_split_gap_ratio(value: float) -> float:
    """Project BOOK's broad split domain into the legible chassis contract."""
    source_low, source_high = PARAMETER_BOUNDS["gap_ratio"]
    bounded = max(source_low, min(source_high, float(value)))
    return split_wing_gap_ratio_from_unit(
        (bounded - source_low) / (source_high - source_low)
    )


def validate_book_chassis_compatibility(
    program: Any,
    calls: Iterable[Any],
) -> dict[str, object]:
    """Validate that BOOK development preserves the source chassis relation."""
    operators = {
        str(node.operator)
        for node in program.topological_nodes()
    }
    verbs = tuple(str(call.verb) for call in calls)
    checked: list[dict[str, object]] = []
    for invariant in CHASSIS_RELATION_INVARIANTS:
        if invariant.chassis_operator not in operators:
            continue
        conflicts = sorted(
            set(verbs) & set(invariant.incompatible_book_verbs)
        )
        checked.append({
            "chassis_operator": invariant.chassis_operator,
            "protected_relation": invariant.protected_relation,
            "book_verbs": list(verbs),
            "incompatible_book_verbs": sorted(invariant.incompatible_book_verbs),
            "conflicts": conflicts,
            "rationale": invariant.rationale,
        })
        if conflicts:
            raise ValueError(
                "incompatible_book_chassis_relation:"
                f"{invariant.chassis_operator}:{','.join(conflicts)}:"
                f"{invariant.protected_relation}"
            )
    return {
        "schema_version": "arr.maas.book_chassis_compatibility.v1",
        "status": "compatible",
        "source_chassis_operators": sorted(operators),
        "book_verbs": list(verbs),
        "checked_relations": checked,
        "parcel_coordinates_used": False,
        "completed_form_template_used": False,
    }


__all__ = [
    "CHASSIS_RELATION_INVARIANTS",
    "ChassisRelationInvariant",
    "SPLIT_WING_RELATION_CONTRACT",
    "SplitWingRelationContract",
    "project_book_split_gap_ratio",
    "split_wing_gap_ratio_from_unit",
    "validate_book_chassis_compatibility",
]
