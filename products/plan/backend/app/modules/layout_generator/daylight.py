from __future__ import annotations

from collections.abc import Iterable

from shapely.geometry import LineString, Polygon
from shapely.ops import linemerge, unary_union

from backend.app.schemas.layout import LayoutCandidate

Point = tuple[float, float]
MINIMUM_USABLE_DAYLIGHT_WINDOW_FRONTAGE_M = 1.2
MINIMUM_USABLE_DAYLIGHT_INWARD_DEPTH_M = 2.4
_TOLERANCE = 1e-8


def room_has_usable_daylight_frontage(
    layout: LayoutCandidate,
    *,
    boundary: Iterable[Point],
    room_id: str,
) -> bool:
    room = next((item for item in layout.rooms if item.room_id == room_id), None)
    features = layout.basic_design
    if room is None or features is None:
        return False
    room_shape = Polygon(room.polygon)
    boundary_shape = Polygon(tuple(boundary))
    if (
        not room_shape.is_valid
        or room_shape.is_empty
        or not boundary_shape.is_valid
        or boundary_shape.is_empty
    ):
        return False
    for line in features.lines:
        if (
            line.kind != "window"
            or line.host_id != room_id
            or len(line.points) != 2
        ):
            continue
        window = LineString(line.points)
        if (
            window.length + _TOLERANCE
            < MINIMUM_USABLE_DAYLIGHT_WINDOW_FRONTAGE_M
            or not room_shape.boundary.buffer(_TOLERANCE).covers(window)
            or not boundary_shape.boundary.buffer(_TOLERANCE).covers(window)
        ):
            continue
        if any(
            room_shape.buffer(_TOLERANCE).covers(zone)
            for zone in daylight_frontage_zones(window)
        ):
            return True
    return False


def require_usable_daylight_frontage(
    layout: LayoutCandidate,
    *,
    boundary: Iterable[Point],
    room_ids: tuple[str, ...],
) -> None:
    if room_ids != tuple(sorted(set(room_ids))):
        raise ValueError("requested daylight room ids must be sorted and unique")
    boundary_points = tuple(boundary)
    failed = tuple(
        room_id
        for room_id in room_ids
        if not room_has_usable_daylight_frontage(
            layout,
            boundary=boundary_points,
            room_id=room_id,
        )
    )
    if failed:
        raise ValueError(
            "requested room "
            + ", ".join(failed)
            + " lacks usable daylight frontage"
        )


def daylight_frontage_zones(window: LineString) -> tuple[Polygon, Polygon]:
    (start_x, start_y), (end_x, end_y) = window.coords
    length = window.length
    unit_x = (end_x - start_x) / length
    unit_y = (end_y - start_y) / length
    center_x = (start_x + end_x) / 2.0
    center_y = (start_y + end_y) / 2.0
    half_frontage = MINIMUM_USABLE_DAYLIGHT_WINDOW_FRONTAGE_M / 2.0
    front_start = (
        center_x - unit_x * half_frontage,
        center_y - unit_y * half_frontage,
    )
    front_end = (
        center_x + unit_x * half_frontage,
        center_y + unit_y * half_frontage,
    )
    normal = (
        -unit_y * MINIMUM_USABLE_DAYLIGHT_INWARD_DEPTH_M,
        unit_x * MINIMUM_USABLE_DAYLIGHT_INWARD_DEPTH_M,
    )
    return tuple(
        Polygon(
            (
                front_start,
                front_end,
                (
                    front_end[0] + normal[0] * direction,
                    front_end[1] + normal[1] * direction,
                ),
                (
                    front_start[0] + normal[0] * direction,
                    front_start[1] + normal[1] * direction,
                ),
            )
        )
        for direction in (-1.0, 1.0)
    )


def polygon_has_usable_daylight_frontage(
    room_shape: Polygon,
    *,
    exterior_segments: tuple[tuple[Point, Point], ...],
) -> bool:
    exterior_lines = tuple(
        line
        for start, end in exterior_segments
        if (
            line := LineString(
                tuple(
                    sorted(
                        (
                            (float(start[0]), float(start[1])),
                            (float(end[0]), float(end[1])),
                        )
                    )
                )
            )
        )
        .length
        > _TOLERANCE
    )
    if not exterior_lines:
        return False
    exterior_linework = _merged_line_strings(unary_union(exterior_lines))
    normalized_exterior = unary_union(exterior_linework)
    room_edges = tuple(
        sorted(
            (
                LineString((geometry.coords[0], geometry.coords[-1]))
                for start, end in zip(
                    room_shape.exterior.coords,
                    room_shape.exterior.coords[1:],
                )
                for geometry in _merged_line_strings(
                    LineString((start, end)).intersection(
                        normalized_exterior
                    )
                )
                if geometry.length > _TOLERANCE
            ),
            key=lambda edge: tuple(
                sorted(
                    (
                        tuple(map(float, edge.coords[0])),
                        tuple(map(float, edge.coords[-1])),
                    )
                )
            ),
        )
    )
    return any(
        edge.length + _TOLERANCE
        >= MINIMUM_USABLE_DAYLIGHT_WINDOW_FRONTAGE_M
        and any(
            room_shape.buffer(_TOLERANCE).covers(zone)
            for zone in daylight_frontage_zones(edge)
        )
        for edge in room_edges
    )


def _line_strings(geometry) -> tuple[LineString, ...]:
    if geometry.is_empty:
        return ()
    if geometry.geom_type == "LineString":
        return (geometry,)
    if geometry.geom_type in {"MultiLineString", "GeometryCollection"}:
        return tuple(
            line
            for item in geometry.geoms
            for line in _line_strings(item)
        )
    return ()


def _merged_line_strings(geometry) -> tuple[LineString, ...]:
    lines = _line_strings(geometry)
    if not lines:
        return ()
    if len(lines) == 1:
        return lines
    return _line_strings(linemerge(unary_union(lines)))
