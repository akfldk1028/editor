"""The floor's fixed structure, planned once and shared by every room solver.

Corridor spine, core, remote stair and the rectilinear cover are decided
before any room is placed -- the topology solver and the growth solver both
start from the same ``FloorStructure``, so the vertical elements stack the
same way whichever solver partitions the rooms.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace

from shapely.geometry import Polygon, box

from backend.app.modules.topology_planner.dimensioning import TopologyInfeasible
from backend.app.modules.topology_planner.service import (
    _EPS,
    _PRIMARY,
    _half_diameter,
    _lay_street_side,
    _longest_run,
    _rectilinear_cover,
)
from backend.app.modules.topology_planner.slicing import Band, plan_double_loaded_spine
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

    @property
    def free_region(self):
        """What is left for rooms: the cover less core, corridor and stair.

        Usually two pieces, one either side of the spine, so a MultiPolygon.
        """
        taken = [self.core, box(*self.spine)]
        if self.stair is not None:
            taken.append(box(*self.stair))
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
) -> FloorStructure:
    """Cover, spine, bands, core and the remote stair for one floor.

    The stair is placed exactly as the topology solver places it when the
    street row is empty: against the spine at the end farther from the core,
    scanned inward until it fits the cover and its door clears the exit
    separation (half the plate's diameter).  ``stair_footprint`` fixes the box
    instead, for stacking.  ``stair_inset`` keeps the stair that far in from
    the far end so the primary room can wrap around the corridor's end.
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
    primary = next((node for node in program.nodes if node.node_id in _PRIMARY), None)
    if primary is None:
        raise ValueError("floor structure needs a primary (residual) room")
    exit_separation = _half_diameter(plate)
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
    )
