from __future__ import annotations

import hashlib
import json
import math

from shapely.geometry import Point, Polygon, box

from backend.app.modules.core_planner.contracts import CoreCandidate


_STRATEGIES = ("central", "notch_adjacent", "long_edge_adjacent")
_GRID_STEP = 0.25
_MAX_DIMENSION_SAMPLES = 24


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
    if common.is_empty:
        return ()

    rectangles = tuple(
        rectangle
        for width, depth in _dimension_options(
            common,
            required_area=required_area,
            minimum_width=minimum_width,
            minimum_depth=minimum_depth,
        )
        for rectangle in _contained_rectangles(common, width=width, depth=depth)
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


def _contained_rectangles(common, *, width: float, depth: float) -> tuple:
    min_x, min_y, max_x, max_y = common.bounds
    result = []
    x = min_x
    while x + width <= max_x + 1e-9:
        y = min_y
        while y + depth <= max_y + 1e-9:
            rectangle = box(x, y, x + width, y + depth)
            if common.covers(rectangle):
                result.append(rectangle)
            y = round(y + _GRID_STEP, 8)
        x = round(x + _GRID_STEP, 8)
    return tuple(result)


def _round_up(value: float) -> float:
    return math.ceil(value * 1_000_000) / 1_000_000


def _dimension_options(
    common,
    *,
    required_area: float,
    minimum_width: float,
    minimum_depth: float,
) -> tuple[tuple[float, float], ...]:
    min_x, min_y, max_x, max_y = common.bounds
    available_width = max_x - min_x
    available_depth = max_y - min_y
    options: list[tuple[float, float]] = []
    for horizontal_minimum, vertical_minimum in (
        (minimum_width, minimum_depth),
        (minimum_depth, minimum_width),
    ):
        for width in _sample_dimension_values(
            minimum=horizontal_minimum,
            maximum=available_width,
            preferred=(
                math.sqrt(required_area),
                required_area / available_depth,
            ),
        ):
            depth = max(vertical_minimum, _round_up(required_area / width))
            if depth <= available_depth + 1e-9:
                option = (width, depth)
                if option not in options:
                    options.append(option)
    return tuple(options)


def _sample_dimension_values(
    *,
    minimum: float,
    maximum: float,
    preferred: tuple[float, ...],
) -> tuple[float, ...]:
    if maximum < minimum:
        return ()
    values = {minimum, maximum}
    values.update(value for value in preferred if minimum <= value <= maximum)
    remaining = _MAX_DIMENSION_SAMPLES - len(values)
    step_count = int(math.floor((maximum - minimum) / _GRID_STEP))
    if step_count <= remaining:
        values.update(minimum + index * _GRID_STEP for index in range(1, step_count + 1))
    elif remaining > 0:
        values.update(
            minimum + (maximum - minimum) * index / (remaining + 1)
            for index in range(1, remaining + 1)
        )
    return tuple(sorted(values))


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
