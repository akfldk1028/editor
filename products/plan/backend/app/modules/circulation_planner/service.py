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
from backend.engine.geometry import snap_coordinate, snap_ring
from backend.engine.geometry.distance import segment_to_segment_distance


_DOOR_WIDTH = 0.9
_GRID_STEP = 0.25
_MAX_AUXILIARY_INTERVALS_PER_AXIS = 64
_MAX_CORRIDOR_NETWORK_CANDIDATES = 64
_MAX_REMOTE_STAIR_VALID_ORIGINS_PER_DIMENSION = 256
_MAX_REMOTE_STAIR_CANDIDATES = 128
_TOLERANCE = 1e-8
# How far a room may sit from the corridor before the floor counts as out of
# reach. Roughly one deep room off either side of the spine.
_CORRIDOR_REACH_M = 14.0
# A sliver of the plate beyond that distance is normal; a limb of it is not.
_MAX_OUT_OF_REACH_RATIO = 0.08
_MAX_BRANCH_CANDIDATES = 24


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
    polygons = tuple(_canonical_ring(rectangle) for rectangle in corridor_rectangles)
    remote_stair = snap_ring(remote_stair)
    # Judge connectivity on the geometry that leaves this module, not on the
    # raw arithmetic behind it, so a candidate cannot pass here and read as
    # disconnected to its consumer.
    corridor = union_all([Polygon(polygon) for polygon in polygons])

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
        core_fingerprint=core.fingerprint,
        polygons=polygons,
        remote_stair_polygon=remote_stair,
        fingerprint=circulation_geometry_fingerprint(
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
    for rectangles in _corridor_network_candidates(
        boundary,
        core,
        minimum_width,
        minimum_exit_separation=minimum_exit_separation,
    ):
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
            minimum_exit_separation=minimum_exit_separation,
        ):
            separation = _maximum_doorway_separation(core, corridor, stair)
            if separation + _TOLERANCE < minimum_exit_separation:
                continue
            candidates.append(
                (
                    _out_of_reach_ratio(boundary, corridor) > _MAX_OUT_OF_REACH_RATIO,
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
    # A corridor that leaves a limb of the floor unreachable loses to one that
    # does not, however much smaller it is. Among those that reach, the compact
    # network still wins.
    *_, rectangles, stair = min(candidates)
    return rectangles, _canonical_ring(stair)


def _corridor_network_candidates(
    boundary: Polygon,
    core: Polygon,
    width: float,
    *,
    minimum_exit_separation: float | None = None,
) -> tuple[tuple[Polygon, ...], ...]:
    # The legacy strip is one option among several, not a precondition. It only
    # fits beside a core that leaves room for it, and letting its absence raise
    # here hid every other topology from a plate that had one.
    try:
        legacy_networks = (_legacy_corridor_rectangles(boundary, core, width),)
    except CirculationPlanningError:
        legacy_networks = ()
    critical_networks, auxiliary_networks = _long_edge_corridor_networks(
        boundary,
        core,
        width,
        minimum_exit_separation=minimum_exit_separation,
    )
    selected = []
    seen = set()
    for group in ((*legacy_networks, *critical_networks), auxiliary_networks):
        for rectangles in group:
            key = tuple(rectangle.bounds for rectangle in rectangles)
            if key in seen:
                continue
            seen.add(key)
            selected.append(rectangles)
            if len(selected) == _MAX_CORRIDOR_NETWORK_CANDIDATES:
                return tuple(selected)
    for rectangles in _branch_corridor_networks(boundary, tuple(selected), width):
        key = tuple(rectangle.bounds for rectangle in rectangles)
        if key in seen:
            continue
        seen.add(key)
        selected.append(rectangles)
        if len(selected) == _MAX_CORRIDOR_NETWORK_CANDIDATES:
            break
    return tuple(selected)


def _out_of_reach_ratio(boundary: Polygon, corridor: Polygon) -> float:
    """Share of the floor that sits further than a room's depth from a corridor."""
    if boundary.area <= 0:
        return 0.0
    stranded = boundary.difference(corridor.buffer(_CORRIDOR_REACH_M))
    return stranded.area / boundary.area


def _branch_corridor_networks(
    boundary: Polygon,
    base_networks: Iterable[tuple[Polygon, ...]],
    width: float,
) -> tuple[tuple[Polygon, ...], ...]:
    """Extend a network with one spur toward the part of the floor it misses.

    A template anchored to the core stays in the limb that holds the core, so a
    plate with more than one limb leaves the others without circulation to open
    a room onto. Each spur runs from a rectangle already in the network to the
    stranded area, along one axis at a time so it stays orthogonal.
    """
    branched: list[tuple[Polygon, ...]] = []
    for rectangles in base_networks:
        corridor = union_all(rectangles)
        if not isinstance(corridor, Polygon):
            continue
        stranded = boundary.difference(corridor.buffer(_CORRIDOR_REACH_M))
        if stranded.is_empty:
            continue
        limbs = (
            list(stranded.geoms)
            if stranded.geom_type == "MultiPolygon"
            else [stranded]
        )
        for limb in sorted(limbs, key=lambda shape: -shape.area):
            target = limb.representative_point()
            for source in rectangles:
                for spur in _spur_options(source, target, width):
                    if not boundary.covers(spur):
                        continue
                    if spur.intersection(corridor).area > _TOLERANCE:
                        continue
                    if (
                        spur.boundary.intersection(corridor.boundary).length
                        + _TOLERANCE
                        < _DOOR_WIDTH
                    ):
                        continue
                    branched.append((*rectangles, spur))
                    if len(branched) == _MAX_BRANCH_CANDIDATES:
                        return tuple(branched)
    return tuple(branched)


def _spur_options(
    source: Polygon,
    target,
    width: float,
) -> tuple[Polygon, ...]:
    min_x, min_y, max_x, max_y = source.bounds
    options = []
    if target.y > max_y:
        options.append(box(min_x, max_y, min_x + width, target.y))
        options.append(box(max_x - width, max_y, max_x, target.y))
    if target.y < min_y:
        options.append(box(min_x, target.y, min_x + width, min_y))
        options.append(box(max_x - width, target.y, max_x, min_y))
    if target.x > max_x:
        options.append(box(max_x, min_y, target.x, min_y + width))
        options.append(box(max_x, max_y - width, target.x, max_y))
    if target.x < min_x:
        options.append(box(target.x, min_y, min_x, min_y + width))
        options.append(box(target.x, max_y - width, min_x, max_y))
    return tuple(
        option
        for option in options
        if option.is_valid and option.area > _TOLERANCE
    )


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
    *,
    minimum_exit_separation: float | None,
) -> tuple[
    tuple[tuple[Polygon, ...], ...],
    tuple[tuple[Polygon, ...], ...],
]:
    min_y = boundary.bounds[1]
    core_min_x, core_min_y, core_max_x, _ = core.bounds
    route_y = _clean(core_min_y - width)
    if route_y <= min_y + _TOLERANCE:
        return (), ()
    critical_origins = {
        core_min_x,
        core_min_x - width,
        core_max_x,
        core_max_x - width,
    }
    if minimum_exit_separation is not None:
        core_center_x = float(core.centroid.x)
        critical_origins.update(
            (
                core_min_x - minimum_exit_separation,
                core_max_x - minimum_exit_separation,
                core_center_x - minimum_exit_separation,
                core_min_x + minimum_exit_separation - width,
                core_max_x + minimum_exit_separation - width,
                core_center_x + minimum_exit_separation - width,
            )
        )
    origin_groups = _candidate_origin_groups(
        boundary,
        axis=0,
        extent=width,
        extra=critical_origins,
        bounded_auxiliary=True,
    )
    network_groups = []
    for origins in origin_groups:
        networks = []
        for trunk_x in origins:
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
        network_groups.append(tuple(networks))
    return tuple(network_groups)


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
        street_segments=street_segments,
        raise_on_empty_reserve=True,
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
    minimum_exit_separation: float | None = None,
    street_segments: tuple[tuple[Point, Point], ...] = (),
    raise_on_empty_reserve: bool = False,
) -> tuple[Polygon, ...]:
    free = boundary.difference(union_all((core, corridor)))
    if free.is_empty:
        if raise_on_empty_reserve:
            raise CirculationPlanningError(
                "circulation leaves no remote stair reserve"
            )
        return ()
    candidates: dict[tuple[float, ...], tuple[bool, Polygon]] = {}
    for stair_width, stair_length in stair_dimensions:
        target_x = _separation_origins(
            core,
            axis=0,
            extent=stair_width,
            minimum_exit_separation=minimum_exit_separation,
        )
        target_y = _separation_origins(
            core,
            axis=1,
            extent=stair_length,
            minimum_exit_separation=minimum_exit_separation,
        )
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
        if minimum_exit_separation is None:
            grid_x = _candidate_origins(
                free,
                axis=0,
                extent=stair_width,
                bounded_auxiliary=False,
            )
            grid_y = _candidate_origins(
                free,
                axis=1,
                extent=stair_length,
                bounded_auxiliary=False,
            )
            origin_groups = (
                {
                    *((x, y) for x in adjacent_x for y in grid_y),
                    *((x, y) for x in grid_x for y in adjacent_y),
                },
            )
        else:
            critical_x, auxiliary_x = _candidate_origin_groups(
                free,
                axis=0,
                extent=stair_width,
                extra=target_x,
                bounded_auxiliary=True,
            )
            critical_y, auxiliary_y = _candidate_origin_groups(
                free,
                axis=1,
                extent=stair_length,
                extra=target_y,
                bounded_auxiliary=True,
            )
            origin_groups = (
                {
                    *((x, y) for x in adjacent_x for y in critical_y),
                    *((x, y) for x in critical_x for y in adjacent_y),
                },
                {
                    *((x, y) for x in adjacent_x for y in auxiliary_y),
                    *((x, y) for x in auxiliary_x for y in adjacent_y),
                },
            )
        valid_origin_count = 0
        for priority, origins in enumerate(origin_groups):
            is_critical = priority == 0 and minimum_exit_separation is not None
            ranked_origins = sorted(
                origins,
                key=lambda origin: (
                    -math.dist(
                        (
                            origin[0] + stair_width / 2.0,
                            origin[1] + stair_length / 2.0,
                        ),
                        (float(core.centroid.x), float(core.centroid.y)),
                    ),
                    origin,
                ),
            )
            for x, y in ranked_origins:
                stair = box(x, y, x + stair_width, y + stair_length)
                if (
                    not free.covers(stair)
                    or stair.boundary.intersection(corridor.boundary).length
                    + _TOLERANCE
                    < _DOOR_WIDTH
                ):
                    continue
                previous = candidates.get(stair.bounds)
                candidates[stair.bounds] = (
                    is_critical or (previous[0] if previous is not None else False),
                    stair,
                )
                valid_origin_count += 1
                if (
                    minimum_exit_separation is not None
                    and valid_origin_count
                    == _MAX_REMOTE_STAIR_VALID_ORIGINS_PER_DIMENSION
                ):
                    break
            if (
                minimum_exit_separation is not None
                and valid_origin_count
                == _MAX_REMOTE_STAIR_VALID_ORIGINS_PER_DIMENSION
            ):
                break
    if minimum_exit_separation is None:
        street_lines = tuple(LineString(segment) for segment in street_segments)
        ranked_candidates = sorted(
            (item[1] for item in candidates.values()),
            key=lambda stair: (
                not any(
                    stair.boundary.intersection(line).length > _TOLERANCE
                    for line in street_lines
                ),
                stair.centroid.distance(core.centroid),
                tuple(-value for value in stair.bounds),
            ),
            reverse=True,
        )
        return tuple(sorted(ranked_candidates, key=lambda stair: stair.bounds))
    else:
        ranked_candidates = sorted(
            candidates.values(),
            key=lambda item: (
                not item[0],
                -item[1].centroid.distance(core.centroid),
                item[1].bounds,
            ),
        )
    selected = [
        item[1]
        for item in ranked_candidates[:_MAX_REMOTE_STAIR_CANDIDATES]
    ]
    return tuple(sorted(selected, key=lambda stair: stair.bounds))


def _maximum_doorway_separation(
    core: Polygon,
    corridor: Polygon,
    stair: Polygon,
) -> float:
    core_line = _longest_shared_line(core, corridor)
    stair_line = _longest_shared_line(stair, corridor)
    if core_line is None or stair_line is None:
        return 0.0
    separations = [
        segment_to_segment_distance(core_opening, stair_opening)
        for core_opening in _end_openings(core_line)
        for stair_opening in _end_openings(stair_line)
    ]
    # A shared edge too short to hold a doorway offers no separation to measure,
    # which is the same answer as sharing no edge at all.
    return max(separations, default=0.0)


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


def _grid_values(
    minimum: float,
    maximum: float,
    *,
    bounded: bool,
) -> tuple[float, ...]:
    if maximum < minimum - _TOLERANCE:
        return ()
    if not bounded:
        count = math.floor((maximum - minimum) / _GRID_STEP + _TOLERANCE)
        values = [minimum + index * _GRID_STEP for index in range(count + 1)]
        values.append(maximum)
        return tuple(sorted({_clean(value) for value in values}))
    span = maximum - minimum
    if span <= _TOLERANCE:
        return tuple(sorted({_clean(minimum), _clean(maximum)}))
    natural_interval_count = max(
        1,
        math.ceil(span / _GRID_STEP - _TOLERANCE),
    )
    interval_count = min(
        natural_interval_count,
        _MAX_AUXILIARY_INTERVALS_PER_AXIS,
    )
    if natural_interval_count <= _MAX_AUXILIARY_INTERVALS_PER_AXIS:
        values = [
            (
                minimum + index * _GRID_STEP
                if index < interval_count
                else maximum
            )
            for index in range(interval_count + 1)
        ]
    else:
        values = [
            (
                minimum
                if index == 0
                else maximum
                if index == interval_count
                else minimum + span * index / interval_count
            )
            for index in range(interval_count + 1)
        ]
    return tuple(sorted({_clean(value) for value in values}))


def _candidate_origins(
    shape,
    *,
    axis: int,
    extent: float,
    extra: Iterable[float] = (),
    bounded_auxiliary: bool = True,
) -> tuple[float, ...]:
    critical, auxiliary = _candidate_origin_groups(
        shape,
        axis=axis,
        extent=extent,
        extra=extra,
        bounded_auxiliary=bounded_auxiliary,
    )
    return tuple(sorted({*critical, *auxiliary}))


def _candidate_origin_groups(
    shape,
    *,
    axis: int,
    extent: float,
    extra: Iterable[float],
    bounded_auxiliary: bool,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    minimum = shape.bounds[axis]
    maximum = shape.bounds[axis + 2] - extent
    polygons = tuple(shape.geoms) if hasattr(shape, "geoms") else (shape,)
    edges = {
        float(coordinate[axis])
        for polygon in polygons
        for coordinate in polygon.exterior.coords
    }
    critical = {
        *(
            origin
            for edge in edges
            for origin in (edge, edge - extent)
            if minimum - _TOLERANCE <= origin <= maximum + _TOLERANCE
        ),
        *(
            float(origin)
            for origin in extra
            if minimum - _TOLERANCE
            <= float(origin)
            <= maximum + _TOLERANCE
        ),
    }
    auxiliary = set(
        _grid_values(
            minimum,
            maximum,
            bounded=bounded_auxiliary,
        )
    ).difference(critical)
    return tuple(sorted(critical)), tuple(sorted(auxiliary))


def _separation_origins(
    core: Polygon,
    *,
    axis: int,
    extent: float,
    minimum_exit_separation: float | None,
) -> tuple[float, ...]:
    if minimum_exit_separation is None:
        return ()
    minimum = core.bounds[axis]
    maximum = core.bounds[axis + 2]
    center = float(core.centroid.coords[0][axis])
    return tuple(
        coordinate + direction * minimum_exit_separation - offset
        for coordinate in (minimum, center, maximum)
        for direction in (-1.0, 1.0)
        for offset in (0.0, extent)
    )


def circulation_geometry_fingerprint(
    *,
    strategy: str,
    core_fingerprint: str | None,
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


_fingerprint = circulation_geometry_fingerprint


def _canonical_ring(points: Iterable[Point] | Polygon) -> tuple[Point, ...]:
    coordinates = (
        tuple((float(x), float(y)) for x, y in points.exterior.coords[:-1])
        if isinstance(points, Polygon)
        else _points(points)
    )
    # Corridor pieces are built along several paths, some of which already
    # round their origins. Two that meet flush could land a nanometre apart,
    # and then a cell behind the seam shared no boundary with any corridor at
    # all. Emitting on the shared grid keeps the seams closed.
    normalized = snap_ring(coordinates)
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
    return (snap_coordinate(point[0]), snap_coordinate(point[1]))


def _clean(value: float) -> float:
    return 0.0 if math.isclose(value, 0.0, abs_tol=_TOLERANCE) else round(value, 8)
