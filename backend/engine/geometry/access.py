from __future__ import annotations

import math

from shapely.geometry import LineString, Polygon

from backend.engine.geometry.polygon import Segment, validate_polygon

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
    if any(start[0] != end[0] and start[1] != end[1] for start, end in zip(points, [*points[1:], points[0]])):
        # a room whose outer wall follows a slanted or curved facade: the shortest axis slice would read the
        # clipped corner as a knife edge, so its width is the widest circle that fits (the short side, on a
        # rectangle) - what furniture and a door actually need
        return _inscribed_width(Polygon(points))

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


def _inscribed_width(shape: Polygon) -> float:
    """Diameter of the largest disk that can be swept through the whole of `shape`: the largest r whose inward
    buffer is still one piece reaching every side of the shape's box (bisection, 1 mm). A dumbbell of two 4 m
    halves joined by a 0.4 m neck measures 0.4 (the buffer splits there), a corridor measures its narrowest
    run, a rectangle its short side - the bottleneck, which is what a door and a person need."""
    shape = shape.buffer(0)
    if shape.is_empty:
        raise ValueError("polygon has no measurable width")
    min_x, min_y, max_x, max_y = shape.bounds

    def sweeps(r: float) -> bool:
        # the ground a disk of radius r can reach (morphological opening): it must stay one piece and keep
        # nearly all of the shape - only oblique corners, which no disk fills, may be lost
        core = shape.buffer(-r)
        if core.is_empty or core.geom_type != "Polygon":
            return False
        reached = core.buffer(r)
        return reached.geom_type == "Polygon" and reached.area >= 0.92 * shape.area

    lo, hi = 0.0, min(max_x - min_x, max_y - min_y) / 2 + 1e-9
    while hi - lo > 5e-4:
        mid = (lo + hi) / 2
        if sweeps(mid):
            lo = mid
        else:
            hi = mid
    return float(2 * lo + 1e-3)


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
