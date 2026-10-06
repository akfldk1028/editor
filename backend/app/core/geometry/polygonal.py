from __future__ import annotations

import math
from collections.abc import Iterable

from shapely import union_all
from shapely.geometry import MultiPolygon, Polygon, box
from shapely.prepared import prep

Point = tuple[float, float]
Rectangle = tuple[Point, Point, Point, Point]
_TOLERANCE = 1e-8


def common_polygon_region(
    floor_polygons: Iterable[Iterable[Point]],
) -> tuple[Point, ...]:
    polygons = [
        _simple_polygon(points, label=f"floor footprint {index}")
        for index, points in enumerate(floor_polygons, start=1)
    ]
    if not polygons:
        raise ValueError("at least one floor footprint is required")
    common = polygons[0]
    for polygon in polygons[1:]:
        common = common.intersection(polygon)
    if (
        common.is_empty
        or isinstance(common, MultiPolygon)
        or not isinstance(common, Polygon)
        or common.area <= _TOLERANCE
        or common.interiors
    ):
        raise ValueError(
            "common floor region must be one connected polygon without holes"
        )
    return _canonical_polygon(common)


def fixed_rectangle_candidates(
    floor_polygons: Iterable[Iterable[Point]],
    *,
    width: float,
    depth: float,
    grid_step: float = 0.25,
) -> tuple[Rectangle, ...]:
    if not all(
        math.isfinite(float(value)) and float(value) > 0
        for value in (width, depth, grid_step)
    ):
        raise ValueError("rectangle dimensions and grid step must be positive")
    common = Polygon(common_polygon_region(floor_polygons))
    prepared = prep(common)
    min_x, min_y, max_x, max_y = common.bounds
    candidates: set[Rectangle] = set()
    for candidate_width, candidate_depth in {
        (float(width), float(depth)),
        (float(depth), float(width)),
    }:
        x_origins = _sample_values(
            min_x,
            max_x - candidate_width,
            grid_step,
            (
                coordinate
                for x, _ in common.exterior.coords[:-1]
                for coordinate in (x, x - candidate_width)
            ),
        )
        y_origins = _sample_values(
            min_y,
            max_y - candidate_depth,
            grid_step,
            (
                coordinate
                for _, y in common.exterior.coords[:-1]
                for coordinate in (y, y - candidate_depth)
            ),
        )
        for x0 in x_origins:
            for y0 in y_origins:
                candidate_shape = box(
                    x0,
                    y0,
                    x0 + candidate_width,
                    y0 + candidate_depth,
                )
                if prepared.covers(candidate_shape):
                    candidates.add(
                        _rectangle(
                            x0,
                            y0,
                            x0 + candidate_width,
                            y0 + candidate_depth,
                        )
                    )
    return tuple(sorted(candidates, key=_rectangle_bounds))


def largest_inscribed_axis_aligned_rectangle(
    boundary: Iterable[Point],
    *,
    required_polygons: Iterable[Iterable[Point]] = (),
    grid_step: float = 0.5,
) -> Rectangle:
    if not math.isfinite(grid_step) or grid_step <= 0:
        raise ValueError("grid step must be finite and positive")
    polygon = _simple_polygon(boundary, label="floor footprint")
    required = [
        _simple_polygon(points, label="required polygon")
        for points in required_polygons
    ]
    if any(not polygon.covers(item) for item in required):
        raise ValueError("required polygons must be inside the floor footprint")
    required_shape = (
        required[0]
        if len(required) == 1
        else None if not required else union_all(required)
    )
    required_bounds = required_shape.bounds if required_shape is not None else None
    min_x, min_y, max_x, max_y = polygon.bounds
    xs = _grid_coordinates(
        min_x,
        max_x,
        grid_step,
        (
            *(x for x, _ in polygon.exterior.coords[:-1]),
            *(
                value
                for item in required
                for value in (item.bounds[0], item.bounds[2])
            ),
        ),
    )
    ys = _grid_coordinates(
        min_y,
        max_y,
        grid_step,
        (
            *(y for _, y in polygon.exterior.coords[:-1]),
            *(
                value
                for item in required
                for value in (item.bounds[1], item.bounds[3])
            ),
        ),
    )
    covered = [
        [
            polygon.covers(box(xs[column], ys[row], xs[column + 1], ys[row + 1]))
            for column in range(len(xs) - 1)
        ]
        for row in range(len(ys) - 1)
    ]
    best = None
    best_area = -1.0
    for bottom in range(len(covered)):
        available = [True] * (len(xs) - 1)
        for top in range(bottom, len(covered)):
            available = [
                current and cell
                for current, cell in zip(available, covered[top])
            ]
            for start, end in _true_runs(available):
                candidate = _rectangle(
                    xs[start],
                    ys[bottom],
                    xs[end],
                    ys[top + 1],
                )
                candidate_shape = Polygon(candidate)
                if (
                    required_bounds is not None
                    and not candidate_shape.covers(required_shape)
                ):
                    continue
                area = candidate_shape.area
                if area > best_area + _TOLERANCE or (
                    math.isclose(area, best_area, abs_tol=_TOLERANCE)
                    and (
                        best is None
                        or _rectangle_bounds(candidate)
                        < _rectangle_bounds(best)
                    )
                ):
                    best = candidate
                    best_area = area
    if best is None:
        raise ValueError(
            "floor footprint cannot fit one axis-aligned planning rectangle"
        )
    return best


def _simple_polygon(
    points: Iterable[Point],
    *,
    label: str,
) -> Polygon:
    vertices = tuple((float(x), float(y)) for x, y in points)
    if len(vertices) >= 2 and vertices[0] == vertices[-1]:
        vertices = vertices[:-1]
    if len(vertices) < 3:
        raise ValueError(f"{label} needs at least three points")
    if any(not math.isfinite(value) for point in vertices for value in point):
        raise ValueError(f"{label} coordinates must be finite")
    polygon = Polygon(vertices)
    if not polygon.is_valid or polygon.area <= _TOLERANCE:
        raise ValueError(f"{label} must be a valid positive-area polygon")
    if polygon.interiors:
        raise ValueError(f"{label} holes are unsupported")
    return polygon


def _sample_values(
    minimum: float,
    maximum: float,
    step: float,
    extra: Iterable[float],
) -> tuple[float, ...]:
    if maximum < minimum - _TOLERANCE:
        return ()
    count = max(0, math.ceil((maximum - minimum) / step))
    values = {
        minimum,
        maximum,
        *(
            minimum + index * step
            for index in range(count + 1)
            if minimum + index * step <= maximum + _TOLERANCE
        ),
        *(
            float(value)
            for value in extra
            if minimum - _TOLERANCE <= float(value) <= maximum + _TOLERANCE
        ),
    }
    return tuple(sorted(_clean(value) for value in values))


def _grid_coordinates(
    minimum: float,
    maximum: float,
    step: float,
    extra: Iterable[float],
) -> tuple[float, ...]:
    return _sample_values(minimum, maximum, step, extra)


def _true_runs(values: list[bool]) -> tuple[tuple[int, int], ...]:
    runs = []
    start = None
    for index, value in enumerate((*values, False)):
        if value and start is None:
            start = index
        elif not value and start is not None:
            runs.append((start, index))
            start = None
    return tuple(runs)


def _canonical_polygon(polygon: Polygon) -> tuple[Point, ...]:
    points = tuple(
        (_clean(x), _clean(y))
        for x, y in polygon.exterior.coords[:-1]
    )
    start = min(range(len(points)), key=lambda index: points[index])
    forward = points[start:] + points[:start]
    reversed_points = tuple(reversed(points))
    reverse_start = min(
        range(len(reversed_points)),
        key=lambda index: reversed_points[index],
    )
    backward = (
        reversed_points[reverse_start:]
        + reversed_points[:reverse_start]
    )
    return min(forward, backward)


def _rectangle(
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
) -> Rectangle:
    return (
        (_clean(min_x), _clean(min_y)),
        (_clean(max_x), _clean(min_y)),
        (_clean(max_x), _clean(max_y)),
        (_clean(min_x), _clean(max_y)),
    )


def _rectangle_bounds(
    rectangle: Rectangle,
) -> tuple[float, float, float, float]:
    return (
        rectangle[0][0],
        rectangle[0][1],
        rectangle[2][0],
        rectangle[2][1],
    )


def _clean(value: float) -> float:
    cleaned = round(float(value), 9)
    return 0.0 if cleaned == 0 else cleaned
