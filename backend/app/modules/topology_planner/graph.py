"""The adjacency graph a floor has to satisfy, decided before geometry.

GFLAN (2026) and the AI EDAM circulation paper (2025) both fix topology --
which rooms touch which, and that every room reaches the corridor -- before
placing anything.  The corridor is a node here, not a rectangle drawn first.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from backend.app.schemas.program import ProgramGraph


CORRIDOR = "corridor"
_HARD_RELATIONS = frozenset({"service_adjacent"})
_SOFT_RELATIONS = frozenset({"functional_adjacency"})


@dataclass(frozen=True)
class AdjacencyGraph:
    nodes: tuple[str, ...]
    required: frozenset[frozenset[str]]
    soft: frozenset[frozenset[str]]

    def missing_required(
        self, pairs_present: Iterable[tuple[str, str]]
    ) -> tuple[tuple[str, str], ...]:
        present = {frozenset(pair) for pair in pairs_present}
        return tuple(
            tuple(sorted(pair))
            for pair in sorted(self.required, key=lambda item: tuple(sorted(item)))
            if pair not in present
        )


def build_adjacency_graph(program: ProgramGraph) -> AdjacencyGraph:
    room_ids = tuple(node.node_id for node in program.nodes)
    required: set[frozenset[str]] = set()
    soft: set[frozenset[str]] = set()
    for room in room_ids:
        # Spanning circulation: every room, the core included, opens onto the corridor.
        required.add(frozenset({room, CORRIDOR}))
    known = set(room_ids)
    for edge in program.edges:
        if edge.source not in known or edge.target not in known:
            continue  # "street" and other external endpoints are not rooms
        pair = frozenset({edge.source, edge.target})
        if edge.relation in _HARD_RELATIONS:
            required.add(pair)
        elif edge.relation in _SOFT_RELATIONS:
            soft.add(pair)
    return AdjacencyGraph(
        nodes=(*room_ids, CORRIDOR),
        required=frozenset(required),
        soft=frozenset(soft - required),
    )
