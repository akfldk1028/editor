from __future__ import annotations

import math
from dataclasses import replace

from backend.app.schemas.layout import LayoutCandidate, OpeningSegment, RoomPolygon
from backend.app.schemas.mass import MassAnalysis
from backend.app.schemas.program import ProgramGraph
from backend.app.modules.basic_design.stair import (
    required_stair_enclosure,
    resolve_floor_height,
)
from engine.geometry import shared_boundary_segments
from engine.geometry.polygon import polygon_area


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
    min_circulation_width: float = 1.2,
) -> LayoutCandidate:
    commercial_tenants = (
        [node for node in program.nodes if node.space_type == "sales"]
        if program.use_type == "neighborhood_commercial"
        else []
    )
    if program.use_type == "neighborhood_commercial":
        tenant_ids = [node.tenant_id for node in commercial_tenants]
        if (
            len(commercial_tenants) != 2
            or set(node.node_id for node in commercial_tenants)
            != {"sales_a", "sales_b"}
            or any(not tenant_id for tenant_id in tenant_ids)
            or len(set(tenant_ids)) != 2
        ):
            raise ValueError(
                "commercial role contract requires sales_a/sales_b with unique tenant_id"
            )
    generation_program = program
    if len(commercial_tenants) >= 2:
        total_target = sum(float(node.target_area) for node in commercial_tenants)
        template = commercial_tenants[0]
        consolidated = replace(
            template,
            node_id="sales",
            tenant_id=None,
            target_area=total_target,
            min_area=total_target * 0.85,
            max_area=total_target * 1.15,
            min_width=5.0,
        )
        generation_program = replace(
            program,
            nodes=[
                consolidated,
                *(node for node in program.nodes if node.space_type != "sales"),
            ],
        )
    expected_roles = {
        "neighborhood_commercial": {
            "sales", "checkout", "stock", "staff", "restroom", "core", "utility"
        },
        "office": {
            "open_work", "meeting", "reception", "focus", "pantry", "restroom",
            "core", "it_storage",
        },
    }
    if generation_program.use_type in expected_roles:
        roles = [node.space_type for node in generation_program.nodes]
        expected = expected_roles[generation_program.use_type]
        missing = sorted(expected - set(roles))
        extra = sorted(set(roles) - expected)
        duplicate = sorted(role for role in set(roles) if roles.count(role) > 1)
        if missing or extra or duplicate:
            raise ValueError(
                "role-driven program roles must match the use-specific profile: "
                f"missing={missing}, extra={extra}, duplicate={duplicate}"
            )
        _validate_role_driven_core(core_polygon, generation_program, analysis.bounds)
        generated = _generate_role_driven_layout(
            analysis, generation_program, core_polygon
        )
        if commercial_tenants:
            return _split_sales_tenants(generated, commercial_tenants)
        return generated
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
        min(
            min_x + room_scale * float(primary.target_area) / height,
            service_x - min_circulation_width,
        )
    )
    if (float(primary_end) - min_x) * height < float(primary.min_area or 0):
        raise ValueError("minimum circulation width violates primary room minimum area")
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
    service_boundaries: list[tuple[float, float, float]] = []
    for node in service_nodes:
        scaled_area = room_scale * float(node.target_area)
        room_height = max(scaled_area / service_band_width, 0.9)
        room_width = scaled_area / room_height
        room_min_x = _aligned_number(max_x - room_width)
        next_y = _aligned_number(cursor + room_height)
        if next_y > max_y + 1e-6:
            raise ValueError("service program exceeds the shared service band")
        next_y = min(next_y, max_y)
        rooms.append(
            RoomPolygon(
                node.node_id,
                node.space_type,
                _aligned_rectangle(room_min_x, cursor, max_x, next_y),
            )
        )
        service_boundaries.append((float(room_min_x), float(cursor), float(next_y)))
        cursor = next_y

    circulation_polygon = [
        (_aligned_number(primary_end), _aligned_number(min_y)),
        (_aligned_number(service_x), _aligned_number(min_y)),
        (_aligned_number(service_x), _aligned_number(core_max_y)),
    ]
    for index, (room_min_x, room_min_y, room_max_y) in enumerate(service_boundaries):
        if circulation_polygon[-1][0] != _aligned_number(room_min_x):
            circulation_polygon.append(
                (_aligned_number(room_min_x), _aligned_number(room_min_y))
            )
        circulation_polygon.append(
            (_aligned_number(room_min_x), _aligned_number(room_max_y))
        )
        if index + 1 < len(service_boundaries):
            next_min_x = service_boundaries[index + 1][0]
            if room_min_x != next_min_x:
                circulation_polygon.append(
                    (_aligned_number(next_min_x), _aligned_number(room_max_y))
                )
    if cursor < max_y - 1e-6:
        circulation_polygon.extend(
            [
                (_aligned_number(max_x), _aligned_number(cursor)),
                (_aligned_number(max_x), _aligned_number(max_y)),
            ]
        )
    circulation_polygon.append(
        (_aligned_number(primary_end), _aligned_number(max_y))
    )

    circulation = RoomPolygon(
        room_id="corridor",
        space_type="circulation",
        polygon=circulation_polygon,
    )
    openings = [
        _centered_door(room, circulation)
        for room in rooms
    ]
    return LayoutCandidate(
        candidate_id=f"{program.project_id}-f{program.floor_index}-core-aligned",
        project_id=program.project_id,
        floor_index=program.floor_index,
        rooms=rooms,
        circulation=[circulation],
        score=0.0,
        openings=openings,
    )


def generate_rear_center_layout(
    analysis: MassAnalysis,
    program: ProgramGraph,
    *,
    min_circulation_width: float = 1.2,
    core_position: str = "rear_center",
    floor_to_floor_height_m: float | None = None,
) -> LayoutCandidate:
    """Generate a direct rear-center-core topology with a public access spine."""
    min_x, min_y, max_x, max_y = analysis.bounds
    stair_height, _ = resolve_floor_height(floor_to_floor_height_m)
    _, stair_long_side = required_stair_enclosure(stair_height)
    depth = max_y - min_y
    core_node = next(node for node in program.nodes if node.space_type == "core")
    rear_height = max(stair_long_side + 0.25, 5.2, depth * 0.5)
    core_width = max(7.0, _layout_area(core_node) / rear_height)
    if core_position == "rear_center":
        core_min_x = (min_x + max_x - core_width) / 2
    elif core_position == "rear_right":
        core_min_x = max_x - core_width
    else:
        raise ValueError("core_position must be rear_center or rear_right")
    core_max_x = core_min_x + core_width
    core_min_y = max_y - rear_height
    branch_bottom = core_min_y - min_circulation_width
    if branch_bottom <= min_y + 3.0:
        raise ValueError("rear-center core leaves insufficient front program depth")
    core_room = RoomPolygon(
        core_node.node_id,
        "core",
        _aligned_rectangle(core_min_x, core_min_y, core_max_x, max_y),
    )
    branch = RoomPolygon(
        "corridor-branch",
        "circulation",
        _aligned_rectangle(min_x, branch_bottom, max_x, core_min_y),
    )
    service_nodes = [
        node
        for node in program.nodes
        if node.space_type not in {"core", "sales", "open_work"}
    ]
    service_nodes.sort(key=lambda node: node.node_id)
    service_widths = {
        node.node_id: max(
            _layout_area(node) / rear_height,
            float(node.min_width or 0),
            1.1,
        )
        for node in service_nodes
    }
    service_rooms = []
    left_cursor = min_x + stair_long_side
    right_cursor = core_max_x
    left_capacity = core_min_x - left_cursor
    right_capacity = max_x - right_cursor
    support_ids = {"pantry", "restroom", "it_storage"} & set(service_widths)
    feasible_splits = []
    for mask in range(1 << len(service_nodes)):
        left_ids = {
            node.node_id
            for index, node in enumerate(service_nodes)
            if mask & (1 << index)
        }
        left_used = sum(service_widths[node_id] for node_id in left_ids)
        right_used = sum(
            width
            for node_id, width in service_widths.items()
            if node_id not in left_ids
        )
        if (
            left_used <= left_capacity + 1e-7
            and right_used <= right_capacity + 1e-7
        ):
            feasible_splits.append(
                (
                    (
                        0
                        if not support_ids
                        or support_ids.issubset(left_ids)
                        or not (support_ids & left_ids)
                        else 1
                    ),
                    abs(
                        (left_capacity - left_used)
                        - (right_capacity - right_used)
                    ),
                    tuple(sorted(left_ids)),
                    left_ids,
                )
            )
    if feasible_splits:
        left_ids = min(feasible_splits, key=lambda split: split[:3])[3]
    else:
        fallback_splits = []
        for mask in range(1 << len(service_nodes)):
            left_ids = {
                node.node_id
                for index, node in enumerate(service_nodes)
                if mask & (1 << index)
            }
            left_used = sum(service_widths[node_id] for node_id in left_ids)
            right_used = sum(
                width
                for node_id, width in service_widths.items()
                if node_id not in left_ids
            )
            fallback_splits.append(
                (
                    sum(
                        (
                            node.node_id in left_ids
                            and left_capacity <= 1e-7
                        )
                        or (
                            node.node_id not in left_ids
                            and right_capacity <= 1e-7
                        )
                        for node in service_nodes
                    ),
                    max(0.0, left_used - left_capacity)
                    + max(0.0, right_used - right_capacity),
                    (
                        0
                        if not support_ids
                        or support_ids.issubset(left_ids)
                        or not (support_ids & left_ids)
                        else 1
                    ),
                    abs(
                        (left_capacity - left_used)
                        - (right_capacity - right_used)
                    ),
                    tuple(sorted(left_ids)),
                    left_ids,
                ),
            )
        left_ids = min(fallback_splits, key=lambda split: split[:5])[5]
        left_used = sum(service_widths[node_id] for node_id in left_ids)
        right_used = sum(
            width
            for node_id, width in service_widths.items()
            if node_id not in left_ids
        )
        nodes_by_id = {node.node_id: node for node in service_nodes}
        for side_ids, used, side_capacity in (
            (left_ids, left_used, left_capacity),
            (set(service_widths) - left_ids, right_used, right_capacity),
        ):
            if used <= side_capacity + 1e-7:
                continue
            minimums = {
                node_id: max(
                    float(nodes_by_id[node_id].min_width or 0),
                    min(
                        rear_height
                        / float(
                            nodes_by_id[node_id].max_aspect_ratio
                            or math.inf
                        ),
                        math.sqrt(
                            _layout_area(nodes_by_id[node_id])
                            / float(
                                nodes_by_id[node_id].max_aspect_ratio
                                or math.inf
                            )
                        ),
                    ),
                    1.1,
                )
                for node_id in side_ids
            }
            minimum_total = sum(minimums.values())
            if minimum_total > side_capacity + 1e-7:
                raise ValueError(
                    "rear-center service minimum widths exceed rear bay"
                )
            desired_excess = sum(
                service_widths[node_id] - minimums[node_id]
                for node_id in side_ids
            )
            excess_scale = (
                (side_capacity - minimum_total) / desired_excess
                if desired_excess > 0
                else 0.0
            )
            for node_id in side_ids:
                service_widths[node_id] = minimums[node_id] + (
                    service_widths[node_id] - minimums[node_id]
                ) * excess_scale
    for node in service_nodes:
        target_area = _layout_area(node)
        room_width = service_widths[node.node_id]
        room_height = min(target_area / room_width, rear_height)
        if node.node_id in left_ids:
            cursor = left_cursor
            left_cursor += room_width
        else:
            cursor = right_cursor
            right_cursor += room_width
        if cursor + room_width > max_x + 1e-7:
            raise ValueError("rear-center service program exceeds rear bays")
        service_rooms.append(
            RoomPolygon(
                node.node_id,
                node.space_type,
                _aligned_rectangle(
                    cursor,
                    core_min_y,
                    cursor + room_width,
                    core_min_y + room_height,
                ),
            )
        )

    if program.use_type == "neighborhood_commercial":
        tenants = [node for node in program.nodes if node.space_type == "sales"]
        if len(tenants) != 2:
            raise ValueError("rear-center commercial layout requires two tenants")
        spine_left = (min_x + max_x - min_circulation_width) / 2
        spine_right = spine_left + min_circulation_width
        tenant_rooms = [
            RoomPolygon(
                tenants[0].node_id,
                "sales",
                _aligned_rectangle(min_x, min_y, spine_left, branch_bottom),
            ),
            RoomPolygon(
                tenants[1].node_id,
                "sales",
                _aligned_rectangle(spine_right, min_y, max_x, branch_bottom),
            ),
        ]
        spine = RoomPolygon(
            "corridor-spine",
            "circulation",
            _aligned_rectangle(spine_left, min_y, spine_right, branch_bottom),
        )
        rooms = [*tenant_rooms, core_room, *service_rooms]
    else:
        primary = next(node for node in program.nodes if node.space_type == "open_work")
        spine_left = min_x
        spine_right = min_x + min_circulation_width
        actual_width = min(
            _layout_area(primary) / branch_bottom,
            max_x - spine_right,
        )
        rooms = [
            RoomPolygon(
                primary.node_id,
                primary.space_type,
                _aligned_rectangle(
                    spine_right,
                    min_y,
                    spine_right + actual_width,
                    branch_bottom,
                ),
            ),
            core_room,
            *service_rooms,
        ]
        spine = RoomPolygon(
            "corridor-spine",
            "circulation",
            _aligned_rectangle(spine_left, min_y, spine_right, branch_bottom),
        )
    circulation = [spine, branch]
    openings = [_centered_door(room, circulation) for room in rooms]
    return LayoutCandidate(
        candidate_id=(
            f"{program.project_id}-f{program.floor_index}-"
            f"{core_position.replace('_', '-')}"
        ),
        project_id=program.project_id,
        floor_index=program.floor_index,
        rooms=rooms,
        circulation=circulation,
        score=0.0,
        openings=openings,
        remote_stair_footprint=tuple(
            _aligned_rectangle(
                min_x,
                core_min_y,
                min_x + stair_long_side,
                core_min_y + 2.8,
            )
        ),
    )


def generate_side_mid_layout(
    analysis: MassAnalysis,
    program: ProgramGraph,
    *,
    min_circulation_width: float = 1.2,
    cross_bottom_override: float | None = None,
    floor_to_floor_height_m: float | None = None,
) -> LayoutCandidate:
    """Generate a right-side mid-core with a longitudinal public corridor."""
    min_x, min_y, max_x, max_y = analysis.bounds
    stair_height, _ = resolve_floor_height(floor_to_floor_height_m)
    _, stair_long_side = required_stair_enclosure(stair_height)
    depth = max_y - min_y
    core_node = next(node for node in program.nodes if node.space_type == "core")
    core_height = max(7.2, depth * 0.6)
    core_width = max(
        _layout_area(core_node) / core_height,
        stair_long_side + 0.25,
    )
    core_min_x = max_x - core_width
    core_min_y = (min_y + max_y - core_height) / 2
    core_max_y = core_min_y + core_height
    branch_right = core_min_x
    branch_left = branch_right - min_circulation_width

    if program.use_type == "neighborhood_commercial":
        tenants = [node for node in program.nodes if node.space_type == "sales"]
        tenant_width = (branch_left - min_x) / 2
        tenant_height = max(
            _layout_area(node) / tenant_width for node in tenants
        )
        rooms = [
            RoomPolygon(
                tenants[0].node_id,
                "sales",
                _aligned_rectangle(
                    min_x, min_y, min_x + tenant_width, min_y + tenant_height
                ),
            ),
            RoomPolygon(
                tenants[1].node_id,
                "sales",
                _aligned_rectangle(
                    min_x + tenant_width,
                    min_y,
                    branch_left,
                    min_y + tenant_height,
                ),
            ),
        ]
    else:
        primary = next(node for node in program.nodes if node.space_type == "open_work")
        primary_width = branch_left - min_x
        tenant_height = _layout_area(primary) / primary_width
        rooms = [
            RoomPolygon(
                primary.node_id,
                primary.space_type,
                _aligned_rectangle(
                    min_x, min_y, branch_left, min_y + tenant_height
                ),
            )
        ]
    cross_bottom = (
        float(cross_bottom_override)
        if cross_bottom_override is not None
        else min_y + tenant_height
    )
    tenant_height = cross_bottom - min_y
    for index, room in enumerate(rooms):
        room_min_x, _, room_max_x, _ = _polygon_bounds(room.polygon)
        rooms[index] = RoomPolygon(
            room.room_id,
            room.space_type,
            _aligned_rectangle(
                room_min_x,
                min_y,
                room_max_x,
                cross_bottom,
            ),
        )
    cross_top = cross_bottom + min_circulation_width
    service_nodes = [
        node
        for node in program.nodes
        if node.space_type not in {"core", "sales", "open_work"}
    ]
    required_service_height = max(
        2.4,
        sum(_layout_area(node) for node in service_nodes)
        / max(branch_left - min_x - stair_long_side, 1.0),
    )
    while (
        sum(
            max(
                _layout_area(node) / required_service_height,
                float(node.min_width or 0),
                1.1,
            )
            for node in service_nodes
        )
        > branch_left - min_x - stair_long_side
        and required_service_height < depth - min_circulation_width - 2.0
    ):
        required_service_height += 0.1
    if max_y - cross_top < required_service_height:
        cross_top = max_y - required_service_height
        cross_bottom = cross_top - min_circulation_width
        tenant_height = cross_bottom - min_y
        for index, room in enumerate(rooms):
            room_min_x, _, room_max_x, _ = _polygon_bounds(room.polygon)
            rooms[index] = RoomPolygon(
                room.room_id,
                room.space_type,
                _aligned_rectangle(
                    room_min_x, min_y, room_max_x, min_y + tenant_height
                ),
            )
    if cross_top >= max_y - 2.4:
        raise ValueError("side-mid layout leaves insufficient rear service depth")
    horizontal = RoomPolygon(
        "corridor-cross",
        "circulation",
        _aligned_rectangle(min_x, cross_bottom, branch_left, cross_top),
    )
    longitudinal = RoomPolygon(
        "corridor-longitudinal",
        "circulation",
        _aligned_rectangle(branch_left, min_y, branch_right, max_y),
    )
    core_room = RoomPolygon(
        core_node.node_id,
        "core",
        _aligned_rectangle(core_min_x, core_min_y, max_x, core_max_y),
    )
    service_height = max_y - cross_top
    cursor = min_x + stair_long_side
    for node in service_nodes:
        room_width = max(
            _layout_area(node) / service_height,
            float(node.min_width or 0),
            1.1,
        )
        room_height = _layout_area(node) / room_width
        if cursor + room_width > branch_left + 1e-7:
            raise ValueError("side-mid service program exceeds rear service bay")
        rooms.append(
            RoomPolygon(
                node.node_id,
                node.space_type,
                _aligned_rectangle(
                    cursor,
                    cross_top,
                    cursor + room_width,
                    cross_top + room_height,
                ),
            )
        )
        cursor += room_width
    rooms.append(core_room)
    circulation = [horizontal, longitudinal]
    openings = [_centered_door(room, circulation) for room in rooms]
    return LayoutCandidate(
        candidate_id=f"{program.project_id}-f{program.floor_index}-side-mid",
        project_id=program.project_id,
        floor_index=program.floor_index,
        rooms=rooms,
        circulation=circulation,
        score=0.0,
        openings=openings,
        remote_stair_footprint=tuple(
            _aligned_rectangle(
                min_x,
                cross_top,
                min_x + stair_long_side,
                cross_top + 2.8,
            )
        ),
    )


def _generate_role_driven_layout(
    analysis: MassAnalysis,
    program: ProgramGraph,
    core_polygon: list[tuple[float, float]],
) -> LayoutCandidate:
    """Place the two supported profiles around one connected spine and branch."""
    min_x, min_y, max_x, max_y = analysis.bounds
    height = max_y - min_y
    nodes = {node.space_type: node for node in program.nodes}
    if len(nodes) != len(program.nodes):
        raise ValueError("role-driven layout requires unique room roles")
    primary_role = "sales" if program.use_type == "neighborhood_commercial" else "open_work"
    if primary_role not in nodes or "core" not in nodes:
        raise ValueError("role-driven layout is missing its required primary or core role")
    core_min_x, core_min_y, core_max_x, core_max_y = _polygon_bounds(core_polygon)
    if core_max_x != max_x or core_min_y != min_y:
        raise ValueError("shared core must anchor at the rear-bottom corner")

    primary = nodes[primary_role]
    primary_depth = (
        height - 1.2
        if program.use_type == "neighborhood_commercial"
        else height
    )
    primary_width = _layout_area(primary) / primary_depth
    spine_right = primary_width + min_x + 1.2
    spine_left = float(_aligned_number(spine_right - 1.2))
    spine_right = float(_aligned_number(spine_right))
    if spine_right >= core_min_x:
        raise ValueError("program leaves no space for a connected circulation spine")
    branch_bottom = core_max_y
    branch_top = branch_bottom + 1.2
    if branch_top >= max_y:
        raise ValueError("shared core leaves no space for circulation branch")
    lower_width = core_min_x - spine_right
    upper_height = max_y - branch_top
    if lower_width <= 0 or upper_height <= 0:
        raise ValueError("program leaves no room for service roles")

    rooms = [
        RoomPolygon(primary.node_id, primary.space_type, _aligned_rectangle(min_x, min_y, spine_left, max_y)),
        RoomPolygon(nodes["core"].node_id, nodes["core"].space_type, list(core_polygon)),
    ]
    lower_roles, upper_roles = (
        (("checkout", "staff"), ("stock", "restroom", "utility"))
        if primary_role == "sales"
        else (("focus", "pantry"), ("meeting", "reception", "restroom", "it_storage"))
    )
    lower_cursor = min_y if primary_role == "sales" and height >= 12 else spine_right
    for role in lower_roles:
        node = nodes[role]
        if primary_role == "sales":
            target_area = _layout_area(node)
            if height < 12:
                room_width = max(
                    float(node.min_width or 0),
                    math.sqrt(
                        target_area / float(node.max_aspect_ratio or math.inf)
                    )
                    * 1.001,
                )
                room_height = target_area / room_width
                if lower_cursor + room_width > core_min_x + 1e-7:
                    raise ValueError(f"role '{role}' cannot fit beside the shared core")
                room_min_y = branch_bottom - room_height
                rooms.append(RoomPolygon(node.node_id, node.space_type, _aligned_rectangle(lower_cursor, room_min_y, lower_cursor + room_width, branch_bottom)))
                lower_cursor += room_width
                continue
            room_width = min(
                lower_width,
                math.sqrt(target_area * float(node.max_aspect_ratio or math.inf)) * 0.999999,
                target_area / float(node.min_width or 1),
            )
            room_height = target_area / room_width
            if lower_cursor + room_height > branch_bottom + 1e-7:
                raise ValueError(f"role '{role}' cannot fit beside the shared core")
            rooms.append(RoomPolygon(node.node_id, node.space_type, _aligned_rectangle(spine_right, lower_cursor, spine_right + room_width, lower_cursor + room_height)))
            lower_cursor += room_height
            continue
        target_area = _layout_area(node)
        room_width = max(
            min(
                lower_width,
                math.sqrt(target_area * float(node.max_aspect_ratio or math.inf))
                * 0.999,
                target_area / float(node.min_width or 1),
            ),
            float(node.min_width or 0),
            math.sqrt(target_area / float(node.max_aspect_ratio or math.inf)) * 1.001,
        )
        room_height = target_area / room_width
        lower_cursor = min_y if lower_cursor == spine_right else lower_cursor
        if lower_cursor + room_height > branch_bottom + 1e-7:
            raise ValueError(f"role '{role}' cannot fit beside the shared core")
        rooms.append(
            RoomPolygon(
                node.node_id,
                node.space_type,
                _aligned_rectangle(
                    spine_right,
                    lower_cursor,
                    spine_right + room_width,
                    lower_cursor + room_height,
                ),
            )
        )
        lower_cursor += room_height
    upper_cursor = spine_right
    for role in upper_roles:
        node = nodes[role]
        target_area = _layout_area(node)
        room_width = max(
            target_area / upper_height,
            float(node.min_width or 0),
            math.sqrt(target_area / float(node.max_aspect_ratio or math.inf)) * 1.001,
        )
        room_height = target_area / room_width
        room_min_y = branch_top
        if upper_cursor + room_width > max_x + 1e-7:
            raise ValueError(f"role '{role}' cannot fit above the circulation branch")
        rooms.append(RoomPolygon(node.node_id, node.space_type, _aligned_rectangle(upper_cursor, room_min_y, upper_cursor + room_width, room_min_y + room_height)))
        upper_cursor += room_width

    branch = RoomPolygon(
        room_id="corridor-branch",
        space_type="circulation",
        polygon=[
            (_aligned_number(spine_right), _aligned_number(branch_bottom)),
            (_aligned_number(max_x), _aligned_number(branch_bottom)),
            (_aligned_number(max_x), _aligned_number(branch_top)),
            (_aligned_number(spine_right), _aligned_number(branch_top)),
        ],
    )
    spine = RoomPolygon(
        room_id="corridor-spine",
        space_type="circulation",
        polygon=[
            (_aligned_number(spine_left), _aligned_number(min_y)),
            (_aligned_number(spine_right), _aligned_number(min_y)),
            (_aligned_number(spine_right), _aligned_number(max_y)),
            (_aligned_number(spine_left), _aligned_number(max_y)),
        ],
    )
    if primary_role == "sales" and height >= 12:
        circulation = [branch, spine]
    else:
        circulation = [
            RoomPolygon(
                room_id="corridor",
                space_type="circulation",
                polygon=[
                    (_aligned_number(spine_left), _aligned_number(min_y)),
                    (_aligned_number(spine_right), _aligned_number(min_y)),
                    (_aligned_number(spine_right), _aligned_number(branch_bottom)),
                    (_aligned_number(max_x), _aligned_number(branch_bottom)),
                    (_aligned_number(max_x), _aligned_number(branch_top)),
                    (_aligned_number(spine_right), _aligned_number(branch_top)),
                    (_aligned_number(spine_right), _aligned_number(max_y)),
                    (_aligned_number(spine_left), _aligned_number(max_y)),
                ],
            )
        ]
    openings = [_centered_door(room, circulation) for room in rooms]
    return LayoutCandidate(
        candidate_id=f"{program.project_id}-f{program.floor_index}-role-driven",
        project_id=program.project_id,
        floor_index=program.floor_index,
        rooms=rooms,
        circulation=circulation,
        score=0.0,
        openings=openings,
    )


def _split_sales_tenants(
    layout: LayoutCandidate,
    tenant_nodes,
) -> LayoutCandidate:
    sales = next(room for room in layout.rooms if room.room_id == "sales")
    min_x, min_y, max_x, max_y = _polygon_bounds(sales.polygon)
    public_corridor_width = 1.2
    tenant_max_y = max_y - public_corridor_width
    weights = [float(node.target_area) for node in tenant_nodes]
    split_x = min_x + (max_x - min_x) * weights[0] / sum(weights)
    tenant_rooms = [
        RoomPolygon(
            tenant_nodes[0].node_id,
            "sales",
            _aligned_rectangle(min_x, min_y, split_x, tenant_max_y),
        ),
        RoomPolygon(
            tenant_nodes[1].node_id,
            "sales",
            _aligned_rectangle(split_x, min_y, max_x, tenant_max_y),
        ),
    ]
    public_corridor = RoomPolygon(
        "tenant-public-corridor",
        "circulation",
        _aligned_rectangle(min_x, tenant_max_y, max_x, max_y),
    )
    rooms = [
        *tenant_rooms,
        *(room for room in layout.rooms if room.room_id != "sales"),
    ]
    circulation = [public_corridor, *layout.circulation]
    openings = [_centered_door(room, circulation) for room in rooms]
    return replace(
        layout,
        rooms=rooms,
        circulation=circulation,
        openings=openings,
    )


def _validate_role_driven_core(core_polygon, program: ProgramGraph, bounds) -> None:
    min_x, min_y, max_x, _ = bounds
    if len(core_polygon) != 4:
        raise ValueError("role-driven shared core must be an axis-aligned rectangle")
    core_min_x, core_min_y, core_max_x, core_max_y = _polygon_bounds(core_polygon)
    expected = {
        (core_min_x, core_min_y),
        (core_max_x, core_min_y),
        (core_max_x, core_max_y),
        (core_min_x, core_max_y),
    }
    if set(core_polygon) != expected or core_min_x <= min_x or core_max_x != max_x or core_min_y != min_y or core_max_y <= min_y:
        raise ValueError("role-driven shared core must be a rear-bottom axis-aligned rectangle")
    core = next(node for node in program.nodes if node.space_type == "core")
    area = polygon_area(core_polygon)
    target = float(core.target_area)
    if not target * 0.85 <= area <= target * 1.15:
        raise ValueError("role-driven shared core area must satisfy the core program tolerance")


def _layout_area(node) -> float:
    """Use the explicit program-area intent without a universal fill factor."""
    return float(node.target_area)


def _centered_door(
    room: RoomPolygon,
    circulation: RoomPolygon | list[RoomPolygon],
) -> OpeningSegment:
    paths = circulation if isinstance(circulation, list) else [circulation]
    candidates = [
        (path, segment)
        for path in paths
        for segment in shared_boundary_segments(room.polygon, path.polygon)
    ]
    if not candidates:
        raise ValueError(f"room '{room.room_id}' has no shared circulation boundary")
    circulation_path, (start, end) = max(
        candidates,
        key=lambda item: (math.dist(*item[1]), item[0].room_id, item[1]),
    )
    length = math.dist(start, end)
    width = 0.9
    if length + 1e-9 < width:
        raise ValueError(f"room '{room.room_id}' shared boundary is shorter than door")
    offset = (length - width) / (2 * length)
    door_start = tuple(
        start[index] + (end[index] - start[index]) * offset
        for index in range(2)
    )
    door_end = tuple(
        end[index] - (end[index] - start[index]) * offset
        for index in range(2)
    )
    return OpeningSegment(
        opening_id=f"{room.room_id}-door",
        kind="door",
        connects=(room.room_id, circulation_path.room_id),
        start=door_start,
        end=door_end,
        clear_width=width,
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
