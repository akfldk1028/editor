"""Topology-first layout: graph -> slicing plan -> LP widths -> polygons.

The result is checked against the adjacency graph it was built from.  A room
that does not reach the corridor, or a restroom that does not touch the core,
is a bug here and raises; it is not a metric to be averaged away.

Two depths are decided deterministically rather than inherited from the
plate.  On the core's side the band is as deep as the core, and a room whose
gates cannot be met at that depth is moved across the corridor instead of
having its gates widened.  On the street side the rooms take a depth chosen
from a grid to minimise the LP's deviation from target, and the primary room
absorbs the strip along the street frontage -- which is where open work
belongs.
"""

from __future__ import annotations

from collections.abc import Iterable

from shapely.geometry import Polygon
from shapely.ops import unary_union

from backend.app.modules.topology_planner.dimensioning import (
    RoomWidth,
    TopologyInfeasible,
    dimension_band,
)
from backend.app.modules.topology_planner.graph import (
    CORRIDOR,
    AdjacencyGraph,
    build_adjacency_graph,
)
from backend.app.modules.topology_planner.slicing import Band, plan_double_loaded_spine
from backend.app.schemas.layout import LayoutCandidate, Point, RoomPolygon
from backend.app.schemas.program import ProgramGraph, ProgramNode


_PRIMARY = frozenset({"open_work", "sales"})
_DOOR = 0.9
_EPS = 1e-6
_DEPTH_STEP = 0.5
_MIN_ROOM_DEPTH = 3.0


def generate_topology_layout(
    boundary: Iterable[Point],
    program: ProgramGraph,
    *,
    core_polygon: Iterable[Point],
    corridor_width: float = 1.6,
) -> LayoutCandidate:
    plate = Polygon(list(boundary))
    core = Polygon(list(core_polygon))
    graph = build_adjacency_graph(program)
    plan = plan_double_loaded_spine(
        plate.bounds, core_bounds=core.bounds, program=program, corridor_width=corridor_width
    )
    nodes = {node.node_id: node for node in program.nodes}
    core_node = next(node for node in program.nodes if node.space_type == "core")
    primary = next((node for node in program.nodes if node.node_id in _PRIMARY), None)
    if primary is None:
        raise ValueError("topology layout needs a primary (residual) room")

    street_band, core_band = plan.bands
    core_side_ids = [r for r in core_band.room_ids if r != primary.node_id]
    street_ids = [r for r in street_band.room_ids if r != primary.node_id]

    # Rooms that cannot meet their gates at the core's depth cross the corridor.
    kept: list[str] = []
    for room_id in core_side_ids:
        if _feasible_at_depth(nodes[room_id], core_band.depth):
            kept.append(room_id)
        else:
            street_ids.append(room_id)
    core_side_ids = kept

    rooms: list[RoomPolygon] = [
        RoomPolygon(core_node.node_id, core_node.space_type, _ring(core.bounds))
    ]
    rooms.extend(_lay_core_side(core_band, core, [nodes[r] for r in core_side_ids], primary, graph))
    rooms.extend(_lay_street_side(street_band, [nodes[r] for r in street_ids], primary, plan.spine))
    rooms = _merge_primary(rooms, primary.node_id)

    sx0, sy0, sx1, sy1 = plan.spine
    corridor = RoomPolygon(CORRIDOR, "circulation", _ring((sx0, sy0, sx1, sy1)))
    _verify_adjacency(graph, rooms, corridor)
    return LayoutCandidate(
        candidate_id=f"{program.project_id}-f{program.floor_index}-topology",
        project_id=program.project_id,
        floor_index=program.floor_index,
        rooms=rooms,
        circulation=[corridor],
        score=0.0,
    )


def _feasible_at_depth(node: ProgramNode, depth: float) -> bool:
    probe = Band("probe", 0.0, 0.0, 1e6, depth, (node.node_id,))
    try:
        dimension_band(probe, [node], residual_room_id=None)
    except TopologyInfeasible:
        return False
    return True


def _lay_core_side(
    band: Band,
    core: Polygon,
    room_nodes: list[ProgramNode],
    primary: ProgramNode,
    graph: AdjacencyGraph,
) -> list[RoomPolygon]:
    """Rooms beside the core, those that must touch it nearest, the rest outward."""
    cx0, _, cx1, _ = core.bounds
    usable = Band(band.name, band.x0, band.y0, band.x1 - (cx1 - cx0), band.y1, tuple(n.node_id for n in room_nodes))
    widths = {w.room_id: w.width for w in dimension_band(usable, room_nodes, residual_room_id=None)}
    must_touch = [n for n in room_nodes if frozenset({n.node_id, "core"}) in graph.required]
    others = [n for n in room_nodes if n not in must_touch]
    # Alternate sides starting to the right of the core so both flanks get a
    # core-adjacent room when two are required.
    right: list[ProgramNode] = []
    left: list[ProgramNode] = []
    for index, node in enumerate(must_touch + others):
        (right if index % 2 == 0 else left).append(node)

    out: list[RoomPolygon] = []
    x = cx1
    for node in right:
        out.append(RoomPolygon(node.node_id, node.space_type, _ring((x, band.y0, x + widths[node.node_id], band.y1))))
        x += widths[node.node_id]
    _residual(out, primary, x, band.x1, band, suffix="core_right")
    x = cx0
    for node in left:
        out.append(RoomPolygon(node.node_id, node.space_type, _ring((x - widths[node.node_id], band.y0, x, band.y1))))
        x -= widths[node.node_id]
    _residual(out, primary, band.x0, x, band, suffix="core_left")
    return out


def _lay_street_side(
    band: Band,
    room_nodes: list[ProgramNode],
    primary: ProgramNode,
    spine: tuple[float, float, float, float],
) -> list[RoomPolygon]:
    """Rooms hang off the corridor at a chosen depth; the primary takes the frontage strip."""
    primary_min = float(primary.min_width or 0.0)
    below_spine = abs(band.y1 - spine[1]) <= _EPS  # band sits under the spine
    best: tuple[float, float, tuple[RoomWidth, ...]] | None = None
    depth = _MIN_ROOM_DEPTH
    while depth <= band.depth - primary_min + _EPS or abs(depth - band.depth) <= _EPS:
        if depth > band.depth + _EPS:
            break
        strip = band.depth - depth
        if 0 < strip < primary_min - _EPS:
            depth += _DEPTH_STEP
            continue
        probe = Band(band.name, band.x0, 0.0, band.x1, depth, tuple(n.node_id for n in room_nodes))
        try:
            widths = dimension_band(probe, room_nodes, residual_room_id=None)
        except TopologyInfeasible:
            depth += _DEPTH_STEP
            continue
        deviation = sum(abs(w.width * depth - float(n.target_area)) for w, n in zip(widths, room_nodes))
        if best is None or deviation < best[0] - _EPS:
            best = (deviation, depth, widths)
        depth += _DEPTH_STEP
    if best is None:
        raise TopologyInfeasible([f"no room depth in [{_MIN_ROOM_DEPTH}, {band.depth}] serves the street-side rooms"])
    _, depth, widths = best

    if below_spine:
        room_y0, room_y1 = band.y1 - depth, band.y1
        strip_y0, strip_y1 = band.y0, band.y1 - depth
    else:
        room_y0, room_y1 = band.y0, band.y0 + depth
        strip_y0, strip_y1 = band.y0 + depth, band.y1
    out: list[RoomPolygon] = []
    x = band.x0
    for node, w in zip(room_nodes, widths):
        out.append(RoomPolygon(node.node_id, node.space_type, _ring((x, room_y0, x + w.width, room_y1))))
        x += w.width
    if band.x1 - x > _EPS:
        if band.x1 - x < primary_min - _EPS and strip_y1 - strip_y0 <= _EPS:
            raise TopologyInfeasible([f"{primary.node_id}: leftover {band.x1 - x:.2f} m beside the street rooms is under its {primary_min:.2f} m minimum"])
        out.append(RoomPolygon(f"{primary.node_id}::street_tail", primary.space_type, _ring((x, room_y0, band.x1, room_y1))))
    if strip_y1 - strip_y0 > _EPS:
        out.append(RoomPolygon(f"{primary.node_id}::frontage", primary.space_type, _ring((band.x0, strip_y0, band.x1, strip_y1))))
    return out


def _residual(out: list[RoomPolygon], primary: ProgramNode, x0: float, x1: float, band: Band, *, suffix: str) -> None:
    width = x1 - x0
    if width <= _EPS:
        return
    if width < float(primary.min_width or 0.0) - _EPS:
        raise TopologyInfeasible([f"{primary.node_id}: {width:.2f} m left on the {suffix} is under its {float(primary.min_width):.2f} m minimum"])
    out.append(RoomPolygon(f"{primary.node_id}::{suffix}", primary.space_type, _ring((x0, band.y0, x1, band.y1))))


def _merge_primary(rooms: list[RoomPolygon], primary_id: str) -> list[RoomPolygon]:
    prefix = f"{primary_id}::"
    parts = [Polygon(r.polygon) for r in rooms if r.room_id.startswith(prefix)]
    others = [r for r in rooms if not r.room_id.startswith(prefix)]
    if not parts:
        return rooms
    space_type = next(r.space_type for r in rooms if r.room_id.startswith(prefix))
    merged = unary_union(parts)
    pieces = [merged] if merged.geom_type == "Polygon" else sorted(merged.geoms, key=lambda g: (-g.area, g.bounds))
    return others + [
        RoomPolygon(primary_id if i == 0 else f"{primary_id}::{i + 1}", space_type, _coords(piece))
        for i, piece in enumerate(pieces)
    ]


def _verify_adjacency(graph: AdjacencyGraph, rooms: list[RoomPolygon], corridor: RoomPolygon) -> None:
    base = lambda room_id: room_id.split("::")[0]  # noqa: E731
    polys: dict[str, list[Polygon]] = {}
    for room in rooms:
        polys.setdefault(base(room.room_id), []).append(Polygon(room.polygon))
    corridor_poly = Polygon(corridor.polygon)
    present: list[tuple[str, str]] = []
    for room_id, pieces in polys.items():
        if any(_shares_door(p, corridor_poly) for p in pieces):
            present.append((room_id, CORRIDOR))
    ids = list(polys)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if any(_shares_door(pa, pb) for pa in polys[a] for pb in polys[b]):
                present.append((a, b))
    missing = graph.missing_required(present)
    if missing:
        raise ValueError("missing required adjacency: " + ", ".join(f"{a}-{b}" for a, b in missing))


def _shares_door(a: Polygon, b: Polygon) -> bool:
    return a.boundary.intersection(b.boundary).length + _EPS >= _DOOR


def _ring(bounds: tuple[float, float, float, float]) -> list[Point]:
    x0, y0, x1, y1 = bounds
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _coords(polygon: Polygon) -> list[Point]:
    return [(float(x), float(y)) for x, y in list(polygon.exterior.coords)[:-1]]
