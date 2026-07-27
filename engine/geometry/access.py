from __future__ import annotations

import math

from shapely.geometry import LineString, Polygon

from engine.geometry.polygon import Segment, validate_polygon

Point = tuple[float, float]


def shared_boundary_segments(
    left: list[Point],
    right: list[Point],
) -> list[Segment]:
    validate_polygon(left, label="left polygon")
    validate_polygon(right, label="right polygon")
    intersection = Polygon(left).boundary.intersection(Polygon(right).boundary)
    segments: list[Segment] = []
    for line in _line_parts(intersection):
        coordinates = list(line.coords)
        for start, end in zip(coordinates, coordinates[1:]):
            first = (float(start[0]), float(start[1]))
            second = (float(end[0]), float(end[1]))
            if math.dist(first, second) <= 1e-9:
                continue
            segments.append(tuple(sorted((first, second))))
    return sorted(set(segments))


def orthogonal_min_width(polygon: list[Point]) -> float:
    validate_polygon(polygon, label="polygon")
    points = polygon[:-1] if polygon[:1] == polygon[-1:] else polygon
    for start, end in zip(points, [*points[1:], points[0]]):
        if start[0] != end[0] and start[1] != end[1]:
            raise ValueError("polygon edges must be axis-aligned")

    shape = Polygon(points)
    min_x, min_y, max_x, max_y = shape.bounds
    widths: list[float] = []
    x_values = sorted({float(point[0]) for point in points})
    y_values = sorted({float(point[1]) for point in points})
    margin = max(max_x - min_x, max_y - min_y, 1.0)

    for left, right in zip(x_values, x_values[1:]):
        x = (left + right) / 2
        widths.extend(
            line.length
            for line in _line_parts(
                shape.intersection(
                    LineString([(x, min_y - margin), (x, max_y + margin)])
                )
            )
            if line.length > 1e-9
        )
    for bottom, top in zip(y_values, y_values[1:]):
        y = (bottom + top) / 2
        widths.extend(
            line.length
            for line in _line_parts(
                shape.intersection(
                    LineString([(min_x - margin, y), (max_x + margin, y)])
                )
            )
            if line.length > 1e-9
        )
    if not widths:
        raise ValueError("polygon has no measurable width")
    return float(min(widths))


def bounding_box_aspect_ratio(polygon: list[Point]) -> float:
    validate_polygon(polygon, label="polygon")
    points = polygon[:-1] if polygon[:1] == polygon[-1:] else polygon
    x_values = [float(point[0]) for point in points]
    y_values = [float(point[1]) for point in points]
    width = max(x_values) - min(x_values)
    height = max(y_values) - min(y_values)
    short_side = min(width, height)
    if short_side <= 1e-9:
        raise ValueError("polygon bounding box has no measurable short side")
    return max(width, height) / short_side


def _line_parts(geometry):
    if geometry.geom_type == "LineString":
        return [geometry]
    if geometry.geom_type in {"MultiLineString", "GeometryCollection"}:
        return [
            part
            for item in geometry.geoms
            for part in _line_parts(item)
        ]
    return []
