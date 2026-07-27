from __future__ import annotations

from typing import Iterable

Point = tuple[float, float]


def polygon_area(points: Iterable[Point]) -> float:
    vertices = list(points)
    if len(vertices) < 3:
        raise ValueError("polygon needs at least 3 points")
    total = 0.0
    for index, current in enumerate(vertices):
        following = vertices[(index + 1) % len(vertices)]
        total += current[0] * following[1] - following[0] * current[1]
    return abs(total) / 2


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
