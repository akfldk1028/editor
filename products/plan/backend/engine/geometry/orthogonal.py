from __future__ import annotations

import math
from typing import Iterable

from shapely.geometry import Polygon, box
from shapely.ops import unary_union

Point = tuple[float, float]
Rectangle = tuple[Point, Point, Point, Point]
_TOLERANCE = 1e-9


def orthogonal_rectangle_cells(
    points: Iterable[Point],
) -> tuple[Rectangle, ...]:
    polygon = _orthogonal_polygon(points, label="floor footprint")
    xs = sorted({float(x) for x, _ in polygon.exterior.coords[:-1]})
    ys = sorted({float(y) for _, y in polygon.exterior.coords[:-1]})
    cells: list[Rectangle] = []
    for x0, x1 in zip(xs, xs[1:]):
        for y0, y1 in zip(ys, ys[1:]):
            if x1 - x0 <= _TOLERANCE or y1 - y0 <= _TOLERANCE:
                continue
            candidate = box(x0, y0, x1, y1)
            if polygon.covers(candidate):
                cells.append(_rectangle(x0, y0, x1, y1))
    if not cells:
        raise ValueError("floor footprint has no rectangular cells")
    merged = unary_union([Polygon(cell) for cell in cells])
    if not merged.equals(polygon):
        raise ValueError(
            "orthogonal decomposition does not exactly cover floor footprint"
        )
    return tuple(
        sorted(cells, key=lambda cell: _rectangle_bounds(cell))
    )


def common_floor_region(
    floor_polygons: Iterable[Iterable[Point]],
) -> tuple[Point, ...]:
    polygons = [
        _orthogonal_polygon(points, label=f"floor footprint {index}")
        for index, points in enumerate(floor_polygons, start=1)
    ]
    if not polygons:
        raise ValueError("common floor region requires at least one floor")
    common = polygons[0]
    for polygon in polygons[1:]:
        common = common.intersection(polygon)
    if (
        common.is_empty
        or not isinstance(common, Polygon)
        or common.interiors
    ):
        raise ValueError(
            "common floor region must be one connected polygon without holes"
        )
    points = _canonical_polygon(common)
    _orthogonal_polygon(points, label="common floor region")
    return points


def shared_core_candidates(
    floor_polygons: Iterable[Iterable[Point]],
    *,
    width: float,
    depth: float,
) -> tuple[Rectangle, ...]:
    if not all(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) > 0
        for value in (width, depth)
    ):
        raise ValueError("core width and depth must be finite and positive")
    common_points = common_floor_region(floor_polygons)
    common = Polygon(common_points)
    cells = orthogonal_rectangle_cells(common_points)
    candidates: set[Rectangle] = set()
    for candidate_width, candidate_depth in {
        (float(width), float(depth)),
        (float(depth), float(width)),
    }:
        x_origins = _candidate_origins(
            [bound for cell in cells for bound in _rectangle_bounds(cell)[::2]],
            candidate_width,
        )
        y_origins = _candidate_origins(
            [
                bound
                for cell in cells
                for bound in (
                    _rectangle_bounds(cell)[1],
                    _rectangle_bounds(cell)[3],
                )
            ],
            candidate_depth,
        )
        for x0 in x_origins:
            for y0 in y_origins:
                candidate_shape = box(
                    x0,
                    y0,
                    x0 + candidate_width,
                    y0 + candidate_depth,
                )
                if common.covers(candidate_shape):
                    candidates.add(
                        _rectangle(
                            x0,
                            y0,
                            x0 + candidate_width,
                            y0 + candidate_depth,
                        )
                    )
    return tuple(
        sorted(candidates, key=lambda candidate: _rectangle_bounds(candidate))
    )


def _candidate_origins(
    coordinates: Iterable[float],
    length: float,
) -> tuple[float, ...]:
    values = sorted({float(value) for value in coordinates})
    origins = {
        value for value in values
    } | {
        value - length for value in values
    }
    for low in values:
        for high in values:
            if high - low + _TOLERANCE >= length:
                origins.add((low + high - length) / 2)
    return tuple(sorted(_clean(value) for value in origins))


def _orthogonal_polygon(
    points: Iterable[Point],
    *,
    label: str,
) -> Polygon:
    try:
        vertices = [(float(x), float(y)) for x, y in points]
    except (TypeError, ValueError):
        raise ValueError(f"{label} points must be coordinate pairs") from None
    if len(vertices) >= 2 and vertices[0] == vertices[-1]:
        vertices.pop()
    if len(vertices) < 3 or len(set(vertices)) < 3:
        raise ValueError(f"{label} needs at least 3 distinct points")
    if not all(math.isfinite(value) for point in vertices for value in point):
        raise ValueError(f"{label} coordinates must be finite")
    for start, end in zip(vertices, vertices[1:] + vertices[:1]):
        if (
            abs(start[0] - end[0]) > _TOLERANCE
            and abs(start[1] - end[1]) > _TOLERANCE
        ):
            raise ValueError(f"{label} edges must be axis-aligned")
    polygon = Polygon(vertices)
    if not polygon.is_valid or polygon.area <= _TOLERANCE:
        raise ValueError(f"{label} must be a valid positive-area polygon")
    if polygon.interiors:
        raise ValueError(f"{label} holes are unsupported")
    return polygon


def _canonical_polygon(polygon: Polygon) -> tuple[Point, ...]:
    points = [
        (_clean(x), _clean(y))
        for x, y in polygon.exterior.coords[:-1]
    ]
    rotations: list[list[Point]] = []
    for vertices in (points, list(reversed(points))):
        rotations.extend(
            vertices[index:] + vertices[:index]
            for index in range(len(vertices))
        )
    return tuple(min(rotations))


def _rectangle(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
) -> Rectangle:
    return (
        (_clean(x0), _clean(y0)),
        (_clean(x1), _clean(y0)),
        (_clean(x1), _clean(y1)),
        (_clean(x0), _clean(y1)),
    )


def _rectangle_bounds(
    rectangle: Rectangle,
) -> tuple[float, float, float, float]:
    return (
        float(rectangle[0][0]),
        float(rectangle[0][1]),
        float(rectangle[2][0]),
        float(rectangle[2][1]),
    )


def _clean(value: float) -> float:
    cleaned = round(float(value), 9)
    return 0.0 if cleaned == 0 else cleaned
