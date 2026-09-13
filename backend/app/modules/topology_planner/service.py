"""Topology-first layout: graph -> slicing plan -> LP widths -> polygons.

The result is checked against the adjacency graph it was built from.  A room
that does not reach the corridor, or a restroom that does not touch the core,
is a bug here and raises; it is not a metric to be averaged away.

Which flank of the core -- or which side of the corridor -- each room takes
is a small combinatorial choice (a handful of rooms, three places each).  It
is searched exhaustively and scored by the linear program's deviation from
target, with a penalty for leaving the zone the slicing plan preferred.  That
replaces any greedy rule that would have to be patched per plate, and nothing
in the search can widen a gate: an assignment either satisfies every room's
band, width and aspect limit, or it is discarded.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from itertools import permutations, product

from shapely.geometry import Polygon
from shapely.ops import unary_union

from backend.app.modules.topology_planner.dimensioning import (
    TopologyInfeasible,
    dimension_band,
)
from backend.app.modules.topology_planner.graph import (
    CORRIDOR,
    AdjacencyGraph,
    build_adjacency_graph,
)
from backend.app.modules.layout_generator.orthogonal import (
    _centered_opening,
    _rectangle_cells,
)
from backend.app.modules.topology_planner.slicing import Band, plan_double_loaded_spine
from backend.app.schemas.layout import LayoutCandidate, Point, RoomPolygon
from backend.app.schemas.program import ProgramGraph, ProgramNode


_PRIMARY = frozenset({"open_work", "sales"})
_DOOR = 0.9
_EPS = 1e-6
# The LP returns widths with ~1e-6 of solver noise and the validator compares
# widths exactly, so every strip the primary must clear its minimum width in
# is asked for a millimetre more than the minimum.
_SLACK = 1e-3
# The validator's minimum circulation width: a strip narrower than this is
# not a passage and cannot become a corridor spur.
_MIN_PASSAGE = 1.2
_DEPTH_STEP = 0.5
_MIN_ROOM_DEPTH = 3.0
# Cost, in m2 of target deviation, of placing a room away from its zone's side.
_OFF_ZONE_PENALTY = 10.0
_PLACES = ("right", "left", "street")


def generate_topology_layout(
    boundary: Iterable[Point],
    program: ProgramGraph,
    *,
    core_polygon: Iterable[Point],
    corridor_width: float = 1.6,
    stair_dimensions: tuple[float, float] | None = None,
    stair_footprint: tuple[float, float, float, float] | None = None,
) -> LayoutCandidate:
    """``stair_dimensions`` is (length along the spine, depth off it) for the
    remote egress stair.  The stair is reserved against the spine at the end
    farther from the core, on the street side, so it shares a protected-exit
    width with the corridor by construction.  ``stair_footprint`` fixes the
    stair box instead (a stair stacks, so every floor must take the same
    one); the room row then ends against it."""
    if stair_footprint is not None:
        stair_dimensions = (
            stair_footprint[2] - stair_footprint[0],
            stair_footprint[3] - stair_footprint[1],
        )
    plate = Polygon(list(boundary))
    core = Polygon(list(core_polygon))
    graph = build_adjacency_graph(program)
    # Rooms and corridor stay axis-aligned.  Chamfers and notches in the
    # outline are left unassigned, exactly as the orthogonal generator leaves
    # them, so the plane everything is fitted to is the plate's rectilinear
    # cover rather than the plate itself.
    cover = _rectilinear_cover(plate)
    plan = plan_double_loaded_spine(
        plate.bounds, core_bounds=core.bounds, program=program, corridor_width=corridor_width
    )
    sx0, sy0, sx1, sy1 = plan.spine
    spine_x0, spine_x1 = _longest_run(cover, sy0, sy1, sx0, sx1)
    if spine_x1 - spine_x0 <= _EPS:
        raise TopologyInfeasible(["the outline leaves no room for a corridor at the spine's depth"])
    from dataclasses import replace as _replace

    plan = _replace(
        plan,
        spine=(spine_x0, sy0, spine_x1, sy1),
        bands=tuple(_replace(band, x0=spine_x0, x1=spine_x1) for band in plan.bands),
    )
    nodes = {node.node_id: node for node in program.nodes}
    core_node = next(node for node in program.nodes if node.space_type == "core")
    primary = next((node for node in program.nodes if node.space_type in _PRIMARY), None)
    if primary is None:
        raise ValueError("topology layout needs a primary (residual) room")

    street_band, core_band = plan.bands
    preferred = {
        **{r: "street" for r in street_band.room_ids if r != primary.node_id},
        **{r: "core" for r in core_band.room_ids if r != primary.node_id},
    }
    room_nodes = [nodes[r] for r in preferred]
    must_touch = {
        n.node_id for n in room_nodes if frozenset({n.node_id, "core"}) in graph.required
    }

    # The validator asks the two protected exits -- the core's door onto the
    # corridor and the remote stair's -- to be at least half the plate's
    # diameter apart.  Generated here, not checked afterwards.
    exit_separation = _half_diameter(plate)
    placed, stair = _search_assignment(
        room_nodes, must_touch, preferred, core_band, street_band, core, primary, plan.spine, cover,
        stair_dimensions, exit_separation, stair_footprint,
    )
    spurs = [Polygon(r.polygon) for r in placed if r.space_type == "circulation"]
    placed = [r for r in placed if r.space_type != "circulation"]

    # The corridor runs only as far as it has something to serve.  Beyond the
    # last room the open work wraps around both ends of it, which is what
    # makes the primary one polygon instead of pieces on either side.
    sx0, sy0, sx1, sy1 = plan.spine
    occupied = [core.bounds[0], core.bounds[2]]
    for room in placed:
        if not room.room_id.startswith(primary.node_id):
            x0, _, x1, _ = Polygon(room.polygon).bounds
            occupied.extend((x0, x1))
    for spur in spurs:
        occupied.extend((spur.bounds[0], spur.bounds[2]))
    if stair is not None:
        occupied.extend((stair[0], stair[2]))
    spine = (max(sx0, min(occupied)), sy0, min(sx1, max(occupied)), sy1)
    for gap_x0, gap_x1, name in ((sx0, spine[0], "spine_left"), (spine[2], sx1, "spine_right")):
        if gap_x1 - gap_x0 > _EPS:
            placed.append(RoomPolygon(f"{primary.node_id}::{name}", primary.space_type,
                                      _ring((gap_x0, sy0, gap_x1, sy1))))

    rooms: list[RoomPolygon] = [
        RoomPolygon(core_node.node_id, core_node.space_type, _ring(core.bounds)),
        *placed,
    ]
    rooms = _clip_to_cover(cover, rooms, primary.node_id)
    # Merge first: the strips wrapping the corridor ends are only as tall as
    # the corridor and would be eroded on their own, yet inside the merged
    # polygon they sit within a block wider than the minimum.
    rooms = _merge_primary(rooms, primary.node_id)
    rooms = _erode_primary_slivers(rooms, primary)
    rooms = _merge_primary(rooms, primary.node_id)
    split = [r.room_id for r in rooms if "::" in r.room_id]
    if split:
        raise TopologyInfeasible(
            [f"{primary.node_id} would be split into disconnected pieces: {', '.join(split)}"]
        )

    corridor_shape = unary_union([Polygon(_ring(spine)), *spurs])
    if corridor_shape.geom_type != "Polygon":
        raise TopologyInfeasible(["corridor spurs do not join the spine"])
    corridor = RoomPolygon(CORRIDOR, "circulation", _coords(corridor_shape))
    _verify_adjacency(graph, rooms, corridor)
    # Every room reaches the corridor (verified above); a primary piece that
    # does not touch it itself is reached through the piece that does.
    corridor_poly = Polygon(corridor.polygon)
    openings = [
        _centered_opening(room, [corridor])
        for room in rooms
        if _shares_door(Polygon(room.polygon), corridor_poly)
    ]
    return LayoutCandidate(
        candidate_id=f"{program.project_id}-f{program.floor_index}-topology",
        project_id=program.project_id,
        floor_index=program.floor_index,
        rooms=rooms,
        circulation=[corridor],
        score=0.0,
        openings=openings,
        remote_stair_footprint=(tuple(_ring(stair)) if stair is not None else None),
    )


def front_edge_core_x(
    boundaries: Iterable[Iterable[Point]],
    *,
    width: float,
    depth: float,
    min_y: float,
    flank: float = 0.0,
) -> float:
    """Left x of a core of ``width`` x ``depth`` on the front edge, at one end of the run every floor shares.

    A double-loaded spine puts the core at one end and the remote stair at
    the other, which is what separates the two exits by half the plate.  The
    end is the one that leaves the longer spine on the far side; ties go
    left.  ``flank`` keeps that much of the run between the plate's end and
    the core -- room for a second wet room bound to the core (see
    structure.core_flank_width).  Raises TopologyInfeasible when no
    floor-common run holds the core.
    """
    plates = [Polygon(list(b)) for b in boundaries]
    if not plates:
        raise ValueError("front_edge_core_x needs at least one floor boundary")
    run_x0, run_x1 = -math.inf, math.inf
    for plate in plates:
        cover = _rectilinear_cover(plate)
        x0, x1 = _longest_run(cover, min_y, min_y + depth, cover.bounds[0], cover.bounds[2])
        run_x0, run_x1 = max(run_x0, x0), min(run_x1, x1)
    if run_x1 - run_x0 < width + flank - _EPS:
        raise TopologyInfeasible(
            [f"the front edge shared by every floor is {max(0.0, run_x1 - run_x0):.2f} m, "
             f"under the core's {width:.2f} m plus its {flank:.2f} m flank"]
        )
    far_left = min(plate.bounds[0] for plate in plates)
    far_right = max(plate.bounds[2] for plate in plates)
    at_left = run_x0 + flank
    at_right = run_x1 - width - flank
    # Spine beyond the core when it sits at each end.
    spine_if_left = far_right - (at_left + width)
    spine_if_right = at_right - far_left
    return at_left if spine_if_left >= spine_if_right - _EPS else at_right


def _search_assignment(
    room_nodes: list[ProgramNode],
    must_touch: set[str],
    preferred: dict[str, str],
    core_band: Band,
    street_band: Band,
    core: Polygon,
    primary: ProgramNode,
    spine: tuple[float, float, float, float],
    plate: Polygon,
    stair_dimensions: tuple[float, float] | None,
    exit_separation: float = 0.0,
    stair_footprint: tuple[float, float, float, float] | None = None,
) -> tuple[list[RoomPolygon], tuple[float, float, float, float] | None]:
    """Every room to one of {right flank, left flank, street}; best LP cost wins."""
    cx0, _, cx1, _ = core.bounds
    # A flank is as long as the outline keeps the band's full depth inside it,
    # not as long as the bounding box: a chamfer beside the core shortens it,
    # and the LP has to know that rather than place a room into the chamfer.
    flank_lengths = {
        "right": _usable_run(plate, core_band.y0, core_band.y1, cx1, core_band.x1) - cx1,
        "left": cx0 - _usable_run(plate, core_band.y0, core_band.y1, cx0, core_band.x0),
    }
    street_cache: dict = {}
    best = None
    errors: list[str] = []

    choices = [
        ("right", "left") if node.node_id in must_touch else _PLACES for node in room_nodes
    ]
    for assignment in product(*choices):
        # Each flank: core-adjacent rooms nearest the core, the rest in every
        # order -- which room sits outermost decides how far apart the
        # support rooms end up, and the validator caps that spread.
        flank_options: dict[str, list[tuple[float, list[RoomPolygon]]]] = {}
        feasible = True
        for place in ("right", "left"):
            side = [n for n, p in zip(room_nodes, assignment) if p == place]
            touching = sorted((n for n in side if n.node_id in must_touch), key=lambda n: n.node_id)
            others = [n for n in side if n.node_id not in must_touch]
            options = []
            for order in permutations(others):
                try:
                    options.append(_lay_flank(
                        touching + list(order), flank_lengths[place], place, core_band,
                        cx0, cx1, primary, must_touch,
                    ))
                except TopologyInfeasible as error:
                    errors.append(str(error))
            if not options:
                feasible = False
                break
            flank_options[place] = options
        if not feasible:
            continue
        # The street row depends only on which rooms are beside the core, not
        # on their order, so it is laid once per assignment.
        placed = flank_options["right"][0][1] + flank_options["left"][0][1]
        street = tuple(n.node_id for n, p in zip(room_nodes, assignment) if p == "street")
        # Street rooms line up with the left extent of what sits beside the
        # core, so the corridor stops early at the right end and the open
        # work wraps around it there; that is what keeps the primary one piece.
        left_extent = min(
            [cx0] + [Polygon(r.polygon).bounds[0] for r in placed if not r.room_id.startswith(primary.node_id)]
        )
        # A flank that keeps a primary residual needs the corridor to stop
        # short on that end so the open work can wrap around and join it.
        wrap_left = any(r.room_id == f"{primary.node_id}::core_left" for r in placed)
        wrap_right = any(r.room_id == f"{primary.node_id}::core_right" for r in placed)
        # The wrap joins that residual through a neck beside the corridor's
        # end, and the neck must clear the primary's minimum width too: the
        # corridor may reach no farther than the residual's outer end less
        # that width.  The residual always sits at the flank's outer end, so
        # the limit does not depend on the flank's room order.
        wrap_limits = (
            next((Polygon(r.polygon).bounds[0] for r in placed
                  if r.room_id == f"{primary.node_id}::core_left"), None),
            next((Polygon(r.polygon).bounds[2] for r in placed
                  if r.room_id == f"{primary.node_id}::core_right"), None),
        )
        street_key = (street, round(left_extent, 6), wrap_left, wrap_right, wrap_limits)
        if street_key not in street_cache:
            street_nodes = [n for n in room_nodes if n.node_id in street]
            try:
                street_cache[street_key] = _lay_street_side(
                    street_band, street_nodes, primary, spine, plate, stair_dimensions,
                    start_x=left_extent, core=core, wrap_left=wrap_left, wrap_right=wrap_right,
                    wrap_limits=wrap_limits, exit_separation=exit_separation,
                    stair_footprint=stair_footprint,
                )
            except TopologyInfeasible as error:
                errors.append(str(error))
                street_cache[street_key] = None
        cached = street_cache[street_key]
        if cached is None:
            continue
        street_cost, street_rooms, street_stair = cached
        zone_penalty = _OFF_ZONE_PENALTY * sum(
            1
            for n, p in zip(room_nodes, assignment)
            if (preferred[n.node_id] == "street") != (p == "street")
        )
        clustered = False
        for right_cost, right_rooms in flank_options["right"]:
            for left_cost, left_rooms in flank_options["left"]:
                placed = right_rooms + left_rooms
                # The row's widths do not depend on its order, so the order
                # is chosen here: the one that keeps the support rooms
                # together with those beside the core.
                ordered = _order_street_row(street_rooms, placed, plate, primary.node_id)
                if ordered is None:
                    continue
                clustered = True
                cost = right_cost + left_cost + street_cost + zone_penalty
                if best is None or (cost, assignment) < (best[0], best[1]):
                    best = (cost, assignment, placed + ordered, street_stair)
        if not clustered:
            errors.append("support rooms spread over more than half the floor diagonal")
    if best is None:
        raise TopologyInfeasible(
            ["no assignment of rooms to the core flanks or the street side satisfies every gate"]
            + sorted(set(errors))[:6]
        )
    return best[2], best[3]


def _order_street_row(
    street_rooms: list[RoomPolygon],
    placed: list[RoomPolygon],
    plate: Polygon,
    primary_id: str,
) -> list[RoomPolygon] | None:
    """Permute the street row's rooms along their run until the support rooms cluster.

    The row is the contiguous run of non-primary rooms sharing one depth;
    every permutation keeps the same span, so the corridor, stair and wraps
    are unaffected.  The given order is tried first.  Returns the street
    rooms with the row reordered, or None when no order clusters.
    """
    row = [r for r in street_rooms if not r.room_id.startswith(primary_id)]
    rest = [r for r in street_rooms if r.room_id.startswith(primary_id)]
    if not row:
        return street_rooms if _supports_clustered(placed + street_rooms, plate) else None
    boxes = [Polygon(r.polygon).bounds for r in row]
    y0, y1 = boxes[0][1], boxes[0][3]
    if any(abs(b[1] - y0) > _EPS or abs(b[3] - y1) > _EPS for b in boxes):
        return street_rooms if _supports_clustered(placed + street_rooms, plate) else None
    start = min(b[0] for b in boxes)
    for order in permutations(range(len(row))):
        x = start
        reordered: list[RoomPolygon] = []
        for index in order:
            width = boxes[index][2] - boxes[index][0]
            reordered.append(RoomPolygon(row[index].room_id, row[index].space_type,
                                         _ring((x, y0, x + width, y1))))
            x += width
        if _supports_clustered(placed + reordered, plate):
            return rest + reordered
    return None


def _lay_flank(
    side: list[ProgramNode],
    length: float,
    place: str,
    band: Band,
    cx0: float,
    cx1: float,
    primary: ProgramNode,
    must_touch: set[str] = frozenset(),
) -> tuple[float, list[RoomPolygon]]:
    """Rooms along one flank of the core; the primary takes what is left, if enough."""
    primary_min = float(primary.min_width or 0.0)
    rooms: list[RoomPolygon] = []
    # The primary's residual on a flank is a room too: its short side must
    # clear the minimum width, and on a shallow band that is the depth.
    residual_ok = lambda width: width <= _EPS or (  # noqa: E731
        width >= primary_min + _SLACK and band.depth >= primary_min - _EPS
    )
    if not side:
        if not residual_ok(length):
            # Too narrow for the primary and holding no room.  Wide enough
            # for a passage, the corridor takes it as a spur along the core,
            # which gives the core a second circulation face; narrower than
            # that it is left unassigned, as the outline's chamfers are.
            # Either way its area is charged as cost so an assignment that
            # fills the flank with rooms wins whenever one exists.
            if length < _MIN_PASSAGE - _EPS:
                return length * band.depth, []
            spur = RoomPolygon(
                f"{CORRIDOR}::spur_{place}", "circulation",
                _flank_ring(place, 0.0, length, band, cx0, cx1),
            )
            return length * band.depth, [spur]
        _residual_piece(rooms, primary, place, length, band, cx0, cx1, offset=0.0)
        return 0.0, rooms
    cost = 0.0
    offset = 0.0
    row = list(side)
    # Two rooms that both have to touch the core cannot both be first in a
    # single row; they share the first slot as a column, one above the other.
    touching = [n for n in row if n.node_id in must_touch]
    if len(touching) >= 2:
        upper, lower = touching[0], touching[1]
        column_cost, column_width, split = _stack_column(upper, lower, band.depth)
        if band.y0 < band.y1:
            rooms.append(RoomPolygon(upper.node_id, upper.space_type,
                                     _flank_box(place, 0.0, column_width, band.y1 - split, band.y1, cx0, cx1)))
            rooms.append(RoomPolygon(lower.node_id, lower.space_type,
                                     _flank_box(place, 0.0, column_width, band.y0, band.y1 - split, cx0, cx1)))
        cost += column_cost
        offset = column_width
        row = [n for n in row if n is not upper and n is not lower]
    remaining = length - offset
    if row:
        flank = Band(band.name, 0.0, band.y0, remaining, band.y1, tuple(n.node_id for n in row))
        widths = dimension_band(flank, row, residual_room_id=None)
        leftover = remaining - sum(w.width for w in widths)
        if not residual_ok(leftover):
            # Two admissible regimes, both inside every room's own band: shrink
            # the rooms so a full-width residual fits, or stretch them so
            # nothing is left.  The lower deviation from target wins.
            options = []
            if remaining - (primary_min + _SLACK) > _EPS and band.depth >= primary_min - _EPS:
                shorter = Band(
                    band.name, 0.0, band.y0, remaining - (primary_min + _SLACK), band.y1, flank.room_ids
                )
                try:
                    options.append(dimension_band(shorter, row, residual_room_id=None))
                except TopologyInfeasible:
                    pass
            try:
                options.append(dimension_band(flank, row, residual_room_id=None, fill=True))
            except TopologyInfeasible as error:
                if not options:
                    raise error
            widths = min(
                options,
                key=lambda ws: sum(abs(w.width * band.depth - float(n.target_area)) for w, n in zip(ws, row)),
            )
            leftover = remaining - sum(w.width for w in widths)
            if 0 < leftover < primary_min - _EPS:
                leftover = 0.0 if abs(leftover) <= 1e-6 else leftover
        cost += sum(abs(w.width * band.depth - float(n.target_area)) for w, n in zip(widths, row))
        for index, (node, w) in enumerate(zip(row, widths)):
            width = w.width
            if index == len(row) - 1 and leftover <= _EPS and abs((offset + width) - length) <= 1e-5:
                # Solver noise on the filled flank: land exactly on its end.
                width = length - offset
            rooms.append(
                RoomPolygon(node.node_id, node.space_type, _flank_ring(place, offset, width, band, cx0, cx1))
            )
            offset += width
    else:
        leftover = remaining
        if not residual_ok(leftover):
            raise TopologyInfeasible(
                [f"{primary.node_id}: {leftover:.2f} m left beside the core column is under its minimum width"]
            )
    _residual_piece(rooms, primary, place, leftover, band, cx0, cx1, offset=offset)
    return cost, rooms


def _stack_column(upper: ProgramNode, lower: ProgramNode, depth: float) -> tuple[float, float, float]:
    """Two rooms one above the other beside the core, sharing one width.

    The depth split is scanned on a grid; at each split every room's feasible
    width interval (area band, minimum width, aspect limit) is intersected,
    and the width closest to both targets is taken.  Returns (cost, width,
    upper depth).  Infeasible at every split raises.
    """
    best: tuple[float, float, float] | None = None
    split = _MIN_ROOM_DEPTH
    while split <= depth - _MIN_ROOM_DEPTH + _EPS:
        lo = 0.0
        hi = float("inf")
        for node, d in ((upper, split), (lower, depth - split)):
            n_lo, n_hi = _width_interval(node, d)
            lo, hi = max(lo, n_lo), min(hi, n_hi)
        if lo <= hi + _EPS:
            targets = [float(upper.target_area) / split, float(lower.target_area) / (depth - split)]
            width = min(max(sum(targets) / 2, lo), hi)
            cost = abs(width * split - float(upper.target_area)) + abs(
                width * (depth - split) - float(lower.target_area)
            )
            if best is None or cost < best[0] - _EPS:
                best = (cost, width, split)
        split += _DEPTH_STEP
    if best is None:
        raise TopologyInfeasible(
            [f"{upper.node_id} and {lower.node_id} cannot share a column of depth {depth:.2f} m beside the core"]
        )
    return best


def _width_interval(node: ProgramNode, depth: float) -> tuple[float, float]:
    import math

    target = float(node.target_area)
    min_area = float(node.min_area) if node.min_area else target * 0.85
    max_area = float(node.max_area) if node.max_area else target * 1.15
    lo = max(min_area * (1 + 1e-7) / depth, float(node.min_width or 0.0))
    hi = max_area * (1 - 1e-7) / depth
    r = float(node.max_aspect_ratio) if node.max_aspect_ratio else math.inf
    if math.isfinite(r):
        lo = max(lo, depth / r)
        hi = min(hi, r * depth)
    return lo, hi


def _flank_box(place: str, offset: float, width: float, y0: float, y1: float, cx0: float, cx1: float) -> list[Point]:
    if place == "right":
        return _ring((cx1 + offset, y0, cx1 + offset + width, y1))
    return _ring((cx0 - offset - width, y0, cx0 - offset, y1))


def _flank_ring(
    place: str, offset: float, width: float, band: Band, cx0: float, cx1: float
) -> list[Point]:
    if place == "right":
        return _ring((cx1 + offset, band.y0, cx1 + offset + width, band.y1))
    return _ring((cx0 - offset - width, band.y0, cx0 - offset, band.y1))


def _residual_piece(
    rooms: list[RoomPolygon],
    primary: ProgramNode,
    place: str,
    width: float,
    band: Band,
    cx0: float,
    cx1: float,
    *,
    offset: float,
) -> None:
    if width <= _EPS:
        return
    rooms.append(
        RoomPolygon(
            f"{primary.node_id}::core_{place}",
            primary.space_type,
            _flank_ring(place, offset, width, band, cx0, cx1),
        )
    )


def _lay_street_side(
    band: Band,
    room_nodes: list[ProgramNode],
    primary: ProgramNode,
    spine: tuple[float, float, float, float],
    plate: Polygon,
    stair_dimensions: tuple[float, float] | None = None,
    start_x: float | None = None,
    core: Polygon | None = None,
    wrap_left: bool = False,
    wrap_right: bool = False,
    wrap_limits: tuple[float | None, float | None] = (None, None),
    exit_separation: float = 0.0,
    stair_footprint: tuple[float, float, float, float] | None = None,
    far_end_inset: float = 0.0,
) -> tuple[float, list[RoomPolygon], tuple[float, float, float, float] | None]:
    """Rooms hang off the corridor at a chosen depth; the primary takes the frontage strip.

    ``far_end_inset`` (empty row only) keeps the stair that far in from the
    run's far end, leaving the primary room to wrap around the corridor there.

    ``wrap_limits`` are the outer ends of the primary's residuals beside the
    core (left, right); a wrap-around on that side must leave the primary's
    minimum width between the corridor's end and that limit.

    The remote stair is placed against the spine at the far end of the room
    row (away from the core), so the corridor stops there and the open work
    wraps around both corridor ends.  Returns (cost, rooms, stair box).
    """
    primary_min = float(primary.min_width or 0.0)
    below_spine = abs(band.y1 - spine[1]) <= _EPS
    from shapely.geometry import box as _box

    covered = plate.buffer(_EPS)
    core_x = (core.bounds[0] + core.bounds[2]) / 2 if core is not None else (band.x0 + band.x1) / 2
    stair_len, stair_depth = stair_dimensions if stair_dimensions is not None else (0.0, 0.0)
    if below_spine:
        st_y1, st_y0 = spine[1], spine[1] - stair_depth
    else:
        st_y0, st_y1 = spine[3], spine[3] + stair_depth

    core_edge = None
    if core is not None:
        cx0, cy0, cx1, cy1 = core.bounds
        core_edge = (cx0, cx1, cy1 if cy1 <= spine[1] + _EPS else cy0)

    def stair_for(x0: float, x1: float, far_right: bool):
        """Stair box beside the row's far end, or None when there is no stair."""
        if stair_dimensions is None:
            return None
        if stair_footprint is not None:
            return stair_footprint
        sx0 = x1 if far_right else x0 - stair_len
        return (sx0, st_y0, sx0 + stair_len, st_y1)

    def stair_admissible(stair) -> bool:
        """Some pair of protected-exit doors is far enough apart.

        The basic design slides the core's door along the core/corridor
        boundary and puts the stair's at either end of the stair/corridor
        boundary, so what has to clear the target is the best pair of door
        openings, measured edge to edge as the basic design measures it.
        """
        if stair is None or core_edge is None or exit_separation <= 0:
            return True
        door_y = st_y1 if below_spine else st_y0
        cx0, cx1, cy = core_edge
        dy = abs(door_y - cy)
        core_doors = ((cx0, cx0 + _DOOR), (cx1 - _DOOR, cx1))
        stair_doors = ((stair[0], stair[0] + _DOOR), (stair[2] - _DOOR, stair[2]))
        best = max(
            math.hypot(max(0.0, b0 - a1, a0 - b1), dy)
            for a0, a1 in core_doors
            for b0, b1 in stair_doors
        )
        return best + _EPS >= exit_separation

    if not room_nodes:
        far_right = abs(band.x1 - core_x) >= abs(band.x0 - core_x)
        # No row: the stair sits at the core's far side of the band.
        stair = None
        if stair_footprint is not None:
            if not (covered.covers(_box(*stair_footprint)) and stair_admissible(stair_footprint)):
                raise TopologyInfeasible(["the stacked remote stair does not fit this floor"])
            stair = stair_footprint
        elif stair_dimensions is not None:
            anchor = band.x1 - stair_len - far_end_inset if far_right else band.x0 + far_end_inset
            step = -_SCAN_STEP if far_right else _SCAN_STEP
            x = anchor
            while band.x0 - _EPS <= x and x + stair_len <= band.x1 + _EPS:
                candidate = (x, st_y0, x + stair_len, st_y1)
                if covered.covers(_box(*candidate)) and stair_admissible(candidate):
                    stair = candidate
                    break
                x += step
            if stair is None:
                raise TopologyInfeasible(["no position along the spine keeps the remote stair inside the plate"])
        whole = Polygon(_ring((band.x0, band.y0, band.x1, band.y1)))
        if stair is not None:
            whole = whole.difference(Polygon(_ring(stair)))
        return 0.0, [
            RoomPolygon(f"{primary.node_id}::frontage", primary.space_type, _coords(piece))
            for piece in ([whole] if whole.geom_type == "Polygon" else list(whole.geoms))
        ], stair
    best = None
    depth = _MIN_ROOM_DEPTH
    while depth <= band.depth + _EPS:
        strip = band.depth - depth
        if 0 < strip < primary_min - _EPS:
            depth += _DEPTH_STEP
            continue
        ry0, ry1 = (band.y1 - depth, band.y1) if below_spine else (band.y0, band.y0 + depth)
        if strip > _EPS:
            fy0, fy1 = (band.y0, ry0) if below_spine else (ry1, band.y1)
            frontage = Polygon(_ring((band.x0, fy0, band.x1, fy1))).intersection(plate)
            if frontage.geom_type != "Polygon":
                frontage = max(frontage.geoms, key=lambda g: g.area)
            opened = _open_rectilinear(frontage, primary_min)
            if opened.is_empty or opened.geom_type != "Polygon":
                # A notch in the outline cuts the strip below the minimum width.
                depth += _DEPTH_STEP
                continue
        # Only the stretch of this strip the outline keeps fully inside can
        # hold rectangular rooms; the rest is the primary's, clipped later.
        run_x0, run_x1 = _longest_run(plate, ry0, ry1, band.x0, band.x1)
        cover_run_x0 = run_x0
        shallow = depth < primary_min - _EPS  # head/tail here could not be the primary
        if run_x1 - run_x0 <= _EPS:
            depth += _DEPTH_STEP
            continue
        clear = primary_min + _SLACK
        reserved = stair_len + (clear if wrap_left else 0.0) + (clear if wrap_right else 0.0)
        left_bound, right_bound = _wrap_bounds(run_x0, run_x1, wrap_left, wrap_right, wrap_limits)
        usable = (right_bound - left_bound) - (0.0 if shallow else reserved)
        if usable <= _EPS:
            depth += _DEPTH_STEP
            continue
        ids = tuple(n.node_id for n in room_nodes)
        # Row lengths to dimension at this depth.  Free stair: the LP picks
        # the length inside the usable run.  Fixed stair: the row ends against
        # the stair, so its length is set by where it may start -- flush with
        # the run's end (no head) or one cleared width in from it -- and the
        # rooms stretch or shrink within their bands to that length.
        trials: list[tuple[float, bool]] = [(usable, shallow)]
        if stair_footprint is not None and not shallow:
            far_right = abs(run_x1 - core_x) >= abs(run_x0 - core_x)
            if far_right:
                avail = stair_footprint[0] - left_bound
                heads = ([avail] if not wrap_left else []) + [avail - clear]
            else:
                avail = right_bound - stair_footprint[2]
                heads = ([avail] if not wrap_right else []) + [avail - clear]
            trials = [(length, True) for length in heads if length > _EPS]
        for length, fill in trials:
            probe = Band(band.name, run_x0, 0.0, run_x0 + length, depth, ids)
            try:
                widths = dimension_band(probe, room_nodes, residual_room_id=None, fill=fill)
            except TopologyInfeasible:
                continue
            placement = _place_row(
                run_x0, run_x1, sum(w.width for w in widths), primary_min + _SLACK, shallow,
                start_x, core_x, stair_len, stair_for, covered, wrap_left, wrap_right, wrap_limits,
                pocket=bool(stair_len) and depth > stair_depth + _EPS,
                stair_admissible=stair_admissible,
                fixed_stair=stair_footprint,
            )
            if placement is None:
                continue
            deviation = sum(
                abs(w.width * depth - float(n.target_area)) for w, n in zip(widths, room_nodes)
            )
            if placement[2]:
                # The strip above an end stair goes unassigned; charge it,
                # and with a stacked stair the setback strip beyond it too.
                deviation += stair_len * (depth - stair_depth)
                if stair_footprint is not None:
                    far_right = abs(run_x1 - core_x) >= abs(run_x0 - core_x)
                    beyond = (right_bound - stair_footprint[2]) if far_right else (stair_footprint[0] - left_bound)
                    if 0 < beyond < clear:
                        deviation += beyond * depth
            if best is None or deviation < best[0] - _EPS:
                best = (deviation, depth, widths, placement[0], run_x1, cover_run_x0, placement[1])
        depth += _DEPTH_STEP
    if best is None:
        raise TopologyInfeasible(
            [f"no room depth in [{_MIN_ROOM_DEPTH}, {band.depth}] serves the street-side rooms"]
        )
    deviation, depth, widths, run_x0, run_x1, cover_run_x0, stair = best

    if below_spine:
        room_y0, room_y1 = band.y1 - depth, band.y1
        strip_y0, strip_y1 = band.y0, band.y1 - depth
    else:
        room_y0, room_y1 = band.y0, band.y0 + depth
        strip_y0, strip_y1 = band.y0 + depth, band.y1
    out: list[RoomPolygon] = []
    if run_x0 - band.x0 > _EPS:
        head = Polygon(_ring((band.x0, room_y0, run_x0, room_y1)))
        if stair is not None:
            head = head.difference(Polygon(_ring(stair)))
        for piece in ([head] if head.geom_type == "Polygon" else list(head.geoms)):
            if piece.area > _EPS:
                out.append(RoomPolygon(f"{primary.node_id}::street_head", primary.space_type, _coords(piece)))
    x = run_x0
    for index, (node, w) in enumerate(zip(room_nodes, widths)):
        x1 = x + w.width
        if index == len(room_nodes) - 1 and stair is not None and abs(x1 - stair[0]) <= 1e-5:
            x1 = stair[0]  # solver noise: the row meets the stair edge exactly
        out.append(RoomPolygon(node.node_id, node.space_type, _ring((x, room_y0, x1, room_y1))))
        x = x1
    if band.x1 - x > _EPS:
        tail = Polygon(_ring((x, room_y0, band.x1, room_y1)))
        if stair is not None:
            tail = tail.difference(Polygon(_ring(stair)))
        for piece in ([tail] if tail.geom_type == "Polygon" else list(tail.geoms)):
            if piece.area > _EPS:
                out.append(RoomPolygon(f"{primary.node_id}::street_tail", primary.space_type, _coords(piece)))
    if stair is not None and strip_y1 - strip_y0 > _EPS:
        pass  # the frontage strip below is added next; the stair never reaches it
    if strip_y1 - strip_y0 > _EPS:
        out.append(
            RoomPolygon(
                f"{primary.node_id}::frontage",
                primary.space_type,
                _ring((band.x0, strip_y0, band.x1, strip_y1)),
            )
        )
    return deviation, out, stair


def _place_row(
    run_x0: float,
    run_x1: float,
    total: float,
    primary_min: float,
    shallow: bool,
    start_x: float | None,
    core_x: float,
    stair_len: float,
    stair_for,
    covered,
    wrap_left: bool = False,
    wrap_right: bool = False,
    wrap_limits: tuple[float | None, float | None] = (None, None),
    pocket: bool = False,
    stair_admissible=lambda stair: True,
    fixed_stair: tuple[float, float, float, float] | None = None,
):
    """Choose where the room row starts along its run.

    With ``fixed_stair`` the row has one place to be: ending against the
    stair box on its core side.

    ``pocket`` says the stair is shallower than the row, so the strip above it
    (as wide as the stair) is the primary's and must join the head or tail
    beside it into a block at least the primary's minimum width.

    The row plus its stair occupy [start, start + total + stair_len].  The head
    (before the row) and the tail (after the stair) are the open work's wrap
    around the corridor ends, so each must be nothing or at least the
    primary's minimum width -- unless the row is too shallow to hold the
    primary at all, in which case it fills the run.  Among admissible starts
    the one nearest the core-side occupancy wins.  Returns (start, stair) or
    None.
    """
    span = total + stair_len
    if shallow:
        # A row too shallow for the primary cannot carry a wrap-around either.
        if wrap_left or wrap_right or abs((run_x1 - run_x0) - total) > _EPS:
            return None
        stair = stair_for(run_x0, run_x1, True) if stair_len else None
        if not stair_admissible(stair):
            return None
        return run_x0, stair, False
    slack = (run_x1 - run_x0) - span
    if slack < -_EPS:
        return None
    left_bound, right_bound = _wrap_bounds(run_x0, run_x1, wrap_left, wrap_right, wrap_limits)
    far_right = abs(run_x1 - core_x) >= abs(run_x0 - core_x)
    target = start_x if start_x is not None else run_x0
    candidates: list[float] = []
    if fixed_stair is not None:
        start = fixed_stair[0] - total if far_right else fixed_stair[0]
        if run_x0 - _EPS <= start and start + span <= run_x1 + _EPS:
            candidates.append(start)
    else:
        x = run_x0
        while x <= run_x1 - span + _EPS:
            candidates.append(x)
            x += _SCAN_STEP
        if run_x1 - span not in candidates:
            candidates.append(run_x1 - span)
    admissible = []
    for pocket_allowed in ((False, True) if (pocket or fixed_stair is not None) else (False,)):
        for start in candidates:
            row_x0 = start + (stair_len if not far_right else 0.0)
            row_x1 = row_x0 + total
            head = row_x0 - left_bound - (stair_len if not far_right else 0.0)
            tail = right_bound - row_x1 - (stair_len if far_right else 0.0)
            head_ok = head >= primary_min - _EPS or (
                head <= _EPS and not wrap_left and (pocket_allowed or not (pocket and not far_right))
            )
            tail_ok = tail >= primary_min - _EPS or (
                tail <= _EPS and not wrap_right and (pocket_allowed or not (pocket and far_right))
            )
            if fixed_stair is not None and pocket_allowed:
                # Beyond a stacked stair the leftover is this floor's setback
                # offset; it goes unassigned rather than blocking the stack.
                if far_right and not wrap_right:
                    tail_ok = tail_ok or tail > _EPS
                if not far_right and not wrap_left:
                    head_ok = head_ok or head > _EPS
            if not (head_ok and tail_ok):
                continue
            stair = stair_for(row_x0, row_x1, far_right) if stair_len else None
            if stair is not None:
                from shapely.geometry import box as _box

                if not covered.covers(_box(*stair)) or not stair_admissible(stair):
                    continue
            admissible.append((abs(row_x0 - target), row_x0, stair, pocket_allowed))
        if admissible:
            break
    if not admissible:
        return None
    admissible.sort(key=lambda item: (item[0], item[1]))
    _, row_x0, stair, pocketed = admissible[0]
    return row_x0, stair, pocketed


def _wrap_bounds(
    run_x0: float,
    run_x1: float,
    wrap_left: bool,
    wrap_right: bool,
    wrap_limits: tuple[float | None, float | None],
) -> tuple[float, float]:
    """The run's ends as the wrap-around sees them.

    Where the open work wraps a corridor end to join its residual beside the
    core, the wrap is measured to that residual's outer end, not to the end
    of the street run, so the neck between the two clears the minimum width.
    """
    left_limit, right_limit = wrap_limits
    left = max(run_x0, left_limit) if wrap_left and left_limit is not None else run_x0
    right = min(run_x1, right_limit) if wrap_right and right_limit is not None else run_x1
    return left, right


_SUPPORT_TYPES = frozenset({"pantry", "restroom", "it_storage"})


def _supports_clustered(rooms: list[RoomPolygon], plate: Polygon) -> bool:
    """The validator's rule: support rooms within half the floor diagonal of each other."""
    import math

    points = [Polygon(r.polygon).centroid for r in rooms if r.space_type in _SUPPORT_TYPES]
    if len(points) < 2:
        return True
    min_x, min_y, max_x, max_y = plate.bounds
    diagonal = math.hypot(max_x - min_x, max_y - min_y)
    spread = max(a.distance(b) for i, a in enumerate(points) for b in points[i + 1 :])
    return spread <= 0.5 * diagonal + _EPS


def _erode_primary_slivers(rooms: list[RoomPolygon], primary: ProgramNode) -> list[RoomPolygon]:
    """Drop the parts of the primary narrower than its minimum width.

    Clipping to a chamfered outline leaves the open work thin arms along the
    cut corners.  A morphological opening by the minimum width removes them
    (mitred, so the result stays rectilinear); what it removes is left
    unassigned, as the orthogonal generator leaves its own chamfer slivers.
    """
    width = float(primary.min_width or 0.0)
    if width <= 0:
        return rooms
    out: list[RoomPolygon] = []
    for room in rooms:
        if not room.room_id.startswith(primary.node_id):
            out.append(room)
            continue
        opened = _open_rectilinear(Polygon(room.polygon), width)
        pieces = [opened] if opened.geom_type == "Polygon" else list(getattr(opened, "geoms", []))
        for index, piece in enumerate(pieces):
            if piece.area <= _EPS:
                continue
            # Always prefixed, so the merge that follows sees every piece.
            out.append(
                RoomPolygon(f"{primary.node_id}::eroded{index}", room.space_type, _coords(piece))
            )
    return out


_OPEN_TOL = 1e-3


def _open_rectilinear(polygon: Polygon, width: float):
    """Morphological opening of a rectilinear polygon by a ``width`` square.

    Erode and dilate by a millimetre less than the half width, so a part that
    is exactly ``width`` wide survives as a thin strip instead of a degenerate
    seam (the mitred dilation of a seam shoots off along it); then snap every
    coordinate back onto the source polygon's own grid, which returns the
    millimetre and leaves the opening exact.
    """
    radius = width / 2 - _OPEN_TOL
    if radius <= 0:
        return polygon
    opened = polygon.buffer(-radius, join_style=2).buffer(radius, join_style=2)
    if opened.is_empty:
        return opened
    xs = sorted({round(float(x), 6) for x, _ in polygon.exterior.coords})
    ys = sorted({round(float(y), 6) for _, y in polygon.exterior.coords})
    for ring in polygon.interiors:
        xs = sorted(set(xs) | {round(float(x), 6) for x, _ in ring.coords})
        ys = sorted(set(ys) | {round(float(y), 6) for _, y in ring.coords})

    def snap(value: float, grid: list[float]) -> float:
        nearest = min(grid, key=lambda g: abs(g - value))
        return nearest if abs(nearest - value) <= 3 * _OPEN_TOL else round(value, 6)

    def snap_polygon(piece: Polygon) -> Polygon:
        shell = [(snap(x, xs), snap(y, ys)) for x, y in piece.exterior.coords]
        holes = [[(snap(x, xs), snap(y, ys)) for x, y in ring.coords] for ring in piece.interiors]
        snapped = Polygon(shell, holes).buffer(0)
        return snapped

    pieces = [opened] if opened.geom_type == "Polygon" else list(opened.geoms)
    return unary_union([snap_polygon(piece) for piece in pieces if piece.area > _EPS])


def _merge_primary(rooms: list[RoomPolygon], primary_id: str) -> list[RoomPolygon]:
    prefix = f"{primary_id}::"
    parts = [Polygon(r.polygon) for r in rooms if r.room_id.startswith(prefix)]
    others = [r for r in rooms if not r.room_id.startswith(prefix)]
    if not parts:
        return rooms
    space_type = next(r.space_type for r in rooms if r.room_id.startswith(prefix))
    merged = unary_union(parts)
    pieces = (
        [merged]
        if merged.geom_type == "Polygon"
        else sorted(merged.geoms, key=lambda g: (-g.area, g.bounds))
    )
    return others + [
        RoomPolygon(primary_id if i == 0 else f"{primary_id}::{i + 1}", space_type, _coords(piece))
        for i, piece in enumerate(pieces)
    ]


def _rectilinear_cover(plate: Polygon) -> Polygon:
    """The union of axis-aligned cells of the plate's own coordinate grid."""
    cells = _rectangle_cells(plate, require_complete=False)
    cover = unary_union([Polygon(cell) for cell in cells])
    if cover.geom_type != "Polygon":
        cover = max(cover.geoms, key=lambda g: g.area)
    return cover


def _clip_to_cover(
    cover: Polygon,
    rooms: list[RoomPolygon],
    primary_id: str,
) -> list[RoomPolygon]:
    """Keep every polygon inside the rectilinear cover.

    Non-primary rooms are placed inside it by construction; one that is not is
    a real conflict and is reported, not quietly shrunk.  Primary pieces are
    clipped to the cover, which keeps them rectilinear.
    """
    covered = cover.buffer(_EPS)
    clipped: list[RoomPolygon] = []
    for room in rooms:
        polygon = Polygon(room.polygon)
        if not room.room_id.startswith(primary_id):
            if not covered.covers(polygon):
                lost = 1.0 - polygon.intersection(cover).area / polygon.area
                raise TopologyInfeasible(
                    [f"{room.room_id}: {lost:.0%} of the room falls outside the plate outline"]
                )
            clipped.append(room)
            continue
        inside = polygon.intersection(cover)
        if inside.geom_type != "Polygon":
            inside = max(inside.geoms, key=lambda g: g.area)
        if inside.area <= _EPS:
            continue
        clipped.append(RoomPolygon(room.room_id, room.space_type, _coords(inside)))
    return clipped


def _verify_adjacency(
    graph: AdjacencyGraph, rooms: list[RoomPolygon], corridor: RoomPolygon
) -> None:
    polys: dict[str, list[Polygon]] = {}
    for room in rooms:
        polys.setdefault(room.room_id.split("::")[0], []).append(Polygon(room.polygon))
    corridor_poly = Polygon(corridor.polygon)
    present: list[tuple[str, str]] = []
    for room_id, pieces in polys.items():
        if any(_shares_door(p, corridor_poly) for p in pieces):
            present.append((room_id, CORRIDOR))
    ids = list(polys)
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            if any(_shares_door(pa, pb) for pa in polys[a] for pb in polys[b]):
                present.append((a, b))
    missing = graph.missing_required(present)
    if missing:
        raise ValueError(
            "missing required adjacency: " + ", ".join(f"{a}-{b}" for a, b in missing)
        )


_SCAN_STEP = 0.25


def _usable_run(plate: Polygon, y0: float, y1: float, start: float, stop: float) -> float:
    """Farthest x from ``start`` toward ``stop`` with the strip [y0, y1] fully inside the plate."""
    from shapely.geometry import box

    direction = 1.0 if stop >= start else -1.0
    covered = plate.buffer(_EPS)
    x = start
    while abs(stop - x) > _EPS:
        nxt = x + direction * min(_SCAN_STEP, abs(stop - x))
        cell = box(min(x, nxt), y0, max(x, nxt), y1)
        if not covered.covers(cell):
            break
        x = nxt
    return x


def _longest_run(plate: Polygon, y0: float, y1: float, x0: float, x1: float) -> tuple[float, float]:
    """Longest x-interval in [x0, x1] whose full-depth strip [y0, y1] is inside the plate."""
    from shapely.geometry import box

    covered = plate.buffer(_EPS)
    best = (x0, x0)
    run_start = None
    x = x0
    while x < x1 - _EPS:
        nxt = min(x + _SCAN_STEP, x1)
        inside = covered.covers(box(x, y0, nxt, y1))
        if inside and run_start is None:
            run_start = x
        if (not inside or nxt >= x1 - _EPS) and run_start is not None:
            run_end = nxt if inside else x
            if run_end - run_start > best[1] - best[0]:
                best = (run_start, run_end)
            run_start = None
        x = nxt
    return best


def _half_diameter(plate: Polygon) -> float:
    """Half the longest distance between two outline vertices -- the validator's exit separation target."""
    points = list(plate.exterior.coords)[:-1]
    return max(math.dist(a, b) for i, a in enumerate(points) for b in points[i + 1 :]) / 2


def _shares_door(a: Polygon, b: Polygon) -> bool:
    return a.boundary.intersection(b.boundary).length + _EPS >= _DOOR


def _ring(bounds: tuple[float, float, float, float]) -> list[Point]:
    # Same micron snap as _coords, so every polygon shares exact edge lines.
    x0, y0, x1, y1 = (round(float(v), 6) for v in bounds)
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _coords(polygon: Polygon) -> list[Point]:
    # Snapped to a micron: the erosion/dilation buffers leave 1e-15 drift that
    # breaks collinearity with the corridor edge, and a shared edge that is
    # not exactly collinear reads as a point contact.
    ring = [(round(float(x), 6), round(float(y), 6)) for x, y in list(polygon.exterior.coords)[:-1]]
    # Drop consecutive duplicates the snap may create.
    cleaned: list[Point] = []
    for point in ring:
        if not cleaned or point != cleaned[-1]:
            cleaned.append(point)
    if len(cleaned) > 1 and cleaned[0] == cleaned[-1]:
        cleaned.pop()
    return cleaned
