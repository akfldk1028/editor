from __future__ import annotations

import hashlib
import json
import math

from shapely.geometry import Point, Polygon, box
from shapely.prepared import prep

from backend.app.modules.core_planner.contracts import CoreCandidate


_STRATEGIES = ("central", "notch_adjacent", "long_edge_adjacent")
_GRID_STEP = 0.25
_MAX_AUXILIARY_INTERVALS_PER_AXIS = 64
_TOLERANCE = 1e-9


def generate_shared_core_candidates(
    floor_boundaries: tuple[tuple[tuple[float, float], ...], ...],
    *,
    required_area: float,
    minimum_width: float,
    minimum_depth: float,
) -> tuple[CoreCandidate, ...]:
    """Return deterministic rectangular cores contained by every floor."""
    _validate_requirements(
        floor_boundaries,
        required_area=required_area,
        minimum_width=minimum_width,
        minimum_depth=minimum_depth,
    )
    floors = tuple(Polygon(boundary) for boundary in floor_boundaries)
    common = floors[0]
    for floor in floors[1:]:
        common = common.intersection(floor)
    if (
        common.is_empty
        or common.geom_type not in {"Polygon", "MultiPolygon"}
        or common.area <= _TOLERANCE
    ):
        return ()
    x_coordinates, y_coordinates = _critical_coordinates(common)
    if len(x_coordinates) < 2 or len(y_coordinates) < 2:
        return ()
    boundary_segments = _boundary_segments(common)

    rectangles = tuple(
        rectangle
        for width, depth in _dimension_options(
            x_coordinates,
            y_coordinates,
            bounds=common.bounds,
            required_area=required_area,
            minimum_width=minimum_width,
            minimum_depth=minimum_depth,
        )
        for rectangle in _contained_rectangles(
            common,
            boundary_segments=boundary_segments,
            x_coordinates=x_coordinates,
            y_coordinates=y_coordinates,
            width=width,
            depth=depth,
        )
    )
    if not rectangles:
        return ()

    targets = _strategy_targets(common)
    selected: list[CoreCandidate] = []
    used: set[str] = set()
    for strategy in _STRATEGIES:
        ranked = sorted(
            rectangles,
            key=lambda rectangle: (
                rectangle.centroid.distance(targets[strategy]),
                rectangle.bounds,
            ),
        )
        for rectangle in ranked:
            polygon = _rectangle_points(rectangle)
            returned_shape = Polygon(polygon)
            contained_floor_indices = tuple(
                index for index, floor in enumerate(floors) if floor.covers(returned_shape)
            )
            if len(contained_floor_indices) != len(floors):
                continue
            fingerprint = _geometry_fingerprint(polygon)
            if fingerprint in used:
                continue
            used.add(fingerprint)
            selected.append(
                CoreCandidate(
                    strategy=strategy,
                    polygon=polygon,
                    fingerprint=fingerprint,
                    contained_floor_indices=contained_floor_indices,
                )
            )
            break
    return tuple(selected)


def _validate_requirements(
    floor_boundaries: tuple[tuple[tuple[float, float], ...], ...],
    *,
    required_area: float,
    minimum_width: float,
    minimum_depth: float,
) -> None:
    if not floor_boundaries:
        raise ValueError("floor_boundaries must not be empty")
    values = (required_area, minimum_width, minimum_depth)
    if any(not math.isfinite(value) or value <= 0 for value in values):
        raise ValueError("core requirements must be finite and positive")
    for boundary in floor_boundaries:
        polygon = Polygon(boundary)
        if not polygon.is_valid or polygon.area <= 0:
            raise ValueError("floor boundaries must be valid polygons")


def _contained_rectangles(
    common,
    *,
    boundary_segments: tuple[
        tuple[tuple[float, float], tuple[float, float]], ...
    ],
    x_coordinates: tuple[float, ...],
    y_coordinates: tuple[float, ...],
    width: float,
    depth: float,
) -> tuple:
    min_x, min_y, max_x, max_y = common.bounds
    maximum_x_origin = max_x - width
    maximum_y_origin = max_y - depth
    if (
        maximum_x_origin < min_x - _TOLERANCE
        or maximum_y_origin < min_y - _TOLERANCE
    ):
        return ()

    x_origins = _sample_values(
        minimum=min_x,
        maximum=maximum_x_origin,
        extra=(
            coordinate
            for coordinate in x_coordinates
            for coordinate in (coordinate, coordinate - width)
        ),
    )
    y_origins = _sample_values(
        minimum=min_y,
        maximum=maximum_y_origin,
        extra=(
            coordinate
            for coordinate in y_coordinates
            for coordinate in (coordinate, coordinate - depth)
        ),
    )

    prepared_common = prep(common)
    result = []
    seen: set[tuple[float, float, float, float]] = set()
    tested_origins: set[tuple[float, float]] = set()

    def test_origin(x: float, y: float) -> None:
        origin = (x, y)
        if origin in tested_origins:
            return
        tested_origins.add(origin)
        if not prepared_common.covers(Point(x + width / 2, y + depth / 2)):
            return
        rectangle_max_x = x + width
        rectangle_max_y = y + depth
        if rectangle_max_x - x < width:
            rectangle_max_x = math.nextafter(rectangle_max_x, math.inf)
        if rectangle_max_y - y < depth:
            rectangle_max_y = math.nextafter(rectangle_max_y, math.inf)
        rectangle = box(x, y, rectangle_max_x, rectangle_max_y)
        if prepared_common.covers(rectangle):
            bounds = tuple(float(value) for value in rectangle.bounds)
            if bounds not in seen:
                seen.add(bounds)
                result.append(rectangle)

    for x in x_origins:
        for y in y_origins:
            test_origin(x, y)

    for y in y_origins:
        for x in _edge_x_origins(
            boundary_segments,
            y_coordinates=(y, y + depth),
            width=width,
            minimum=min_x,
            maximum=maximum_x_origin,
        ):
            test_origin(x, y)
    for x in x_origins:
        for y in _edge_y_origins(
            boundary_segments,
            x_coordinates=(x, x + width),
            depth=depth,
            minimum=min_y,
            maximum=maximum_y_origin,
        ):
            test_origin(x, y)
    return tuple(result)


def _dimension_options(
    x_coordinates: tuple[float, ...],
    y_coordinates: tuple[float, ...],
    *,
    bounds: tuple[float, float, float, float],
    required_area: float,
    minimum_width: float,
    minimum_depth: float,
) -> tuple[tuple[float, float], ...]:
    options: list[tuple[float, float]] = []
    min_x, min_y, max_x, max_y = bounds
    available_width = max_x - min_x
    available_depth = max_y - min_y
    horizontal_spans = _critical_spans(x_coordinates)
    vertical_spans = _critical_spans(y_coordinates)
    for horizontal_minimum, vertical_minimum in (
        (minimum_width, minimum_depth),
        (minimum_depth, minimum_width),
    ):
        if available_depth < vertical_minimum - _TOLERANCE:
            continue
        maximum_useful_width = min(
            available_width,
            max(horizontal_minimum, required_area / vertical_minimum),
        )
        widths = {horizontal_minimum, math.sqrt(required_area)}
        widths.update(span for span in horizontal_spans if span >= horizontal_minimum)
        widths.update(
            required_area / span
            for span in vertical_spans
            if span >= vertical_minimum
        )
        for width in _sample_values(
            minimum=horizontal_minimum,
            maximum=maximum_useful_width,
            extra=widths,
        ):
            depth = max(vertical_minimum, required_area / width)
            if depth > available_depth + _TOLERANCE:
                continue
            option = (width, depth)
            if option not in options:
                options.append(option)
    return tuple(options)


def _sample_values(
    *,
    minimum: float,
    maximum: float,
    extra,
) -> tuple[float, ...]:
    if maximum < minimum - _TOLERANCE:
        return ()
    values = {
        *_auxiliary_grid_values(minimum=minimum, maximum=maximum),
        *(
            float(value)
            for value in extra
            if minimum - _TOLERANCE <= float(value) <= maximum + _TOLERANCE
        ),
    }
    return tuple(sorted(values))


def _auxiliary_grid_values(
    *,
    minimum: float,
    maximum: float,
) -> tuple[float, ...]:
    if maximum < minimum - _TOLERANCE:
        return ()
    span = maximum - minimum
    if span <= _TOLERANCE:
        return tuple(sorted({minimum, maximum}))

    natural_interval_count = max(
        1,
        math.ceil(span / _GRID_STEP - _TOLERANCE),
    )
    if natural_interval_count <= _MAX_AUXILIARY_INTERVALS_PER_AXIS:
        return tuple(
            (
                minimum + index * _GRID_STEP
                if index < natural_interval_count
                else maximum
            )
            for index in range(natural_interval_count + 1)
        )

    return tuple(
        (
            minimum
            if index == 0
            else maximum
            if index == _MAX_AUXILIARY_INTERVALS_PER_AXIS
            else minimum
            + span * index / _MAX_AUXILIARY_INTERVALS_PER_AXIS
        )
        for index in range(_MAX_AUXILIARY_INTERVALS_PER_AXIS + 1)
    )


def _boundary_segments(
    common,
) -> tuple[tuple[tuple[float, float], tuple[float, float]], ...]:
    polygons = (common,) if common.geom_type == "Polygon" else tuple(common.geoms)
    rings = tuple(
        ring
        for polygon in polygons
        for ring in (polygon.exterior, *polygon.interiors)
    )
    return tuple(
        ((float(start[0]), float(start[1])), (float(end[0]), float(end[1])))
        for ring in rings
        for start, end in zip(ring.coords, ring.coords[1:])
    )


def _edge_x_origins(
    segments: tuple[tuple[tuple[float, float], tuple[float, float]], ...],
    *,
    y_coordinates: tuple[float, ...],
    width: float,
    minimum: float,
    maximum: float,
) -> tuple[float, ...]:
    intersections = {
        x
        for y in y_coordinates
        for x in _horizontal_intersections(segments, y)
    }
    return tuple(
        sorted(
            {
                origin
                for coordinate in intersections
                for origin in (coordinate, coordinate - width)
                if minimum - _TOLERANCE <= origin <= maximum + _TOLERANCE
            }
        )
    )


def _edge_y_origins(
    segments: tuple[tuple[tuple[float, float], tuple[float, float]], ...],
    *,
    x_coordinates: tuple[float, ...],
    depth: float,
    minimum: float,
    maximum: float,
) -> tuple[float, ...]:
    intersections = {
        y
        for x in x_coordinates
        for y in _vertical_intersections(segments, x)
    }
    return tuple(
        sorted(
            {
                origin
                for coordinate in intersections
                for origin in (coordinate, coordinate - depth)
                if minimum - _TOLERANCE <= origin <= maximum + _TOLERANCE
            }
        )
    )


def _horizontal_intersections(
    segments: tuple[tuple[tuple[float, float], tuple[float, float]], ...],
    y: float,
) -> tuple[float, ...]:
    intersections = []
    for (start_x, start_y), (end_x, end_y) in segments:
        if math.isclose(start_y, end_y, abs_tol=_TOLERANCE):
            if math.isclose(y, start_y, abs_tol=_TOLERANCE):
                intersections.extend((start_x, end_x))
            continue
        if min(start_y, end_y) - _TOLERANCE <= y <= max(start_y, end_y) + _TOLERANCE:
            ratio = (y - start_y) / (end_y - start_y)
            if -_TOLERANCE <= ratio <= 1 + _TOLERANCE:
                intersections.append(start_x + ratio * (end_x - start_x))
    return tuple(intersections)


def _vertical_intersections(
    segments: tuple[tuple[tuple[float, float], tuple[float, float]], ...],
    x: float,
) -> tuple[float, ...]:
    intersections = []
    for (start_x, start_y), (end_x, end_y) in segments:
        if math.isclose(start_x, end_x, abs_tol=_TOLERANCE):
            if math.isclose(x, start_x, abs_tol=_TOLERANCE):
                intersections.extend((start_y, end_y))
            continue
        if min(start_x, end_x) - _TOLERANCE <= x <= max(start_x, end_x) + _TOLERANCE:
            ratio = (x - start_x) / (end_x - start_x)
            if -_TOLERANCE <= ratio <= 1 + _TOLERANCE:
                intersections.append(start_y + ratio * (end_y - start_y))
    return tuple(intersections)


def _critical_coordinates(common) -> tuple[tuple[float, ...], tuple[float, ...]]:
    polygons = (common,) if common.geom_type == "Polygon" else tuple(common.geoms)
    coordinates = tuple(
        coordinate
        for polygon in polygons
        for coordinate in polygon.exterior.coords[:-1]
    )
    return (
        tuple(sorted({float(x) for x, _ in coordinates})),
        tuple(sorted({float(y) for _, y in coordinates})),
    )


def _critical_spans(coordinates: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(
        right - left
        for index, left in enumerate(coordinates)
        for right in coordinates[index + 1:]
        if right > left
    )


def _strategy_targets(common) -> dict[str, Point]:
    coordinates = tuple(common.exterior.coords) if common.geom_type == "Polygon" else ()
    concave = _concave_vertices(coordinates)
    notch = min(concave, key=lambda point: point.distance(common.centroid), default=None)
    segments = tuple(zip(coordinates, coordinates[1:]))
    longest_start, longest_end = max(
        segments,
        key=lambda segment: math.dist(segment[0], segment[1]),
        default=((common.centroid.x, common.centroid.y),) * 2,
    )
    longest_midpoint = Point(
        (longest_start[0] + longest_end[0]) / 2,
        (longest_start[1] + longest_end[1]) / 2,
    )
    return {
        "central": common.centroid,
        "notch_adjacent": notch or common.centroid,
        "long_edge_adjacent": longest_midpoint,
    }


def _concave_vertices(coordinates: tuple[tuple[float, float], ...]) -> tuple[Point, ...]:
    if len(coordinates) < 4:
        return ()
    signed_area = sum(
        start[0] * end[1] - end[0] * start[1]
        for start, end in zip(coordinates, coordinates[1:])
    )
    orientation = 1 if signed_area > 0 else -1
    vertices = coordinates[:-1]
    return tuple(
        Point(current)
        for previous, current, following in zip(
            vertices[-1:] + vertices[:-1], vertices, vertices[1:] + vertices[:1], strict=True
        )
        if orientation
        * ((current[0] - previous[0]) * (following[1] - current[1])
           - (current[1] - previous[1]) * (following[0] - current[0]))
        < 0
    )


def _rectangle_points(rectangle) -> tuple[tuple[float, float], ...]:
    return tuple(
        (float(x), float(y))
        for x, y in tuple(rectangle.exterior.coords)[:-1]
    )


def _geometry_fingerprint(polygon: tuple[tuple[float, float], ...]) -> str:
    normalized = tuple((0.0 if x == 0 else x, 0.0 if y == 0 else y) for x, y in polygon)
    rotations = [normalized[index:] + normalized[:index] for index in range(len(normalized))]
    reversed_polygon = tuple(reversed(normalized))
    rotations.extend(
        reversed_polygon[index:] + reversed_polygon[:index]
        for index in range(len(reversed_polygon))
    )
    canonical = json.dumps(min(rotations), separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
