from __future__ import annotations

import math
from dataclasses import dataclass

from backend.app.schemas.layout import (
    BasicDesignFeatures,
    LayoutCandidate,
    PlanElement,
    PlanLine,
    RoomPolygon,
)
from engine.geometry.access import orthogonal_min_width, shared_boundary_segments
from engine.geometry.polygon import contains_polygon, polygon_overlap_area

Point = tuple[float, float]
Segment = tuple[Point, Point]
_EPSILON = 1e-7


@dataclass(frozen=True)
class StructureSet:
    lines: tuple[PlanLine, ...]
    columns: tuple[PlanElement, ...]


def generate_basic_design(
    layout: LayoutCandidate,
    *,
    boundary: list[Point],
    street_segments: list[Segment],
    shared_structure: StructureSet | None = None,
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

    elements = _core_elements(core)
    exits = _protected_exits(core, layout.circulation)
    lines: list[PlanLine] = list(exits)
    lines.extend(_egress_routes(layout, exits))
    if shared_structure is None:
        grid_lines, columns = _structure(boundary, (layout,), ((elements, exits),))
    else:
        grid_lines, columns = list(shared_structure.lines), list(shared_structure.columns)
    lines.extend(grid_lines)
    elements.extend(columns)
    envelope_lines = _envelope(layout, boundary, street_segments)
    lines.extend(envelope_lines)
    object_elements = _room_contents(layout, elements)
    elements.extend(object_elements)
    lines.extend(_dimensions_and_site(boundary, layout.circulation, street_segments))
    return BasicDesignFeatures(elements=tuple(elements), lines=tuple(lines))


def generate_shared_structure(
    boundary: list[Point],
    layouts: tuple[LayoutCandidate, ...],
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
        elements = _core_elements(core)
        exits = _protected_exits(core, layout.circulation)
        core_data.append((elements, exits))
    lines, columns = _structure(boundary, layouts, tuple(core_data))
    return StructureSet(lines=tuple(lines), columns=tuple(columns))


def _core_elements(core: RoomPolygon) -> list[PlanElement]:
    min_x, min_y, max_x, max_y = _bounds(core.polygon)
    width, height = max_x - min_x, max_y - min_y
    if width < 5.0 or height < 3.2:
        raise ValueError("core is too small to place two stairs, elevator, lobby, and shaft")
    lower_height = min(2.4, height * 0.58)
    stair_width = min(1.5, width * 0.24)
    elevator_width = min(1.8, width * 0.28)
    shaft_width = width - 2 * stair_width - elevator_width
    if shaft_width < 0.7 or height - lower_height < 0.7:
        raise ValueError("core cannot fit required vertical transport content")
    cells = (
        ("core-stair-1", "stair", "UP", min_x, min_y, min_x + stair_width, min_y + lower_height),
        ("core-stair-2", "stair", "UP", min_x + stair_width, min_y, min_x + 2 * stair_width, min_y + lower_height),
        ("core-elevator", "elevator", "ELEV", min_x + 2 * stair_width, min_y, min_x + 2 * stair_width + elevator_width, min_y + lower_height),
        ("core-shaft", "shaft", "SHAFT", min_x + 2 * stair_width + elevator_width, min_y, max_x, min_y + lower_height),
        ("core-lobby", "lobby", "LOBBY", min_x, min_y + lower_height, max_x, max_y),
    )
    elements = [
        PlanElement(
            element_id=element_id,
            category="vertical",
            kind=kind,
            host_id=core.room_id,
            label=label,
            footprint=_rectangle(left, bottom, right, top),
        )
        for element_id, kind, label, left, bottom, right, top in cells
    ]
    if not all(contains_polygon(core.polygon, element.footprint) for element in elements):
        raise ValueError("core subdivision must remain contained in the actual core")
    if any(
        polygon_overlap_area(left.footprint, right.footprint) > _EPSILON
        for index, left in enumerate(elements)
        for right in elements[index + 1 :]
    ):
        raise ValueError("core subdivision elements must not overlap")
    return elements


def _protected_exits(core: RoomPolygon, circulation: list[RoomPolygon]) -> list[PlanLine]:
    shared = [
        segment
        for path in circulation
        for segment in shared_boundary_segments(core.polygon, path.polygon)
    ]
    if not shared:
        raise ValueError("core has no shared circulation boundary for protected exits")
    start, end = max(shared, key=lambda segment: math.dist(*segment))
    length = math.dist(start, end)
    if length < 2.7 - _EPSILON:
        raise ValueError("core/circulation shared boundary cannot fit two protected exits")
    first = _segment_between(start, end, 0.15, 0.15 + 0.9 / length)
    second = _segment_between(start, end, 0.85 - 0.9 / length, 0.85)
    return [
        PlanLine(
            line_id=f"protected-exit-{index}",
            category="egress",
            kind="protected_exit",
            points=points,
            host_id=core.room_id,
            target_id=f"core-stair-{index}",
            label=f"EXIT {index}",
            clear_width=0.9,
        )
        for index, points in enumerate((first, second), start=1)
    ]


def _egress_routes(layout: LayoutCandidate, exits: list[PlanLine]) -> list[PlanLine]:
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
                    points=(start, _midpoint(*exit_line.points)),
                    host_id=room.room_id,
                    target_id=exit_line.line_id,
                    label="EGRESS",
                )
            )
    return routes


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
        raise ValueError("no interior structural columns can be placed without collisions")
    return lines, columns


def _envelope(layout: LayoutCandidate, boundary: list[Point], streets: list[Segment]) -> list[PlanLine]:
    lines: list[PlanLine] = []
    street = streets[0] if streets else None
    commercial_sales = next((room for room in layout.rooms if room.space_type == "sales"), None)
    if commercial_sales is not None:
        if street is None:
            raise ValueError("commercial design requires a supplied street edge")
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
        lines.append(
            PlanLine(
                line_id="commercial-entrance",
                category="envelope",
                kind="entrance",
                points=entrance,
                host_id=commercial_sales.room_id,
                label="ENTRANCE",
                clear_width=1.8,
            )
        )
    for room in layout.rooms:
        if room.space_type == "core":
            continue
        candidates = _exterior_segments(room.polygon, boundary)
        if not candidates:
            continue
        storefront_window: tuple[Point, Point] | None = None
        if room is commercial_sales and street is not None:
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
        if room is commercial_sales and _collinear_overlap_length(window, entrance) > _EPSILON:
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


def _room_contents(layout: LayoutCandidate, fixed_elements: list[PlanElement]) -> list[PlanElement]:
    required = {
        "open_work": (("workstation", "furniture"), ("workstation", "furniture")),
        "meeting": (("meeting_table", "furniture"),),
        "reception": (("reception_desk", "furniture"),),
        "focus": (("focus_desk", "furniture"),),
        "pantry": (("pantry_counter", "fixture"), ("sink", "fixture")),
        "restroom": (("wc", "fixture"), ("lavatory", "fixture")),
        "it_storage": (("it_rack", "fixture"), ("it_rack", "fixture")),
        "sales": (("sales_shelf", "furniture"), ("sales_shelf", "furniture")),
        "checkout": (("checkout_counter", "furniture"),),
        "stock": (("stock_rack", "furniture"), ("stock_rack", "furniture")),
        "staff": (("staff_table", "furniture"),),
        "utility": (("utility_equipment", "fixture"),),
    }
    placed: list[PlanElement] = []
    for room in layout.rooms:
        for kind, category in required.get(room.space_type, ()):
            footprint = _place_object(room, kind, [*fixed_elements, *placed])
            placed.append(
                PlanElement(
                    element_id=f"{room.room_id}-{kind}-{sum(item.kind == kind for item in placed) + 1}",
                    category=category,
                    kind=kind,
                    host_id=room.room_id,
                    label=kind.upper(),
                    footprint=footprint,
                )
            )
    return placed


def _place_object(room: RoomPolygon, kind: str, occupied: list[PlanElement]) -> tuple[Point, ...]:
    min_x, min_y, max_x, max_y = _bounds(room.polygon)
    width, height = max_x - min_x, max_y - min_y
    object_width = min(1.2, max(0.45, width * 0.18))
    object_height = min(0.7, max(0.35, height * 0.16))
    if object_width + 0.4 > width or object_height + 0.4 > height:
        raise ValueError(f"room '{room.room_id}' cannot fit required {kind}")
    for y in _search_values(min_y + 0.2, max_y - object_height - 0.2):
        for x in _search_values(min_x + 0.2, max_x - object_width - 0.2):
            footprint = _rectangle(x, y, x + object_width, y + object_height)
            if not contains_polygon(room.polygon, footprint):
                continue
            if any(polygon_overlap_area(footprint, item.footprint) > _EPSILON for item in occupied):
                continue
            return footprint
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
    return (round((start[0] + end[0]) / 2, 6), round((start[1] + end[1]) / 2, 6))


def _centered_segment(segment: Segment, length: float) -> tuple[Point, Point]:
    start, end = segment
    total = math.dist(start, end)
    if length > total + _EPSILON:
        raise ValueError("line content cannot fit its host boundary")
    return _segment_between(start, end, (total - length) / (2 * total), (total + length) / (2 * total))


def _search_values(start: float, end: float) -> list[float]:
    if end < start - _EPSILON:
        return []
    count = max(1, int((end - start) / 0.2) + 1)
    return [round(min(start + index * 0.2, end), 6) for index in range(count)]


def _rectangle_intersects_segment(rectangle: tuple[Point, ...], start: Point, end: Point) -> bool:
    min_x, min_y, max_x, max_y = _bounds(rectangle)
    if start[0] == end[0]:
        return min_x - _EPSILON <= start[0] <= max_x + _EPSILON and max(min_y, min(start[1], end[1])) <= min(max_y, max(start[1], end[1])) + _EPSILON
    if start[1] == end[1]:
        return min_y - _EPSILON <= start[1] <= max_y + _EPSILON and max(min_x, min(start[0], end[0])) <= min(max_x, max(start[0], end[0])) + _EPSILON
    return False


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
