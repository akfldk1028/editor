"""The floor's fixed structure, planned once and shared by every room solver.

Corridor spine, core, remote stair and the rectilinear cover are decided
before any room is placed -- the topology solver and the growth solver both
start from the same ``FloorStructure``, so the vertical elements stack the
same way whichever solver partitions the rooms.
"""

from __future__ import annotations

import math

from collections.abc import Iterable
from dataclasses import dataclass, replace

from shapely.geometry import Polygon, box

from backend.app.modules.topology_planner.dimensioning import TopologyInfeasible
from backend.app.modules.topology_planner.graph import build_adjacency_graph
from backend.app.modules.topology_planner.service import (
    _EPS,
    _PRIMARY,
    _half_diameter,
    _lay_street_side,
    _longest_run,
    _rectilinear_cover,
)
from backend.app.modules.topology_planner.slicing import _CORE_SIDE_ZONES, Band, plan_double_loaded_spine
from backend.app.schemas.layout import Point
from backend.app.schemas.program import ProgramGraph, ProgramNode


@dataclass(frozen=True)
class FloorStructure:
    plate: Polygon
    cover: Polygon
    spine: tuple[float, float, float, float]
    street_band: Band
    core_band: Band
    core: Polygon
    stair: tuple[float, float, float, float] | None
    exit_separation: float
    primary: ProgramNode
    # Every residual room (split commercial tenants are several); ``primary`` is the first.
    primaries: tuple[ProgramNode, ...] = ()
    # The public entrance from the street to the corridor (a commercial floor
    # whose core stands at the rear): a passage of corridor width across the
    # street band at the corridor's end nearer the core.
    entry: tuple[float, float, float, float] | None = None

    @property
    def free_region(self):
        """What is left for rooms: the cover less core, corridor and stair.

        Usually two pieces, one either side of the spine, so a MultiPolygon.
        """
        taken = [self.core, box(*self.spine)]
        if self.stair is not None:
            taken.append(box(*self.stair))
        if self.entry is not None:
            taken.append(box(*self.entry))
        free = self.cover
        for shape in taken:
            free = free.difference(shape)
        return free


def plan_floor_structure(
    boundary: Iterable[Point],
    program: ProgramGraph,
    *,
    core_polygon: Iterable[Point],
    corridor_width: float = 1.6,
    stair_dimensions: tuple[float, float] | None = None,
    stair_footprint: tuple[float, float, float, float] | None = None,
    stair_inset: float = 0.0,
    entry: bool = False,
) -> FloorStructure:
    """Cover, spine, bands, core and the remote stair for one floor.

    The stair is placed exactly as the topology solver places it when the
    street row is empty: against the spine at the end farther from the core,
    scanned inward until it fits the cover and its door clears the exit
    separation (half the plate's diameter).  ``stair_footprint`` fixes the box
    instead, for stacking.  ``stair_inset`` keeps the stair that far in from
    the far end so the primary room can wrap around the corridor's end.
    ``entry`` adds the public entrance: a passage of corridor width from the
    street edge to the corridor at its end nearer the core, for a floor
    whose rooms take the street edge and whose core stands at the rear.
    """
    if stair_footprint is not None:
        stair_dimensions = (
            stair_footprint[2] - stair_footprint[0],
            stair_footprint[3] - stair_footprint[1],
        )
    plate = Polygon(list(boundary))
    core = Polygon(list(core_polygon))
    cover = _rectilinear_cover(plate)
    plan = plan_double_loaded_spine(
        plate.bounds, core_bounds=core.bounds, program=program, corridor_width=corridor_width
    )
    sx0, sy0, sx1, sy1 = plan.spine
    spine_x0, spine_x1 = _longest_run(cover, sy0, sy1, sx0, sx1)
    if spine_x1 - spine_x0 <= _EPS:
        raise TopologyInfeasible(["the outline leaves no room for a corridor at the spine's depth"])
    spine = (spine_x0, sy0, spine_x1, sy1)
    street_band, core_band = (replace(band, x0=spine_x0, x1=spine_x1) for band in plan.bands)
    primaries = tuple(node for node in program.nodes if node.space_type in _PRIMARY)
    if not primaries:
        raise ValueError("floor structure needs a primary (residual) room")
    primary = primaries[0]
    exit_separation = _half_diameter(plate)
    entry_box = None
    if entry:
        at_left = abs(core.bounds[0] - spine_x0) <= abs(spine_x1 - core.bounds[2])
        ex0 = spine_x0 if at_left else spine_x1 - corridor_width
        ey0, ey1 = (street_band.y0, sy0) if street_band.y1 <= sy0 + _EPS else (sy1, street_band.y1)
        entry_box = (ex0, ey0, ex0 + corridor_width, ey1)
        if not cover.buffer(_EPS).covers(box(*entry_box)):
            raise TopologyInfeasible(["the outline has no room for the entrance at the corridor's end"])
    stair = None
    if stair_dimensions is not None:
        _, _, stair = _lay_street_side(
            street_band, [], primary, spine, cover, stair_dimensions,
            core=core, exit_separation=exit_separation, stair_footprint=stair_footprint,
            far_end_inset=stair_inset,
        )
    return FloorStructure(
        plate=plate,
        cover=cover,
        spine=spine,
        street_band=street_band,
        core_band=core_band,
        core=core,
        stair=stair,
        exit_separation=exit_separation,
        primary=primary,
        primaries=primaries,
        entry=entry_box,
    )


_Interval = tuple[float, float]


def _width_band(node: ProgramNode, depth: float) -> _Interval | None:
    """The widths at which a room of the row depth ``depth`` meets its own gates (area band, min width, aspect)."""
    target = float(node.target_area)
    low = float(node.min_area) if node.min_area else target * 0.85
    high = float(node.max_area) if node.max_area else target * 1.15
    aspect = float(node.max_aspect_ratio) if node.max_aspect_ratio else None
    lo = max(float(node.min_width or 0.0), low / depth, (depth / aspect) if aspect else 0.0)
    hi = min(high / depth, (aspect * depth) if aspect else high / depth)
    return (lo, hi) if lo <= hi + 1e-9 else None


def _union(intervals: Iterable[_Interval | None]) -> list[_Interval]:
    out: list[_Interval] = []
    for lo, hi in sorted(item for item in intervals if item is not None):
        if out and lo <= out[-1][1] + 1e-9:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


def _intersect(a: list[_Interval], b: list[_Interval]) -> list[_Interval]:
    out: list[_Interval] = []
    for a0, a1 in a:
        for b0, b1 in b:
            lo, hi = max(a0, b0), min(a1, b1)
            if lo <= hi + 1e-9:
                out.append((lo, hi))
    return _union(out)


def _row_depth_options(depth: float) -> list[float]:
    """The depths a core-side row can take: from three metres to the core's depth, by quarter metres."""
    out = []
    d = 3.0
    while d < depth - 1e-9:
        out.append(d)
        d += 0.25
    out.append(depth)
    return out


def core_flank_width(programs: Iterable[ProgramGraph], depth: float) -> float:
    """How far the core stands in from the plate's end, for the building.

    A core at the very end of the run has one flank, so one room can touch
    it.  A floor with two rooms bound to the core (restroom and utility on a
    commercial floor) needs a second flank between the plate's end and the
    core, wide enough for one of them at its row's depth.  The width is
    common to every floor, so it is chosen from the widths those floors'
    bound rooms accept at some row depth and, within that, from the widths
    every other floor can fill with one of its core-side rooms -- a flank no
    floor's room fits would be a pocket beside the core.  Among those, the
    width that lets the rows stay deepest wins.  Zero when no floor needs a
    second flank.
    """
    depths = _row_depth_options(depth)
    required: list[list[_Interval]] = []          # per floor needing the flank: widths its bound rooms accept
    fillable: list[list[tuple[float, list[_Interval]]]] = []  # per floor: (row depth, widths a room fills at it)
    for program in programs:
        graph = build_adjacency_graph(program)
        core = next((node for node in program.nodes if node.space_type == "core"), None)
        if core is None:
            continue
        rooms = [n for n in program.nodes if n.space_type not in _PRIMARY and n.node_id != core.node_id]
        bound = [n for n in rooms if frozenset({n.node_id, core.node_id}) in graph.required]
        core_side = [n for n in rooms if (n.zone or "") in _CORE_SIDE_ZONES or n in bound]
        by_depth = []
        accepted: list[_Interval] = []
        for d in depths:
            if any(_width_band(n, d) is None for n in core_side):
                continue  # no row of that depth holds every core-side room
            by_depth.append((d, _union(_width_band(n, d) for n in core_side)))
            if len(bound) >= 2:
                accepted.extend(_union(_width_band(n, d) for n in bound))
        if len(bound) >= 2:
            required.append(_union(accepted))
        fillable.append(by_depth)
    if not required:
        return 0.0
    feasible = required[0]
    for item in required[1:]:
        feasible = _intersect(feasible, item)
    if not feasible:
        raise TopologyInfeasible(["no flank width beside the core suits every floor's rooms bound to it"])

    def fit(width: float) -> tuple[float, float]:
        """(row depth lost over the floors, margin to the nearest band edge) for a flank of ``width``."""
        lost, margin = 0.0, math.inf
        for by_depth in fillable:
            fits = [(d, bands) for d, bands in by_depth if any(lo - 1e-9 <= width <= hi + 1e-9 for lo, hi in bands)]
            if not fits:
                lost += depth
                margin = 0.0
                continue
            d, bands = max(fits, key=lambda item: item[0])
            lost += depth - d
            margin = min(margin, max(min(width - lo, hi - width) for lo, hi in bands if lo - 1e-9 <= width <= hi + 1e-9))
        return lost, margin

    # The rows stay deepest first; then the width sits farthest inside the
    # bands, as the rooms are laid in whole grid cells around it.
    candidates = [round(lo + k * 0.05, 3) for lo, hi in feasible for k in range(int((hi - lo) / 0.05) + 1)]
    candidates.extend(hi for _, hi in feasible)
    return min(candidates, key=lambda w: (round(fit(w)[0], 6), -round(fit(w)[1], 6), w))


