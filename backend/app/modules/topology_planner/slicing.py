"""The topology decision: a spine and two bands, rooms assigned by zone.

Nothing here has room widths.  It says which side of the corridor each room
is on and that the corridor runs the length of the plate, which is the
double-loaded arrangement that halves every room's depth.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.schemas.program import ProgramGraph


_PRIMARY = frozenset({"open_work", "sales"})
_CORE_SIDE_ZONES = frozenset({"service", "core"})
_TOLERANCE = 1e-6


@dataclass(frozen=True)
class Band:
    name: str
    x0: float
    y0: float
    x1: float
    y1: float
    room_ids: tuple[str, ...]

    @property
    def length(self) -> float:
        return self.x1 - self.x0

    @property
    def depth(self) -> float:
        return self.y1 - self.y0


@dataclass(frozen=True)
class SlicingPlan:
    spine: tuple[float, float, float, float]
    bands: tuple[Band, Band]
    axis: str


def plan_double_loaded_spine(
    bounds: tuple[float, float, float, float],
    *,
    core_bounds: tuple[float, float, float, float],
    program: ProgramGraph,
    corridor_width: float = 1.6,
) -> SlicingPlan:
    min_x, min_y, max_x, max_y = bounds
    _, cy0, _, cy1 = core_bounds
    width, depth = max_x - min_x, max_y - min_y
    if width < depth:
        raise ValueError("double-loaded spine expects the plate's long axis along x")
    core_at_rear = abs(cy1 - max_y) <= _TOLERANCE
    core_at_front = abs(cy0 - min_y) <= _TOLERANCE
    if not (core_at_rear or core_at_front):
        raise ValueError("core must sit on the plate's rear or front edge")

    # The spine hugs the core's inner edge so the core opens onto it.
    if core_at_rear:
        spine_y1 = cy0
        spine_y0 = spine_y1 - corridor_width
    else:
        spine_y0 = cy1
        spine_y1 = spine_y0 + corridor_width
    spine = (min_x, spine_y0, max_x, spine_y1)

    rooms = [node for node in program.nodes if node.space_type != "core"]
    primary = tuple(node.node_id for node in rooms if node.space_type in _PRIMARY)
    core_side_ids = tuple(
        node.node_id
        for node in rooms
        if (node.zone or "") in _CORE_SIDE_ZONES and node.space_type not in _PRIMARY
    )
    other_ids = tuple(
        node.node_id
        for node in rooms
        if node.node_id not in core_side_ids and node.space_type not in _PRIMARY
    )

    if core_at_rear:
        core_band = Band("core_side", min_x, spine_y1, max_x, max_y, (*core_side_ids, *primary))
        street_band = Band("street_side", min_x, min_y, max_x, spine_y0, (*other_ids, *primary))
    else:
        core_band = Band("core_side", min_x, min_y, max_x, spine_y0, (*core_side_ids, *primary))
        street_band = Band("street_side", min_x, spine_y1, max_x, max_y, (*other_ids, *primary))
    return SlicingPlan(spine=spine, bands=(street_band, core_band), axis="x")
