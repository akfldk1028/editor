from __future__ import annotations

from backend.app.schemas.layout import LayoutCandidate, RoomPolygon
from backend.app.schemas.mass import MassAnalysis
from backend.app.schemas.program import ProgramGraph


def generate_baseline_layout(
    analysis: MassAnalysis,
    program: ProgramGraph,
) -> LayoutCandidate:
    min_x, min_y, max_x, max_y = analysis.bounds
    width = max_x - min_x
    total = sum(node.target_area for node in program.nodes) or 1
    cursor = min_x
    rooms: list[RoomPolygon] = []

    for index, node in enumerate(program.nodes):
        if index == len(program.nodes) - 1:
            next_x = max_x
        else:
            next_x = cursor + width * (node.target_area / total)
        rooms.append(
            RoomPolygon(
                room_id=node.node_id,
                space_type=node.space_type,
                polygon=[
                    (_clean_number(cursor), _clean_number(min_y)),
                    (_clean_number(next_x), _clean_number(min_y)),
                    (_clean_number(next_x), _clean_number(max_y)),
                    (_clean_number(cursor), _clean_number(max_y)),
                ],
            )
        )
        cursor = next_x

    return LayoutCandidate(
        candidate_id=f"{program.project_id}-f{program.floor_index}-baseline",
        project_id=program.project_id,
        floor_index=program.floor_index,
        rooms=rooms,
        circulation=[],
        score=0.0,
    )


def generate_stripe_layout(
    analysis: MassAnalysis,
    program: ProgramGraph,
    *,
    axis: str,
    reverse: bool = False,
) -> LayoutCandidate:
    if axis not in {"x", "y"}:
        raise ValueError("stripe axis must be 'x' or 'y'")
    nodes = list(reversed(program.nodes)) if reverse else list(program.nodes)
    min_x, min_y, max_x, max_y = analysis.bounds
    span = (max_x - min_x) if axis == "x" else (max_y - min_y)
    total = sum(node.target_area for node in nodes) or 1
    cursor = min_x if axis == "x" else min_y
    rooms: list[RoomPolygon] = []
    for index, node in enumerate(nodes):
        end = (
            (max_x if axis == "x" else max_y)
            if index == len(nodes) - 1
            else cursor + span * node.target_area / total
        )
        if axis == "x":
            polygon = _rectangle(cursor, min_y, end, max_y)
        else:
            polygon = _rectangle(min_x, cursor, max_x, end)
        rooms.append(RoomPolygon(node.node_id, node.space_type, polygon))
        cursor = end
    suffix = f"stripe-{axis}" + ("-reversed" if reverse else "")
    return _candidate(program, suffix, rooms)


def generate_guillotine_layout(
    analysis: MassAnalysis,
    program: ProgramGraph,
    *,
    reverse: bool = False,
) -> LayoutCandidate:
    nodes = list(reversed(program.nodes)) if reverse else list(program.nodes)
    rooms: list[RoomPolygon] = []

    def partition(items, rectangle, depth: int) -> None:
        min_x, min_y, max_x, max_y = rectangle
        if len(items) == 1:
            node = items[0]
            rooms.append(
                RoomPolygon(
                    node.node_id,
                    node.space_type,
                    _rectangle(min_x, min_y, max_x, max_y),
                )
            )
            return
        split_index = _balanced_split_index(items)
        left, right = items[:split_index], items[split_index:]
        left_weight = sum(node.target_area for node in left)
        total_weight = left_weight + sum(node.target_area for node in right)
        if depth % 2 == 0:
            split = min_x + (max_x - min_x) * left_weight / total_weight
            partition(left, (min_x, min_y, split, max_y), depth + 1)
            partition(right, (split, min_y, max_x, max_y), depth + 1)
        else:
            split = min_y + (max_y - min_y) * left_weight / total_weight
            partition(left, (min_x, min_y, max_x, split), depth + 1)
            partition(right, (min_x, split, max_x, max_y), depth + 1)

    partition(nodes, analysis.bounds, 0)
    suffix = "guillotine-balanced" + ("-reversed" if reverse else "")
    return _candidate(program, suffix, rooms)


def generate_core_aligned_layout(
    analysis: MassAnalysis,
    program: ProgramGraph,
    *,
    core_polygon: list[tuple[float, float]],
    service_band_width: float,
    room_scale: float = 0.9,
) -> LayoutCandidate:
    if not 0.85 <= room_scale < 1:
        raise ValueError("room_scale must leave circulation and respect program minima")
    min_x, min_y, max_x, max_y = analysis.bounds
    height = max_y - min_y
    width = max_x - min_x
    if height <= 0 or width <= 0:
        raise ValueError("mass bounds must have positive width and height")
    if service_band_width <= 0 or service_band_width >= width:
        raise ValueError("service band width must fit inside the floor plate")

    primary_nodes = [
        node
        for node in program.nodes
        if node.space_type in {"shop_unit", "office_area"}
    ]
    core_nodes = [node for node in program.nodes if node.space_type == "core"]
    if len(primary_nodes) != 1 or len(core_nodes) != 1:
        raise ValueError("core-aligned layout requires one primary space and one core")

    primary = primary_nodes[0]
    core = core_nodes[0]
    service_nodes = [
        node
        for node in program.nodes
        if node.node_id not in {primary.node_id, core.node_id}
    ]
    service_x = max_x - service_band_width
    primary_end = _aligned_number(
        min_x + room_scale * float(primary.target_area) / height
    )
    if primary_end >= service_x:
        raise ValueError("program leaves no connected circulation spine")

    core_min_x, core_min_y, core_max_x, core_max_y = _polygon_bounds(core_polygon)
    if (
        abs(core_min_x - service_x) > 1e-7
        or abs(core_min_y - min_y) > 1e-7
        or abs(core_max_x - max_x) > 1e-7
    ):
        raise ValueError("shared core must anchor to the service band")

    rooms = [
        RoomPolygon(
            primary.node_id,
            primary.space_type,
            _aligned_rectangle(min_x, min_y, primary_end, max_y),
        ),
        RoomPolygon(core.node_id, core.space_type, list(core_polygon)),
    ]
    cursor = core_max_y
    for node in service_nodes:
        next_y = _aligned_number(
            cursor + room_scale * float(node.target_area) / service_band_width
        )
        if next_y > max_y + 1e-6:
            raise ValueError("service program exceeds the shared service band")
        next_y = min(next_y, max_y)
        rooms.append(
            RoomPolygon(
                node.node_id,
                node.space_type,
                _aligned_rectangle(service_x, cursor, max_x, next_y),
            )
        )
        cursor = next_y

    if cursor < max_y - 1e-6:
        circulation_polygon = [
            (_aligned_number(primary_end), _aligned_number(min_y)),
            (_aligned_number(service_x), _aligned_number(min_y)),
            (_aligned_number(service_x), _aligned_number(cursor)),
            (_aligned_number(max_x), _aligned_number(cursor)),
            (_aligned_number(max_x), _aligned_number(max_y)),
            (_aligned_number(primary_end), _aligned_number(max_y)),
        ]
    else:
        circulation_polygon = _aligned_rectangle(
            primary_end,
            min_y,
            service_x,
            max_y,
        )

    return LayoutCandidate(
        candidate_id=f"{program.project_id}-f{program.floor_index}-core-aligned",
        project_id=program.project_id,
        floor_index=program.floor_index,
        rooms=rooms,
        circulation=[
            RoomPolygon(
                room_id="corridor",
                space_type="circulation",
                polygon=circulation_polygon,
            )
        ],
        score=0.0,
    )


def _balanced_split_index(nodes) -> int:
    total = sum(node.target_area for node in nodes)
    return min(
        range(1, len(nodes)),
        key=lambda index: abs(
            sum(node.target_area for node in nodes[:index]) - total / 2
        ),
    )


def _polygon_bounds(polygon: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    return (
        min(point[0] for point in polygon),
        min(point[1] for point in polygon),
        max(point[0] for point in polygon),
        max(point[1] for point in polygon),
    )


def _aligned_rectangle(
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
) -> list[tuple[float | int, float | int]]:
    return [
        (_aligned_number(min_x), _aligned_number(min_y)),
        (_aligned_number(max_x), _aligned_number(min_y)),
        (_aligned_number(max_x), _aligned_number(max_y)),
        (_aligned_number(min_x), _aligned_number(max_y)),
    ]


def _aligned_number(value: float) -> float | int:
    return int(value) if float(value).is_integer() else round(value, 6)


def _candidate(
    program: ProgramGraph,
    suffix: str,
    rooms: list[RoomPolygon],
) -> LayoutCandidate:
    return LayoutCandidate(
        candidate_id=f"{program.project_id}-f{program.floor_index}-{suffix}",
        project_id=program.project_id,
        floor_index=program.floor_index,
        rooms=rooms,
        circulation=[],
        score=0.0,
    )


def _rectangle(min_x: float, min_y: float, max_x: float, max_y: float):
    return [
        (_clean_number(min_x), _clean_number(min_y)),
        (_clean_number(max_x), _clean_number(min_y)),
        (_clean_number(max_x), _clean_number(max_y)),
        (_clean_number(min_x), _clean_number(max_y)),
    ]


def _clean_number(value: float) -> float | int:
    return int(value) if float(value).is_integer() else round(value, 4)
