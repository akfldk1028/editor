from __future__ import annotations

import math
from typing import Iterable

from shapely import union_all
from shapely.geometry import LineString, LinearRing, Polygon

Point = tuple[float, float]
Segment = tuple[Point, Point]

# Geometry crosses several module boundaries before anything compares two
# walls for contact, and those comparisons are exact. Every module that emits
# plan geometry rounds its vertices to this many decimals so a wall built
# flush against another stays flush, at ten nanometres — far below any
# dimension this product reasons about.
GEOMETRY_DECIMALS = 8


def snap_coordinate(value: float) -> float:
    """Put one coordinate on the shared plan grid."""
    snapped = round(float(value), GEOMETRY_DECIMALS)
    return 0.0 if snapped == 0 else snapped


def snap_ring(points: Iterable[Point]) -> tuple[Point, ...]:
    """Put every vertex of a ring on the shared plan grid."""
    return tuple((snap_coordinate(x), snap_coordinate(y)) for x, y in points)


def validate_polygon(points: Iterable[Point], *, label: str = "polygon") -> None:
    _as_polygon(points, label=label)


def contains_polygon(container: Iterable[Point], candidate: Iterable[Point]) -> bool:
    container_polygon = _as_polygon(container, label="container")
    candidate_polygon = _as_polygon(candidate, label="candidate")
    return bool(container_polygon.covers(candidate_polygon))


def polygon_overlap_area(a: Iterable[Point], b: Iterable[Point]) -> float:
    left = _as_polygon(a, label="first polygon")
    right = _as_polygon(b, label="second polygon")
    return float(left.intersection(right).area)


def shared_boundary_length(a: Iterable[Point], b: Iterable[Point]) -> float:
    left = _as_polygon(a, label="first polygon")
    right = _as_polygon(b, label="second polygon")
    return float(left.boundary.intersection(right.boundary).length)


def union_area(polygons: Iterable[Iterable[Point]]) -> float:
    shapes = [_as_polygon(points, label=f"polygon {index}") for index, points in enumerate(polygons)]
    if not shapes:
        return 0.0
    return float(union_all(shapes).area)


def union_polygon(
    polygons: Iterable[Iterable[Point]],
) -> tuple[Point, ...]:
    shapes = [
        _as_polygon(points, label=f"polygon {index}")
        for index, points in enumerate(polygons)
    ]
    if not shapes:
        raise ValueError("polygon union requires at least one polygon")
    merged = union_all(shapes)
    if not isinstance(merged, Polygon) or merged.is_empty:
        raise ValueError("polygon union must produce one connected polygon")
    if merged.interiors:
        raise ValueError("polygon union with holes is unsupported")
    points = tuple(
        (float(x), float(y))
        for x, y in tuple(merged.exterior.coords)[:-1]
    )
    _as_polygon(points, label="polygon union")
    return points


def union_intersection_area(
    container: Iterable[Point],
    polygons: Iterable[Iterable[Point]],
) -> float:
    container_polygon = _as_polygon(container, label="container")
    shapes = [_as_polygon(points, label=f"polygon {index}") for index, points in enumerate(polygons)]
    if not shapes:
        return 0.0
    return float(union_all(shapes).intersection(container_polygon).area)


def validate_boundary_segments(
    boundary: Iterable[Point],
    segments: Iterable[Segment],
    *,
    label: str = "boundary segments",
) -> None:
    boundary_polygon = _as_polygon(boundary, label="boundary")
    for index, line in enumerate(_as_lines(segments, label=label)):
        if not boundary_polygon.boundary.covers(line):
            raise ValueError(f"{label} segment {index} must lie on the boundary")


def shared_boundary_with_segments_length(
    polygon: Iterable[Point],
    segments: Iterable[Segment],
) -> float:
    shape = _as_polygon(polygon)
    lines = _as_lines(segments, label="segments")
    if not lines:
        return 0.0
    length = shape.boundary.intersection(union_all(lines)).length
    if not math.isfinite(length):
        raise ValueError("shared boundary length must be finite")
    return float(length)


def polygon_area(points: Iterable[Point]) -> float:
    return float(_as_polygon(points).area)


def bounds(points: Iterable[Point]) -> tuple[float, float, float, float]:
    vertices = list(points)
    if not vertices:
        raise ValueError("polygon needs at least 1 point")
    xs = [point[0] for point in vertices]
    ys = [point[1] for point in vertices]
    return min(xs), min(ys), max(xs), max(ys)


def bbox_area(box: tuple[float, float, float, float]) -> float:
    min_x, min_y, max_x, max_y = box
    return max(0.0, max_x - min_x) * max(0.0, max_y - min_y)


def contains_bbox(boundary: Iterable[Point], polygon: Iterable[Point]) -> bool:
    b_min_x, b_min_y, b_max_x, b_max_y = bounds(boundary)
    p_min_x, p_min_y, p_max_x, p_max_y = bounds(polygon)
    return b_min_x <= p_min_x and p_max_x <= b_max_x and b_min_y <= p_min_y and p_max_y <= b_max_y


def bboxes_overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _as_polygon(points: Iterable[Point], *, label: str = "polygon") -> Polygon:
    try:
        vertices = [(float(x), float(y)) for x, y in points]
    except (TypeError, ValueError):
        raise ValueError(f"{label} points must be coordinate pairs") from None

    if len(vertices) >= 2 and vertices[0] == vertices[-1]:
        vertices.pop()
    if len(vertices) < 3 or len(set(vertices)) < 3:
        raise ValueError(f"{label} needs at least 3 distinct points")
    if not all(math.isfinite(coordinate) for point in vertices for coordinate in point):
        raise ValueError(f"{label} coordinates must be finite")
    if not _derived_metrics_are_finite(vertices):
        raise ValueError(f"{label} must have finite area and perimeter")

    ring = LinearRing(vertices)
    polygon = Polygon(ring)
    if not ring.is_simple:
        if _has_non_collinear_vertices(vertices):
            raise ValueError(f"{label} is self-intersecting")
        raise ValueError(f"{label} must have positive area")
    if polygon.area <= 0:
        raise ValueError(f"{label} must have positive area")
    if not math.isfinite(polygon.area) or not math.isfinite(polygon.length):
        raise ValueError(f"{label} must have finite area and perimeter")
    if not polygon.is_valid:
        raise ValueError(f"{label} is invalid")
    return polygon


def _has_non_collinear_vertices(vertices: list[Point]) -> bool:
    origin = vertices[0]
    for index in range(1, len(vertices) - 1):
        first = vertices[index]
        for second in vertices[index + 1 :]:
            cross_product = (
                (first[0] - origin[0]) * (second[1] - origin[1])
                - (first[1] - origin[1]) * (second[0] - origin[0])
            )
            if cross_product != 0:
                return True
    return False


def _derived_metrics_are_finite(vertices: list[Point]) -> bool:
    twice_area = 0.0
    perimeter = 0.0
    for index, current in enumerate(vertices):
        following = vertices[(index + 1) % len(vertices)]
        cross_product = current[0] * following[1] - following[0] * current[1]
        edge_length = math.hypot(
            following[0] - current[0],
            following[1] - current[1],
        )
        if not math.isfinite(cross_product) or not math.isfinite(edge_length):
            return False
        twice_area += cross_product
        perimeter += edge_length
        if not math.isfinite(twice_area) or not math.isfinite(perimeter):
            return False
    return True


def _as_lines(segments: Iterable[Segment], *, label: str) -> list[LineString]:
    lines: list[LineString] = []
    try:
        raw_segments = list(segments)
    except TypeError:
        raise ValueError(f"{label} must be an iterable of point pairs") from None
    for index, segment in enumerate(raw_segments):
        try:
            start, end = segment
            start_point = (float(start[0]), float(start[1]))
            end_point = (float(end[0]), float(end[1]))
        except (TypeError, ValueError, IndexError):
            raise ValueError(f"{label} segment {index} must contain two coordinate pairs") from None
        if not all(math.isfinite(value) for point in (start_point, end_point) for value in point):
            raise ValueError(f"{label} segment {index} coordinates must be finite")
        if start_point == end_point:
            raise ValueError(f"{label} segment {index} must have positive length")
        line = LineString([start_point, end_point])
        if not math.isfinite(line.length):
            raise ValueError(f"{label} segment {index} length must be finite")
        lines.append(line)
    return lines
