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
    hard_failure_facts: tuple[tuple[int, str], ...] = ()


_INTERNAL_GRAPH_FAILURE_PREFIXES = (
    "invalid_protected_exit_portal:",
    "protected_exit_portal_missing",
    "route_connectivity",
    "unreachable_occupied_room:",
)


def aggregate_egress_quality(
    building: BuildingGenerationResult,
) -> EgressQualityMeasurement:
    """Aggregate the evidence already attached to each generated floor."""
    checked_floor_indexes: list[int] = []
    failed_floor_indexes: list[int] = []
    unresolved_facts: set[str] = set()
    hard_failure_facts: set[tuple[int, str]] = set()
    all_floors_pass = bool(building.floor_results)

    for floor in building.floor_results:
        floor_index = floor.program.floor_index
        screening = floor.validation.regulatory_screening
        graph = floor.egress_graph
        if graph is None:
            unresolved_facts.add("measured_travel_distance")
            all_floors_pass = False
        else:
            unresolved_facts.update(graph.unresolved_facts)
            floor_hard_failure_facts = {
                (floor_index, fact)
                for fact in graph.unresolved_facts
                if _is_internal_graph_failure(fact)
            }
            hard_failure_facts.update(floor_hard_failure_facts)
            if floor_hard_failure_facts:
                failed_floor_indexes.append(floor_index)
            if graph.status != "checked" or graph.unresolved_facts:
                all_floors_pass = False
        if screening is None or not screening.checks:
            all_floors_pass = False
            continue

        unresolved_facts.update(screening.unresolved_facts)
        statuses = tuple(check.status for check in screening.checks)
        if (
            graph is not None
            and graph.status == "checked"
            and not (graph.unresolved_facts or screening.unresolved_facts)
            and all(status == "pass" for status in statuses)
        ):
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
        hard_failure_facts=tuple(sorted(hard_failure_facts)),
    )


def _is_internal_graph_failure(fact: str) -> bool:
    return fact.startswith(_INTERNAL_GRAPH_FAILURE_PREFIXES)
