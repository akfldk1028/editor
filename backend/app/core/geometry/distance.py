from __future__ import annotations

import math

Point = tuple[float, float]
Segment = tuple[Point, Point]
_EPSILON = 1e-9


def segment_to_segment_distance(left: Segment, right: Segment) -> float:
    if _line_segments_intersect(left, right):
        return 0.0
    return min(
        _point_to_segment_distance(point, segment)
        for point, segment in (
            (left[0], right),
            (left[1], right),
            (right[0], left),
            (right[1], left),
        )
    )


def _point_to_segment_distance(point: Point, segment: Segment) -> float:
    start, end = segment
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if length_squared <= _EPSILON:
        return math.dist(point, start)
    projection = (
        (point[0] - start[0]) * dx + (point[1] - start[1]) * dy
    ) / length_squared
    clamped = min(1.0, max(0.0, projection))
    closest = (start[0] + clamped * dx, start[1] + clamped * dy)
    return math.dist(point, closest)


def _line_segments_intersect(left: Segment, right: Segment) -> bool:
    def orientation(a: Point, b: Point, c: Point) -> float:
        return (
            (b[0] - a[0]) * (c[1] - a[1])
            - (b[1] - a[1]) * (c[0] - a[0])
        )

    def on_segment(a: Point, b: Point, point: Point) -> bool:
        return (
            min(a[0], b[0]) - _EPSILON
            <= point[0]
            <= max(a[0], b[0]) + _EPSILON
            and min(a[1], b[1]) - _EPSILON
            <= point[1]
            <= max(a[1], b[1]) + _EPSILON
        )

    first = orientation(left[0], left[1], right[0])
    second = orientation(left[0], left[1], right[1])
    third = orientation(right[0], right[1], left[0])
    fourth = orientation(right[0], right[1], left[1])
    if first * second < -_EPSILON and third * fourth < -_EPSILON:
        return True
    return (
        abs(first) <= _EPSILON and on_segment(left[0], left[1], right[0])
        or abs(second) <= _EPSILON
        and on_segment(left[0], left[1], right[1])
        or abs(third) <= _EPSILON
        and on_segment(right[0], right[1], left[0])
        or abs(fourth) <= _EPSILON
        and on_segment(right[0], right[1], left[1])
    )
