from __future__ import annotations

from collections.abc import Iterable
from itertools import permutations, product

from backend.app.schemas.loop import CandidateRecord
from engine.geometry.polygon import shared_boundary_length


def rank_candidate(record: CandidateRecord) -> tuple:
    report = record.validation
    return (
        0 if report.accepted else 1,
        report.hard_violation_count,
        report.violation_score,
        -report.total_score,
        record.fingerprint,
    )


def select_frontier(
    records: list[CandidateRecord],
    beam_width: int,
) -> list[CandidateRecord]:
    return sorted(records, key=rank_candidate)[:beam_width]


def canonical_building_topology_signature(
    floor_results: Iterable[object],
) -> str:
    """Return an ID- and coordinate-independent topology signature."""
    return repr(
        tuple(
            (
                floor.program.use_type,
                _canonical_floor_topology(floor.layout),
            )
            for floor in floor_results
        )
    )


def _canonical_floor_topology(layout) -> tuple:
    roles: dict[str, str] = {}
    references: dict[str, str] = {}
    edges: list[tuple[str, str, str]] = []

    for room in layout.rooms:
        key = f"room:{room.room_id}"
        roles[key] = f"room:{room.space_type}"
        references[room.room_id] = key
    for path in layout.circulation:
        key = f"circulation:{path.room_id}"
        roles[key] = "circulation"
        references[path.room_id] = key
    for index, first in enumerate(layout.circulation):
        for second in layout.circulation[index + 1 :]:
            if shared_boundary_length(
                first.polygon,
                second.polygon,
            ) > 0:
                edges.append(
                    (
                        "circulation-adjacency",
                        references[first.room_id],
                        references[second.room_id],
                    )
                )

    basic_design = layout.basic_design
    if basic_design is not None:
        for element in basic_design.elements:
            if element.kind not in {"stair", "lobby", "elevator", "shaft"}:
                continue
            key = f"element:{element.element_id}"
            if element.kind == "stair":
                host_role = "remote" if element.host_id == "floor" else "core"
                roles[key] = f"vertical:stair:{host_role}"
            else:
                roles[key] = f"vertical:{element.kind}"
            references[element.element_id] = key

    def reference(value: str, *, role: str) -> str:
        if value in references:
            return references[value]
        key = f"unresolved:{role}:{value}"
        roles.setdefault(key, f"unresolved:{role}")
        return key

    for opening in layout.openings:
        source = reference(opening.connects[0], role="door-source")
        target = reference(opening.connects[1], role="door-target")
        door = f"opening:{opening.opening_id}"
        roles[door] = "door"
        edges.extend(
            (
                ("door-connects", door, source),
                ("door-connects", door, target),
            )
        )

    if basic_design is not None:
        for line in basic_design.lines:
            if line.kind not in {"protected_exit", "stair_door"}:
                continue
            source = reference(line.host_id or "", role=f"{line.kind}-host")
            target = reference(
                line.target_id or "",
                role=f"{line.kind}-target",
            )
            line_node = f"line:{line.line_id}"
            roles[line_node] = line.kind
            edges.extend(
                (
                    (f"{line.kind}-host", source, line_node),
                    (f"{line.kind}-target", line_node, target),
                )
            )

    role_groups = tuple(
        (role, tuple(sorted(node for node, value in roles.items() if value == role)))
        for role in sorted(set(roles.values()))
    )
    group_permutations = [
        tuple(permutations(nodes))
        for _, nodes in role_groups
    ]
    role_counts = tuple((role, len(nodes)) for role, nodes in role_groups)
    canonical_edges = None
    for ordered_groups in product(*group_permutations):
        labels = {
            node: index
            for index, node in enumerate(
                node
                for ordered_nodes in ordered_groups
                for node in ordered_nodes
            )
        }
        encoded = tuple(
            sorted(
                (kind, labels[source], labels[target])
                for kind, source, target in edges
            )
        )
        if canonical_edges is None or encoded < canonical_edges:
            canonical_edges = encoded
    return role_counts, canonical_edges or ()
