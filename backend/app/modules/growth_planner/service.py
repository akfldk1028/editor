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
ENTRY = "entry"
_CORE_SIDE_ZONES = frozenset({"service", "core"})
# A row of rooms along the corridor is at least this deep.
_MIN_ROW_DEPTH = 3.0
# Rows are packed at real dimensions -- depths in 10 cm, widths in 5 cm -- and
# the grid is then drawn through every packed edge, so a room whose area band
# allows one width only (a pantry at 1.80 m) is not lost to cell rounding.
_DEPTH_STEP = 0.1
_WIDTH_STEP = 0.05
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
    core_side: str | None = None,
) -> LayoutCandidate:
    primary_node = next(node for node in program.nodes if node.space_type in ("open_work", "sales"))
    graph = build_adjacency_graph(program)
    streets = [((float(a[0]), float(a[1])), (float(b[0]), float(b[1]))) for a, b in street_segments]
    rng = random.Random(seed)
    primary_min = float(primary_node.min_width or 0.0)
    reasons: dict[str, int] = {}
    # The stair stops short of the far end so the primary can wrap around
    # the corridor there and be one room on both sides of it -- by at least
    # its minimum width, and further in when the wrap has to hold a whole
    # tenant (the pieces the stair cuts the residual into are the tenants).
    for inset in _stair_insets(boundary, core_polygon, stair_dimensions, stair_footprint, primary_min):
        try:
            structure = plan_floor_structure(
                boundary, program, core_polygon=core_polygon, corridor_width=corridor_width,
                stair_dimensions=stair_dimensions, stair_footprint=stair_footprint, stair_inset=inset,
                # Rooms on the street edge put the core at the rear; the
                # public then reaches the corridor through an entrance.
                entry=any(node.frontage_required for node in program.nodes),
                core_side=core_side,
            )
        except TopologyInfeasible as error:
            reasons[str(error)] = reasons.get(str(error), 0) + 1
            continue
        best, why = _solve_floor(structure, program, graph, streets, grid_size, trials, rng)
        if best is not None:
            return _layout(structure, program, best)
        for reason, count in why.items():
            reasons[reason] = reasons.get(reason, 0) + count
    summary = sorted(reasons.items(), key=lambda item: -item[1])[:5]
    raise TopologyInfeasible(
        [f"no growth trial of {trials} passed every gate"] + [f"{count}x {reason}" for reason, count in summary]
    )


def _stair_insets(boundary, core_polygon, stair_dimensions, stair_footprint, primary_min: float) -> list[float]:
    """The far-end insets to try for the remote stair: the primary's minimum
    width, then every half metre until the stair would leave the far half of
    the run beyond the core.  One value when the stair is fixed or absent."""
    if stair_footprint is not None or stair_dimensions is None:
        return [primary_min]
    min_x, _, max_x, _ = Polygon(list(boundary)).bounds
    cx0, _, cx1, _ = Polygon(list(core_polygon)).bounds
    room = max(max_x - cx1, cx0 - min_x) - stair_dimensions[0]
    out = []
    inset = primary_min
    while inset <= room / 2 + _EPS:
        out.append(round(inset, 3))
        inset += 0.5
    return out or [primary_min]


def _solve_floor(structure: FloorStructure, program: ProgramGraph, graph, streets, grid_size: float,
                 trials: int, rng: random.Random):
    """Rows packed, rooms grown and gated on one structure: (best, reasons)."""
    primary = structure.primary
    primaries = structure.primaries
    core_node = next(node for node in program.nodes if node.space_type == "core")
    primary_ids = {node.node_id for node in primaries}
    others = [node for node in program.nodes if node.node_id not in primary_ids and node.node_id != core_node.node_id]
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
    if structure.entry is not None:
        region = region.difference(box(*structure.entry))
    grid_template, cell_areas = region_to_cells(region, xs, ys)
    cells = _cell_facts(grid_template, cell_areas, xs, ys, structure, streets)
    primary_min = float(primary.min_width or 0.0)
    ids = {node.node_id: index + 1 for index, node in enumerate(growers)}
    primary_id = len(growers) + 1

    best: tuple[float, list[RoomPolygon], RoomPolygon] | None = None
    reasons: dict[str, int] = {}
    # Each side of the corridor is a row: one depth for its rooms, chosen
    # like the topology solver chooses a row depth -- the depth at which the
    # rooms' widths meet their gates and their areas miss their targets least.
    # A room's first block is its width at that depth; growth then only
    # fine-tunes.  The primary takes the strip beyond the row.
    wrap = _wrap(structure, primary_min)
    span = _growable_span(structure, primary_min)
    # What the floor has for rooms against what the program asks: every room
    # is sized by the same factor (within its band), so a surplus does not
    # all land in the primary and a deficit does not all come out of it.
    # The rows are packed at that factor; what they then leave the primary
    # (with the corridor released beyond them) is checked against its band
    # and the factor moved until the primary is inside it.
    for_rooms = float(cells.area[cells.interior].sum()) - box(*structure.spine).area
    grower_target = sum(float(node.target_area) for node in growers)
    primary_target = sum(float(node.target_area) for node in primaries)
    scale = min(1.15, max(0.85, for_rooms / (grower_target + primary_target))) if growers else 1.0
    for _ in range(4):
        core_side_nodes = [n for n in growers if (n.zone or "") in _CORE_SIDE_ZONES or n.node_id in must_touch_core]
        street_nodes = [n for n in growers if n not in core_side_nodes]
        # Beside the core the leftover strip can still be taken by a room
        # (pocket absorption) or is waste the energy charges; on the street
        # side it is the primary's frontage and has to be primary-wide.  A
        # core-side row that does not pack its flanks spills its largest dry
        # room to the street row, as the topology solver's assignment would.
        core_row = street_row = None
        while True:
            core_row = _row_depth(core_side_nodes, "core", structure, cells, span, wrap, must_touch_core, scale, primary_min)
            street_row = _row_depth(street_nodes, "street", structure, cells, span, wrap, set(), scale, primary_min)
            if core_row is not None and street_row is not None:
                break
            movable = [n for n in core_side_nodes if n.node_id not in must_touch_core]
            if core_row is not None or not movable:
                break
            spilled = max(movable, key=lambda n: float(n.target_area))
            core_side_nodes.remove(spilled)
            street_nodes.append(spilled)
        if core_row is None:
            core_row = _unpacked_row(core_side_nodes, structure.core_band.depth,
                                     _flanks(structure, "core", structure.core_band.depth, span, wrap))
        if street_row is None:
            street_row = _unpacked_row(street_nodes, structure.street_band.depth,
                                       _flanks(structure, "street", structure.street_band.depth, span, wrap))
        rows = {**{n.node_id: ("core", core_row) for n in core_side_nodes},
                **{n.node_id: ("street", street_row) for n in street_nodes}}
        if not growers:
            break
        expected = _expected_primary(structure, rows, growers, for_rooms)
        low = sum((float(n.min_area) if n.min_area else float(n.target_area) * 0.85) for n in primaries)
        high = sum((float(n.max_area) if n.max_area else float(n.target_area) * 1.15) for n in primaries)
        if low - _EPS <= expected <= high + _EPS:
            break
        aim = primary_target * scale
        moved = min(1.15, max(0.85, scale + (expected - aim) / grower_target))
        if abs(moved - scale) < 1e-3:
            break
        scale = moved
    # The grid the rooms grow on runs through every packed room edge and both
    # row depths as well as the structure, so each packed room is a whole
    # block of cells and its first block is exactly its packed rectangle.
    extra_x: list[float] = []
    extra_y: list[float] = []
    for node in growers:
        side, row = rows[node.node_id]
        packed = row.span_of(node.node_id)
        if packed is not None:
            extra_x.extend(packed)
            extra_y.extend(_row_y(structure, side, row.depth))
    if extra_x:
        xs = rectilinear_lines(anchors_x + extra_x, grid_size)
        ys = rectilinear_lines(anchors_y + extra_y, grid_size)
        grid_template, cell_areas = region_to_cells(region, xs, ys)
        cells = _cell_facts(grid_template, cell_areas, xs, ys, structure, streets)
    grid_template = _reserve_corridor_and_wrap(grid_template, cells, structure, primary_min)
    masks = []
    for node in growers:
        side, row = rows[node.node_id]
        masks.append(_seed_mask(node, cells, must_touch_core, side == "core", row.span_of(node.node_id),
                                _row_y(structure, side, row.depth)))
    for node, mask in zip(growers, masks):
        if not mask.any():
            raise TopologyInfeasible([f"{node.node_id}: no cell of the free region can seed it in its zone"])
    for _ in range(max(1, trials)):
        rooms = [_room_info(node, ids[node.node_id], cells, structure, *rows[node.node_id], scale) for node in growers]
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
            grid, cells, growers, ids, primaries, primary_id, structure, graph,
            must_touch_core, streets, core_node, corridor_span,
        )
        if isinstance(candidate, str):
            reasons[candidate] = reasons.get(candidate, 0) + 1
            continue
        energy, placed, corridor = candidate
        if best is None or energy < best[0] - _EPS:
            best = (energy, placed, corridor)
    return best, reasons


def _expected_primary(structure: FloorStructure, rows, growers, for_rooms: float) -> float:
    """What the packed rows leave the primary: the free area less the rows,
    plus the corridor released beyond the last thing it serves."""
    taken = 0.0
    reach = [structure.core.bounds[0], structure.core.bounds[2]]
    if structure.stair is not None:
        reach.extend((structure.stair[0], structure.stair[2]))
    if structure.entry is not None:
        reach.extend((structure.entry[0], structure.entry[2]))
    for node in growers:
        _, row = rows[node.node_id]
        taken += row.width_of(node) * row.depth
        span = row.span_of(node.node_id)
        if span is not None:
            reach.extend(span)
    sx0, sy0, sx1, sy1 = structure.spine
    released = ((sx1 - min(sx1, max(reach))) + (max(sx0, min(reach)) - sx0)) * (sy1 - sy0)
    return for_rooms - taken + released


def _layout(structure: FloorStructure, program: ProgramGraph, best) -> LayoutCandidate:
    core_node = next(node for node in program.nodes if node.space_type == "core")
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
        circulation=[corridor] + (
            [RoomPolygon(ENTRY, "circulation", _ring(structure.entry))] if structure.entry is not None else []
        ),
        score=0.0,
        openings=openings,
        remote_stair_footprint=(tuple(_ring(structure.stair)) if structure.stair is not None else None),
    )


@dataclass(frozen=True)
class _Flank:
    """A stretch of one side of the spine a row can occupy, and whether what
    the row leaves of it is the primary's (it ends at the wrap) or a pocket."""

    x0: float
    x1: float
    open: bool
    # Rooms pack from this end: the core's end beside the core, the closed
    # end of an open flank (so its leftover stays joined to the wrap).
    from_x1: bool = False

    @property
    def length(self) -> float:
        return self.x1 - self.x0


@dataclass(frozen=True)
class _Row:
    """One side of the corridor: its depth, its flanks and each room's flank and width."""

    depth: float
    flanks: list[_Flank]
    placement: dict[str, tuple[int, float, tuple[float, float]]]

    def flank_of(self, room_id: str) -> _Flank | None:  # noqa: D102
        item = self.placement.get(room_id)
        return self.flanks[item[0]] if item is not None else None

    def width_of(self, node: ProgramNode) -> float:
        item = self.placement.get(node.node_id)
        return item[1] if item is not None else _target_width(node, self.depth)

    def span_of(self, room_id: str) -> tuple[float, float] | None:
        """The x range the packed row gives a room."""
        item = self.placement.get(room_id)
        return item[2] if item is not None else None


def _target_width(node: ProgramNode, depth: float) -> float:
    aspect = float(node.max_aspect_ratio) if node.max_aspect_ratio else math.inf
    return max(float(node.min_width or 0.0), float(node.target_area) / depth, depth / aspect)


def _row_y(structure: FloorStructure, side: str, depth: float) -> tuple[float, float]:
    """The y range a row of ``depth`` on ``side`` of the spine occupies."""
    _, sy0, _, sy1 = structure.spine
    band = structure.core_band if side == "core" else structure.street_band
    if band.y0 >= sy1 - _EPS:  # band above the spine
        return sy1, min(band.y1, sy1 + depth)
    return max(band.y0, sy0 - depth), sy0


def _flanks(structure: FloorStructure, side: str, depth: float, span: tuple[float, float],
            wrap: tuple[str, float] | None) -> list[_Flank]:
    """The stretches a row of the given depth can occupy on one side of the spine.

    The growable span less what sits on that side (the core, the stair),
    each stretch shortened to what the outline keeps at the row's full depth.
    The stretch that ends at the wrap is open: its leftover is the primary's.
    """
    y0, y1 = _row_y(structure, side, depth)
    blockers = [structure.core.bounds[0::2]] if side == "core" else []
    if side == "street" and structure.stair is not None:
        blockers.append(structure.stair[0::2])
    if side == "street" and structure.entry is not None:
        blockers.append(structure.entry[0::2])
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
    flanks = []
    for a0, a1 in segments:
        run0, run1 = _longest_run(structure.cover, y0, y1, a0, a1)
        if run1 - run0 > _EPS:
            # A street flank's leftover is the primary's frontage; beside
            # the core only the flank that runs on to the wrap is the primary's.
            is_open = side == "street" or (wrap is not None and (
                (wrap[0] == "right" and run1 >= span[1] - _EPS) or (wrap[0] == "left" and run0 <= span[0] + _EPS)
            ))
            if side == "core":
                from_x1 = run1 <= structure.core.bounds[0] + _EPS  # the flank left of the core
            else:
                from_x1 = is_open and wrap is not None and wrap[0] == "left"
            flanks.append(_Flank(run0, run1, is_open, from_x1))
    return flanks


def _spine_polygon(structure: FloorStructure) -> Polygon:
    return box(*structure.spine)


def _cell_width(cells: _Cells, flank: _Flank) -> float:
    """The width of the grid's cells along a flank (equal between two structure lines)."""
    cx = (cells.xs[:-1] + cells.xs[1:]) / 2
    count = max(1, int(((cx > flank.x0 + _EPS) & (cx < flank.x1 - _EPS)).sum()))
    return flank.length / count


def _pack(nodes: list[ProgramNode], depth: float, flanks: list[_Flank], cell_ws: list[float],
          must_touch: set[str], scale: float = 1.0) -> dict[str, tuple[int, float, tuple[float, float]]] | None:
    """Each room's flank, width and x span at ``depth``, widths in steps of ``cell_ws``, or None when the row does not pack.

    Rooms bound to the core go first, one per flank (every core-side flank
    starts at the core) into the flank with the least to spare, so a pocket
    beside the core stays small; the rest go first-fit decreasing into the
    flank with the most left.  A room takes its target width when the flank
    has it, else the most the flank has -- as long as the area that makes
    stays in the room's band and the room keeps its minimum width and aspect.
    """
    left = [flank.length for flank in flanks]
    fresh = [True] * len(flanks)
    order = sorted(range(len(nodes)), key=lambda i: (nodes[i].node_id not in must_touch, -float(nodes[i].target_area)))
    out: dict[str, tuple[int, float, tuple[float, float]]] = {}
    for i in order:
        node = nodes[i]
        bound = node.node_id in must_touch
        target = float(node.target_area)
        low = float(node.min_area) if node.min_area else target * 0.85
        high = float(node.max_area) if node.max_area else target * 1.15
        target = min(high, max(low, target * scale))
        aspect = float(node.max_aspect_ratio) if node.max_aspect_ratio else math.inf
        min_width = max(float(node.min_width or 0.0), depth / aspect)
        choices: list[tuple[int, float]] = []
        for k, flank in enumerate(flanks):
            if bound and not fresh[k]:
                continue
            cw = cell_ws[k]
            available = math.floor(left[k] / cw + 1e-9) * cw
            width = min(math.ceil(target / depth / cw - 1e-9) * cw, available)
            if width * depth > high + _EPS:  # rounding up to cells overshot the band
                width = math.floor(high / depth / cw + 1e-9) * cw
            if (width < min_width - _EPS or width > available + _EPS or width * depth < low - _EPS
                    or width * depth > high + _EPS or width / depth > aspect + _EPS):
                continue
            choices.append((k, width))
        if not choices:
            return None
        k, width = (min(choices, key=lambda item: left[item[0]] - item[1]) if bound
                    else max(choices, key=lambda item: left[item[0]]))
        flank = flanks[k]
        # Packed from the flank's origin: after what the flank already holds.
        used = flank.length - left[k]
        span = (flank.x1 - used - width, flank.x1 - used) if flank.from_x1 else (flank.x0 + used, flank.x0 + used + width)
        out[node.node_id] = (k, width, span)
        left[k] -= width
        fresh[k] = False
    return out


def _row_depths(cells: _Cells, structure: FloorStructure, side: str) -> list[float]:
    """The depths a row on ``side`` can have: every 10 cm from the minimum row depth to the band's full depth."""
    band = structure.core_band if side == "core" else structure.street_band
    depths = []
    step = 0
    while _MIN_ROW_DEPTH + step * _DEPTH_STEP < band.depth - _EPS:
        depths.append(round(_MIN_ROW_DEPTH + step * _DEPTH_STEP, 6))
        step += 1
    depths.append(band.depth)
    return depths


def _row_depth(nodes: list[ProgramNode], side: str, structure: FloorStructure, cells: _Cells,
               span: tuple[float, float], wrap: tuple[str, float] | None, must_touch: set[str],
               scale: float = 1.0, remainder_min: float = 0.0) -> _Row | None:
    """The row at the depth where every room packs into the flanks within its
    gates and the areas miss their targets least -- the leftover of a closed
    flank (a pocket) counting as a miss.  The grid is drawn through the packed
    edges afterwards, so the row that packs is the row that grows.

    What the row leaves of the band behind its rooms is the primary's only
    when it is at least the primary's minimum width (``remainder_min``);
    a thinner strip is waste and counts as a miss.
    """
    band_depth = (structure.core_band if side == "core" else structure.street_band).depth
    if not nodes:
        return _Row(band_depth, _flanks(structure, side, band_depth, span, wrap), {})
    best: tuple[float, _Row] | None = None
    for depth in _row_depths(cells, structure, side):
        if depth < _MIN_ROW_DEPTH - _EPS:
            continue
        remainder = band_depth - depth
        flanks = _flanks(structure, side, depth, span, wrap)
        placement = _pack(nodes, depth, flanks, [_WIDTH_STEP] * len(flanks), must_touch, scale)
        if placement is None:
            continue
        miss = sum(abs(placement[n.node_id][1] * depth - float(n.target_area) * scale) for n in nodes)
        taken = [0.0] * len(flanks)
        for k, width, _ in placement.values():
            taken[k] += width
        miss += sum((flank.length - used) * depth for flank, used in zip(flanks, taken) if not flank.open)
        if _EPS < remainder < remainder_min - _EPS:
            miss += remainder * sum(taken)
        if best is None or miss < best[0] - _EPS:
            best = (miss, _Row(depth, flanks, placement))
    return best[1] if best is not None else None


def _unpacked_row(nodes: list[ProgramNode], band_depth: float, flanks: list[_Flank]) -> _Row:
    """The full band as the row when no depth packs: rooms keep their target widths and any flank."""
    return _Row(band_depth, flanks, {})


def _room_info(node: ProgramNode, room_id: int, cells: _Cells, structure: FloorStructure,
               side: str, row: _Row, scale: float = 1.0) -> RoomInfo:
    """A room's growth spec: its first block is the room at the row's depth
    and its packed width, in the row's actual cells."""
    target = float(node.target_area)
    min_width = float(node.min_width or 0.0)
    aspect = float(node.max_aspect_ratio) if node.max_aspect_ratio else None
    high = float(node.max_area) if node.max_area else target * 1.15
    low = float(node.min_area) if node.min_area else target * 0.85
    # The grid's cells are equal between two structure lines but not across
    # them, so the block is counted in the cells of its own row and flank.
    y0, y1 = _row_y(structure, side, row.depth)
    cy = (cells.ys[:-1] + cells.ys[1:]) / 2
    block_h = max(1, int(((cy > y0 + _EPS) & (cy < y1 - _EPS)).sum()))
    cell_h = (y1 - y0) / block_h
    flank = row.flank_of(node.node_id)
    packed = row.span_of(node.node_id)
    width = row.width_of(node)
    if packed is not None:
        # The grid runs through the packed edges: the block is those cells.
        cx = (cells.xs[:-1] + cells.xs[1:]) / 2
        block_w = max(1, int(((cx > packed[0] + _EPS) & (cx < packed[1] - _EPS)).sum()))
        cell_w = (packed[1] - packed[0]) / block_w
        chunk = 1
    else:
        whole = _Flank(float(cells.xs[0]), float(cells.xs[-1]), False)
        cell_w = _cell_width(cells, flank if flank is not None else whole)
        flank_cells = max(1, round((flank if flank is not None else whole).length / cell_w))
        chunk = max(1, math.ceil(max(min_width, 2 * 0.9) / cell_w - 1e-9))
        block_w = max(chunk, round(width / cell_w))
        block_w = min(block_w, flank_cells) if flank is not None else block_w
    cell_area = cell_w * cell_h
    target_cells = max(1, round(target / cell_area))
    # A block that is not from a packed row was rounded up to cells: it must
    # not start over its band or its aspect limit.
    while block_w > chunk and (
        block_w * block_h * cell_area > high + _EPS
        or (aspect and block_w > aspect * block_h + _EPS)
    ):
        block_w -= 1
    max_w = int(aspect * block_h + _EPS) if aspect else None
    max_h = int(aspect * block_w + _EPS) if aspect else None
    return RoomInfo(
        room_id=room_id,
        name=node.node_id,
        target_cells=target_cells,
        max_cells=None,  # the area cap below is exact on the rectilinear grid
        target_area=target,
        # Growth stops at the target (one strip past it at most, never past
        # the band): what rooms take beyond their targets the primary loses
        # below its own band.
        max_area=min(high, max(low, target * scale) + cell_area * max(block_w, block_h)),
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
    for bounds in (structure.spine, structure.core.bounds, structure.stair, structure.entry):
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
    if structure.entry is not None:
        reach.extend((structure.entry[0], structure.entry[2]))
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
    if structure.entry is not None:
        reach.extend((structure.entry[0], structure.entry[2]))
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


def _assign_residual(pieces: list[Polygon], nodes) -> list | None:
    """(node, piece) pairs: pieces to nodes by size; the largest piece cut for the nodes left over."""
    pieces = sorted(pieces, key=lambda p: -p.area)
    nodes = sorted(nodes, key=lambda n: -float(n.target_area))
    if len(pieces) == len(nodes):
        return list(zip(nodes, pieces))
    extra = len(nodes) - len(pieces)
    head, rest = nodes[: extra + 1], nodes[extra + 1:]
    cut = _split_residual(pieces[0], head)
    if cut is None:
        return None
    return cut + list(zip(rest, pieces[1:]))


def _split_residual(polygon: Polygon, nodes) -> list | None:
    """Cut the residual into one rectilinear piece per node by vertical lines, areas in proportion to targets."""
    min_x, min_y, max_x, max_y = polygon.bounds
    total = sum(float(node.target_area) for node in nodes)
    pieces = []
    left = min_x
    remaining = polygon
    for index, node in enumerate(nodes):
        if index == len(nodes) - 1:
            piece = remaining
        else:
            want = polygon.area * float(node.target_area) / total
            lo, hi = left, max_x
            for _ in range(40):  # bisection on the cut's x to the wanted area
                mid = (lo + hi) / 2
                if remaining.intersection(box(min_x, min_y, mid, max_y)).area < want:
                    lo = mid
                else:
                    hi = mid
            cut = round((lo + hi) / 2, 3)
            piece = remaining.intersection(box(min_x, min_y, cut, max_y))
            remaining = remaining.difference(box(min_x, min_y, cut, max_y))
            left = cut
        if piece.is_empty or piece.geom_type != "Polygon":
            return None
        pieces.append((node, piece))
    return pieces


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


def _seed_mask(node: ProgramNode, cells: _Cells, must_touch_core: set[str], core_side: bool,
               span: tuple[float, float] | None, row_y: tuple[float, float]) -> np.ndarray:
    """Where a room's first block may go: the place its packed row gives it,
    or -- for a room no row packed -- its side of the corridor and its hard
    adjacencies."""
    if span is not None:
        cx = (cells.xs[:-1] + cells.xs[1:]) / 2
        cy = (cells.ys[:-1] + cells.ys[1:]) / 2
        within_x = (cx > span[0] - _EPS) & (cx < span[1] + _EPS)
        within_y = (cy > row_y[0] - _EPS) & (cy < row_y[1] + _EPS)
        placed = cells.interior & within_y[:, None] & within_x[None, :]
        if placed.any():
            return placed
    if node.node_id in must_touch_core:
        both = cells.touches_core & cells.touches_corridor
        return both if both.any() else cells.touches_core
    if node.frontage_required:
        return cells.touches_street & cells.interior
    if core_side:
        inside = cells.core_side & cells.touches_corridor
        return inside if inside.any() else cells.touches_corridor
    inside = ~cells.core_side & cells.touches_corridor
    return inside if inside.any() else cells.touches_corridor


def _candidate(grid, cells, growers, ids, primaries, primary_id, structure, graph,
               must_touch_core, streets, core_node, corridor_span):
    """Gate one grown grid; return (energy, rooms, corridor) or the reason it failed."""
    primary = primaries[0]
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
    if len(survivors) > len(primaries):
        return f"{primary.node_id}: left in {len(survivors)} pieces above its minimum width"
    # Several residual rooms (commercial tenants) share the residual: each
    # piece is one tenant, largest to largest, and the largest piece is cut
    # across the corridor's direction when there are fewer pieces than tenants.
    slices = _assign_residual(survivors, primaries)
    if slices is None:
        return f"{primary.node_id}: the residual cannot be cut into its tenants"
    for node, piece in slices:
        piece = _without_collinear_vertices(piece)
        ring = _coords(piece)
        area = piece.area
        low = float(node.min_area) if node.min_area else float(node.target_area) * 0.85
        high = float(node.max_area) if node.max_area else float(node.target_area) * 1.15
        if not (low - _EPS <= area <= high + _EPS):
            return f"{node.node_id}: area {area:.1f} outside [{low:.1f}, {high:.1f}]"
        if node.min_width and orthogonal_min_width(ring) + _EPS < float(node.min_width):
            return f"{node.node_id}: narrower than {float(node.min_width):.2f} m"
        if not _shares_door(piece, spine):
            return f"{node.node_id}: no door-width edge on the corridor"
        if node.frontage_required and streets and shared_boundary_with_segments_length(ring, streets) <= _EPS:
            return f"{node.node_id}: not on the street frontage"
        placed.append(RoomPolygon(node.node_id, node.space_type, ring))
        energy += _W_RATIO * abs(area - float(node.target_area)) / float(node.target_area)

    assigned = sum(Polygon(room.polygon).area for room in placed) + structure.core.area + spine.area
    if structure.stair is not None:
        assigned += box(*structure.stair).area
    if structure.entry is not None:
        assigned += box(*structure.entry).area
    energy += _W_WASTE * max(0.0, structure.cover.area - assigned) / structure.cover.area

    rooms_for_rules = [RoomPolygon(core_node.node_id, core_node.space_type, _ring(structure.core.bounds)), *placed]
    if not _supports_clustered(rooms_for_rules, structure.plate):
        return "support rooms spread over more than half the floor diagonal"
    try:
        _verify_adjacency(graph, rooms_for_rules, corridor)
    except TopologyInfeasible as error:
        return str(error)
    return energy, placed, corridor
