from __future__ import annotations

import hashlib
import json

from backend.app.modules.layout_generator.service import (
    generate_baseline_layout,
    generate_guillotine_layout,
    generate_stripe_layout,
)
from backend.app.schemas.layout import LayoutCandidate, RoomPolygon
from backend.app.schemas.loop import CandidateRecord
from backend.app.schemas.mass import MassAnalysis
from backend.app.schemas.metrics import ValidationReport
from backend.app.schemas.program import ProgramGraph


def layout_fingerprint(layout: LayoutCandidate) -> str:
    payload = {
        "rooms": _canonical_shapes(layout.rooms),
        "circulation": _canonical_shapes(layout.circulation),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def generate_initial_candidates(
    analysis: MassAnalysis,
    program: ProgramGraph,
) -> list[LayoutCandidate]:
    return deduplicate_candidates(
        [
            generate_baseline_layout(analysis, program),
            generate_stripe_layout(analysis, program, axis="x", reverse=True),
            generate_stripe_layout(analysis, program, axis="y"),
            generate_stripe_layout(analysis, program, axis="y", reverse=True),
            generate_guillotine_layout(analysis, program),
            generate_guillotine_layout(analysis, program, reverse=True),
        ]
    )


def deduplicate_candidates(
    candidates: list[LayoutCandidate],
) -> list[LayoutCandidate]:
    seen: set[str] = set()
    unique: list[LayoutCandidate] = []
    for candidate in candidates:
        fingerprint = layout_fingerprint(candidate)
        if fingerprint not in seen:
            seen.add(fingerprint)
            unique.append(candidate)
    return unique


def refine_candidates(
    frontier: list[CandidateRecord | LayoutCandidate],
    reports: list[ValidationReport],
    analysis: MassAnalysis,
    program: ProgramGraph,
    iteration: int,
) -> list[LayoutCandidate]:
    candidates: list[LayoutCandidate] = []
    for parent, report in zip(frontier, reports):
        if "circulation_missing" not in {
            violation.code for violation in report.violations
        }:
            continue
        parent_layout = parent.layout if isinstance(parent, CandidateRecord) else parent
        candidates.extend(
            _corridor_candidates(
                parent_layout,
                analysis,
                program,
                iteration,
            )
        )
    return deduplicate_candidates(candidates)


def _corridor_candidates(
    parent: LayoutCandidate,
    analysis: MassAnalysis,
    program: ProgramGraph,
    iteration: int,
) -> list[LayoutCandidate]:
    scale = _room_scale(program)
    if scale >= 1:
        return []
    orderings = [
        ("original", list(program.nodes)),
        ("reversed", list(reversed(program.nodes))),
        (
            "frontage-first",
            sorted(program.nodes, key=lambda node: (not node.frontage_required, node.node_id)),
        ),
        (
            "service-grouped",
            sorted(
                program.nodes,
                key=lambda node: (
                    node.space_type not in {"core", "restroom", "utility", "storage", "pantry", "ps_eps"},
                    node.node_id,
                ),
            ),
        ),
    ]
    candidates = []
    for axis in ("horizontal", "vertical"):
        for order_name, nodes in orderings:
            candidates.append(
                _corridor_layout(
                    parent,
                    analysis,
                    program,
                    iteration=iteration,
                    axis=axis,
                    order_name=order_name,
                    nodes=nodes,
                    scale=scale,
                )
            )
    return candidates


def _corridor_layout(
    parent: LayoutCandidate,
    analysis: MassAnalysis,
    program: ProgramGraph,
    *,
    iteration: int,
    axis: str,
    order_name: str,
    nodes,
    scale: float,
) -> LayoutCandidate:
    min_x, min_y, max_x, max_y = analysis.bounds
    split = _balanced_split_index(nodes)
    first, second = nodes[:split], nodes[split:]
    first_area = scale * sum(float(node.target_area) for node in first)
    second_area = scale * sum(float(node.target_area) for node in second)
    rooms: list[RoomPolygon] = []

    if axis == "horizontal":
        width = max_x - min_x
        first_end = min_y + first_area / width
        second_start = max_y - second_area / width
        rooms.extend(_band_rooms(first, min_x, max_x, min_y, first_end, horizontal=True))
        rooms.extend(_band_rooms(second, min_x, max_x, second_start, max_y, horizontal=True))
        corridor_polygon = _rectangle(min_x, first_end, max_x, second_start)
    else:
        height = max_y - min_y
        first_end = min_x + first_area / height
        second_start = max_x - second_area / height
        rooms.extend(_band_rooms(first, min_y, max_y, min_x, first_end, horizontal=False))
        rooms.extend(_band_rooms(second, min_y, max_y, second_start, max_x, horizontal=False))
        corridor_polygon = _rectangle(first_end, min_y, second_start, max_y)

    operator = f"corridor-{axis}"
    candidate_id = (
        f"{parent.candidate_id}::i{iteration}:{operator}:{order_name}"
    )
    return LayoutCandidate(
        candidate_id=candidate_id,
        project_id=program.project_id,
        floor_index=program.floor_index,
        rooms=rooms,
        circulation=[
            RoomPolygon(
                room_id="corridor",
                space_type="circulation",
                polygon=corridor_polygon,
            )
        ],
        score=0.0,
    )


def _band_rooms(nodes, start: float, end: float, low: float, high: float, *, horizontal: bool):
    total = sum(float(node.target_area) for node in nodes)
    cursor = start
    rooms = []
    for index, node in enumerate(nodes):
        next_cursor = (
            end
            if index == len(nodes) - 1
            else cursor + (end - start) * float(node.target_area) / total
        )
        polygon = (
            _rectangle(cursor, low, next_cursor, high)
            if horizontal
            else _rectangle(low, cursor, high, next_cursor)
        )
        rooms.append(RoomPolygon(node.node_id, node.space_type, polygon))
        cursor = next_cursor
    return rooms


def _room_scale(program: ProgramGraph) -> float:
    minimum_scale = max(
        (
            float(node.min_area) / float(node.target_area)
            if node.min_area is not None
            else 0.99
        )
        for node in program.nodes
    )
    return round(max(0.9, minimum_scale), 6)


def _balanced_split_index(nodes) -> int:
    total = sum(float(node.target_area) for node in nodes)
    return min(
        range(1, len(nodes)),
        key=lambda index: abs(
            sum(float(node.target_area) for node in nodes[:index]) - total / 2
        ),
    )


def _rectangle(min_x: float, min_y: float, max_x: float, max_y: float):
    return [
        (_rounded_coordinate(min_x), _rounded_coordinate(min_y)),
        (_rounded_coordinate(max_x), _rounded_coordinate(min_y)),
        (_rounded_coordinate(max_x), _rounded_coordinate(max_y)),
        (_rounded_coordinate(min_x), _rounded_coordinate(max_y)),
    ]


def _canonical_shapes(shapes: list[RoomPolygon]) -> list[dict]:
    return sorted(
        (
            {
                "room_id": shape.room_id,
                "space_type": shape.space_type,
                "polygon": _canonical_polygon(shape.polygon),
            }
            for shape in shapes
        ),
        key=lambda shape: (
            shape["room_id"],
            shape["space_type"],
            shape["polygon"],
        ),
    )


def _canonical_polygon(points) -> list[list[float | int]]:
    rounded = [_canonical_point(point) for point in points]
    if len(rounded) > 1 and rounded[0] == rounded[-1]:
        rounded.pop()
    if not rounded:
        return []
    rotations = []
    for vertices in (rounded, list(reversed(rounded))):
        rotations.extend(vertices[index:] + vertices[:index] for index in range(len(vertices)))
    canonical = min(rotations)
    return [list(point) for point in canonical]


def _canonical_point(point) -> tuple[float | int, float | int]:
    return tuple(_rounded_coordinate(value) for value in point)


def _rounded_coordinate(value: float) -> float | int:
    rounded = round(float(value), 6)
    return int(rounded) if rounded.is_integer() else rounded
