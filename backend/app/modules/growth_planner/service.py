"""Growth strategy: rooms grown on a grid from zone-placed seeds, gated like the validator.

The floor's structure -- cover, corridor spine, core, stacked stair -- is
planned first (``topology_planner.structure``); this solver only partitions
what is left.  Rooms other than the primary start as blocks at seeds chosen
from their zone (beside the core, on the street edge, across the corridor)
and grow as rectangles (MANSION / ProcTHOR growth, vendored); the primary
takes every cell nothing else claimed.  Each trial is checked against the
same gates the validator applies -- area band, minimum width, aspect ratio,
door-width corridor contact, wet rooms on the core, support clustering,
frontage -- and the survivors are ranked by MANSION's energy (area error,
extra corners, exterior wall contact).  Nothing is relaxed: with no survivor
the solver raises.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
from shapely.geometry import MultiPolygon, Polygon, box

from backend.app.modules.growth_planner.vendor.grid import (
    FREE_CELL,
    cells_to_polygons,
    rectilinear_lines,
    region_to_cells,
)
from backend.app.modules.growth_planner.vendor.mansion_growth import (
    RoomInfo,
    expand_rooms,
    fill_holes_components,
)
from backend.app.modules.layout_generator.orthogonal import _centered_opening, _without_collinear_vertices
from backend.app.modules.topology_planner.dimensioning import TopologyInfeasible
from backend.app.modules.topology_planner.graph import (
    CORRIDOR,
    WET_SERVICE_TYPES,
    build_adjacency_graph,
)
from backend.app.modules.topology_planner.service import (
    _coords,
    _open_rectilinear,
    _ring,
    _shares_door,
    _supports_clustered,
    _verify_adjacency,
)
from backend.app.modules.topology_planner.structure import FloorStructure, plan_floor_structure
from backend.app.schemas.layout import LayoutCandidate, Point, RoomPolygon
from backend.app.schemas.program import ProgramGraph, ProgramNode
from backend.engine.geometry.access import bounding_box_aspect_ratio, orthogonal_min_width
from backend.engine.geometry.polygon import shared_boundary_with_segments_length

_EPS = 1e-6
_CORE_SIDE_ZONES = frozenset({"service", "core"})
# Grid ids below zero block growth; these two are released to the primary
# afterwards: the corridor beyond the last room and the wrap zone past it.
_CORRIDOR_CELL = -2
_WRAP_CELL = -3
# MANSION's energy weights (seed_energy.DEFAULT_WEIGHTS); the seed term is
# dropped because seeds here are zones, not proposed centroids.
_W_RATIO, _W_CORNER, _W_WALL = 6.0, 3.0, 0.8


@dataclass(frozen=True)
class _Cells:
    """Per-cell facts about the free region, computed once per floor."""

    interior: np.ndarray
    area: np.ndarray
    xs: np.ndarray
    ys: np.ndarray
    touches_corridor: np.ndarray
    touches_core: np.ndarray
    touches_street: np.ndarray
    core_side: np.ndarray


def generate_growth_layout(
    boundary: Iterable[Point],
    program: ProgramGraph,
    *,
    core_polygon: Iterable[Point],
    corridor_width: float = 1.6,
    stair_dimensions: tuple[float, float] | None = None,
    stair_footprint: tuple[float, float, float, float] | None = None,
    street_segments: Iterable[tuple[Point, Point]] = (),
    grid_size: float = 0.5,
    trials: int = 64,
    seed: int = 0,
) -> LayoutCandidate:
    primary_node = next(node for node in program.nodes if node.node_id in ("open_work", "sales"))
    structure = plan_floor_structure(
        boundary, program, core_polygon=core_polygon, corridor_width=corridor_width,
        stair_dimensions=stair_dimensions, stair_footprint=stair_footprint,
        # The stair stops short of the far end so the primary can wrap around
        # the corridor there and be one room on both sides of it.
        stair_inset=float(primary_node.min_width or 0.0),
    )
    graph = build_adjacency_graph(program)
    streets = [((float(a[0]), float(a[1])), (float(b[0]), float(b[1]))) for a, b in street_segments]
    primary = structure.primary
    core_node = next(node for node in program.nodes if node.space_type == "core")
    others = [node for node in program.nodes if node.node_id not in (primary.node_id, core_node.node_id)]
    must_touch_core = {
        node.node_id for node in others if frozenset({node.node_id, core_node.node_id}) in graph.required
    }
    # Rooms bound to the core seed first (their zone is a few cells), then
    # the largest rooms, so each claims its span before smaller ones.
    growers = sorted(others, key=lambda node: (node.node_id not in must_touch_core, -float(node.target_area)))

    # The grid runs through every edge of the structure -- outline, spine,
    # core, stair -- with cells no larger than grid_size in between, so a
    # room made of cells meets the corridor and the core exactly.
    anchors_x, anchors_y = _anchors(structure)
    xs = rectilinear_lines(anchors_x, grid_size)
    ys = rectilinear_lines(anchors_y, grid_size)
    # The corridor stays on the grid, blocked for growth and released to the
    # primary beyond the last room it serves (the wrap-around).
    region = structure.cover.difference(structure.core)
    if structure.stair is not None:
        region = region.difference(box(*structure.stair))
    grid_template, cell_areas = region_to_cells(region, xs, ys)
    cells = _cell_facts(grid_template, cell_areas, xs, ys, structure, streets)
    grid_template = _reserve_corridor_and_wrap(grid_template, cells, structure)
    cell_area = grid_size * grid_size
    ids = {node.node_id: index + 1 for index, node in enumerate(growers)}
    primary_id = len(growers) + 1
    masks = [_seed_mask(node, cells, must_touch_core) for node in growers]
    for node, mask in zip(growers, masks):
        if not mask.any():
            raise TopologyInfeasible([f"{node.node_id}: no cell of the free region can seed it in its zone"])

    rng = random.Random(seed)
    best: tuple[float, list[RoomPolygon], RoomPolygon] | None = None
    reasons: dict[str, int] = {}
    for _ in range(max(1, trials)):
        rooms = [_room_info(node, ids[node.node_id], cell_area, grid_size) for node in growers]
        grid = grid_template.copy()
        try:
            expand_rooms(
                rooms, grid, rng, allowed=masks, l_shapes=False,
                prelimit_enabled=True, prelimit_start_ratio=0.6,
                boost={room.room_id: float(room.target_cells) for room in rooms},
                cell_area=cells.area,
            )
        except ValueError as error:
            reasons[str(error)] = reasons.get(str(error), 0) + 1
            continue
        grid, corridor_span = _release_to_primary(grid, cells, structure, rooms)
        grid = fill_holes_components(grid, cells.interior, fill_id=primary_id)
        candidate = _candidate(
            grid, cells, growers, ids, primary, primary_id, structure, graph,
            must_touch_core, streets, core_node, corridor_span,
        )
        if isinstance(candidate, str):
            reasons[candidate] = reasons.get(candidate, 0) + 1
            continue
        energy, placed, corridor = candidate
        if best is None or energy < best[0] - _EPS:
            best = (energy, placed, corridor)
    if best is None:
        summary = sorted(reasons.items(), key=lambda item: -item[1])[:5]
        raise TopologyInfeasible(
            [f"no growth trial of {trials} passed every gate"]
            + [f"{count}x {reason}" for reason, count in summary]
        )
    _, placed, corridor = best
    rooms_out = [RoomPolygon(core_node.node_id, core_node.space_type, _ring(structure.core.bounds)), *placed]
    corridor_poly = Polygon(corridor.polygon)
    openings = [
        _centered_opening(room, [corridor])
        for room in rooms_out
        if _shares_door(Polygon(room.polygon), corridor_poly)
    ]
    return LayoutCandidate(
        candidate_id=f"{program.project_id}-f{program.floor_index}-growth",
        project_id=program.project_id,
        floor_index=program.floor_index,
        rooms=rooms_out,
        circulation=[corridor],
        score=0.0,
        openings=openings,
        remote_stair_footprint=(tuple(_ring(structure.stair)) if structure.stair is not None else None),
    )


def _room_info(node: ProgramNode, room_id: int, cell_area: float, grid_size: float) -> RoomInfo:
    target = float(node.target_area)
    max_area = float(node.max_area) if node.max_area else target * 1.15
    target_cells = max(1, round(target / cell_area))
    max_cells = None  # the area cap below is exact on the rectilinear grid
    min_width = float(node.min_width or 0.0)
    # The first block already clears the minimum width; a rectangle grown
    # from it never loses that.
    chunk = max(1, math.ceil(max(min_width, 2 * 0.9) / grid_size - 1e-9))
    aspect = float(node.max_aspect_ratio) if node.max_aspect_ratio else None
    max_side = int(math.ceil(math.sqrt(aspect * target_cells))) if aspect else None
    return RoomInfo(
        room_id=room_id,
        name=node.node_id,
        target_cells=target_cells,
        max_cells=max_cells,
        target_area=target,
        max_area=max_area,
        min_chunk=chunk,
        spacing=max(1, math.ceil(math.sqrt(target_cells))),
        max_w_allowed=max_side,
        max_h_allowed=max_side,
    )


def _anchors(structure: FloorStructure) -> tuple[list[float], list[float]]:
    xs: list[float] = []
    ys: list[float] = []
    for x, y in structure.cover.exterior.coords:
        xs.append(x)
        ys.append(y)
    for bounds in (structure.spine, structure.core.bounds, structure.stair):
        if bounds is None:
            continue
        xs.extend((bounds[0], bounds[2]))
        ys.extend((bounds[1], bounds[3]))
    return xs, ys


def _reserve_corridor_and_wrap(grid: np.ndarray, cells: _Cells, structure: FloorStructure) -> np.ndarray:
    """Block growth on the corridor and on the wrap zone past the stair (or core) at the far end."""
    reserved = grid.copy()
    sx0, sy0, sx1, sy1 = structure.spine
    core_x = (structure.core.bounds[0] + structure.core.bounds[2]) / 2
    far_right = abs(sx1 - core_x) >= abs(sx0 - core_x)
    # Everything the corridor must reach: the core and the stair.
    reach = [structure.core.bounds[0], structure.core.bounds[2]]
    if structure.stair is not None:
        reach.extend((structure.stair[0], structure.stair[2]))
    wrap_from = max(reach) if far_right else min(reach)
    xs, ys = cells.xs, cells.ys
    for j, i in np.argwhere(cells.interior):
        cx, cy = (xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2
        if sy0 < cy < sy1 and sx0 <= cx <= sx1:
            reserved[j, i] = _CORRIDOR_CELL
        elif (cx > wrap_from) if far_right else (cx < wrap_from):
            reserved[j, i] = _WRAP_CELL
    return reserved


def _release_to_primary(grid: np.ndarray, cells: _Cells, structure: FloorStructure, rooms) -> tuple[np.ndarray, tuple[float, float]]:
    """Free the wrap zone and the corridor beyond the last thing it serves; return the corridor's x span."""
    released = grid.copy()
    released[released == _WRAP_CELL] = FREE_CELL
    sx0, _, sx1, _ = structure.spine
    reach = [structure.core.bounds[0], structure.core.bounds[2]]
    if structure.stair is not None:
        reach.extend((structure.stair[0], structure.stair[2]))
    xs = cells.xs
    for room in rooms:
        reach.extend((float(xs[room.min_x]), float(xs[room.max_x])))
    span = (max(sx0, min(reach)), min(sx1, max(reach)))
    for j, i in np.argwhere(released == _CORRIDOR_CELL):
        cx = (xs[i] + xs[i + 1]) / 2
        released[j, i] = FREE_CELL if not (span[0] <= cx <= span[1]) else _CORRIDOR_CELL
    return released, span


def _cell_facts(grid: np.ndarray, area: np.ndarray, xs: np.ndarray, ys: np.ndarray,
                structure: FloorStructure, streets) -> _Cells:
    interior = grid == FREE_CELL
    touches_corridor = np.zeros_like(interior)
    touches_core = np.zeros_like(interior)
    touches_street = np.zeros_like(interior)
    core_side = np.zeros_like(interior)
    spine = box(*structure.spine)
    core = structure.core
    core_band_y0, core_band_y1 = structure.core_band.y0, structure.core_band.y1
    from shapely.geometry import LineString

    street_lines = [LineString(segment) for segment in streets]
    for j, i in np.argwhere(interior):
        cell = box(xs[i], ys[j], xs[i + 1], ys[j + 1])
        edge = min(xs[i + 1] - xs[i], ys[j + 1] - ys[j]) - _EPS
        touches_corridor[j, i] = cell.boundary.intersection(spine.boundary).length >= edge
        touches_core[j, i] = cell.boundary.intersection(core.boundary).length >= edge
        touches_street[j, i] = any(cell.boundary.intersection(line).length >= edge for line in street_lines)
        cy = (ys[j] + ys[j + 1]) / 2
        core_side[j, i] = core_band_y0 - _EPS <= cy <= core_band_y1 + _EPS
    return _Cells(interior, area, xs, ys, touches_corridor, touches_core, touches_street, core_side)


def _seed_mask(node: ProgramNode, cells: _Cells, must_touch_core: set[str]) -> np.ndarray:
    """Where a room's first block may go, from its zone and its hard adjacencies."""
    if node.node_id in must_touch_core:
        both = cells.touches_core & cells.touches_corridor
        return both if both.any() else cells.touches_core
    if node.frontage_required:
        return cells.touches_street & cells.interior
    if (node.zone or "") in _CORE_SIDE_ZONES:
        mask = cells.core_side & cells.touches_corridor
        return mask if mask.any() else cells.touches_corridor
    mask = ~cells.core_side & cells.touches_corridor
    return mask if mask.any() else cells.touches_corridor


def _candidate(grid, cells, growers, ids, primary, primary_id, structure, graph,
               must_touch_core, streets, core_node, corridor_span):
    """Gate one grown grid; return (energy, rooms, corridor) or the reason it failed."""
    polys = cells_to_polygons(grid, cells.xs, cells.ys)
    nodes = {ids[node.node_id]: node for node in growers}
    _, sy0, _, sy1 = structure.spine
    spine_bounds = (corridor_span[0], sy0, corridor_span[1], sy1)
    spine = box(*spine_bounds)
    corridor = RoomPolygon(CORRIDOR, "circulation", _ring(spine_bounds))
    placed: list[RoomPolygon] = []
    energy = 0.0
    cover_boundary = structure.cover.boundary
    for room_id, node in nodes.items():
        geometry = polys.get(room_id)
        if geometry is None or geometry.geom_type != "Polygon":
            return f"{node.node_id}: grew into pieces or nothing"
        # A union of cells keeps a vertex at every cell corner along a straight
        # edge; the door placement wants whole edges.
        geometry = _without_collinear_vertices(geometry)
        ring = _coords(geometry)
        area = geometry.area
        low = float(node.min_area) if node.min_area else float(node.target_area) * 0.85
        high = float(node.max_area) if node.max_area else float(node.target_area) * 1.15
        if not (low - _EPS <= area <= high + _EPS):
            return f"{node.node_id}: area {area:.1f} outside [{low:.1f}, {high:.1f}]"
        if node.min_width and orthogonal_min_width(ring) + _EPS < float(node.min_width):
            return f"{node.node_id}: narrower than {float(node.min_width):.2f} m"
        if node.max_aspect_ratio and bounding_box_aspect_ratio(ring) > float(node.max_aspect_ratio) + _EPS:
            return f"{node.node_id}: aspect over {float(node.max_aspect_ratio):g}"
        if not _shares_door(geometry, spine):
            return f"{node.node_id}: no door-width edge on the corridor"
        if node.node_id in must_touch_core and not _shares_door(geometry, structure.core):
            return f"{node.node_id}: does not reach the core"
        if node.frontage_required and streets and shared_boundary_with_segments_length(ring, streets) <= _EPS:
            return f"{node.node_id}: not on the street frontage"
        placed.append(RoomPolygon(node.node_id, node.space_type, ring))
        target = float(node.target_area)
        corners = sum(1 for _ in ring)
        wall = geometry.boundary.intersection(cover_boundary).length / geometry.length
        energy += _W_RATIO * abs(area - target) / target + _W_CORNER * max(0, corners - 4) - _W_WALL * min(1.0, wall)

    residual = polys.get(primary_id)
    if residual is None:
        return f"{primary.node_id}: nothing left for the primary"
    if isinstance(residual, MultiPolygon):
        return f"{primary.node_id}: left in {len(residual.geoms)} pieces"
    opened = _open_rectilinear(residual, float(primary.min_width or 0.0))
    if opened.is_empty or isinstance(opened, MultiPolygon):
        return f"{primary.node_id}: splits into pieces under its minimum width"
    opened = _without_collinear_vertices(opened)
    ring = _coords(opened)
    area = opened.area
    low = float(primary.min_area) if primary.min_area else float(primary.target_area) * 0.85
    high = float(primary.max_area) if primary.max_area else float(primary.target_area) * 1.15
    if not (low - _EPS <= area <= high + _EPS):
        return f"{primary.node_id}: area {area:.1f} outside [{low:.1f}, {high:.1f}]"
    if not _shares_door(opened, spine):
        return f"{primary.node_id}: no door-width edge on the corridor"
    placed.append(RoomPolygon(primary.node_id, primary.space_type, ring))
    energy += _W_RATIO * abs(area - float(primary.target_area)) / float(primary.target_area)

    rooms_for_rules = [RoomPolygon(core_node.node_id, core_node.space_type, _ring(structure.core.bounds)), *placed]
    if not _supports_clustered(rooms_for_rules, structure.plate):
        return "support rooms spread over more than half the floor diagonal"
    try:
        _verify_adjacency(graph, rooms_for_rules, corridor)
    except TopologyInfeasible as error:
        return str(error)
    return energy, placed, corridor
