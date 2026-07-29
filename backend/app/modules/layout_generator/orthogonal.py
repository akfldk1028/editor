from __future__ import annotations

import math
from heapq import heappop, heappush
from typing import Iterable

from shapely import union_all
from shapely.geometry import LineString, MultiPolygon, Polygon, box
from shapely.prepared import prep

from backend.app.modules.basic_design.stair import (
    CONCEPT_DEFAULT_FLOOR_TO_FLOOR_HEIGHT_M,
    required_stair_enclosure,
)
from backend.app.modules.circulation_planner.contracts import CirculationCandidate
from backend.app.schemas.layout import (
    LayoutCandidate,
    OpeningSegment,
    RoomPolygon,
)
from backend.app.schemas.program import ProgramGraph, ProgramNode
from engine.geometry import shared_boundary_segments
from engine.geometry.orthogonal import orthogonal_rectangle_cells

Point = tuple[float, float]
_TOLERANCE = 1e-8
_DOOR_WIDTH = 0.9
_MIN_FURNISHED_FRONTAGE_DEPTH = 2.8


def generate_orthogonal_office_layout(
    boundary: Iterable[Point],
    program: ProgramGraph,
    *,
    core_polygon: Iterable[Point],
    remote_stair_polygon: Iterable[Point] | None = None,
    circulation_candidate: CirculationCandidate | None = None,
    frontage_segments: Iterable[tuple[Point, Point]] = (),
    min_circulation_width: float = 1.2,
    respect_program_order: bool = False,
) -> LayoutCandidate:
    """Generate a deterministic rectangular-cell layout for supported uses."""
    if program.use_type not in {"office", "neighborhood_commercial"}:
        raise ValueError("orthogonal layout requires a supported use program")
    if not math.isfinite(min_circulation_width) or min_circulation_width < 1.2:
        raise ValueError("minimum circulation width must be finite and at least 1.2")
    if circulation_candidate is not None and remote_stair_polygon is not None:
        raise ValueError("remote_stair_polygon conflicts with circulation_candidate")
    boundary_points = tuple((float(x), float(y)) for x, y in boundary)
    frontage_segments = tuple(
        (
            (float(start[0]), float(start[1])),
            (float(end[0]), float(end[1])),
        )
        for start, end in frontage_segments
    )
    boundary_shape = Polygon(boundary_points)
    core_points = tuple((float(x), float(y)) for x, y in core_polygon)
    core_shape = Polygon(core_points)
    _validate_rectangular_core(
        boundary_shape,
        core_shape,
        core_points,
        allow_tolerance=circulation_candidate is not None,
    )
    core_nodes = [node for node in program.nodes if node.space_type == "core"]
    if len(core_nodes) != 1:
        raise ValueError("orthogonal program requires exactly one core node")

    if circulation_candidate is None:
        cells = orthogonal_rectangle_cells(boundary_points)
        corridor_shape = _corridor_network(
            boundary_shape,
            cells,
            core_shape,
            min_circulation_width,
        )
        circulation_rectangles = _rectangle_cells(corridor_shape)
        fixed_remote_stair = (
            Polygon(tuple((float(x), float(y)) for x, y in remote_stair_polygon))
            if remote_stair_polygon is not None
            else None
        )
    else:
        circulation_rectangles = circulation_candidate.polygons
        corridor_shape = union_all(
            [Polygon(polygon) for polygon in circulation_candidate.polygons]
        )
        fixed_remote_stair = Polygon(circulation_candidate.remote_stair_polygon)
    circulation = [
        RoomPolygon(
            room_id=f"corridor-{index:03d}",
            space_type="circulation",
            polygon=list(rectangle),
        )
        for index, rectangle in enumerate(circulation_rectangles, start=1)
    ]
    if fixed_remote_stair is not None:
        _validate_remote_stair(
            boundary_shape,
            core_shape,
            fixed_remote_stair,
            circulation,
            allow_tolerant_adjacency=circulation_candidate is not None,
        )
    free_shape = boundary_shape.difference(
        union_all(
            [
                core_shape,
                corridor_shape,
                *([fixed_remote_stair] if fixed_remote_stair is not None else []),
            ]
        )
    )
    non_core_nodes = [node for node in program.nodes if node.space_type != "core"]
    minimum_room_width = min(
        max(float(node.min_width or 0), 1.1) for node in non_core_nodes
    )
    available = [
        rectangle
        for rectangle in _rectangle_cells(
            free_shape,
            require_complete=circulation_candidate is None,
        )
        if (
            _longest_shared_edge(rectangle, circulation) >= _DOOR_WIDTH
            and min(
                _bounds(rectangle)[2] - _bounds(rectangle)[0],
                _bounds(rectangle)[3] - _bounds(rectangle)[1],
            )
            >= minimum_room_width
        )
    ]
    if frontage_segments:
        available = _coalesce_frontage_rectangles(
            available,
            circulation,
            frontage_segments=frontage_segments,
        )
    available = _subdivide_accessible_rectangles(
        available,
        circulation,
        required_count=len(non_core_nodes) + 1,
        frontage_segments=frontage_segments,
        frontage_required_count=(
            sum(node.frontage_required for node in non_core_nodes)
            if frontage_segments
            else 0
        ),
        frontage_min_width=min(
            _MIN_FURNISHED_FRONTAGE_DEPTH,
            max(
                (
                    float(node.min_width or 0)
                    for node in non_core_nodes
                    if node.frontage_required
                ),
                default=0.0,
            ),
        ),
    )
    if fixed_remote_stair is None:
        remote_stair, available = _reserve_remote_stair(
            available,
            circulation,
            core_shape,
            frontage_segments=frontage_segments,
        )
    else:
        remote_stair = (
            circulation_candidate.remote_stair_polygon
            if circulation_candidate is not None
            else _canonical_rectangle(fixed_remote_stair.bounds)
        )
    assignments = _assign_rectangles(
        non_core_nodes,
        available,
        frontage_segments=frontage_segments,
        respect_program_order=respect_program_order,
    )
    if circulation_candidate is not None:
        assignments = _absorb_residual_cells(
            assignments,
            free_shape=free_shape,
        )
    rooms = [
        RoomPolygon(
            room_id=core_nodes[0].node_id,
            space_type=core_nodes[0].space_type,
            polygon=list(
                core_points
                if circulation_candidate is not None
                else _canonical_rectangle(core_shape.bounds)
            ),
        ),
        *[
            RoomPolygon(
                room_id=node.node_id,
                space_type=node.space_type,
                polygon=list(rectangle),
            )
            for node, rectangle in assignments
        ],
    ]
    openings = [_centered_opening(room, circulation) for room in rooms]
    return LayoutCandidate(
        candidate_id=(f"{program.project_id}-f{program.floor_index}-orthogonal-cells"),
        project_id=program.project_id,
        floor_index=program.floor_index,
        rooms=rooms,
        circulation=circulation,
        score=0.0,
        openings=openings,
        remote_stair_footprint=remote_stair,
    )


def _corridor_network(
    boundary: Polygon,
    cells,
    core: Polygon,
    width: float,
) -> Polygon:
    min_x, min_y, max_x, max_y = boundary.bounds
    core_min_x, core_min_y, core_max_x, core_max_y = core.bounds
    t_networks = (
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
    for vertical, horizontal in t_networks:
        network = (
            union_all((vertical, horizontal)).intersection(boundary).difference(core)
        )
        if (
            isinstance(network, Polygon)
            and not network.is_empty
            and network.boundary.intersection(core.boundary).length >= _DOOR_WIDTH
        ):
            return network

    cell_shapes = [Polygon(cell) for cell in cells]
    half = width / 2
    pieces = []
    for cell in cell_shapes:
        min_x, min_y, max_x, max_y = cell.bounds
        if min(max_x - min_x, max_y - min_y) + _TOLERANCE < width:
            raise ValueError("orthogonal footprint cell is narrower than circulation")
        center_x = (min_x + max_x) / 2
        center_y = (min_y + max_y) / 2
        pieces.extend(
            (
                box(min_x, center_y - half, max_x, center_y + half),
                box(center_x - half, min_y, center_x + half, max_y),
            )
        )
    for left_index, left in enumerate(cell_shapes):
        for right in cell_shapes[left_index + 1 :]:
            shared = left.boundary.intersection(right.boundary)
            if shared.is_empty or shared.length <= _TOLERANCE:
                continue
            midpoint = shared.interpolate(0.5, normalized=True)
            for cell in (left, right):
                center = cell.centroid
                route = LineString(
                    (
                        (center.x, center.y),
                        (center.x, midpoint.y),
                        (midpoint.x, midpoint.y),
                    )
                )
                pieces.append(
                    route.buffer(
                        half,
                        cap_style="square",
                        join_style="mitre",
                    ).intersection(cell)
                )
    core_ring = core.buffer(
        width,
        cap_style="square",
        join_style="mitre",
    ).difference(core)
    network = union_all([*pieces, core_ring]).intersection(boundary)
    network = network.difference(core)
    if not isinstance(network, Polygon) or network.is_empty:
        raise ValueError("circulation network must be one connected polygon")
    if network.boundary.intersection(core.boundary).length < _DOOR_WIDTH:
        raise ValueError("circulation network does not provide core access")
    return network


def _rectangle_cells(
    shape,
    *,
    require_complete: bool = True,
    preserve_precision: bool = False,
) -> tuple[tuple[Point, ...], ...]:
    if shape.is_empty:
        return ()
    polygons = tuple(shape.geoms) if isinstance(shape, MultiPolygon) else (shape,)
    if any(not isinstance(polygon, Polygon) for polygon in polygons):
        raise ValueError("layout residual must contain polygonal regions")
    prepared_shape = prep(shape)
    xs = sorted(
        {
            float(x)
            for polygon in polygons
            for ring in (polygon.exterior, *polygon.interiors)
            for x, _ in ring.coords
        }
    )
    ys = sorted(
        {
            float(y)
            for polygon in polygons
            for ring in (polygon.exterior, *polygon.interiors)
            for _, y in ring.coords
        }
    )
    rectangles = []
    for min_x, max_x in zip(xs, xs[1:]):
        for min_y, max_y in zip(ys, ys[1:]):
            if max_x - min_x <= _TOLERANCE or max_y - min_y <= _TOLERANCE:
                continue
            candidate = box(min_x, min_y, max_x, max_y)
            if prepared_shape.covers(candidate):
                rectangles.append(
                    _canonical_rectangle(
                        candidate.bounds,
                        preserve_precision=preserve_precision,
                    )
                )
    covered = union_all([Polygon(item) for item in rectangles])
    if (
        require_complete
        and rectangles
        and shape.symmetric_difference(covered).area > _TOLERANCE
    ):
        raise ValueError("rectangular decomposition lost layout area")
    return tuple(sorted(rectangles, key=_rectangle_sort_key))


def _assign_rectangles(
    nodes: list[ProgramNode],
    rectangles: list[tuple[Point, ...]],
    *,
    frontage_segments: tuple[tuple[Point, Point], ...] = (),
    respect_program_order: bool = False,
) -> list[tuple[ProgramNode, tuple[Point, ...]]]:
    if len(rectangles) < len(nodes):
        raise ValueError(
            "orthogonal footprint leaves too few accessible room rectangles"
        )
    remaining = list(rectangles)
    support_types = {"pantry", "restroom", "it_storage"}
    input_order = {node.node_id: index for index, node in enumerate(nodes)}
    ordered_nodes = sorted(
        nodes,
        key=lambda node: (
            (
                0
                if node.space_type == "open_work"
                or (frontage_segments and node.frontage_required)
                else 1
                if node.space_type in support_types
                else 2
            ),
            (
                input_order[node.node_id]
                if respect_program_order
                else -float(node.target_area)
            ),
            "" if respect_program_order else node.node_id,
        ),
    )
    assignments = []
    support_centers = []
    for node in ordered_nodes:
        enforce_frontage = bool(frontage_segments) and node.frontage_required
        frontage_options = (
            [
                rectangle
                for rectangle in remaining
                if _touches_frontage(rectangle, frontage_segments)
            ]
            if enforce_frontage
            else []
        )
        if enforce_frontage and not frontage_options:
            raise ValueError(
                f"orthogonal layout cannot place frontage room {node.node_id}"
            )
        candidates = frontage_options or remaining
        width_compliant = [
            rectangle
            for rectangle in candidates
            if min(
                _bounds(rectangle)[2] - _bounds(rectangle)[0],
                _bounds(rectangle)[3] - _bounds(rectangle)[1],
            )
            + _TOLERANCE
            >= float(node.min_width or 0)
        ]
        candidates = width_compliant or candidates
        if node.space_type == "open_work":
            chosen = max(
                candidates,
                key=lambda rectangle: (
                    Polygon(rectangle).area,
                    tuple(-value for value in _rectangle_sort_key(rectangle)),
                ),
            )
        elif node.space_type in support_types and support_centers:
            anchor_x = sum(point[0] for point in support_centers) / len(support_centers)
            anchor_y = sum(point[1] for point in support_centers) / len(support_centers)
            chosen = min(
                candidates,
                key=lambda rectangle: (
                    math.dist(
                        (
                            Polygon(rectangle).centroid.x,
                            Polygon(rectangle).centroid.y,
                        ),
                        (anchor_x, anchor_y),
                    ),
                    _room_fit_score(node, rectangle),
                ),
            )
        else:
            chosen = min(
                candidates,
                key=lambda rectangle: _room_fit_score(node, rectangle),
            )
        remaining.remove(chosen)
        assignments.append((node, chosen))
        if node.space_type in support_types:
            center = Polygon(chosen).centroid
            support_centers.append((center.x, center.y))
    return sorted(assignments, key=lambda item: item[0].node_id)


def _absorb_residual_cells(
    assignments: list[tuple[ProgramNode, tuple[Point, ...]]],
    *,
    free_shape,
) -> list[tuple[ProgramNode, tuple[Point, ...]]]:
    """Grow accessible program seeds across the fixed-circulation free cells."""
    shapes = {
        node.node_id: Polygon(polygon)
        for node, polygon in assignments
    }
    nodes = {node.node_id: node for node, _ in assignments}
    assigned = union_all(tuple(shapes.values()))
    residual_cells = [
        Polygon(cell)
        for cell in _rectangle_cells(
            free_shape.difference(assigned),
            require_complete=False,
            preserve_precision=True,
        )
    ]
    primary_types = {"open_work", "sales"}
    residual_count = len(residual_cells)
    room_ids = tuple(sorted(shapes))
    rectangle_bounds = (
        *(cell.bounds for cell in residual_cells),
        *(shapes[room_id].bounds for room_id in room_ids),
    )
    neighbors: list[list[tuple[int, float]]] = [[] for _ in residual_cells]
    frontier = []
    for left_index, right_index, shared_length in _rectangle_adjacencies(
        rectangle_bounds
    ):
        if right_index < residual_count:
            neighbors[left_index].append((right_index, shared_length))
            neighbors[right_index].append((left_index, shared_length))
            continue
        if left_index >= residual_count:
            continue
        cell_index = left_index
        room_id = room_ids[right_index - residual_count]
        node = nodes[room_id]
        cell = residual_cells[cell_index]
        heappush(
            frontier,
            (
                1,
                0 if node.space_type in primary_types else 1,
                -shared_length,
                room_id,
                cell.bounds,
                cell_index,
            ),
        )
    for cell_neighbors in neighbors:
        cell_neighbors.sort(key=lambda item: item[0])

    absorbed: set[int] = set()
    while frontier:
        distance, _, _, room_id, _, cell_index = heappop(frontier)
        if cell_index in absorbed:
            continue
        cell = residual_cells[cell_index]
        combined = shapes[room_id].union(cell)
        if (
            not isinstance(combined, Polygon)
            or not combined.is_valid
            or combined.interiors
        ):
            continue
        shapes[room_id] = combined
        absorbed.add(cell_index)
        node = nodes[room_id]
        for neighbor_index, shared_length in neighbors[cell_index]:
            if neighbor_index in absorbed:
                continue
            heappush(
                frontier,
                (
                    distance + 1,
                    0 if node.space_type in primary_types else 1,
                    -shared_length,
                    room_id,
                    residual_cells[neighbor_index].bounds,
                    neighbor_index,
                ),
            )

    return [
        (node, _polygon_ring(shapes[node.node_id]))
        for node, _ in assignments
    ]


def _rectangle_adjacencies(
    rectangles: Iterable[tuple[float, float, float, float]],
) -> tuple[tuple[int, int, float], ...]:
    vertical_left: dict[float, list[tuple[float, float, int]]] = {}
    vertical_right: dict[float, list[tuple[float, float, int]]] = {}
    horizontal_bottom: dict[float, list[tuple[float, float, int]]] = {}
    horizontal_top: dict[float, list[tuple[float, float, int]]] = {}
    for index, (min_x, min_y, max_x, max_y) in enumerate(rectangles):
        vertical_left.setdefault(min_x, []).append((min_y, max_y, index))
        vertical_right.setdefault(max_x, []).append((min_y, max_y, index))
        horizontal_bottom.setdefault(min_y, []).append((min_x, max_x, index))
        horizontal_top.setdefault(max_y, []).append((min_x, max_x, index))

    shared_by_pair: dict[tuple[int, int], float] = {}
    edge_groups = (
        (vertical_right, vertical_left),
        (horizontal_top, horizontal_bottom),
    )
    for ending_edges, starting_edges in edge_groups:
        for coordinate in sorted(ending_edges.keys() & starting_edges.keys()):
            for left_index, right_index, shared_length in _sweep_edge_intervals(
                ending_edges[coordinate],
                starting_edges[coordinate],
            ):
                if left_index == right_index:
                    continue
                pair = (
                    min(left_index, right_index),
                    max(left_index, right_index),
                )
                shared_by_pair[pair] = (
                    shared_by_pair.get(pair, 0.0) + shared_length
                )
    return tuple(
        (left_index, right_index, shared_by_pair[(left_index, right_index)])
        for left_index, right_index in sorted(shared_by_pair)
    )


def _sweep_edge_intervals(
    ending_edges: Iterable[tuple[float, float, int]],
    starting_edges: Iterable[tuple[float, float, int]],
) -> Iterable[tuple[int, int, float]]:
    ending = sorted(ending_edges)
    starting = sorted(starting_edges)
    ending_index = 0
    starting_index = 0
    while ending_index < len(ending) and starting_index < len(starting):
        ending_start, ending_end, ending_rectangle = ending[ending_index]
        starting_start, starting_end, starting_rectangle = starting[
            starting_index
        ]
        shared_length = _edge_overlap_length(
            ending_start,
            ending_end,
            starting_start,
            starting_end,
        )
        if shared_length > _TOLERANCE:
            yield ending_rectangle, starting_rectangle, shared_length
        if ending_end < starting_end:
            ending_index += 1
        elif starting_end < ending_end:
            starting_index += 1
        else:
            ending_index += 1
            starting_index += 1


def _edge_overlap_length(
    left_start: float,
    left_end: float,
    right_start: float,
    right_end: float,
) -> float:
    return max(0.0, min(left_end, right_end) - max(left_start, right_start))


def _polygon_ring(polygon: Polygon) -> tuple[Point, ...]:
    return tuple(
        (float(x), float(y))
        for x, y in tuple(polygon.exterior.coords)[:-1]
    )


def _touches_frontage(
    rectangle: tuple[Point, ...],
    frontage_segments: tuple[tuple[Point, Point], ...],
) -> bool:
    room_boundary = Polygon(rectangle).boundary
    return any(
        room_boundary.intersection(LineString(segment)).length + _TOLERANCE
        >= _DOOR_WIDTH
        for segment in frontage_segments
    )


def _coalesce_frontage_rectangles(
    rectangles: list[tuple[Point, ...]],
    circulation: list[RoomPolygon],
    *,
    frontage_segments: tuple[tuple[Point, Point], ...],
) -> list[tuple[Point, ...]]:
    result = list(rectangles)
    while True:
        merged = None
        for left_index, left in enumerate(result):
            if not _touches_frontage(left, frontage_segments):
                continue
            left_shape = Polygon(left)
            for right in result[left_index + 1 :]:
                combined = left_shape.union(Polygon(right))
                if (
                    not isinstance(combined, Polygon)
                    or not math.isclose(
                        combined.area,
                        box(*combined.bounds).area,
                        abs_tol=_TOLERANCE,
                    )
                ):
                    continue
                candidate = _canonical_rectangle(combined.bounds)
                if _longest_shared_edge(candidate, circulation) < _DOOR_WIDTH:
                    continue
                merged = (left, right, candidate)
                break
            if merged is not None:
                break
        if merged is None:
            return sorted(result, key=_rectangle_sort_key)
        left, right, candidate = merged
        result.remove(left)
        result.remove(right)
        result.append(candidate)


def _subdivide_accessible_rectangles(
    rectangles: list[tuple[Point, ...]],
    circulation: list[RoomPolygon],
    *,
    required_count: int,
    frontage_segments: tuple[tuple[Point, Point], ...] = (),
    frontage_required_count: int = 0,
    frontage_min_width: float = 0.0,
) -> list[tuple[Point, ...]]:
    result = list(rectangles)
    while len(result) < required_count:
        options = []
        for rectangle in result:
            shared = [
                segment
                for path in circulation
                for segment in shared_boundary_segments(
                    rectangle,
                    path.polygon,
                )
                if math.dist(*segment) >= _DOOR_WIDTH * 2
            ]
            if not shared:
                continue
            segment = max(shared, key=lambda item: (math.dist(*item), item))
            min_x, min_y, max_x, max_y = _bounds(rectangle)
            if math.isclose(segment[0][1], segment[1][1], abs_tol=_TOLERANCE):
                middle = (min_x + max_x) / 2
                pieces = (
                    _canonical_rectangle((min_x, min_y, middle, max_y)),
                    _canonical_rectangle((middle, min_y, max_x, max_y)),
                )
            else:
                middle = (min_y + max_y) / 2
                pieces = (
                    _canonical_rectangle((min_x, min_y, max_x, middle)),
                    _canonical_rectangle((min_x, middle, max_x, max_y)),
                )
            if all(
                _longest_shared_edge(piece, circulation) >= _DOOR_WIDTH
                for piece in pieces
            ):
                next_rectangles = [
                    item for item in result if item != rectangle
                ] + list(pieces)
                if (
                    _frontage_capacity(
                        next_rectangles,
                        frontage_segments=frontage_segments,
                        minimum_width=frontage_min_width,
                    )
                    < frontage_required_count
                ):
                    continue
                options.append(
                    (
                        Polygon(rectangle).area,
                        _rectangle_sort_key(rectangle),
                        rectangle,
                        pieces,
                    )
                )
        if not options:
            break
        _, _, selected, pieces = max(options)
        result.remove(selected)
        result.extend(pieces)
    return sorted(result, key=_rectangle_sort_key)


def _frontage_capacity(
    rectangles: list[tuple[Point, ...]],
    *,
    frontage_segments: tuple[tuple[Point, Point], ...],
    minimum_width: float,
) -> int:
    return sum(
        _touches_frontage(rectangle, frontage_segments)
        and min(
            _bounds(rectangle)[2] - _bounds(rectangle)[0],
            _bounds(rectangle)[3] - _bounds(rectangle)[1],
        )
        + _TOLERANCE
        >= minimum_width
        for rectangle in rectangles
    )


def _reserve_remote_stair(
    rectangles: list[tuple[Point, ...]],
    circulation: list[RoomPolygon],
    core: Polygon,
    *,
    frontage_segments: tuple[tuple[Point, Point], ...] = (),
) -> tuple[
    tuple[Point, ...],
    list[tuple[Point, ...]],
]:
    required_width, required_length = required_stair_enclosure(
        CONCEPT_DEFAULT_FLOOR_TO_FLOOR_HEIGHT_M
    )
    feasible = []
    for rectangle in rectangles:
        min_x, min_y, max_x, max_y = _bounds(rectangle)
        dimensions = sorted((max_x - min_x, max_y - min_y))
        if (
            dimensions[0] + _TOLERANCE >= required_width
            and dimensions[1] + _TOLERANCE >= required_length
            and _longest_shared_edge(rectangle, circulation) >= _DOOR_WIDTH
        ):
            feasible.append(rectangle)
    if not feasible:
        raise ValueError(
            "orthogonal footprint leaves no accessible remote stair reserve"
        )
    selected = max(
        feasible,
        key=lambda rectangle: (
            not _touches_frontage(rectangle, frontage_segments),
            Polygon(rectangle).centroid.distance(core.centroid),
            -Polygon(rectangle).area,
            tuple(-value for value in _rectangle_sort_key(rectangle)),
        ),
    )
    min_x, min_y, max_x, max_y = _bounds(selected)
    stair_options = []
    for width, length in {
        (required_width, required_length),
        (required_length, required_width),
    }:
        if width > max_x - min_x or length > max_y - min_y:
            continue
        stair_options.extend(
            (
                box(min_x, min_y, min_x + width, min_y + length),
                box(max_x - width, min_y, max_x, min_y + length),
                box(min_x, max_y - length, min_x + width, max_y),
                box(max_x - width, max_y - length, max_x, max_y),
            )
        )
    accessible_stair_options = [
        candidate
        for candidate in stair_options
        if _longest_shared_edge(
            _canonical_rectangle(candidate.bounds),
            circulation,
        )
        >= _DOOR_WIDTH
    ]
    if not accessible_stair_options:
        raise ValueError("remote stair reserve cannot retain circulation access")
    stair_shape = max(
        accessible_stair_options,
        key=lambda candidate: (
            max(
                (
                    Polygon(rectangle).area
                    for rectangle in _rectangle_cells(
                        Polygon(selected).difference(candidate)
                    )
                    if _longest_shared_edge(rectangle, circulation) >= _DOOR_WIDTH
                ),
                default=0.0,
            ),
            candidate.centroid.distance(core.centroid),
            candidate.bounds,
        ),
    )
    remaining = list(rectangles)
    remaining.remove(selected)
    residual = Polygon(selected).difference(stair_shape)
    largest_residual = _largest_accessible_rectangle(
        residual,
        circulation,
    )
    if largest_residual is not None:
        remaining.append(largest_residual)
    else:
        remaining.extend(
            rectangle
            for rectangle in _rectangle_cells(residual)
            if _longest_shared_edge(rectangle, circulation) >= _DOOR_WIDTH
        )
    return _canonical_rectangle(stair_shape.bounds), sorted(
        remaining,
        key=_rectangle_sort_key,
    )


def _largest_accessible_rectangle(
    shape,
    circulation: list[RoomPolygon],
) -> tuple[Point, ...] | None:
    if shape.is_empty:
        return None
    polygons = tuple(shape.geoms) if isinstance(shape, MultiPolygon) else (shape,)
    candidates = []
    for polygon in polygons:
        xs = sorted({float(x) for x, _ in polygon.exterior.coords})
        ys = sorted({float(y) for _, y in polygon.exterior.coords})
        for x_index, min_x in enumerate(xs[:-1]):
            for max_x in xs[x_index + 1 :]:
                for y_index, min_y in enumerate(ys[:-1]):
                    for max_y in ys[y_index + 1 :]:
                        candidate = _canonical_rectangle((min_x, min_y, max_x, max_y))
                        candidate_shape = Polygon(candidate)
                        if (
                            polygon.covers(candidate_shape)
                            and _longest_shared_edge(candidate, circulation)
                            >= _DOOR_WIDTH
                        ):
                            candidates.append(candidate)
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda candidate: (
            Polygon(candidate).area,
            tuple(-value for value in _rectangle_sort_key(candidate)),
        ),
    )


def _room_fit_score(
    node: ProgramNode,
    rectangle: tuple[Point, ...],
) -> tuple[float, float, float, tuple[float, ...]]:
    min_x, min_y, max_x, max_y = _bounds(rectangle)
    width = max_x - min_x
    depth = max_y - min_y
    area = width * depth
    minimum_width = min(width, depth)
    aspect = max(width, depth) / minimum_width
    width_penalty = max(0.0, float(node.min_width or 0) - minimum_width)
    aspect_penalty = max(
        0.0,
        aspect - float(node.max_aspect_ratio or math.inf),
    )
    area_error = abs(area - float(node.target_area))
    return (
        width_penalty,
        aspect_penalty,
        area_error,
        (min_x, min_y, max_x, max_y),
    )


def _centered_opening(
    room: RoomPolygon,
    circulation: list[RoomPolygon],
) -> OpeningSegment:
    choices = [
        (segment, path.room_id)
        for path in circulation
        for segment in shared_boundary_segments(
            room.polygon,
            path.polygon,
        )
        if math.dist(*segment) + _TOLERANCE >= _DOOR_WIDTH
    ]
    if not choices:
        raise ValueError(f"room '{room.room_id}' has no door-width circulation edge")
    segment, path_id = max(
        choices,
        key=lambda item: (
            math.dist(*item[0]),
            item[1],
            item[0],
        ),
    )
    start, end = segment
    length = math.dist(start, end)
    start_ratio = (length - _DOOR_WIDTH) / (2 * length)
    end_ratio = 1 - start_ratio
    door_start = _interpolate(start, end, start_ratio)
    door_end = _interpolate(start, end, end_ratio)
    return OpeningSegment(
        opening_id=f"{room.room_id}-door",
        kind="door",
        connects=(room.room_id, path_id),
        start=door_start,
        end=door_end,
        clear_width=_DOOR_WIDTH,
    )


def _longest_shared_edge(
    rectangle: tuple[Point, ...],
    circulation: list[RoomPolygon],
) -> float:
    return max(
        (
            math.dist(*segment)
            for path in circulation
            for segment in shared_boundary_segments(
                rectangle,
                path.polygon,
            )
        ),
        default=0.0,
    )


def _validate_rectangular_core(
    boundary: Polygon,
    core: Polygon,
    points: tuple[Point, ...],
    *,
    allow_tolerance: bool = False,
) -> None:
    if not core.is_valid or core.area <= _TOLERANCE:
        raise ValueError("core must be a valid positive-area polygon")
    expected = Polygon(_canonical_rectangle(core.bounds))
    is_rectangular = (
        core.symmetric_difference(expected).area <= _TOLERANCE
        if allow_tolerance
        else core.equals(expected)
    )
    if len(points) != 4 or not is_rectangular:
        raise ValueError("core must be an axis-aligned rectangle")
    if not boundary.covers(core):
        raise ValueError("core must be inside the floor footprint")


def _validate_remote_stair(
    boundary: Polygon,
    core: Polygon,
    remote_stair: Polygon,
    circulation: list[RoomPolygon],
    *,
    allow_tolerant_adjacency: bool = False,
) -> None:
    expected = Polygon(_canonical_rectangle(remote_stair.bounds))
    required_width, required_length = required_stair_enclosure(
        CONCEPT_DEFAULT_FLOOR_TO_FLOOR_HEIGHT_M
    )
    dimensions = sorted(
        (
            remote_stair.bounds[2] - remote_stair.bounds[0],
            remote_stair.bounds[3] - remote_stair.bounds[1],
        )
    )
    if remote_stair.symmetric_difference(expected).area > _TOLERANCE:
        raise ValueError("remote stair must be an axis-aligned rectangle")
    if (
        dimensions[0] + _TOLERANCE < required_width
        or dimensions[1] + _TOLERANCE < required_length
    ):
        raise ValueError("remote stair is smaller than the required enclosure")
    if not boundary.covers(remote_stair) or remote_stair.intersects(core):
        raise ValueError("remote stair must be inside the floor and outside core")
    shared_edge = _longest_shared_edge(
        _canonical_rectangle(remote_stair.bounds),
        circulation,
    )
    if allow_tolerant_adjacency:
        shared_edge = max(
            shared_edge,
            _tolerant_shared_boundary_length(remote_stair, circulation),
        )
    if shared_edge < _DOOR_WIDTH:
        raise ValueError("remote stair must share a circulation boundary")


def _tolerant_shared_boundary_length(
    polygon: Polygon,
    circulation: list[RoomPolygon],
) -> float:
    return max(
        (
            polygon.boundary.buffer(_TOLERANCE).intersection(
                Polygon(path.polygon).boundary
            ).length
            for path in circulation
        ),
        default=0.0,
    )


def _canonical_rectangle(
    bounds,
    *,
    preserve_precision: bool = False,
) -> tuple[Point, ...]:
    min_x, min_y, max_x, max_y = bounds
    coordinate = float if preserve_precision else _clean
    return (
        (coordinate(min_x), coordinate(min_y)),
        (coordinate(max_x), coordinate(min_y)),
        (coordinate(max_x), coordinate(max_y)),
        (coordinate(min_x), coordinate(max_y)),
    )


def _rectangle_sort_key(
    rectangle: tuple[Point, ...],
) -> tuple[float, ...]:
    return _bounds(rectangle)


def _bounds(points: Iterable[Point]) -> tuple[float, float, float, float]:
    vertices = tuple(points)
    return (
        min(point[0] for point in vertices),
        min(point[1] for point in vertices),
        max(point[0] for point in vertices),
        max(point[1] for point in vertices),
    )


def _interpolate(
    start: Point,
    end: Point,
    ratio: float,
) -> Point:
    return (
        (
            start[0]
            if start[0] == end[0]
            else _clean(start[0] + (end[0] - start[0]) * ratio)
        ),
        (
            start[1]
            if start[1] == end[1]
            else _clean(start[1] + (end[1] - start[1]) * ratio)
        ),
    )


def _clean(value: float) -> float:
    cleaned = round(float(value), 9)
    return 0.0 if cleaned == 0 else cleaned
