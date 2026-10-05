"""Bounded constraint search for a visually diverse massing portfolio.

Geometry tests live outside this module. The caller supplies pairwise
compatibility and typed candidate facts, so the search can later be replaced
by ILP/CP-SAT without coupling it to Shapely or the MAAS compiler.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class PortfolioCandidateFacts:
    score: float
    group: str
    principle: str
    topology: str
    field_topology: str = ""
    persisted: bool = False
    authored: bool = False
    capacity_target: bool = False
    editable_field: bool = False


def solve_portfolio_beam(
    facts: list[PortfolioCandidateFacts],
    compatibility: list[list[bool]],
    *,
    target_count: int,
    minimum_groups: dict[str, int],
    maximum_groups: dict[str, int] | None = None,
    minimum_field_topologies: dict[str, int] | None = None,
    minimum_authored_count: int = 0,
    minimum_editable_field_count: int = 0,
    minimum_capacity_target_count: int = 0,
    maximum_persisted_count: int | None = None,
    minimum_fresh_count: int = 0,
    maximum_topology_count: int = 2,
    maximum_principle_count: int = 4,
    beam_width: int = 4096,
) -> tuple[int, ...]:
    """Return the highest-quality maximum-cardinality feasible combination."""
    count = len(facts)
    if count == 0 or target_count <= 0 or len(compatibility) != count:
        return ()
    order = sorted(range(count), key=lambda index: facts[index].score, reverse=True)
    states: list[tuple[int, ...]] = [()]
    persisted_limit = target_count if maximum_persisted_count is None else max(0, int(maximum_persisted_count))

    def can_include(state: tuple[int, ...], candidate_index: int) -> bool:
        if len(state) >= target_count:
            return False
        candidate = facts[candidate_index]
        if candidate.persisted and sum(facts[index].persisted for index in state) >= persisted_limit:
            return False
        if sum(facts[index].topology == candidate.topology for index in state) >= maximum_topology_count:
            return False
        if sum(facts[index].principle == candidate.principle for index in state) >= maximum_principle_count:
            return False
        if maximum_groups and sum(facts[index].group == candidate.group for index in state) >= int(
            maximum_groups.get(candidate.group, target_count)
        ):
            return False
        return all(compatibility[candidate_index][other] for other in state)

    def counts(state: tuple[int, ...]):
        groups = Counter(facts[index].group for index in state)
        fields = Counter(facts[index].field_topology for index in state if facts[index].field_topology)
        authored = sum(facts[index].authored for index in state)
        capacity = sum(facts[index].capacity_target for index in state)
        persisted = sum(facts[index].persisted for index in state)
        editable = sum(facts[index].editable_field for index in state)
        return groups, fields, authored, editable, capacity, persisted, len(state) - persisted

    def coverage_key(state: tuple[int, ...]) -> tuple[float, ...]:
        groups, fields, authored, editable, capacity, _, fresh = counts(state)
        coverage = sum(min(groups.get(group, 0), required) for group, required in minimum_groups.items())
        coverage += sum(
            min(fields.get(topology, 0), required)
            for topology, required in (minimum_field_topologies or {}).items()
        )
        coverage += min(authored, max(0, minimum_authored_count))
        coverage += min(editable, max(0, minimum_editable_field_count))
        coverage += min(capacity, max(0, minimum_capacity_target_count))
        coverage += min(fresh, max(0, minimum_fresh_count))
        return (float(coverage), float(len(state)), sum(facts[index].score for index in state))

    def feasible(state: tuple[int, ...]) -> bool:
        groups, fields, authored, editable, capacity, persisted, fresh = counts(state)
        return (
            all(groups.get(group, 0) >= required for group, required in minimum_groups.items())
            and all(
                fields.get(topology, 0) >= required
                for topology, required in (minimum_field_topologies or {}).items()
            )
            and authored >= minimum_authored_count
            and editable >= minimum_editable_field_count
            and capacity >= minimum_capacity_target_count
            and persisted <= persisted_limit
            and fresh >= minimum_fresh_count
        )

    for candidate_index in order:
        expanded = list(states)
        expanded.extend(
            (*state, candidate_index)
            for state in states
            if can_include(state, candidate_index)
        )
        states = sorted(set(expanded), key=coverage_key, reverse=True)[: max(64, int(beam_width))]

    feasible_states = [state for state in states if feasible(state)]
    if not feasible_states:
        return ()
    return max(
        feasible_states,
        key=lambda state: (len(state), sum(facts[index].score for index in state)),
    )


__all__ = ["PortfolioCandidateFacts", "solve_portfolio_beam"]
