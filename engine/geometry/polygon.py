from __future__ import annotations

import math
from typing import Iterable

from shapely import union_all
from shapely.geometry import LinearRing, Polygon

Point = tuple[float, float]


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

    ring = LinearRing(vertices)
    polygon = Polygon(ring)
    if not ring.is_simple:
        if _has_non_collinear_vertices(vertices):
            raise ValueError(f"{label} is self-intersecting")
        raise ValueError(f"{label} must have positive area")
    if polygon.area <= 0:
        raise ValueError(f"{label} must have positive area")
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
