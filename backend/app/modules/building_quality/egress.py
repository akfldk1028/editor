from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from backend.app.schemas.result import BuildingGenerationResult


@dataclass(frozen=True)
class EgressQualityMeasurement:
    status: Literal["pass", "fail", "not_checked"]
    checked_floor_indexes: tuple[int, ...]
    failed_floor_indexes: tuple[int, ...]
    unresolved_facts: tuple[str, ...]


def aggregate_egress_quality(
    building: BuildingGenerationResult,
) -> EgressQualityMeasurement:
    """Aggregate the evidence already attached to each generated floor."""
    checked_floor_indexes: list[int] = []
    failed_floor_indexes: list[int] = []
    unresolved_facts: set[str] = set()
    all_floors_pass = bool(building.floor_results)

    for floor in building.floor_results:
        floor_index = floor.program.floor_index
        screening = floor.validation.regulatory_screening
        if floor.egress_graph is None:
            unresolved_facts.add("measured_travel_distance")
        if screening is None or not screening.checks:
            all_floors_pass = False
            continue

        unresolved_facts.update(screening.unresolved_facts)
        statuses = tuple(check.status for check in screening.checks)
        if all(status in {"pass", "fail"} for status in statuses):
            checked_floor_indexes.append(floor_index)
        if any(status == "fail" for status in statuses):
            failed_floor_indexes.append(floor_index)
        if any(status != "pass" for status in statuses) or screening.unresolved_facts:
            all_floors_pass = False

    failed = tuple(sorted(set(failed_floor_indexes)))
    if failed:
        status: Literal["pass", "fail", "not_checked"] = "fail"
    elif all_floors_pass and not unresolved_facts:
        status = "pass"
    else:
        status = "not_checked"
    return EgressQualityMeasurement(
        status=status,
        checked_floor_indexes=tuple(sorted(set(checked_floor_indexes))),
        failed_floor_indexes=failed,
        unresolved_facts=tuple(sorted(unresolved_facts)),
    )
