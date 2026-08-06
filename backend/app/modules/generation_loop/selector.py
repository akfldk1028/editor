from __future__ import annotations

from collections.abc import Iterable

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

    role_counts = tuple(
        (role, sum(value == role for value in roles.values()))
        for role in sorted(set(roles.values()))
    )
    colors = _refined_node_colors(roles, edges)
    canonical_edges = tuple(
        sorted(
            (kind, colors[source], colors[target])
            for kind, source, target in edges
        )
    )
    color_counts = tuple(
        sorted(
            (color, sum(value == color for value in colors.values()))
            for color in set(colors.values())
        )
    )
    return role_counts, color_counts, canonical_edges


def _refined_node_colors(
    roles: dict[str, str],
    edges: list[tuple[str, str, str]],
) -> dict[str, int]:
    role_palette = {role: index for index, role in enumerate(sorted(set(roles.values())))}
    colors = {node: role_palette[role] for node, role in roles.items()}
    for _ in range(max(1, len(roles))):
        signatures = {
            node: (
                roles[node],
                tuple(
                    sorted(
                        (kind, colors[target])
                        for kind, source, target in edges
                        if source == node
                    )
                ),
                tuple(
                    sorted(
                        (kind, colors[source])
                        for kind, source, target in edges
                        if target == node
                    )
                ),
            )
            for node in roles
        }
        palette = {
            signature: index
            for index, signature in enumerate(sorted(set(signatures.values())))
        }
        refined = {node: palette[signature] for node, signature in signatures.items()}
        if refined == colors:
            return refined
        colors = refined
    return colors
