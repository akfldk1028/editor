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
from shapely.geometry import LineString, MultiPolygon, Polygon, box
from shapely.ops import unary_union

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
    _longest_run,
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
# Ours: area the cover leaves unassigned (pockets between rooms), as a
# fraction of the cover -- a 5 % pocket costs as much as a 17 % area miss.
_W_WASTE = 20.0


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
    grid_template = _reserve_corridor_and_wrap(grid_template, cells, structure, float(primary.min_width or 0.0))
    cell_area = grid_size * grid_size
    ids = {node.node_id: index + 1 for index, node in enumerate(growers)}
    primary_id = len(growers) + 1

    rng = random.Random(seed)
    best: tuple[float, list[RoomPolygon], RoomPolygon] | None = None
    reasons: dict[str, int] = {}
    # Each side of the corridor is a row: one depth for its rooms, chosen
    # like the topology solver chooses a row depth -- the depth at which the
    # rooms' widths meet their gates and their areas miss their targets least.
    # A room's first block is its width at that depth; growth then only
    # fine-tunes.  The primary takes the strip beyond the row.
    primary_min = float(primary.min_width or 0.0)
    core_side_nodes = [n for n in growers if (n.zone or "") in _CORE_SIDE_ZONES or n.node_id in must_touch_core]
    street_nodes = [n for n in growers if n not in core_side_nodes]
    span = _growable_span(structure, primary_min)
    # Beside the core the leftover strip can still be taken by a room (pocket
    # absorption) or is waste the energy charges; on the street side it is the
    # primary's frontage and has to be primary-wide.  A core-side row that
    # does not pack its flanks spills its largest dry room to the street row,
    # as the topology solver's assignment search would.
    core_depth = street_depth = None
    while True:
        core_depth = _row_depth(core_side_nodes, structure.core_band.depth,
                                lambda d: _flanks(structure, "core", d, span))
        street_depth = _row_depth(street_nodes, structure.street_band.depth,
                                  lambda d: _flanks(structure, "street", d, span), primary_min)
        if core_depth is not None and street_depth is not None:
            break
        movable = [n for n in core_side_nodes if n.node_id not in must_touch_core]
        if core_depth is not None or not movable:
            break
        spilled = max(movable, key=lambda n: float(n.target_area))
        core_side_nodes.remove(spilled)
        street_nodes.append(spilled)
    core_depth = core_depth if core_depth is not None else structure.core_band.depth
    street_depth = street_depth if street_depth is not None else structure.street_band.depth
    depths = {
        **{n.node_id: core_depth for n in core_side_nodes},
        **{n.node_id: street_depth for n in street_nodes},
    }
    on_core_side = {n.node_id for n in core_side_nodes}
    masks = [_seed_mask(node, cells, must_touch_core, node.node_id in on_core_side) for node in growers]
    for node, mask in zip(growers, masks):
        if not mask.any():
            raise TopologyInfeasible([f"{node.node_id}: no cell of the free region can seed it in its zone"])
    for _ in range(max(1, trials)):
        rooms = [_room_info(node, ids[node.node_id], cell_area, grid_size, depths[node.node_id]) for node in growers]
        grid = grid_template.copy()
        try:
            expand_rooms(
                rooms, grid, rng, allowed=masks, l_shapes=False,
                prelimit_enabled=True, prelimit_start_ratio=0.0,
                boost={room.room_id: float(room.target_cells) for room in rooms},
                cell_area=cells.area,
            )
        except ValueError as error:
            reasons[str(error)] = reasons.get(str(error), 0) + 1
            continue
        grid, corridor_span = _release_to_primary(grid, cells, structure, rooms)
        grid = _absorb_pockets(grid, cells, rooms, primary)
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


def _flanks(structure: FloorStructure, side: str, depth: float, span: tuple[float, float]) -> list[float]:
    """Lengths of the stretches a row of the given depth can occupy on one side of the spine.

    The growable span less what sits on that side (the core, the stair),
    each stretch shortened to what the outline keeps at the row's full depth.
    """
    sx0, sy0, sx1, sy1 = structure.spine
    band = structure.core_band if side == "core" else structure.street_band
    if band.y0 >= sy1 - _EPS:  # band above the spine
        y0, y1 = sy1, min(band.y1, sy1 + depth)
    else:
        y0, y1 = max(band.y0, sy0 - depth), sy0
    blockers = [structure.core.bounds[0::2]] if side == "core" else []
    if side == "street" and structure.stair is not None:
        blockers.append(structure.stair[0::2])
    segments = [span]
    for b0, b1 in blockers:
        next_segments = []
        for a0, a1 in segments:
            if b1 <= a0 + _EPS or b0 >= a1 - _EPS:
                next_segments.append((a0, a1))
                continue
            if b0 - a0 > _EPS:
                next_segments.append((a0, b0))
            if a1 - b1 > _EPS:
                next_segments.append((b1, a1))
        segments = next_segments
    lengths = []
    for a0, a1 in segments:
        run0, run1 = _longest_run(structure.cover, y0, y1, a0, a1)
        if run1 - run0 > _EPS:
            lengths.append(run1 - run0)
    return lengths


def _packs(widths: list[float], flanks: list[float]) -> bool:
    """First-fit decreasing: every width finds a flank with room left."""
    left = sorted(flanks, reverse=True)
    for width in sorted(widths, reverse=True):
        for index, room in enumerate(left):
            if width <= room + _EPS:
                left[index] = room - width
                break
        else:
            return False
    return True


def _row_depth(nodes: list[ProgramNode], band_depth: float, flanks_at, remainder_min: float = 0.0) -> float | None:
    """The row depth at which every room's width meets its gates, the row packs
    into the flanks, and the areas miss their targets least.

    What the row leaves of the band goes to the primary, so it is either
    nothing or at least the primary's minimum width.
    """
    if not nodes:
        return band_depth
    best: tuple[float, float] | None = None
    depth = 3.0
    while depth <= band_depth + _EPS:
        remainder = band_depth - depth
        if _EPS < remainder < remainder_min - _EPS:
            depth += 0.5
            continue
        widths = []
        ok = True
        for node in nodes:
            target = float(node.target_area)
            min_width = float(node.min_width or 0.0)
            aspect = float(node.max_aspect_ratio) if node.max_aspect_ratio else math.inf
            width = max(min_width, target / depth, depth / aspect)
            low = float(node.min_area) if node.min_area else target * 0.85
            high = float(node.max_area) if node.max_area else target * 1.15
            if width * depth > high + _EPS or width * depth < low - _EPS or width / depth > aspect + _EPS:
                ok = False
                break
            widths.append(width)
        if ok and _packs(widths, flanks_at(depth)):
            miss = sum(abs(w * depth - float(n.target_area)) for w, n in zip(widths, nodes))
            if best is None or miss < best[0] - _EPS:
                best = (miss, depth)
        depth += 0.5
    return best[1] if best is not None else None


def _room_info(node: ProgramNode, room_id: int, cell_area: float, grid_size: float, row_depth: float) -> RoomInfo:
    target = float(node.target_area)
    target_cells = max(1, round(target / cell_area))
    max_cells = None  # the area cap below is exact on the rectilinear grid
    min_width = float(node.min_width or 0.0)
    aspect = float(node.max_aspect_ratio) if node.max_aspect_ratio else None
    # The first block is the room at the row depth: its width there, and at
    # least the minimum width.  Rounding to cells may overshoot the area
    # band, so the block is trimmed to the band and growth fine-tunes.
    chunk = max(1, math.ceil(max(min_width, 2 * 0.9) / grid_size - 1e-9))
    block_h = max(chunk, int(row_depth / grid_size + 1e-9))
    width = max(min_width, target / row_depth, (row_depth / aspect) if aspect else 0.0)
    block_w = max(chunk, math.ceil(width / grid_size - 1e-9))
    # Rounding up to cells must not push the block over its aspect limit or
    # its target; a strip of growth then lands it inside the band.
    while block_w > chunk and (
        block_w * block_h * cell_area > target + _EPS
        or (aspect and block_w > aspect * block_h + _EPS)
    ):
        block_w -= 1
    max_w = int(aspect * block_h + _EPS) if aspect else None
    max_h = int(aspect * block_w + _EPS) if aspect else None
    return RoomInfo(
        room_id=room_id,
        name=node.node_id,
        target_cells=target_cells,
        max_cells=max_cells,
        target_area=target,
        # Growth stops at the target, not the band's top: what rooms take
        # beyond their targets the primary loses below its own band.
        max_area=target + cell_area * max(block_w, block_h),
        min_chunk=1,
        block_w=block_w,
        block_h=block_h,
        spacing=block_w,
        max_w_allowed=max_w,
        max_h_allowed=max_h,
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


def _wrap(structure: FloorStructure, primary_min: float) -> tuple[str, float] | None:
    """Where the primary wraps around the corridor's end: ("right", x) or ("left", x), or None.

    Beyond everything the corridor must reach (core and stair) the spine can
    stop and the primary join its two sides -- if that end of the plate is at
    least the primary's minimum width; the wider such end is taken.
    """
    sx0, _, sx1, _ = structure.spine
    reach = [structure.core.bounds[0], structure.core.bounds[2]]
    if structure.stair is not None:
        reach.extend((structure.stair[0], structure.stair[2]))
    right, left = sx1 - max(reach), min(reach) - sx0
    # The zone is exactly one primary width at that end; rooms may line the
    # corridor right up to it, and the corridor stops where they stop.
    options = []
    if right >= primary_min - _EPS:
        options.append((right, ("right", sx1 - primary_min)))
    if left >= primary_min - _EPS:
        options.append((left, ("left", sx0 + primary_min)))
    return max(options, key=lambda item: item[0])[1] if options else None


def _growable_span(structure: FloorStructure, primary_min: float) -> tuple[float, float]:
    """The stretch of the spine rooms may line up along (the wrap zone excluded)."""
    sx0, _, sx1, _ = structure.spine
    wrap = _wrap(structure, primary_min)
    if wrap is None:
        return sx0, sx1
    side, x = wrap
    return (sx0, x) if side == "right" else (x, sx1)


def _reserve_corridor_and_wrap(grid: np.ndarray, cells: _Cells, structure: FloorStructure, primary_min: float) -> np.ndarray:
    """Block growth on the corridor and on the wrap zone past the last thing the corridor reaches."""
    reserved = grid.copy()
    sx0, sy0, sx1, sy1 = structure.spine
    wrap = _wrap(structure, primary_min)
    xs, ys = cells.xs, cells.ys
    for j, i in np.argwhere(cells.interior):
        cx, cy = (xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2
        if sy0 < cy < sy1 and sx0 <= cx <= sx1:
            reserved[j, i] = _CORRIDOR_CELL
        elif wrap is not None and ((cx > wrap[1]) if wrap[0] == "right" else (cx < wrap[1])):
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


def _absorb_pockets(grid: np.ndarray, cells: _Cells, rooms, primary) -> np.ndarray:
    """A free pocket too narrow for the primary joins the grown room it touches most,
    when that keeps the room a rectangle inside its area band."""
    h, w = grid.shape
    out = grid.copy()
    seen = np.zeros_like(out, dtype=bool)
    by_id = {room.room_id: room for room in rooms}
    primary_min = float(primary.min_width or 0.0)
    for y in range(h):
        for x in range(w):
            if out[y, x] != FREE_CELL or seen[y, x]:
                continue
            component = []
            stack = [(y, x)]
            seen[y, x] = True
            while stack:
                cy, cx = stack.pop()
                component.append((cy, cx))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < w and 0 <= ny < h and out[ny, nx] == FREE_CELL and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            ys_ = [c[0] for c in component]
            xs_ = [c[1] for c in component]
            span_x = float(cells.xs[max(xs_) + 1] - cells.xs[min(xs_)])
            span_y = float(cells.ys[max(ys_) + 1] - cells.ys[min(ys_)])
            if min(span_x, span_y) >= primary_min - _EPS:
                continue  # wide enough to be the primary's
            contact: dict[int, int] = {}
            for cy, cx in component:
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < w and 0 <= ny < h and int(out[ny, nx]) in by_id:
                        contact[int(out[ny, nx])] = contact.get(int(out[ny, nx]), 0) + 1
            for rid, _count in sorted(contact.items(), key=lambda kv: -kv[1]):
                room = by_id[rid]
                x0, x1 = min(room.min_x, min(xs_)), max(room.max_x, max(xs_) + 1)
                y0, y1 = min(room.min_y, min(ys_)), max(room.max_y, max(ys_) + 1)
                block = out[y0:y1, x0:x1]
                fills = ((block == rid) | (block == FREE_CELL)).all()
                free_in_block = int((block == FREE_CELL).sum())
                if not fills or free_in_block != len(component):
                    continue  # the union would not be a rectangle
                area = float(cells.area[y0:y1, x0:x1].sum())
                if room.max_area is not None and area > room.max_area + _EPS:
                    continue
                out[y0:y1, x0:x1] = rid
                room.min_x, room.max_x, room.min_y, room.max_y = x0, x1, y0, y1
                break
    return out


def _cell_facts(grid: np.ndarray, area: np.ndarray, xs: np.ndarray, ys: np.ndarray,
                structure: FloorStructure, streets) -> _Cells:
    interior = grid == FREE_CELL
    touches_corridor = np.zeros_like(interior)
    touches_core = np.zeros_like(interior)
    touches_street = np.zeros_like(interior)
    core_side = np.zeros_like(interior)
    # The grid lines are rounded to a micron; the structure's own values are
    # not, so contact is measured against a micron-wide band of each edge.
    # Contact with the corridor means its long edges: a cell beside the
    # spine's end would seed a room the corridor does not serve.
    sx0, sy0, sx1, sy1 = structure.spine
    spine_edge = unary_union([LineString([(sx0, sy0), (sx1, sy0)]), LineString([(sx0, sy1), (sx1, sy1)])]).buffer(1e-6)
    core_edge = structure.core.boundary.buffer(1e-6)
    core_band_y0, core_band_y1 = structure.core_band.y0, structure.core_band.y1
    street_edges = [LineString(segment).buffer(1e-6) for segment in streets]
    for j, i in np.argwhere(interior):
        cell = box(xs[i], ys[j], xs[i + 1], ys[j + 1])
        edge = min(xs[i + 1] - xs[i], ys[j + 1] - ys[j]) - 1e-4
        touches_corridor[j, i] = cell.boundary.intersection(spine_edge).length >= edge
        touches_core[j, i] = cell.boundary.intersection(core_edge).length >= edge
        touches_street[j, i] = any(cell.boundary.intersection(line).length >= edge for line in street_edges)
        cy = (ys[j] + ys[j + 1]) / 2
        core_side[j, i] = core_band_y0 - _EPS <= cy <= core_band_y1 + _EPS
    return _Cells(interior, area, xs, ys, touches_corridor, touches_core, touches_street, core_side)


def _seed_mask(node: ProgramNode, cells: _Cells, must_touch_core: set[str], core_side: bool) -> np.ndarray:
    """Where a room's first block may go, from its row and its hard adjacencies."""
    if node.node_id in must_touch_core:
        both = cells.touches_core & cells.touches_corridor
        return both if both.any() else cells.touches_core
    if node.frontage_required:
        return cells.touches_street & cells.interior
    if core_side:
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
    # Gates measure against the same micron-rounded geometry the layout
    # carries, so a room flush with the corridor or core reads as touching.
    spine = Polygon(_ring(spine_bounds))
    core_polygon = Polygon(_ring(structure.core.bounds))
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
        if node.node_id in must_touch_core and not _shares_door(geometry, core_polygon):
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
    # Pieces the minimum width erodes away (a pocket beside the core, a
    # sliver at a chamfer) are left unassigned, as the outline's corners are;
    # what survives has to be one room.
    pieces = list(residual.geoms) if isinstance(residual, MultiPolygon) else [residual]
    survivors = []
    for piece in pieces:
        opened = _open_rectilinear(piece, float(primary.min_width or 0.0))
        if not opened.is_empty:
            survivors.extend(list(opened.geoms) if isinstance(opened, MultiPolygon) else [opened])
    if len(survivors) != 1:
        return f"{primary.node_id}: left in {len(survivors)} pieces above its minimum width"
    opened = survivors[0]
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

    assigned = sum(Polygon(room.polygon).area for room in placed) + structure.core.area + spine.area
    if structure.stair is not None:
        assigned += box(*structure.stair).area
    energy += _W_WASTE * max(0.0, structure.cover.area - assigned) / structure.cover.area

    rooms_for_rules = [RoomPolygon(core_node.node_id, core_node.space_type, _ring(structure.core.bounds)), *placed]
    if not _supports_clustered(rooms_for_rules, structure.plate):
        return "support rooms spread over more than half the floor diagonal"
    try:
        _verify_adjacency(graph, rooms_for_rules, corridor)
    except TopologyInfeasible as error:
        return str(error)
    return energy, placed, corridor
