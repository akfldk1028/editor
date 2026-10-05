"""Constrained MAP-Elites archive for graph-authored massing candidates."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable

from backend.app.modules.design.generation.maas.grammar.component_graph import graph_from_sequence


@dataclass
class GraphBehaviorArchive:
    cells: dict[tuple[str, ...], Any] = field(default_factory=dict)
    evaluated_count: int = 0
    replaced_count: int = 0

    def add(self, elite: Any) -> None:
        self.evaluated_count += 1
        key = graph_behavior_key(elite)
        previous = self.cells.get(key)
        if previous is None or float(elite.score) > float(previous.score):
            if previous is not None:
                self.replaced_count += 1
            self.cells[key] = elite

    def extend(self, elites: Iterable[Any]) -> None:
        for elite in elites:
            self.add(elite)

    def values(self) -> list[Any]:
        return sorted(self.cells.values(), key=lambda elite: float(elite.score), reverse=True)

    def evidence(self) -> dict[str, Any]:
        dimensions = Counter(key[0] for key in self.cells)
        return {
            "schema_version": "arr.maas.graph_behavior_archive.v1",
            "evaluated_count": self.evaluated_count,
            "cell_count": len(self.cells),
            "replaced_count": self.replaced_count,
            "language_group_cells": dict(sorted(dimensions.items())),
        }


def graph_behavior_key(elite: Any) -> tuple[str, ...]:
    signature = elite.source.signature()
    graph = graph_from_sequence(elite.sequence)
    child_counts = Counter(node.parent_id for node in graph.nodes if node.parent_id)
    branch_degree = max(child_counts.values(), default=0)
    principle = str(signature.get("formal_principle") or signature.get("primary_language") or "unclassified")
    if principle == "continuous_ribbon_field":
        language_group = "continuous"
    elif principle in {"carved_atrium", "carved_monolith"}:
        language_group = "carved"
    elif principle == "split_bridge_connector":
        language_group = "bridge"
    elif principle in {"folded_section", "terraced_ribbon_section"}:
        language_group = "sectional"
    elif principle in {"stacked_shifted_platforms", "torqued_stack"}:
        language_group = "stacked"
    else:
        language_group = "anchor"
    heights = len({round(float(volume.top_fraction), 1) for volume in elite.source.volumes})
    void_count = sum(1 for node in graph.nodes if node.role == "void")
    coverage = float(elite.source.footprint.area) / max(float(getattr(elite, "feature", {}).get("properties", {}).get("benchmark_site_area_m2") or elite.source.footprint.area), 1e-9)
    primary_verb = next((node.operation.verb for node in graph.nodes if node.role == "primary"), "base")
    coverage_bin = min(4, max(0, int(coverage * 5.0)))
    return (
        language_group,
        principle,
        primary_verb,
        f"branch_degree_{min(branch_degree, 3)}",
        "curved" if signature.get("continuous_surface_evidence", {}).get("hard_pass") else "planar",
        f"void_count_{min(void_count, 2)}",
        f"height_levels_{min(heights, 4)}",
        f"coverage_bin_{coverage_bin}",
    )


def bounded_behavior_frontier(
    elites: Iterable[Any],
    *,
    per_cell: int = 4,
    minimum_count: int = 120,
) -> list[Any]:
    """Keep a score-ranked multi-elite frontier per behavior cell.

    A single MAP-Elites winner per coarse cell is too lossy for visual review,
    while exact all-pairs morphology over thousands of legal candidates is too
    slow. Keeping several representatives per cell preserves alternative graph
    realizations and bounds the later precise pose-invariant comparison.
    """
    population = list(elites)
    buckets: dict[tuple[str, ...], list[Any]] = {}
    for elite in population:
        buckets.setdefault(graph_behavior_key(elite), []).append(elite)
    selected: list[Any] = []
    selected_ids: set[int] = set()
    for bucket in buckets.values():
        for elite in sorted(bucket, key=lambda item: float(item.score), reverse=True)[:max(1, per_cell)]:
            selected.append(elite)
            selected_ids.add(id(elite))
    if len(selected) < max(0, minimum_count):
        for elite in sorted(population, key=lambda item: float(item.score), reverse=True):
            if id(elite) in selected_ids:
                continue
            selected.append(elite)
            selected_ids.add(id(elite))
            if len(selected) >= minimum_count:
                break
    return sorted(selected, key=lambda item: float(item.score), reverse=True)


def field_topology_coverage(
    sequences: Iterable[Any],
    *,
    minimums: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Audit whether the author used distinct field topologies, not poses."""
    required = dict(minimums or {"parallel": 1, "branched": 1})
    counts = {name: 0 for name in required}
    for sequence in sequences:
        for item in getattr(sequence, "calls", ()):
            if str(getattr(item, "verb", "")) != "bend":
                continue
            params = getattr(item, "params", {}) or {}
            topology = str(params.get("field_topology") or "parallel").strip().lower()
            counts[topology] = counts.get(topology, 0) + 1
    missing = {
        name: required_count - counts.get(name, 0)
        for name, required_count in required.items()
        if counts.get(name, 0) < required_count
    }
    return {
        "schema_version": "arr.maas.field_topology_coverage.v1",
        "counts": counts,
        "minimums": required,
        "missing": missing,
        "hard_pass": not missing,
    }


__all__ = [
    "GraphBehaviorArchive",
    "bounded_behavior_frontier",
    "field_topology_coverage",
    "graph_behavior_key",
]
