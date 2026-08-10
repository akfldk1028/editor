from __future__ import annotations

import math
from dataclasses import dataclass, replace

from shapely.geometry import LineString, Polygon

from backend.app.schemas.layout import (
    BasicDesignFeatures,
    LayoutCandidate,
    PlanElement,
    PlanLine,
    RoomPolygon,
    UsePlanningMetadata,
)
from backend.app.modules.basic_design.stair import (
    create_door_swing,
    create_stair_geometry,
    required_stair_enclosure,
    resolve_floor_height,
)
from backend.engine.geometry.access import orthogonal_min_width, shared_boundary_segments
from backend.engine.geometry.distance import segment_to_segment_distance
from backend.engine.geometry.polygon import contains_polygon, polygon_area, polygon_overlap_area

Point = tuple[float, float]
Segment = tuple[Point, Point]
_EPSILON = 1e-7
_ROUTE_TOLERANCE = 1e-6
_STAIR_SHORT_SIDE = 2.8
_CORE_LOBBY_MIN_DEPTH = 0.25
_CORE_BANK_MIN_WIDTH = 1.2
_CORE_BANK_DEPTH = 2.4
_PROTECTED_OPENING_WIDTH = 0.9


class ConceptObjectArrangementError(ValueError):
    def __init__(self, room_id: str, kind: str, message: str) -> None:
        self.room_id = room_id
        self.kind = kind
        super().__init__(message)


@dataclass(frozen=True)
class StructureSet:
    lines: tuple[PlanLine, ...]
    columns: tuple[PlanElement, ...]


@dataclass(frozen=True)
class _CirculationCell:
    min_x: float
    min_y: float
    max_x: float
    max_y: float


def generate_basic_design(
    layout: LayoutCandidate,
    *,
    boundary: list[Point],
    street_segments: list[Segment],
    shared_structure: StructureSet | None = None,
    floor_to_floor_height_m: float | None = None,
) -> BasicDesignFeatures:
    """Generate a deterministic concept-design annotation set for a validated layout."""
    _require_finite_points(boundary, "floor boundary", 3)
    if len(street_segments) != 1:
        raise ValueError("basic design requires exactly one supplied street edge")
    cores = [room for room in layout.rooms if room.space_type == "core"]
    if len(cores) != 1:
        raise ValueError("basic design requires exactly one core room")
    core = cores[0]
    _require_rectangular_core(core)
    if not layout.circulation:
        raise ValueError("basic design requires circulation")
    if not layout.openings:
        raise ValueError("basic design requires validated room doors")
    circulation_cells = _circulation_cells(layout.circulation)

    exits = _protected_exits(
        core,
        layout.circulation,
        layout.remote_stair_footprint,
        boundary,
    )
    resolved_height, height_source = resolve_floor_height(floor_to_floor_height_m)
    elements = _core_elements(
        core,
        exits,
        layout.remote_stair_footprint,
        floor_to_floor_height_m=resolved_height,
    )
    lines: list[PlanLine] = [*exits, *_core_access_lines(elements, exits)]
    entry_lines = {
        line.target_id: line
        for line in lines
        if line.kind in {"protected_exit", "stair_door"}
    }
    elements = [
        replace(
            element,
            stair_geometry=create_stair_geometry(
                element.footprint,
                floor_to_floor_height_m=resolved_height,
                height_source=height_source,
                entry_points=entry_lines[element.element_id].points,
            ),
        )
        if element.kind == "stair"
        else element
        for element in elements
    ]
    stair_geometries = {
        element.element_id: element.stair_geometry
        for element in elements
        if element.stair_geometry is not None
    }
    stair_elements = {
        element.element_id: element
        for element in elements
        if element.kind == "stair"
    }
    lines = [
        replace(
            line,
            door_swing=create_door_swing(
                line,
                next(
                    landing.footprint
                    for landing in stair_geometries[line.target_id].landings
                    if landing.role == "floor_lower"
                ),
            ),
        )
        if (
            line.kind == "stair_door"
            or (
                line.kind == "protected_exit"
                and stair_elements[line.target_id].host_id == "floor"
            )
        )
        else line
        for line in lines
    ]
    lines.extend(_egress_routes(layout, exits, circulation_cells))
    if shared_structure is None:
        grid_lines, columns = _structure(boundary, (layout,), ((elements, exits),))
    else:
        grid_lines, columns = list(shared_structure.lines), list(shared_structure.columns)
    lines.extend(grid_lines)
    elements.extend(columns)
    envelope_lines = _envelope(layout, boundary, street_segments)
    lines.extend(envelope_lines)
    object_elements = _room_contents(layout, elements, lines)
    elements.extend(object_elements)
    lines.extend(_dimensions_and_site(boundary, layout.circulation, street_segments))
    planning = None
    if any(room.space_type == "open_work" for room in layout.rooms):
        reception_route = next(
            (
                line.line_id
                for line in lines
                if line.kind == "egress_route"
                and line.host_id == "reception"
            ),
            None,
        )
        planning = UsePlanningMetadata(
            reception_to_lobby_route_line_id=reception_route,
            support_room_ids=tuple(
                room.room_id
                for room in layout.rooms
                if room.space_type in {"pantry", "restroom", "it_storage"}
            ),
        )
    return BasicDesignFeatures(
        elements=tuple(elements),
        lines=tuple(lines),
        planning=planning,
    )


def generate_shared_structure(
    boundary: list[Point],
    layouts: tuple[LayoutCandidate, ...],
    *,
    floor_to_floor_height_m: float | None = None,
) -> StructureSet:
    if not layouts:
        raise ValueError("shared structure requires at least one floor layout")
    core_data = []
    for layout in layouts:
        cores = [room for room in layout.rooms if room.space_type == "core"]
        if len(cores) != 1:
            raise ValueError("shared structure requires exactly one core per floor")
        core = cores[0]
        _require_rectangular_core(core)
        exits = _protected_exits(
            core,
            layout.circulation,
            layout.remote_stair_footprint,
            boundary,
        )
        resolved_height, _ = resolve_floor_height(floor_to_floor_height_m)
        elements = _core_elements(
            core,
            exits,
            layout.remote_stair_footprint,
            floor_to_floor_height_m=resolved_height,
        )
        core_data.append((elements, exits))
    lines, columns = _structure(boundary, layouts, tuple(core_data))
    return StructureSet(lines=tuple(lines), columns=tuple(columns))


def _core_elements(
    core: RoomPolygon,
    exits: list[PlanLine],
    remote_stair_footprint: tuple[Point, ...] | None,
    *,
    floor_to_floor_height_m: float,
) -> list[PlanElement]:
    min_x, min_y, max_x, max_y = _bounds(core.polygon)
    if len(exits) != 2:
        raise ValueError("core subdivision requires two protected exits")
    first_start, first_end = exits[0].points
    horizontal = abs(first_start[1] - first_end[1]) <= _EPSILON
    if horizontal:
        shared_coordinate = first_start[1]
        if abs(shared_coordinate - min_y) <= _EPSILON:
            inward_sign = 1.0
        elif abs(shared_coordinate - max_y) <= _EPSILON:
            inward_sign = -1.0
        else:
            raise ValueError("protected exits must lie on one core edge")
        span = max_x - min_x
        depth = max_y - min_y

        def local(u: float, d: float) -> Point:
            return (min_x + u, shared_coordinate + inward_sign * d)

    else:
        shared_coordinate = first_start[0]
        if abs(shared_coordinate - min_x) <= _EPSILON:
            inward_sign = 1.0
        elif abs(shared_coordinate - max_x) <= _EPSILON:
            inward_sign = -1.0
        else:
            raise ValueError("protected exits must lie on one core edge")
        span = max_y - min_y
        depth = max_x - min_x

        def local(u: float, d: float) -> Point:
            return (shared_coordinate + inward_sign * d, min_y + u)

    stair_short_side = min(
        _STAIR_SHORT_SIDE,
        (span - _CORE_BANK_MIN_WIDTH) / 2,
    )
    required_stair_short, required_stair_long = required_stair_enclosure(
        floor_to_floor_height_m
    )
    stair_long_side = required_stair_long
    central_width = span - 2 * stair_short_side
    lobby_depth = depth - stair_long_side
    if (
        stair_short_side + _EPSILON < required_stair_short
        or depth - _CORE_LOBBY_MIN_DEPTH + _EPSILON < required_stair_long
        or central_width < _CORE_BANK_MIN_WIDTH - _EPSILON
        or lobby_depth < _CORE_LOBBY_MIN_DEPTH - _EPSILON
    ):
        raise ValueError(
            "core is too small for two height-derived separated stairs, "
            "a central bank, and lobby"
        )
    bank_depth = min(_CORE_BANK_DEPTH, depth - lobby_depth)
    elevator_width = min(1.8, central_width - 0.6)
    if elevator_width < 0.75 - _EPSILON:
        raise ValueError("core central bank cannot fit elevator and shaft")
    bank_start = depth - bank_depth
    stair_start = lobby_depth

    local_shapes = (
        (
            "core-stair-1",
            "stair",
            "UP",
            _local_rectangle(
                local,
                0.0,
                stair_start,
                stair_short_side,
                stair_start + stair_long_side,
            ),
        ),
        (
            "core-stair-2",
            "stair",
            "UP",
            _local_rectangle(
                local,
                span - stair_short_side,
                stair_start,
                span,
                stair_start + stair_long_side,
            ),
        ),
        (
            "core-elevator",
            "elevator",
            "ELEV",
            _local_rectangle(
                local,
                stair_short_side,
                bank_start,
                stair_short_side + elevator_width,
                depth,
            ),
        ),
        (
            "core-shaft",
            "shaft",
            "SHAFT",
            _local_rectangle(
                local,
                stair_short_side + elevator_width,
                bank_start,
                span - stair_short_side,
                depth,
            ),
        ),
        (
            "core-lobby",
            "lobby",
            "LOBBY",
            tuple(
                local(u, d)
                for u, d in (
                    (0.0, 0.0),
                    (span, 0.0),
                    (span, lobby_depth),
                    (span - stair_short_side, lobby_depth),
                    (span - stair_short_side, bank_start),
                    (stair_short_side, bank_start),
                    (stair_short_side, lobby_depth),
                    (0.0, lobby_depth),
                )
            ),
        ),
    )
    elements = [
        PlanElement(
            element_id=element_id,
            category="vertical",
            kind=kind,
            host_id=core.room_id,
            label=label,
            footprint=footprint,
        )
        for element_id, kind, label, footprint in local_shapes
    ]
    if remote_stair_footprint is None:
        raise ValueError("core elements require a remote stair reserve")
    elements = [
        (
            PlanElement(
                element_id="remote-stair-2",
                category="vertical",
                kind="stair",
                host_id="floor",
                label="UP",
                footprint=remote_stair_footprint,
            )
            if element.element_id == "core-stair-2"
            else element
        )
        for element in elements
    ]
    if not all(
        element.host_id == "floor"
        or contains_polygon(core.polygon, element.footprint)
        for element in elements
    ):
        raise ValueError("core subdivision must remain contained in the actual core")
    if any(
        polygon_overlap_area(left.footprint, right.footprint) > _EPSILON
        for index, left in enumerate(elements)
        for right in elements[index + 1 :]
    ):
        raise ValueError("core subdivision elements must not overlap")
    return elements


def _core_access_lines(
    elements: list[PlanElement],
    exits: list[PlanLine],
) -> list[PlanLine]:
    lobby = next(element for element in elements if element.kind == "lobby")
    stairs = {
        element.element_id: element
        for element in elements
        if element.kind == "stair"
    }
    lines: list[PlanLine] = []
    for index, exit_line in enumerate(exits, start=1):
        stair = stairs[exit_line.target_id or ""]
        if stair.host_id == "floor":
            continue
        shared = shared_boundary_segments(
            list(lobby.footprint),
            list(stair.footprint),
        )
        if not shared:
            raise ValueError("each stair must share a boundary with the core lobby")
        boundary = max(shared, key=lambda segment: math.dist(*segment))
        stair_door_points = _boundary_end_segment(
            boundary,
            _PROTECTED_OPENING_WIDTH,
        )
        stair_door = PlanLine(
            line_id=f"core-stair-door-{index}",
            category="egress",
            kind="stair_door",
            points=stair_door_points,
            host_id=lobby.element_id,
            target_id=stair.element_id,
            label=f"STAIR {index}",
            clear_width=_PROTECTED_OPENING_WIDTH,
        )
        exit_midpoint = _midpoint(exit_line.points[0], exit_line.points[-1])
        stair_midpoint = _midpoint(*stair_door_points)
        route_points = _orthogonal_route_in_polygon(
            exit_midpoint,
            stair_midpoint,
            lobby.footprint,
        )
        lines.extend(
            (
                stair_door,
                PlanLine(
                    line_id=f"core-lobby-route-{index}",
                    category="egress",
                    kind="lobby_route",
                    points=route_points,
                    host_id=lobby.element_id,
                    target_id=stair_door.line_id,
                    label="LOBBY ROUTE",
                ),
            )
        )
    return lines


def _protected_exits(
    core: RoomPolygon,
    circulation: list[RoomPolygon],
    remote_stair_footprint: tuple[Point, ...] | None,
    floor_boundary: list[Point],
) -> list[PlanLine]:
    shared = [
        segment
        for path in circulation
        for segment in shared_boundary_segments(core.polygon, path.polygon)
    ]
    if not shared:
        raise ValueError("core has no shared circulation boundary for protected exits")
    start, end = _ordered_segment(
        max(shared, key=lambda segment: math.dist(*segment))
    )
    length = math.dist(start, end)
    if length < _PROTECTED_OPENING_WIDTH - _EPSILON:
        raise ValueError("core/circulation shared boundary cannot fit a protected exit")
    if remote_stair_footprint is None:
        raise ValueError("layout must reserve a remote stair footprint")
    remote_candidates = [
        (path, segment)
        for path in circulation
        for segment in shared_boundary_segments(
            list(remote_stair_footprint),
            path.polygon,
        )
    ]
    if not remote_candidates:
        raise ValueError("remote stair reserve must share a circulation boundary")
    remote_path, remote_boundary = max(
        remote_candidates,
        key=lambda item: math.dist(*item[1]),
    )
    remote_start, remote_end = _ordered_segment(remote_boundary)
    remote_length = math.dist(remote_start, remote_end)
    if remote_length < _PROTECTED_OPENING_WIDTH - _EPSILON:
        raise ValueError("remote stair boundary cannot fit a protected exit")
    unit_x = (remote_end[0] - remote_start[0]) / remote_length
    unit_y = (remote_end[1] - remote_start[1]) / remote_length
    remote_end_segment = (
        (
            remote_end[0] - unit_x * _PROTECTED_OPENING_WIDTH,
            remote_end[1] - unit_y * _PROTECTED_OPENING_WIDTH,
        ),
        remote_end,
    )
    remote_start_segment = (
        remote_start,
        (
            remote_start[0] + unit_x * _PROTECTED_OPENING_WIDTH,
            remote_start[1] + unit_y * _PROTECTED_OPENING_WIDTH,
        ),
    )
    first, second = _nearest_separated_exit_openings(
        core_boundary=(start, end),
        remote_candidates=(remote_start_segment, remote_end_segment),
        opening_width=_PROTECTED_OPENING_WIDTH,
        separation_target=_maximum_pairwise_distance(floor_boundary) / 2.0,
    )
    return [
        PlanLine(
            line_id=f"protected-exit-{index}",
            category="egress",
            kind="protected_exit",
            points=points,
            host_id=core.room_id if index == 1 else remote_path.room_id,
            target_id="core-stair-1" if index == 1 else "remote-stair-2",
            label=f"EXIT {index}",
            clear_width=_PROTECTED_OPENING_WIDTH,
        )
        for index, points in enumerate((first, second), start=1)
    ]


def _egress_routes(
    layout: LayoutCandidate,
    exits: list[PlanLine],
    circulation_cells: list[_CirculationCell],
) -> list[PlanLine]:
    doors = {opening.connects[0]: opening for opening in layout.openings}
    routes: list[PlanLine] = []
    for room in layout.rooms:
        if room.space_type == "core":
            continue
        door = doors.get(room.room_id)
        if door is None:
            raise ValueError(f"room '{room.room_id}' has no validated door for egress")
        start = _midpoint(door.start, door.end)
        for exit_line in exits:
            routes.append(
                PlanLine(
                    line_id=f"{room.room_id}-route-{exit_line.line_id.rsplit('-', 1)[-1]}",
                    category="egress",
                    kind="egress_route",
                    points=_route_through_circulation(
                        start,
                        _midpoint(*exit_line.points),
                        circulation_cells,
                    ),
                    host_id=room.room_id,
                    target_id=exit_line.line_id,
                    label="EGRESS",
                )
            )
    return routes


def _circulation_cells(circulation: list[RoomPolygon]) -> list[_CirculationCell]:
    cells: list[_CirculationCell] = []
    for path in circulation:
        points = path.polygon
        _require_finite_points(points, f"circulation '{path.room_id}'", 4)
        if any(
            start[0] != end[0] and start[1] != end[1]
            for start, end in zip(points, [*points[1:], points[0]])
        ):
            raise ValueError(
                f"circulation '{path.room_id}' must be an axis-aligned rectilinear polygon"
            )
        x_values = sorted({point[0] for point in points})
        y_values = sorted({point[1] for point in points})
        for min_x, max_x in zip(x_values, x_values[1:]):
            for min_y, max_y in zip(y_values, y_values[1:]):
                if (
                    max_x - min_x <= _EPSILON
                    or max_y - min_y <= _EPSILON
                    or not _point_in_polygon_or_boundary(
                        ((min_x + max_x) / 2, (min_y + max_y) / 2),
                        points,
                    )
                ):
                    continue
                cell = _CirculationCell(min_x, min_y, max_x, max_y)
                if cell not in cells:
                    cells.append(cell)
    if not cells:
        raise ValueError("circulation has no routable axis-aligned rectangle cells")
    reachable = {0}
    frontier = [0]
    while frontier:
        current = frontier.pop()
        for index, candidate in enumerate(cells):
            if index not in reachable and _cell_portal(cells[current], candidate) is not None:
                reachable.add(index)
                frontier.append(index)
    if len(reachable) != len(cells):
        raise ValueError("circulation rectangle graph must be connected")
    return cells


def _route_through_circulation(
    start: Point,
    end: Point,
    cells: list[_CirculationCell],
) -> tuple[Point, ...]:
    start_cells = {
        index for index, cell in enumerate(cells) if _cell_contains_point(cell, start)
    }
    end_cells = {
        index for index, cell in enumerate(cells) if _cell_contains_point(cell, end)
    }
    if not start_cells or not end_cells:
        raise ValueError("egress route endpoint must lie on the circulation union")

    previous: dict[int, int | None] = {
        index: None for index in sorted(start_cells)
    }
    queue = list(sorted(start_cells))
    destination: int | None = None
    while queue:
        current = queue.pop(0)
        if current in end_cells:
            destination = current
            break
        for index, candidate in enumerate(cells):
            if (
                index not in previous
                and _cell_portal(cells[current], candidate) is not None
            ):
                previous[index] = current
                queue.append(index)
    if destination is None:
        raise ValueError("egress endpoints are disconnected in the circulation graph")

    cell_path = [destination]
    while previous[cell_path[-1]] is not None:
        cell_path.append(previous[cell_path[-1]])  # type: ignore[arg-type]
    cell_path.reverse()

    points = [start]
    for left_index, right_index in zip(cell_path, cell_path[1:]):
        portal = _cell_portal(cells[left_index], cells[right_index])
        if portal is None:
            raise ValueError("circulation graph contains a missing portal")
        _append_orthogonal(points, portal, cells[left_index])
    _append_orthogonal(points, end, cells[cell_path[-1]])
    return tuple(_simplify_polyline(points))


def _cell_portal(
    left: _CirculationCell,
    right: _CirculationCell,
) -> Point | None:
    if abs(left.max_x - right.min_x) <= _EPSILON or abs(
        right.max_x - left.min_x
    ) <= _EPSILON:
        bottom = max(left.min_y, right.min_y)
        top = min(left.max_y, right.max_y)
        if top - bottom > _EPSILON:
            x = (
                left.max_x
                if abs(left.max_x - right.min_x) <= _EPSILON
                else right.max_x
            )
            return (x, round((bottom + top) / 2, 6))
    if abs(left.max_y - right.min_y) <= _EPSILON or abs(
        right.max_y - left.min_y
    ) <= _EPSILON:
        left_x = max(left.min_x, right.min_x)
        right_x = min(left.max_x, right.max_x)
        if right_x - left_x > _EPSILON:
            y = (
                left.max_y
                if abs(left.max_y - right.min_y) <= _EPSILON
                else right.max_y
            )
            return (round((left_x + right_x) / 2, 6), y)
    return None


def _cell_contains_point(cell: _CirculationCell, point: Point) -> bool:
    return (
        cell.min_x - _ROUTE_TOLERANCE
        <= point[0]
        <= cell.max_x + _ROUTE_TOLERANCE
        and cell.min_y - _ROUTE_TOLERANCE
        <= point[1]
        <= cell.max_y + _ROUTE_TOLERANCE
    )


def _append_orthogonal(
    points: list[Point],
    target: Point,
    cell: _CirculationCell,
) -> None:
    current = points[-1]
    if not _cell_contains_point(cell, current) or not _cell_contains_point(cell, target):
        raise ValueError("egress waypoint must remain inside its circulation cell")
    if abs(current[0] - target[0]) <= _EPSILON or abs(
        current[1] - target[1]
    ) <= _EPSILON:
        points.append(target)
        return
    points.extend(((target[0], current[1]), target))


def _simplify_polyline(points: list[Point]) -> list[Point]:
    simplified: list[Point] = []
    for point in points:
        if simplified and math.dist(simplified[-1], point) <= _EPSILON:
            continue
        if len(simplified) >= 2:
            first, second = simplified[-2:]
            if (
                abs(first[0] - second[0]) <= _EPSILON
                and abs(second[0] - point[0]) <= _EPSILON
            ) or (
                abs(first[1] - second[1]) <= _EPSILON
                and abs(second[1] - point[1]) <= _EPSILON
            ):
                simplified[-1] = point
                continue
        simplified.append(point)
    return simplified


def _structure(
    boundary: list[Point],
    layouts: tuple[LayoutCandidate, ...],
    core_data: tuple[tuple[list[PlanElement], list[PlanLine]], ...],
) -> tuple[list[PlanLine], list[PlanElement]]:
    min_x, min_y, max_x, max_y = _bounds(boundary)
    x_values = _grid_values(min_x, max_x)
    y_values = _grid_values(min_y, max_y)
    lines = [
        PlanLine(
            line_id=f"grid-x-{index}",
            category="structure",
            kind="grid",
            points=((x, min_y), (x, max_y)),
            label=chr(65 + index),
        )
        for index, x in enumerate(x_values)
    ] + [
        PlanLine(
            line_id=f"grid-y-{index}",
            category="structure",
            kind="grid",
            points=((min_x, y), (max_x, y)),
            label=str(index + 1),
        )
        for index, y in enumerate(y_values)
    ]
    exclusions = [
        item
        for layout, (core_elements, _) in zip(layouts, core_data)
        for item in (
            *core_elements,
            *[
                PlanElement(
                    element_id=f"{room.room_id}-structure-exclusion",
                    category="vertical",
                    kind="core_exclusion",
                    host_id=room.room_id,
                    label="",
                    footprint=tuple(room.polygon),
                )
                for room in layout.rooms
                if room.space_type == "core"
            ],
            *[
                PlanElement(
                    element_id=path.room_id,
                    category="circulation",
                    kind="circulation",
                    host_id=path.room_id,
                    label="",
                    footprint=tuple(path.polygon),
                )
                for path in layout.circulation
            ],
        )
    ]
    columns: list[PlanElement] = []
    for x in x_values[1:-1]:
        for y in y_values[1:-1]:
            footprint = _rectangle(x - 0.2, y - 0.2, x + 0.2, y + 0.2)
            if not contains_polygon(boundary, footprint):
                continue
            if any(polygon_overlap_area(footprint, item.footprint) > _EPSILON for item in exclusions):
                continue
            if any(
                _rectangle_intersects_segment(footprint, opening.start, opening.end)
                for layout in layouts
                for opening in layout.openings
            ):
                continue
            if any(
                _rectangle_intersects_segment(footprint, *exit_line.points)
                for _, exits in core_data
                for exit_line in exits
            ):
                continue
            if any(polygon_overlap_area(footprint, column.footprint) > _EPSILON for column in columns):
                continue
            columns.append(
                PlanElement(
                    element_id=f"column-{len(columns) + 1}",
                    category="structure",
                    kind="column",
                    host_id="floor",
                    label="COL",
                    footprint=footprint,
                )
            )
    if not columns:
        fallback_x = _grid_values(min_x + 3.0, max_x - 3.0)
        fallback_y = _grid_values(min_y + 3.0, max_y - 3.0)
        for x in fallback_x:
            for y in fallback_y:
                footprint = _rectangle(x - 0.2, y - 0.2, x + 0.2, y + 0.2)
                if (
                    contains_polygon(boundary, footprint)
                    and not any(
                        polygon_overlap_area(footprint, item.footprint) > _EPSILON
                        for item in exclusions
                    )
                    and not any(
                        _rectangle_intersects_segment(
                            footprint, opening.start, opening.end
                        )
                        for layout in layouts
                        for opening in layout.openings
                    )
                ):
                    columns.append(
                        PlanElement(
                            element_id=f"column-{len(columns) + 1}",
                            category="structure",
                            kind="column",
                            host_id="floor",
                            label="COL",
                            footprint=footprint,
                        )
                    )
        if not columns:
            raise ValueError("no interior structural columns can be placed without collisions")
    return lines, columns


def _envelope(layout: LayoutCandidate, boundary: list[Point], streets: list[Segment]) -> list[PlanLine]:
    lines: list[PlanLine] = []
    street = streets[0] if streets else None
    commercial_sales_rooms = [
        room for room in layout.rooms if room.space_type == "sales"
    ]
    entrances: dict[str, tuple[Point, Point]] = {}
    if commercial_sales_rooms:
        if street is None:
            raise ValueError("commercial design requires a supplied street edge")
        for commercial_sales in commercial_sales_rooms:
            sales_street_edges = [
                segment
                for segment in _exterior_segments(commercial_sales.polygon, boundary)
                if _segment_within(segment, street)
            ]
            if not sales_street_edges:
                raise ValueError("commercial entrance street edge does not touch sales room")
            entrance = _centered_segment(
                max(sales_street_edges, key=lambda segment: math.dist(*segment)),
                1.8,
            )
            entrances[commercial_sales.room_id] = entrance
            lines.append(
                PlanLine(
                    line_id=f"{commercial_sales.room_id}-commercial-entrance",
                    category="envelope",
                    kind="entrance",
                    points=entrance,
                    host_id=commercial_sales.room_id,
                    label="TENANT ENTRANCE",
                    clear_width=1.8,
                )
            )
        public_street_edges = [
            (path.room_id, segment)
            for path in layout.circulation
            for segment in _exterior_segments(path.polygon, boundary)
            if _segment_within(segment, street)
            and math.dist(*segment) >= 0.9
        ]
        if not public_street_edges:
            raise ValueError(
                "commercial core requires a street-connected public circulation entrance"
            )
        public_path_id, public_edge = public_street_edges[0]
        lines.append(
            PlanLine(
                line_id="core-public-entrance",
                category="envelope",
                kind="entrance",
                points=_centered_segment(public_edge, 0.9),
                host_id="core",
                target_id=public_path_id,
                label="CORE ENTRY",
                clear_width=0.9,
            )
        )
    for room in layout.rooms:
        if room.space_type == "core":
            continue
        if room.room_id not in entrances:
            window = generate_room_window(room, boundary=boundary)
            if window is not None:
                lines.append(window)
            continue
        candidates = _exterior_segments(room.polygon, boundary)
        if not candidates:
            continue
        storefront_window: tuple[Point, Point] | None = None
        is_commercial_sales = room.room_id in entrances
        entrance = entrances.get(room.room_id)
        if is_commercial_sales and street is not None:
            alternate = [
                segment for segment in candidates
                if not _segment_within(segment, street)
            ]
            if alternate:
                candidates = alternate
            else:
                storefront_window = _disjoint_storefront_window(
                    max(candidates, key=lambda segment: math.dist(*segment)),
                    entrance,
                )
        selected = max(candidates, key=lambda segment: math.dist(*segment))
        length = math.dist(*selected)
        if storefront_window is None and length < 0.6:
            raise ValueError(f"perimeter room '{room.room_id}' has no usable exterior wall for window")
        window = storefront_window or _centered_segment(selected, min(1.5, length * 0.5))
        if (
            is_commercial_sales
            and entrance is not None
            and _collinear_overlap_length(window, entrance) > _EPSILON
        ):
            raise ValueError("sales window cannot be separated from the commercial entrance")
        lines.append(
            PlanLine(
                line_id=f"{room.room_id}-window",
                category="envelope",
                kind="window",
                points=window,
                host_id=room.room_id,
                label="WINDOW",
            )
        )
    return lines


def generate_room_window(
    room: RoomPolygon,
    *,
    boundary: list[Point],
) -> PlanLine | None:
    """Generate one deterministic exterior window, or None for an interior room."""
    candidates = _exterior_segments(room.polygon, boundary)
    if not candidates:
        return None
    selected = max(
        candidates,
        key=lambda segment: (
            math.dist(*segment),
            _ordered_segment(segment),
        ),
    )
    length = math.dist(*selected)
    if length < 0.6:
        raise ValueError(
            f"perimeter room '{room.room_id}' has no usable exterior wall for window"
        )
    return PlanLine(
        line_id=f"{room.room_id}-window",
        category="envelope",
        kind="window",
        points=_centered_segment(selected, min(1.5, length * 0.5)),
        host_id=room.room_id,
        label="WINDOW",
    )


def _room_contents(
    layout: LayoutCandidate,
    fixed_elements: list[PlanElement],
    fixed_lines: list[PlanLine],
) -> list[PlanElement]:
    """Place concept-basic-v1 representative objects, not ergonomic furniture."""
    required = {
        "meeting": (("meeting_table", "furniture"),),
        "reception": (("reception_desk", "furniture"),),
        "focus": (("focus_desk", "furniture"),),
        "pantry": (("pantry_counter", "fixture"), ("sink", "fixture")),
        "restroom": (("wc", "fixture"), ("lavatory", "fixture")),
        "it_storage": (("it_rack", "fixture"), ("it_rack", "fixture")),
        "checkout": (("checkout_counter", "furniture"),),
        "stock": (("stock_rack", "furniture"), ("stock_rack", "furniture")),
        "staff": (("staff_table", "furniture"),),
        "utility": (("utility_equipment", "fixture"),),
    }
    clearance_segments = [
        (opening.start, opening.end)
        for opening in layout.openings
    ] + [
        segment
        for line in fixed_lines
        if line.kind in {"egress_route", "entrance"}
        for segment in zip(line.points, line.points[1:])
    ]
    placed: list[PlanElement] = []
    for room in layout.rooms:
        room_requirements = required.get(room.space_type, ())
        object_size: tuple[float, float] | None = None
        placement_margin = 0.35
        aisle = 0.8
        room_clearance = list(clearance_segments)
        room_clearance.extend(
            (line.points[0], line.points[-1])
            for line in fixed_lines
            if line.kind == "window" and line.host_id == room.room_id
        )
        if _bounds(room.polygon)[2] - _bounds(room.polygon)[0] < 1.2:
            placement_margin = 0.3
        if room.space_type in {"sales", "open_work"}:
            # Representative density heuristic: at least one primary object
            # for every started 30 m2 of tenant or work area.
            count = max(1, math.ceil(polygon_area(room.polygon) / 30.0))
            primary_kind = (
                "sales_shelf" if room.space_type == "sales" else "workstation"
            )
            room_requirements = tuple(
                (primary_kind, "furniture") for _ in range(count)
            )
            object_size = (
                (2.8, 0.9)
                if room.space_type == "sales"
                else (2.8, 1.5)
            )
            placement_margin = 1.2
            aisle = 1.2
            room_min_x, _, room_max_x, _ = _bounds(room.polygon)
            if room_max_x - room_min_x < 8.5:
                object_size = (
                    (2.4, 0.8)
                    if room.space_type == "sales"
                    else (2.4, 1.4)
                )
                placement_margin = 0.8
                aisle = 1.0
            if room.space_type == "sales" and room.room_id.startswith("sales_"):
                tenant_width = room_max_x - room_min_x
                object_size = (
                    (0.8, 0.5)
                    if tenant_width < 8.0
                    else (1.4, 0.6)
                    if tenant_width < 12.5
                    else (2.0, 0.7)
                )
                placement_margin = 0.3
                aisle = 0.4
            if room.space_type == "open_work":
                work_area = polygon_area(room.polygon)
                minimum_count = math.ceil(work_area / 10.0)
                maximum_count = max(
                    minimum_count,
                    math.floor(work_area / 8.0),
                )
                count = min(
                    maximum_count,
                    max(minimum_count, round(work_area / 9.0)),
                )
                room_requirements = tuple(
                    ("workstation", "furniture") for _ in range(count)
                )
                object_size = (0.7, 0.7)
                placement_margin = 0.6
                aisle = 0.7
            room_clearance.extend(
                _primary_access_segments(room, layout, fixed_lines)
            )
        for kind, category in room_requirements:
            footprint = _place_object(
                room,
                kind,
                [
                    *(
                        element
                        for element in fixed_elements
                        if not (
                            element.kind == "stair"
                            and element.host_id == "floor"
                        )
                    ),
                    *placed,
                ],
                room_clearance,
                object_size=object_size,
                placement_margin=placement_margin,
                aisle=aisle,
            )
            label = {
                "sales_shelf": "GONDOLA",
                "workstation": "WORK BENCH",
            }.get(kind, kind.upper())
            placed.append(
                PlanElement(
                    element_id=f"{room.room_id}-{kind}-{sum(item.kind == kind for item in placed) + 1}",
                    category=category,
                    kind=kind,
                    host_id=room.room_id,
                    label=label,
                    footprint=footprint,
                )
            )
    return placed


def _primary_access_segments(
    room: RoomPolygon,
    layout: LayoutCandidate,
    fixed_lines: list[PlanLine],
) -> list[Segment]:
    min_x, min_y, max_x, max_y = _bounds(room.polygon)
    center = ((min_x + max_x) / 2, (min_y + max_y) / 2)
    endpoints = [
        _midpoint(opening.start, opening.end)
        for opening in layout.openings
        if room.room_id in opening.connects
    ] + [
        _midpoint(line.points[0], line.points[-1])
        for line in fixed_lines
        if line.kind == "entrance" and line.host_id == room.room_id
    ]
    segments = [
        segment
        for endpoint in endpoints
        for segment in _orthogonal_segments(endpoint, center)
    ]
    segments.extend(
        (line.points[0], line.points[-1])
        for line in fixed_lines
        if line.kind == "window" and line.host_id == room.room_id
    )
    return segments


def _orthogonal_segments(start: Point, end: Point) -> list[Segment]:
    bend = (round(end[0], 6), round(start[1], 6))
    return [
        segment
        for segment in ((start, bend), (bend, end))
        if math.dist(*segment) > _EPSILON
    ]


def _place_object(
    room: RoomPolygon,
    kind: str,
    occupied: list[PlanElement],
    clearance_segments: list[Segment],
    *,
    object_size: tuple[float, float] | None = None,
    placement_margin: float = 0.35,
    aisle: float = 0.8,
) -> tuple[Point, ...]:
    min_x, min_y, max_x, max_y = _bounds(room.polygon)
    width, height = max_x - min_x, max_y - min_y
    if object_size is None:
        object_width = min(1.2, max(0.45, width * 0.18))
        object_height = min(0.7, max(0.35, height * 0.16))
    else:
        object_width, object_height = object_size
    if (
        object_width + 2 * placement_margin > width
        or object_height + 2 * placement_margin > height
    ):
        if object_size is not None:
            raise ConceptObjectArrangementError(
                room.room_id,
                kind,
                f"room '{room.room_id}' cannot fit required {kind}",
            )
        raise ValueError(f"room '{room.room_id}' cannot fit required {kind}")
    y_values = _placement_values(
        min_y + placement_margin,
        max_y - object_height - placement_margin,
        object_height + aisle,
        include_end=object_size is None,
    )
    x_values = _placement_values(
        min_x + placement_margin,
        max_x - object_width - placement_margin,
        object_width + aisle,
        include_end=object_size is None,
    )
    room_shape = Polygon(room.polygon)
    occupied_shapes = tuple(Polygon(item.footprint) for item in occupied)

    def available(footprint: tuple[Point, ...]) -> bool:
        footprint_shape = Polygon(footprint)
        return (
            room_shape.covers(footprint_shape)
            and not any(
                footprint_shape.intersection(shape).area > _EPSILON
                for shape in occupied_shapes
            )
            and not any(
                _rectangle_near_segment(footprint, segment, clearance=0.6)
                for segment in clearance_segments
            )
        )

    candidates: list[tuple[Point, ...]] = []
    for y in y_values:
        for x in x_values:
            footprint = _rectangle(x, y, x + object_width, y + object_height)
            if available(footprint):
                candidates.append(footprint)
    if not candidates and object_size is not None:
        end_y_values = _placement_values(
            min_y + placement_margin,
            max_y - object_height - placement_margin,
            object_height + aisle,
        )
        end_x_values = _placement_values(
            min_x + placement_margin,
            max_x - object_width - placement_margin,
            object_width + aisle,
        )
        for y in end_y_values:
            for x in end_x_values:
                footprint = _rectangle(x, y, x + object_width, y + object_height)
                if available(footprint):
                    candidates.append(footprint)
    if not candidates:
        if object_size is not None:
            raise ConceptObjectArrangementError(
                room.room_id,
                kind,
                f"room '{room.room_id}' cannot place concept {kind} "
                "arrangement on its regular grid",
            )
        for y in _search_values(min_y + 0.2, max_y - object_height - 0.2):
            for x in _search_values(min_x + 0.2, max_x - object_width - 0.2):
                footprint = _rectangle(x, y, x + object_width, y + object_height)
                if available(footprint):
                    return footprint
    if candidates:
        siblings = [
            item for item in occupied if item.host_id == room.room_id
        ]
        if not siblings:
            return candidates[0]
        sibling_centers = [
            _footprint_center(item.footprint)
            for item in siblings
        ]
        return max(
            candidates,
            key=lambda footprint: min(
                math.dist(_footprint_center(footprint), center)
                for center in sibling_centers
            ),
        )
    raise ValueError(f"room '{room.room_id}' cannot place required {kind} without overlap")


def _dimensions_and_site(
    boundary: list[Point],
    circulation: list[RoomPolygon],
    streets: list[Segment],
) -> list[PlanLine]:
    min_x, min_y, max_x, max_y = _bounds(boundary)
    width, depth = max_x - min_x, max_y - min_y
    circulation_width = min(
        orthogonal_min_width(path.polygon)
        for path in circulation
    )
    lines = [
        PlanLine("dimension-overall-width", "dimension", "overall_width", ((min_x, min_y), (max_x, min_y)), label="WIDTH", measured_value=width),
        PlanLine("dimension-overall-depth", "dimension", "overall_depth", ((min_x, min_y), (min_x, max_y)), label="DEPTH", measured_value=depth),
        PlanLine("dimension-circulation-width", "dimension", "circulation_width", ((min_x, max_y), (min_x + circulation_width, max_y)), label="CIRC", measured_value=circulation_width),
        PlanLine("north-arrow", "site", "north_arrow", ((max_x - 1.0, max_y - 1.8), (max_x - 1.0, max_y - 0.6)), label="N"),
        PlanLine("scale-line", "site", "scale_line", ((min_x + 0.8, min_y + 0.8), (min_x + 5.8, min_y + 0.8)), label="5m", measured_value=5.0),
    ]
    if streets:
        lines.append(PlanLine("street-line", "site", "street", streets[0], label="STREET"))
    return lines


def _bounds(points: list[Point] | tuple[Point, ...]) -> tuple[float, float, float, float]:
    _require_finite_points(points, "geometry", 1)
    return min(point[0] for point in points), min(point[1] for point in points), max(point[0] for point in points), max(point[1] for point in points)


def _require_finite_points(points, label: str, minimum: int) -> None:
    if len(points) < minimum or not all(math.isfinite(value) for point in points for value in point):
        raise ValueError(f"{label} coordinates must be finite and contain {minimum} points")


def _rectangle(min_x: float, min_y: float, max_x: float, max_y: float) -> tuple[Point, ...]:
    return ((round(min_x, 6), round(min_y, 6)), (round(max_x, 6), round(min_y, 6)), (round(max_x, 6), round(max_y, 6)), (round(min_x, 6), round(max_y, 6)))


def _local_rectangle(
    local,
    min_u: float,
    min_d: float,
    max_u: float,
    max_d: float,
) -> tuple[Point, ...]:
    return tuple(
        local(u, d)
        for u, d in (
            (min_u, min_d),
            (max_u, min_d),
            (max_u, max_d),
            (min_u, max_d),
        )
    )


def _ordered_segment(segment: Segment) -> Segment:
    start, end = segment
    return (start, end) if start <= end else (end, start)


def _grid_values(start: float, end: float) -> list[float]:
    values = [start]
    cursor = start + 6.0
    while cursor < end - _EPSILON:
        values.append(round(cursor, 6))
        cursor += 6.0
    if end - values[-1] > _EPSILON:
        values.append(end)
    return values


def _segment_between(start: Point, end: Point, start_ratio: float, end_ratio: float) -> tuple[Point, Point]:
    return tuple(
        (round(start[0] + (end[0] - start[0]) * ratio, 6), round(start[1] + (end[1] - start[1]) * ratio, 6))
        for ratio in (start_ratio, end_ratio)
    )  # type: ignore[return-value]


def _midpoint(start: Point, end: Point) -> Point:
    x = (
        start[0]
        if abs(start[0] - end[0]) <= _EPSILON
        else round((start[0] + end[0]) / 2, 6)
    )
    y = (
        start[1]
        if abs(start[1] - end[1]) <= _EPSILON
        else round((start[1] + end[1]) / 2, 6)
    )
    return (x, y)


def _centered_segment(segment: Segment, length: float) -> tuple[Point, Point]:
    start, end = _ordered_segment(segment)
    total = math.dist(start, end)
    if length > total + _EPSILON:
        raise ValueError("line content cannot fit its host boundary")
    first, second = _segment_between(
        start,
        end,
        (total - length) / (2 * total),
        (total + length) / (2 * total),
    )
    if abs(first[1] - second[1]) <= _EPSILON:
        second = (round(first[0] + length, 6), first[1])
    else:
        second = (first[0], round(first[1] + length, 6))
    return first, second


def _orthogonal_route_in_polygon(
    start: Point,
    end: Point,
    polygon: tuple[Point, ...],
) -> tuple[Point, ...]:
    candidates = (
        (start, (start[0], end[1]), end),
        (start, (end[0], start[1]), end),
    )
    for candidate in candidates:
        points = tuple(
            point
            for index, point in enumerate(candidate)
            if index == 0 or math.dist(candidate[index - 1], point) > _EPSILON
        )
        if all(
            _axis_segment_in_polygon(segment_start, segment_end, polygon)
            for segment_start, segment_end in zip(points, points[1:])
        ):
            return points
    raise ValueError("core lobby cannot route a protected exit to its stair door")


def _axis_segment_in_polygon(
    start: Point,
    end: Point,
    polygon: tuple[Point, ...],
) -> bool:
    if (
        abs(start[0] - end[0]) > _EPSILON
        and abs(start[1] - end[1]) > _EPSILON
    ):
        return False
    return Polygon(polygon).buffer(_EPSILON * 2).covers(
        LineString((start, end))
    )


def _search_values(start: float, end: float) -> list[float]:
    if end < start - _EPSILON:
        return []
    count = max(1, int((end - start) / 0.2) + 1)
    return [round(min(start + index * 0.2, end), 6) for index in range(count)]


def _placement_values(
    start: float,
    end: float,
    spacing: float,
    *,
    include_end: bool = True,
) -> list[float]:
    if end < start - _EPSILON:
        return []
    coarse = []
    cursor = start
    while cursor <= end + _EPSILON:
        coarse.append(round(min(cursor, end), 6))
        cursor += spacing
    if include_end and coarse and coarse[-1] < end - _EPSILON:
        coarse.append(round(end, 6))
    return coarse


def _footprint_center(footprint: tuple[Point, ...]) -> Point:
    return (
        sum(point[0] for point in footprint) / len(footprint),
        sum(point[1] for point in footprint) / len(footprint),
    )


def _boundary_end_segment(
    segment: Segment,
    length: float,
) -> tuple[Point, Point]:
    start, end = _ordered_segment(segment)
    total = math.dist(start, end)
    if total + _EPSILON < length:
        raise ValueError("boundary segment cannot fit requested opening")
    unit = ((end[0] - start[0]) / total, (end[1] - start[1]) / total)
    return (
        start,
        (start[0] + unit[0] * length, start[1] + unit[1] * length),
    )


def _nearest_separated_exit_openings(
    *,
    core_boundary: Segment,
    remote_candidates: tuple[Segment, Segment],
    opening_width: float,
    separation_target: float,
) -> tuple[Segment, Segment]:
    start, end = _ordered_segment(core_boundary)
    preferred_center = opening_width / 2.0
    feasible: list[tuple[float, tuple[Point, Point], float]] = []
    for remote in remote_candidates:
        remote_ordered = _ordered_segment(remote)
        center = _nearest_separated_boundary_center(
            boundary=(start, end),
            preferred_center=preferred_center,
            remote_segment=remote_ordered,
            opening_width=opening_width,
            separation_target=separation_target,
        )
        if center is None:
            continue
        feasible.append(
            (
                abs(center - preferred_center),
                remote_ordered,
                center,
            )
        )
    if feasible:
        _, remote, center = min(feasible)
        return (
            _boundary_segment_at_center(
                (start, end),
                opening_width,
                center,
            ),
            remote,
        )

    preferred = _boundary_end_segment(
        (start, end),
        opening_width,
    )
    preferred_midpoint = _midpoint(*preferred)
    remote = max(
        remote_candidates,
        key=lambda segment: (
            math.dist(preferred_midpoint, _midpoint(*segment)),
            _ordered_segment(segment),
        ),
    )
    return preferred, _ordered_segment(remote)


def _nearest_separated_boundary_center(
    *,
    boundary: Segment,
    preferred_center: float,
    remote_segment: Segment,
    opening_width: float,
    separation_target: float,
) -> float | None:
    start, end = _ordered_segment(boundary)
    total = math.dist(start, end)
    minimum = opening_width / 2.0
    maximum = total - opening_width / 2.0
    if maximum < minimum - _EPSILON:
        return None
    preferred = min(max(preferred_center, minimum), maximum)

    def separation(center: float) -> float:
        opening = _boundary_segment_at_center(
            (start, end),
            opening_width,
            center,
        )
        return segment_to_segment_distance(opening, remote_segment)

    if separation(preferred) >= separation_target:
        return preferred

    # Distance between a translated segment and a fixed segment is convex in
    # translation. Its below-threshold centers therefore form one interval:
    # any feasible endpoint brackets the nearest exact threshold crossing.
    candidates: list[float] = []
    for endpoint in (minimum, maximum):
        if endpoint == preferred or separation(endpoint) < separation_target:
            continue
        infeasible = preferred
        feasible = endpoint
        while True:
            midpoint = (infeasible + feasible) / 2.0
            if midpoint == infeasible or midpoint == feasible:
                break
            if separation(midpoint) >= separation_target:
                feasible = midpoint
            else:
                infeasible = midpoint
        if separation(feasible) >= separation_target:
            candidates.append(feasible)
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda center: (abs(center - preferred), center),
    )


def _boundary_segment_at_center(
    boundary: Segment,
    length: float,
    center: float,
) -> Segment:
    start, end = _ordered_segment(boundary)
    total = math.dist(start, end)
    unit = (
        (end[0] - start[0]) / total,
        (end[1] - start[1]) / total,
    )
    half = length / 2.0
    return (
        (
            start[0] + unit[0] * (center - half),
            start[1] + unit[1] * (center - half),
        ),
        (
            start[0] + unit[0] * (center + half),
            start[1] + unit[1] * (center + half),
        ),
    )


def _maximum_pairwise_distance(points: list[Point]) -> float:
    return max(
        math.dist(first, second)
        for index, first in enumerate(points)
        for second in points[index + 1 :]
    )


def _rectangle_intersects_segment(rectangle: tuple[Point, ...], start: Point, end: Point) -> bool:
    min_x, min_y, max_x, max_y = _bounds(rectangle)
    if start[0] == end[0]:
        return min_x - _EPSILON <= start[0] <= max_x + _EPSILON and max(min_y, min(start[1], end[1])) <= min(max_y, max(start[1], end[1])) + _EPSILON
    if start[1] == end[1]:
        return min_y - _EPSILON <= start[1] <= max_y + _EPSILON and max(min_x, min(start[0], end[0])) <= min(max_x, max(start[0], end[0])) + _EPSILON
    return False


def _rectangle_near_segment(
    rectangle: tuple[Point, ...],
    segment: Segment,
    *,
    clearance: float,
) -> bool:
    min_x, min_y, max_x, max_y = _bounds(rectangle)
    start, end = segment
    segment_min_x = min(start[0], end[0]) - clearance
    segment_max_x = max(start[0], end[0]) + clearance
    segment_min_y = min(start[1], end[1]) - clearance
    segment_max_y = max(start[1], end[1]) + clearance
    return not (
        max_x < segment_min_x - _EPSILON
        or min_x > segment_max_x + _EPSILON
        or max_y < segment_min_y - _EPSILON
        or min_y > segment_max_y + _EPSILON
    )


def _point_in_polygon_or_boundary(point: Point, polygon: list[Point]) -> bool:
    x, y = point
    inside = False
    for start, end in zip(polygon, [*polygon[1:], polygon[0]]):
        cross = (end[0] - start[0]) * (y - start[1]) - (
            end[1] - start[1]
        ) * (x - start[0])
        if (
            abs(cross) <= _EPSILON
            and min(start[0], end[0]) - _EPSILON
            <= x
            <= max(start[0], end[0]) + _EPSILON
            and min(start[1], end[1]) - _EPSILON
            <= y
            <= max(start[1], end[1]) + _EPSILON
        ):
            return True
        if (start[1] > y) != (end[1] > y):
            intersection_x = start[0] + (y - start[1]) * (
                end[0] - start[0]
            ) / (end[1] - start[1])
            if x < intersection_x:
                inside = not inside
    return inside


def _exterior_segments(room: list[Point], boundary: list[Point]) -> list[Segment]:
    boundary_edges = [*zip(boundary, [*boundary[1:], boundary[0]])]
    return [segment for segment in zip(room, [*room[1:], room[0]]) if any(_segment_within(segment, edge) for edge in boundary_edges)]


def _segment_on_polygon_boundary(segment: Segment, polygon: list[Point]) -> bool:
    return any(_segment_within(segment, edge) for edge in zip(polygon, [*polygon[1:], polygon[0]]))


def _segment_within(inner: Segment, outer: Segment) -> bool:
    (ax, ay), (bx, by) = inner
    (cx, cy), (dx, dy) = outer
    if ax == bx == cx == dx:
        return min(cy, dy) - _EPSILON <= min(ay, by) and max(ay, by) <= max(cy, dy) + _EPSILON
    if ay == by == cy == dy:
        return min(cx, dx) - _EPSILON <= min(ax, bx) and max(ax, bx) <= max(cx, dx) + _EPSILON
    return False


def _same_segment(first: Segment, second: Segment) -> bool:
    return set(first) == set(second)


def _require_rectangular_core(core: RoomPolygon) -> None:
    if len(core.polygon) != 4:
        raise ValueError("basic design core must be an axis-aligned rectangle")
    min_x, min_y, max_x, max_y = _bounds(core.polygon)
    expected = {(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)}
    if set(core.polygon) != expected:
        raise ValueError("basic design core must be an axis-aligned rectangle")


def _disjoint_storefront_window(storefront: Segment, entrance: Segment) -> tuple[Point, Point]:
    pieces = _subtract_collinear_segment(storefront, entrance)
    candidates = [
        _inset_segment(piece, 0.1)
        for piece in pieces
        if math.dist(*piece) >= 0.8
    ]
    if not candidates:
        raise ValueError("sales storefront cannot fit a window separate from the commercial entrance")
    selected = max(candidates, key=lambda segment: math.dist(*segment))
    return _centered_segment(selected, min(1.5, math.dist(*selected)))


def _inset_segment(segment: Segment, inset: float) -> Segment:
    start, end = segment
    length = math.dist(start, end)
    if length <= 2 * inset:
        raise ValueError("storefront segment cannot preserve entrance separation")
    return _segment_between(start, end, inset / length, 1 - inset / length)


def _subtract_collinear_segment(segment: Segment, removed: Segment) -> list[Segment]:
    (ax, ay), (bx, by) = segment
    (cx, cy), (dx, dy) = removed
    if ax == bx == cx == dx:
        values = sorted((ay, by))
        removed_values = sorted((cy, dy))
        return [((ax, values[0]), (ax, min(values[1], removed_values[0]))), ((ax, max(values[0], removed_values[1])), (ax, values[1]))]
    if ay == by == cy == dy:
        values = sorted((ax, bx))
        removed_values = sorted((cx, dx))
        return [((values[0], ay), (min(values[1], removed_values[0]), ay)), ((max(values[0], removed_values[1]), ay), (values[1], ay))]
    raise ValueError("sales storefront and commercial entrance must be collinear")


def _collinear_overlap_length(first: Segment, second: Segment) -> float:
    (ax, ay), (bx, by) = first
    (cx, cy), (dx, dy) = second
    if ax == bx == cx == dx:
        return max(0.0, min(max(ay, by), max(cy, dy)) - max(min(ay, by), min(cy, dy)))
    if ay == by == cy == dy:
        return max(0.0, min(max(ax, bx), max(cx, dx)) - max(min(ax, bx), min(cx, dx)))
    return 0.0
