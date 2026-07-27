from __future__ import annotations

import hashlib
import json
import math
from dataclasses import replace

from backend.app.modules.layout_generator.service import (
    generate_baseline_layout,
    generate_core_aligned_layout,
    generate_guillotine_layout,
    generate_stripe_layout,
)
from backend.app.schemas.layout import LayoutCandidate, RoomPolygon
from backend.app.schemas.loop import CandidateProposal, CandidateRecord
from backend.app.schemas.mass import MassAnalysis
from backend.app.schemas.metrics import ValidationReport
from backend.app.schemas.program import ProgramGraph


def layout_fingerprint(layout: LayoutCandidate) -> str:
    payload: dict[str, object] = {
        "rooms": _canonical_shapes(layout.rooms),
        "circulation": _canonical_shapes(layout.circulation),
    }
    if layout.openings:
        payload["openings"] = sorted(
            (
                {
                    "opening_id": opening.opening_id,
                    "kind": opening.kind,
                    "connects": sorted(opening.connects),
                    "endpoints": sorted(
                        [
                            list(_canonical_point(opening.start)),
                            list(_canonical_point(opening.end)),
                        ]
                    ),
                    "clear_width": _exact_coordinate(opening.clear_width),
                }
                for opening in layout.openings
            ),
            key=lambda opening: json.dumps(opening, sort_keys=True),
        )
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def generate_initial_candidates(
    analysis: MassAnalysis,
    program: ProgramGraph,
) -> list[LayoutCandidate]:
    return [
        proposal.layout
        for proposal in generate_initial_proposals(analysis, program)
    ]


def generate_initial_proposals(
    analysis: MassAnalysis,
    program: ProgramGraph,
) -> list[CandidateProposal]:
    proposals = [
        CandidateProposal(
            layout=generate_baseline_layout(analysis, program),
            parent_id=None,
            operator="baseline",
        ),
        CandidateProposal(
            layout=generate_stripe_layout(analysis, program, axis="x", reverse=True),
            parent_id=None,
            operator="stripe-x-reversed",
        ),
        CandidateProposal(
            layout=generate_stripe_layout(analysis, program, axis="y"),
            parent_id=None,
            operator="stripe-y",
        ),
        CandidateProposal(
            layout=generate_stripe_layout(analysis, program, axis="y", reverse=True),
            parent_id=None,
            operator="stripe-y-reversed",
        ),
        CandidateProposal(
            layout=generate_guillotine_layout(analysis, program),
            parent_id=None,
            operator="guillotine-balanced",
        ),
        CandidateProposal(
            layout=generate_guillotine_layout(analysis, program, reverse=True),
            parent_id=None,
            operator="guillotine-balanced-reversed",
        ),
    ]
    return _deduplicate_proposals(proposals)


def _deduplicate_proposals(
    proposals: list[CandidateProposal],
) -> list[CandidateProposal]:
    seen: set[str] = set()
    unique: list[CandidateProposal] = []
    for proposal in proposals:
        fingerprint = layout_fingerprint(proposal.layout)
        if fingerprint not in seen:
            seen.add(fingerprint)
            unique.append(proposal)
    return unique


def deduplicate_candidates(
    candidates: list[LayoutCandidate],
) -> list[LayoutCandidate]:
    return [
        proposal.layout
        for proposal in _deduplicate_proposals(
            [
                CandidateProposal(
                    layout=candidate,
                    parent_id=None,
                    operator="unspecified",
                )
                for candidate in candidates
            ]
        )
    ]


def refine_candidates(
    frontier: list[CandidateRecord | LayoutCandidate],
    reports: list[ValidationReport],
    analysis: MassAnalysis,
    program: ProgramGraph,
    iteration: int,
) -> list[LayoutCandidate]:
    return [
        proposal.layout
        for proposal in refine_proposals(
            frontier,
            reports,
            analysis,
            program,
            iteration,
        )
    ]


def refine_proposals(
    frontier: list[CandidateRecord | LayoutCandidate],
    reports: list[ValidationReport],
    analysis: MassAnalysis,
    program: ProgramGraph,
    iteration: int,
) -> list[CandidateProposal]:
    proposals: list[CandidateProposal] = []
    for parent, report in zip(frontier, reports):
        if "circulation_missing" not in {
            violation.code for violation in report.violations
        }:
            continue
        parent_layout = parent.layout if isinstance(parent, CandidateRecord) else parent
        parent_fingerprint = (
            parent.fingerprint
            if isinstance(parent, CandidateRecord)
            else layout_fingerprint(parent_layout)
        )
        proposals.extend(
            _corridor_proposals(
                parent_layout,
                parent_fingerprint,
                analysis,
                program,
                iteration,
            )
        )
    return _deduplicate_proposals(proposals)


def _corridor_proposals(
    parent: LayoutCandidate,
    parent_fingerprint: str,
    analysis: MassAnalysis,
    program: ProgramGraph,
    iteration: int,
) -> list[CandidateProposal]:
    role_sets = {
        frozenset({"sales", "checkout", "stock", "staff", "restroom", "core", "utility"}),
        frozenset({"open_work", "meeting", "reception", "focus", "pantry", "restroom", "core", "it_storage"}),
    }
    if frozenset(node.space_type for node in program.nodes) in role_sets:
        min_x, min_y, max_x, max_y = analysis.bounds
        core = next(node for node in program.nodes if node.space_type == "core")
        height = max_y - min_y
        core_height = min(height * (0.47333333333333333 if height >= 12 else 0.46), height - 1.2)
        core_width = float(core.target_area) / core_height
        core = _rectangle(
            round(max_x - core_width, 6), min_y, max_x, round(min_y + core_height, 6)
        )
        try:
            layout = generate_core_aligned_layout(
                analysis,
                program,
                core_polygon=core,
                service_band_width=core_width,
            )
        except ValueError:
            pass
        else:
            return [
                CandidateProposal(
                    layout=replace(layout, candidate_id=f"{layout.candidate_id}-i{iteration}"),
                    parent_id=parent.candidate_id,
                    operator="corridor-role-driven",
                    operator_params={
                        "order": "role-driven",
                        "topology": "spine-branch",
                    },
                )
            ]
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
    proposals = []
    for axis in ("horizontal", "vertical"):
        for order_name, nodes in orderings:
            operator = f"corridor-{axis}"
            layout = _corridor_layout(
                parent_fingerprint,
                analysis,
                program,
                iteration=iteration,
                axis=axis,
                order_name=order_name,
                nodes=nodes,
                scale=scale,
            )
            proposals.append(
                CandidateProposal(
                    layout=layout,
                    parent_id=parent.candidate_id,
                    operator=operator,
                    operator_params={"order": order_name},
                )
            )
    return proposals


def _corridor_layout(
    parent_fingerprint: str,
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

    candidate_id = (
        f"{program.project_id}-f{program.floor_index}-i{iteration}-"
        f"corridor-{axis}-{order_name}-{parent_fingerprint[:12]}"
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
    conservative_minimum = max(
        math.nextafter(minimum_scale, math.inf),
        minimum_scale + 1e-9,
    )
    return max(0.9, conservative_minimum)


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
        (_generated_coordinate(min_x), _generated_coordinate(min_y)),
        (_generated_coordinate(max_x), _generated_coordinate(min_y)),
        (_generated_coordinate(max_x), _generated_coordinate(max_y)),
        (_generated_coordinate(min_x), _generated_coordinate(max_y)),
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


def _canonical_polygon(points) -> list[list[str]]:
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


def _canonical_point(point) -> tuple[str, str]:
    return tuple(_exact_coordinate(value) for value in point)


def _exact_coordinate(value: float) -> str:
    coordinate = float(value)
    if coordinate == 0:
        coordinate = 0.0
    return coordinate.hex()


def _generated_coordinate(value: float) -> float | int:
    coordinate = float(value)
    return int(coordinate) if coordinate.is_integer() else coordinate
