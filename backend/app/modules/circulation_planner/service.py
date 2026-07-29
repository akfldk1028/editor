from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable

from shapely import union_all
from shapely.geometry import LineString, Polygon, box

from backend.app.modules.circulation_planner.contracts import (
    CirculationCandidate,
    CirculationPlanningError,
    Point,
)
from backend.app.modules.core_planner.contracts import CoreCandidate


_DOOR_WIDTH = 0.9
_GRID_STEP = 0.25
_TOLERANCE = 1e-8


def generate_circulation_candidate(
    *,
    floor_boundary: Iterable[Point],
    core: CoreCandidate,
    street_segments: Iterable[tuple[Point, Point]],
    minimum_width: float = 1.2,
    stair_dimensions: Iterable[tuple[float, float]],
) -> CirculationCandidate:
    """Construct a deterministic entrance-to-core-to-stair circulation topology."""
    boundary_points = _points(floor_boundary)
    core_points = _points(core.polygon)
    streets = tuple((_point(start), _point(end)) for start, end in street_segments)
    dimensions = tuple((float(width), float(length)) for width, length in stair_dimensions)
    _validate_inputs(
        boundary_points,
        core_points,
        streets,
        minimum_width=minimum_width,
        stair_dimensions=dimensions,
    )
    boundary = Polygon(boundary_points)
    core_shape = Polygon(core_points)
    corridor = _t_corridor_network(boundary, core_shape, minimum_width)
    if not boundary.covers(corridor):
        raise CirculationPlanningError("circulation crosses the floor boundary")
    polygons = (_canonical_ring(corridor),)
    remote_stair = _select_remote_stair(
        boundary=boundary,
        core=core_shape,
        corridor=corridor,
        street_segments=streets,
        stair_dimensions=dimensions,
    )

    entrance_connected = any(
        corridor.boundary.intersection(LineString(segment)).length
        + _TOLERANCE
        >= _DOOR_WIDTH
        for segment in streets
    )
    core_connected = (
        corridor.boundary.intersection(core_shape.boundary).length + _TOLERANCE
        >= _DOOR_WIDTH
    )
    stair_connected = (
        Polygon(remote_stair).boundary.intersection(corridor.boundary).length
        + _TOLERANCE
        >= _DOOR_WIDTH
    )
    if not (entrance_connected and core_connected and stair_connected):
        raise CirculationPlanningError("circulation topology is disconnected")
    return CirculationCandidate(
        strategy=core.strategy,
        polygons=polygons,
        remote_stair_polygon=remote_stair,
        fingerprint=_fingerprint(
            strategy=core.strategy,
            core_fingerprint=core.fingerprint,
            polygons=polygons,
            remote_stair=remote_stair,
        ),
        entrance_connected=entrance_connected,
        core_connected=core_connected,
        stair_connected=stair_connected,
    )


def _validate_inputs(
    boundary_points: tuple[Point, ...],
    core_points: tuple[Point, ...],
    street_segments: tuple[tuple[Point, Point], ...],
    *,
    minimum_width: float,
    stair_dimensions: tuple[tuple[float, float], ...],
) -> None:
    boundary = Polygon(boundary_points)
    core = Polygon(core_points)
    if not boundary.is_valid or boundary.area <= _TOLERANCE:
        raise CirculationPlanningError("floor boundary must be a valid positive-area polygon")
    if not core.is_valid or core.area <= _TOLERANCE or not boundary.covers(core):
        raise CirculationPlanningError("core must be a valid polygon inside the floor boundary")
    if not math.isfinite(minimum_width) or minimum_width < 1.2:
        raise CirculationPlanningError("minimum_width must be finite and at least 1.2")
    if not street_segments:
        raise CirculationPlanningError("at least one street/access segment is required")
    if any(LineString(segment).length <= _TOLERANCE for segment in street_segments):
        raise CirculationPlanningError("street/access segments must have positive length")
    if not stair_dimensions or any(
        not math.isfinite(value) or value <= 0
        for dimensions in stair_dimensions
        for value in dimensions
    ):
        raise CirculationPlanningError("stair dimensions must be finite and positive")


def _t_corridor_network(boundary: Polygon, core: Polygon, width: float) -> Polygon:
    min_x, min_y, max_x, max_y = boundary.bounds
    core_min_x, core_min_y, core_max_x, core_max_y = core.bounds
    networks = (
        (
            box(core_min_x - width, min_y, core_min_x, max_y),
            box(min_x, core_min_y - width, max_x, core_min_y),
        ),
        (
            box(core_max_x, min_y, core_max_x + width, max_y),
            box(min_x, core_min_y - width, max_x, core_min_y),
        ),
        (
            box(core_min_x - width, min_y, core_min_x, max_y),
            box(min_x, core_max_y, max_x, core_max_y + width),
        ),
        (
            box(core_max_x, min_y, core_max_x + width, max_y),
            box(min_x, core_max_y, max_x, core_max_y + width),
        ),
    )
    for vertical, horizontal in networks:
        network = union_all((vertical, horizontal)).intersection(boundary).difference(core)
        if (
            isinstance(network, Polygon)
            and not network.is_empty
            and network.boundary.intersection(core.boundary).length + _TOLERANCE
            >= _DOOR_WIDTH
        ):
            return network
    raise CirculationPlanningError("floor does not admit a connected corridor network")


def _select_remote_stair(
    *,
    boundary: Polygon,
    core: Polygon,
    corridor: Polygon,
    street_segments: tuple[tuple[Point, Point], ...],
    stair_dimensions: tuple[tuple[float, float], ...],
) -> tuple[Point, ...]:
    free = boundary.difference(union_all((core, corridor)))
    if free.is_empty:
        raise CirculationPlanningError("circulation leaves no remote stair reserve")
    min_x, min_y, max_x, max_y = free.bounds
    candidates = []
    for width, length in stair_dimensions:
        for x in _candidate_origins(free, axis=0, extent=width):
            for y in _candidate_origins(free, axis=1, extent=length):
                stair = box(x, y, x + width, y + length)
                if not free.covers(stair):
                    continue
                if (
                    stair.boundary.intersection(corridor.boundary).length + _TOLERANCE
                    < _DOOR_WIDTH
                ):
                    continue
                candidates.append(stair)
    if not candidates:
        raise CirculationPlanningError("no accessible remote stair reserve fits the floor")
    street_lines = tuple(LineString(segment) for segment in street_segments)
    selected = max(
        candidates,
        key=lambda stair: (
            not any(stair.boundary.intersection(line).length > _TOLERANCE for line in street_lines),
            stair.centroid.distance(core.centroid),
            tuple(-value for value in stair.bounds),
        ),
    )
    return _canonical_ring(selected)


def _grid_values(minimum: float, maximum: float) -> tuple[float, ...]:
    if maximum < minimum - _TOLERANCE:
        return ()
    count = math.floor((maximum - minimum) / _GRID_STEP + _TOLERANCE)
    values = [minimum + index * _GRID_STEP for index in range(count + 1)]
    values.append(maximum)
    return tuple(sorted({_clean(value) for value in values}))


def _candidate_origins(shape, *, axis: int, extent: float) -> tuple[float, ...]:
    minimum = shape.bounds[axis]
    maximum = shape.bounds[axis + 2] - extent
    polygons = tuple(shape.geoms) if hasattr(shape, "geoms") else (shape,)
    edges = {
        float(coordinate[axis])
        for polygon in polygons
        for coordinate in polygon.exterior.coords
    }
    return tuple(
        sorted(
            {
                *_grid_values(minimum, maximum),
                *(
                    origin
                    for edge in edges
                    for origin in (edge, edge - extent)
                    if minimum - _TOLERANCE <= origin <= maximum + _TOLERANCE
                ),
            }
        )
    )


def _fingerprint(
    *,
    strategy: str,
    core_fingerprint: str,
    polygons: tuple[tuple[Point, ...], ...],
    remote_stair: tuple[Point, ...],
) -> str:
    payload = json.dumps(
        {
            "core": core_fingerprint,
            "polygons": sorted(_canonical_ring(polygon) for polygon in polygons),
            "remote_stair": _canonical_ring(remote_stair),
            "strategy": strategy,
        },
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical_ring(points: Iterable[Point] | Polygon) -> tuple[Point, ...]:
    coordinates = (
        tuple((float(x), float(y)) for x, y in points.exterior.coords[:-1])
        if isinstance(points, Polygon)
        else _points(points)
    )
    normalized = tuple(
        (0.0 if math.isclose(x, 0.0, abs_tol=_TOLERANCE) else x,
         0.0 if math.isclose(y, 0.0, abs_tol=_TOLERANCE) else y)
        for x, y in coordinates
    )
    rotations = [normalized[index:] + normalized[:index] for index in range(len(normalized))]
    reversed_points = tuple(reversed(normalized))
    rotations.extend(
        reversed_points[index:] + reversed_points[:index]
        for index in range(len(reversed_points))
    )
    return min(rotations)


def _points(points: Iterable[Point]) -> tuple[Point, ...]:
    return tuple(_point(point) for point in points)


def _point(point: Point) -> Point:
    return (_clean(float(point[0])), _clean(float(point[1])))


def _clean(value: float) -> float:
    return 0.0 if math.isclose(value, 0.0, abs_tol=_TOLERANCE) else round(value, 8)
