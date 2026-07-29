from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable

from shapely import union_all
from shapely.geometry import GeometryCollection, LineString, MultiLineString, Polygon, box

from backend.app.modules.circulation_planner.contracts import (
    CirculationCandidate,
    CirculationPlanningError,
    Point,
)
from backend.app.modules.core_planner.contracts import CoreCandidate
from engine.geometry.distance import segment_to_segment_distance


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
    minimum_exit_separation: float | None = None,
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
        minimum_exit_separation=minimum_exit_separation,
    )
    boundary = Polygon(boundary_points)
    core_shape = Polygon(core_points)
    corridor_rectangles, remote_stair = _select_network_and_stair(
        boundary=boundary,
        core=core_shape,
        street_segments=streets,
        minimum_width=minimum_width,
        stair_dimensions=dimensions,
        minimum_exit_separation=minimum_exit_separation,
    )
    corridor = union_all(corridor_rectangles)
    polygons = tuple(_canonical_ring(rectangle) for rectangle in corridor_rectangles)

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
    minimum_exit_separation: float | None,
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
    if minimum_exit_separation is not None and (
        not math.isfinite(minimum_exit_separation)
        or minimum_exit_separation <= 0
    ):
        raise CirculationPlanningError(
            "minimum_exit_separation must be finite and positive"
        )


def _select_network_and_stair(
    *,
    boundary: Polygon,
    core: Polygon,
    street_segments: tuple[tuple[Point, Point], ...],
    minimum_width: float,
    stair_dimensions: tuple[tuple[float, float], ...],
    minimum_exit_separation: float | None,
) -> tuple[tuple[Polygon, ...], tuple[Point, ...]]:
    if minimum_exit_separation is None:
        rectangles = _legacy_corridor_rectangles(boundary, core, minimum_width)
        corridor = union_all(rectangles)
        stair = _select_remote_stair(
            boundary=boundary,
            core=core,
            corridor=corridor,
            corridor_rectangles=rectangles,
            street_segments=street_segments,
            stair_dimensions=stair_dimensions,
        )
        return rectangles, stair

    candidates = []
    for rectangles in _corridor_network_candidates(boundary, core, minimum_width):
        corridor = union_all(rectangles)
        if (
            not isinstance(corridor, Polygon)
            or not boundary.covers(corridor)
            or corridor.intersection(core).area > _TOLERANCE
        ):
            continue
        if not any(
            corridor.boundary.intersection(LineString(segment)).length
            + _TOLERANCE
            >= _DOOR_WIDTH
            for segment in street_segments
        ):
            continue
        for stair in _remote_stair_candidates(
            boundary=boundary,
            core=core,
            corridor=corridor,
            corridor_rectangles=rectangles,
            stair_dimensions=stair_dimensions,
        ):
            separation = _maximum_doorway_separation(core, corridor, stair)
            if separation + _TOLERANCE < minimum_exit_separation:
                continue
            candidates.append(
                (
                    corridor.area,
                    -separation,
                    tuple(rectangle.bounds for rectangle in rectangles),
                    stair.bounds,
                    rectangles,
                    stair,
                )
            )
    if not candidates:
        raise CirculationPlanningError(
            "no connected circulation topology meets the exit separation target"
        )
    *_, rectangles, stair = min(candidates)
    return rectangles, _canonical_ring(stair)


def _corridor_network_candidates(
    boundary: Polygon,
    core: Polygon,
    width: float,
) -> tuple[tuple[Polygon, ...], ...]:
    candidates = [_legacy_corridor_rectangles(boundary, core, width)]
    candidates.extend(_long_edge_corridor_networks(boundary, core, width))
    unique = {}
    for rectangles in candidates:
        key = tuple(rectangle.bounds for rectangle in rectangles)
        unique[key] = rectangles
    return tuple(unique[key] for key in sorted(unique))


def _legacy_corridor_rectangles(
    boundary: Polygon,
    core: Polygon,
    width: float,
) -> tuple[Polygon, ...]:
    _, min_y, max_x, _ = boundary.bounds
    core_min_x, _, core_max_x, core_max_y = core.bounds
    networks = (
        box(core_min_x - width, min_y, core_min_x, core_max_y),
        box(core_max_x, min_y, core_max_x + width, core_max_y),
    )
    for network in networks:
        if (
            boundary.covers(network)
            and network.boundary.intersection(core.boundary).length + _TOLERANCE
            >= _DOOR_WIDTH
        ):
            if core.bounds[1] > min_y + _TOLERANCE:
                return (network,)
            crossbar = box(
                network.bounds[0],
                core_max_y,
                max_x,
                core_max_y + width,
            )
            if boundary.covers(crossbar):
                return (network, crossbar)
    raise CirculationPlanningError("floor does not admit a connected corridor network")


def _long_edge_corridor_networks(
    boundary: Polygon,
    core: Polygon,
    width: float,
) -> tuple[tuple[Polygon, ...], ...]:
    min_y = boundary.bounds[1]
    core_min_x, core_min_y, core_max_x, _ = core.bounds
    route_y = _clean(core_min_y - width)
    if route_y <= min_y + _TOLERANCE:
        return ()
    networks = []
    for trunk_x in _candidate_origins(boundary, axis=0, extent=width):
        if trunk_x + width > core_max_x + _TOLERANCE:
            continue
        trunk = box(trunk_x, min_y, trunk_x + width, route_y)
        crossbar = box(trunk_x, route_y, core_max_x, core_min_y)
        if (
            boundary.covers(trunk)
            and boundary.covers(crossbar)
            and crossbar.boundary.intersection(core.boundary).length
            + _TOLERANCE
            >= _DOOR_WIDTH
        ):
            networks.append((trunk, crossbar))
    return tuple(networks)


def _select_remote_stair(
    *,
    boundary: Polygon,
    core: Polygon,
    corridor: Polygon,
    corridor_rectangles: tuple[Polygon, ...],
    street_segments: tuple[tuple[Point, Point], ...],
    stair_dimensions: tuple[tuple[float, float], ...],
) -> tuple[Point, ...]:
    candidates = _remote_stair_candidates(
        boundary=boundary,
        core=core,
        corridor=corridor,
        corridor_rectangles=corridor_rectangles,
        stair_dimensions=stair_dimensions,
    )
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


def _remote_stair_candidates(
    *,
    boundary: Polygon,
    core: Polygon,
    corridor: Polygon,
    corridor_rectangles: tuple[Polygon, ...],
    stair_dimensions: tuple[tuple[float, float], ...],
) -> tuple[Polygon, ...]:
    free = boundary.difference(union_all((core, corridor)))
    if free.is_empty:
        return ()
    candidates = {}
    for stair_width, stair_length in stair_dimensions:
        grid_x = _candidate_origins(free, axis=0, extent=stair_width)
        grid_y = _candidate_origins(free, axis=1, extent=stair_length)
        adjacent_x = {
            value
            for rectangle in corridor_rectangles
            for value in (
                rectangle.bounds[0] - stair_width,
                rectangle.bounds[2],
            )
        }
        adjacent_y = {
            value
            for rectangle in corridor_rectangles
            for value in (
                rectangle.bounds[1] - stair_length,
                rectangle.bounds[3],
            )
        }
        origins = {
            *((x, y) for x in adjacent_x for y in grid_y),
            *((x, y) for x in grid_x for y in adjacent_y),
        }
        for x, y in origins:
            stair = box(x, y, x + stair_width, y + stair_length)
            if (
                free.covers(stair)
                and stair.boundary.intersection(corridor.boundary).length
                + _TOLERANCE
                >= _DOOR_WIDTH
            ):
                candidates[stair.bounds] = stair
    return tuple(candidates[key] for key in sorted(candidates))


def _maximum_doorway_separation(
    core: Polygon,
    corridor: Polygon,
    stair: Polygon,
) -> float:
    core_line = _longest_shared_line(core, corridor)
    stair_line = _longest_shared_line(stair, corridor)
    if core_line is None or stair_line is None:
        return 0.0
    return max(
        segment_to_segment_distance(core_opening, stair_opening)
        for core_opening in _end_openings(core_line)
        for stair_opening in _end_openings(stair_line)
    )


def _longest_shared_line(
    first: Polygon,
    second: Polygon,
) -> LineString | None:
    lines = _line_strings(first.boundary.intersection(second.boundary))
    return max(lines, key=lambda line: (line.length, tuple(line.coords)), default=None)


def _line_strings(geometry) -> tuple[LineString, ...]:
    if isinstance(geometry, LineString):
        return (geometry,)
    if isinstance(geometry, (MultiLineString, GeometryCollection)):
        return tuple(
            line
            for part in geometry.geoms
            for line in _line_strings(part)
        )
    return ()


def _end_openings(line: LineString) -> tuple[tuple[Point, Point], ...]:
    start = _point(line.coords[0])
    end = _point(line.coords[-1])
    if end < start:
        start, end = end, start
    length = math.dist(start, end)
    if length + _TOLERANCE < _DOOR_WIDTH:
        return ()
    unit = (
        (end[0] - start[0]) / length,
        (end[1] - start[1]) / length,
    )
    return (
        (
            start,
            (
                start[0] + unit[0] * _DOOR_WIDTH,
                start[1] + unit[1] * _DOOR_WIDTH,
            ),
        ),
        (
            (
                end[0] - unit[0] * _DOOR_WIDTH,
                end[1] - unit[1] * _DOOR_WIDTH,
            ),
            end,
        ),
    )


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
    x, y = float(point[0]), float(point[1])
    return (
        0.0 if math.isclose(x, 0.0, abs_tol=_TOLERANCE) else x,
        0.0 if math.isclose(y, 0.0, abs_tol=_TOLERANCE) else y,
    )


def _clean(value: float) -> float:
    return 0.0 if math.isclose(value, 0.0, abs_tol=_TOLERANCE) else round(value, 8)
