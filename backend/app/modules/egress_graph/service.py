from __future__ import annotations

from dataclasses import dataclass
import heapq
import math

from backend.engine.geometry.polygon import validate_polygon

from backend.app.schemas.egress import (
    FloorEgressGraphResult,
    RoomTravelEvidence,
    RouteEdge,
    RouteEdgeKind,
    RouteNode,
    RouteNodeKind,
)
from backend.app.schemas.layout import (
    LayoutCandidate,
    OpeningSegment,
    PlanLine,
    Point,
)

_DEFAULT_TOLERANCE_M = 1e-6
_MIN_TOLERANCE_M = 1e-9
_MAX_TOLERANCE_M = 1e-3


@dataclass(frozen=True)
class _Space:
    source_id: str
    polygon: tuple[Point, ...]
    is_lobby: bool = False


@dataclass(frozen=True)
class _PointSpec:
    node_id: str
    kind: RouteNodeKind
    host_id: str


@dataclass
class _Graph:
    nodes: dict[str, RouteNode]
    edges: list[RouteEdge]
    adjacency: dict[str, list[tuple[str, float]]]

    @classmethod
    def empty(cls) -> _Graph:
        return cls(nodes={}, edges=[], adjacency={})

    def add_node(self, node: RouteNode) -> None:
        existing = self.nodes.get(node.node_id)
        if existing is not None and existing != node:
            raise ValueError(f"conflicting route node id: {node.node_id}")
        self.nodes[node.node_id] = node
        self.adjacency.setdefault(node.node_id, [])

    def add_edge(self, edge: RouteEdge) -> None:
        self.edges.append(edge)
        self.adjacency[edge.source_id].append(
            (edge.target_id, float(edge.length_m))
        )
        self.adjacency[edge.target_id].append(
            (edge.source_id, float(edge.length_m))
        )


@dataclass(frozen=True)
class _RoomRoute:
    candidate_point: Point
    exit_id: str
    distance_m: float
    node_ids: tuple[str, ...]
    polyline: tuple[Point, ...]


def measure_traversable_egress(
    *,
    layout: LayoutCandidate,
    floor_boundary: tuple[Point, ...],
    occupied_room_ids: tuple[str, ...],
    tolerance_m: float = _DEFAULT_TOLERANCE_M,
) -> FloorEgressGraphResult:
    _validate_call(layout, floor_boundary, occupied_room_ids, tolerance_m)
    rooms = {room.room_id: room for room in layout.rooms}
    occupied_rooms = tuple(rooms[room_id] for room_id in occupied_room_ids)

    floor_polygon, reason = _validated_polygon(
        floor_boundary,
        tolerance_m,
    )
    if reason is not None:
        return _unsupported_result(
            layout.floor_index,
            occupied_room_ids,
            (reason,),
        )
    assert floor_polygon is not None

    room_spaces: dict[str, _Space] = {}
    circulation_spaces: list[_Space] = []
    geometry_reasons: list[str] = []
    for room in occupied_rooms:
        polygon, room_reason = _validated_polygon(
            tuple(room.polygon),
            tolerance_m,
        )
        if room_reason is not None:
            geometry_reasons.append(f"{room_reason}:{room.room_id}")
            continue
        assert polygon is not None
        if not _polygon_within(polygon, floor_polygon, tolerance_m):
            geometry_reasons.append(f"geometry_out_of_boundary:{room.room_id}")
        elif not _is_rectangle(polygon, tolerance_m):
            geometry_reasons.append(f"concave_room_unsupported:{room.room_id}")
        else:
            room_spaces[room.room_id] = _Space(room.room_id, polygon)
    for circulation in layout.circulation:
        polygon, circulation_reason = _validated_polygon(
            tuple(circulation.polygon),
            tolerance_m,
        )
        if circulation_reason is not None:
            geometry_reasons.append(
                f"{circulation_reason}:{circulation.room_id}"
            )
            continue
        assert polygon is not None
        if not _polygon_within(polygon, floor_polygon, tolerance_m):
            geometry_reasons.append(
                f"geometry_out_of_boundary:{circulation.room_id}"
            )
        else:
            circulation_spaces.append(
                _Space(circulation.room_id, polygon)
            )
    lobbies, lobby_reasons = _connected_lobbies(
        layout,
        tuple(circulation_spaces),
        floor_polygon,
        tolerance_m,
    )
    circulation_spaces.extend(lobbies)
    geometry_reasons.extend(lobby_reasons)
    if not circulation_spaces:
        geometry_reasons.append("circulation_geometry_missing")
    if geometry_reasons:
        return _unsupported_result(
            layout.floor_index,
            occupied_room_ids,
            tuple(dict.fromkeys(geometry_reasons)),
        )

    valid_openings, opening_reasons = _validated_openings(
        layout.openings,
        room_spaces,
        tuple(circulation_spaces),
        occupied_room_ids,
        tolerance_m,
    )
    exits, exit_reasons = _validated_exits(
        layout,
        tuple(circulation_spaces),
        floor_polygon,
        tolerance_m,
    )
    unresolved = list(opening_reasons)
    unresolved.extend(exit_reasons)
    unresolved.extend(
        f"multiple_room_doors_farthest_candidates_unsupported:{room_id}"
        for room_id, openings in valid_openings.items()
        if len(openings) > 1
    )
    if not exits:
        unresolved.append("protected_exit_portal_missing")

    graph = _Graph.empty()
    point_specs: dict[Point, _PointSpec] = {}
    portal_conflict = False
    for room_id in occupied_room_ids:
        for opening in valid_openings.get(room_id, ()):
            point = _midpoint(opening.start, opening.end)
            spec = _PointSpec(
                node_id=f"opening:{opening.opening_id}:circulation",
                kind="room_door_portal",
                host_id=_circulation_id(opening, room_id),
            )
            if point in point_specs and point_specs[point] != spec:
                portal_conflict = True
            point_specs[point] = spec
    for exit_line in exits:
        point = _midpoint(exit_line.points[0], exit_line.points[-1])
        spec = _PointSpec(
            node_id=f"exit:{exit_line.line_id}:circulation",
            kind="circulation_vertex",
            host_id=exit_line.host_id or "circulation",
        )
        if point in point_specs and point_specs[point] != spec:
            portal_conflict = True
        point_specs[point] = spec
    if portal_conflict:
        unresolved.append("ambiguous_portal_location")

    _add_space_graph(
        graph,
        tuple(circulation_spaces),
        point_specs,
        prefix="circulation",
        default_kind="circulation_vertex",
        default_edge_kind="inside_circulation",
        tolerance_m=tolerance_m,
    )
    exit_node_to_id: dict[str, str] = {}
    for exit_line in exits:
        point = _midpoint(exit_line.points[0], exit_line.points[-1])
        circulation_node_id = point_specs[point].node_id
        exit_node_id = f"exit:{exit_line.line_id}"
        graph.add_node(
            RouteNode(
                node_id=exit_node_id,
                kind="protected_exit_portal",
                point=point,
                host_id=exit_line.target_id or exit_line.host_id or "exit",
            )
        )
        graph.add_edge(
            RouteEdge(
                source_id=circulation_node_id,
                target_id=exit_node_id,
                kind="through_protected_exit",
                length_m=0.0,
                polyline=(point, point),
                source_geometry_ids=tuple(
                    dict.fromkeys(
                        (
                            exit_line.line_id,
                            exit_line.target_id or exit_line.host_id or "exit",
                        )
                    )
                ),
            )
        )
        exit_node_to_id[exit_node_id] = exit_line.line_id

    candidate_ids: dict[str, tuple[str, ...]] = {}
    for room_id in occupied_room_ids:
        room_space = room_spaces.get(room_id)
        if room_space is None:
            continue
        room_point_specs = {
            point: _PointSpec(
                node_id=f"room:{room_id}:candidate:{index}",
                kind="room_farthest_candidate",
                host_id=room_id,
            )
            for index, point in enumerate(room_space.polygon)
        }
        candidate_ids[room_id] = tuple(
            spec.node_id for spec in room_point_specs.values()
        )
        for opening in valid_openings.get(room_id, ()):
            point = _midpoint(opening.start, opening.end)
            if point in room_point_specs:
                unresolved.append(f"ambiguous_room_portal:{opening.opening_id}")
                continue
            room_node_id = f"opening:{opening.opening_id}:room"
            room_point_specs[point] = _PointSpec(
                node_id=room_node_id,
                kind="room_door_portal",
                host_id=room_id,
            )
        _add_space_graph(
            graph,
            (room_space,),
            room_point_specs,
            prefix=f"room:{room_id}",
            default_kind="room_farthest_candidate",
            default_edge_kind="inside_room",
            tolerance_m=tolerance_m,
        )
        for opening in valid_openings.get(room_id, ()):
            point = _midpoint(opening.start, opening.end)
            room_node_id = f"opening:{opening.opening_id}:room"
            circulation_node_id = f"opening:{opening.opening_id}:circulation"
            if (
                room_node_id not in graph.nodes
                or circulation_node_id not in graph.nodes
            ):
                unresolved.append(f"invalid_opening_portal:{opening.opening_id}")
                continue
            graph.add_edge(
                RouteEdge(
                    source_id=room_node_id,
                    target_id=circulation_node_id,
                    kind="through_opening",
                    length_m=0.0,
                    polyline=(point, point),
                    source_geometry_ids=(opening.opening_id,),
                )
            )

    room_results: list[RoomTravelEvidence] = []
    for room_id in occupied_room_ids:
        room_unresolved = [
            reason
            for reason in unresolved
            if reason.endswith(f":{room_id}")
            or reason.startswith("protected_exit_portal_")
        ]
        openings = valid_openings.get(room_id, ())
        if not openings:
            room_unresolved.append(f"valid_room_door_missing:{room_id}")
        if not exit_node_to_id:
            room_unresolved.append("protected_exit_portal_missing")
        if room_unresolved:
            room_results.append(
                _not_checked_room(
                    layout.floor_index,
                    room_id,
                    tuple(dict.fromkeys(room_unresolved)),
                )
            )
            continue
        route, route_reason = _farthest_room_route(
            graph,
            candidate_ids[room_id],
            exit_node_to_id,
            tolerance_m,
        )
        if route is None:
            reason = route_reason or f"unreachable_occupied_room:{room_id}"
            unresolved.append(reason)
            room_results.append(
                _not_checked_room(
                    layout.floor_index,
                    room_id,
                    (reason,),
                )
            )
            continue
        room_results.append(
            RoomTravelEvidence(
                floor_index=layout.floor_index,
                room_id=room_id,
                farthest_point=route.candidate_point,
                nearest_exit_id=route.exit_id,
                distance_m=route.distance_m,
                route_node_ids=route.node_ids,
                route_polyline=route.polyline,
                status="checked",
                unresolved_facts=(),
            )
        )

    travel_checked = (
        not portal_conflict
        and not opening_reasons
        and not exit_reasons
        and bool(room_results)
        and all(room.status == "checked" for room in room_results)
    )
    common_distance = None
    common_status = "not_checked"
    dead_end_distance = None
    dead_end_status = "not_checked"
    if travel_checked and len(exit_node_to_id) == 2:
        unresolved.append("common_path_unique_route_unverified")
    else:
        unresolved.append("common_path_topology_unresolved")
    unresolved.append("dead_end_topology_unresolved")
    unresolved = list(dict.fromkeys(unresolved))

    if not travel_checked:
        return FloorEgressGraphResult(
            floor_index=layout.floor_index,
            status="not_checked",
            nodes=tuple(graph.nodes.values()),
            edges=tuple(graph.edges),
            room_results=tuple(room_results),
            governing_room_id=None,
            governing_distance_m=None,
            governing_exit_id=None,
            common_path_distance_m=common_distance,
            common_path_status=common_status,
            dead_end_distance_m=dead_end_distance,
            dead_end_status=dead_end_status,
            unresolved_facts=tuple(unresolved),
        )

    governing = max(
        room_results,
        key=lambda room: (room.distance_m or 0.0, room.room_id),
    )
    return FloorEgressGraphResult(
        floor_index=layout.floor_index,
        status="checked",
        nodes=tuple(graph.nodes.values()),
        edges=tuple(graph.edges),
        room_results=tuple(room_results),
        governing_room_id=governing.room_id,
        governing_distance_m=governing.distance_m,
        governing_exit_id=governing.nearest_exit_id,
        common_path_distance_m=common_distance,
        common_path_status=common_status,
        dead_end_distance_m=dead_end_distance,
        dead_end_status=dead_end_status,
        unresolved_facts=tuple(unresolved),
    )


def _validate_call(
    layout: LayoutCandidate,
    floor_boundary: tuple[Point, ...],
    occupied_room_ids: tuple[str, ...],
    tolerance_m: float,
) -> None:
    if not isinstance(layout, LayoutCandidate):
        raise TypeError("layout must be LayoutCandidate")
    if not isinstance(floor_boundary, tuple):
        raise TypeError("floor_boundary must be an immutable point tuple")
    if (
        not isinstance(occupied_room_ids, tuple)
        or not occupied_room_ids
        or any(
            not isinstance(room_id, str) or not room_id.strip()
            for room_id in occupied_room_ids
        )
        or len(occupied_room_ids) != len(set(occupied_room_ids))
    ):
        raise ValueError(
            "occupied_room_ids must be a non-empty tuple of unique room ids"
        )
    known_ids = {room.room_id for room in layout.rooms}
    if any(room_id not in known_ids for room_id in occupied_room_ids):
        raise ValueError("occupied_room_ids must reference layout rooms")
    if (
        not isinstance(tolerance_m, (int, float))
        or isinstance(tolerance_m, bool)
        or not math.isfinite(tolerance_m)
        or not _MIN_TOLERANCE_M <= tolerance_m <= _MAX_TOLERANCE_M
    ):
        raise ValueError(
            "tolerance_m must be finite and within the supported range"
        )


def _validated_polygon(
    raw_points: tuple[Point, ...],
    tolerance_m: float,
) -> tuple[tuple[Point, ...] | None, str | None]:
    if not isinstance(raw_points, tuple):
        return None, "invalid_polygon"
    points = raw_points[:-1] if len(raw_points) > 1 and raw_points[0] == raw_points[-1] else raw_points
    if len(set(points)) < 4:
        return None, "polygon_too_few_vertices"
    if any(
        not isinstance(point, tuple)
        or len(point) != 2
        or any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            for value in point
        )
        for point in points
    ):
        return None, "non_finite_polygon"
    normalized = tuple((float(x), float(y)) for x, y in points)
    if any(
        not _axis_aligned(start, end, tolerance_m)
        for start, end in _polygon_edges(normalized)
    ):
        return None, "non_axis_aligned_polygon"
    if abs(_signed_area(normalized)) <= tolerance_m * tolerance_m:
        return None, "invalid_polygon"
    try:
        validate_polygon(list(normalized), label="egress polygon")
    except ValueError as error:
        return (
            None,
            "self_intersecting_polygon"
            if "self-intersecting" in str(error)
            else "invalid_polygon",
        )
    return normalized, None


def _connected_lobbies(
    layout: LayoutCandidate,
    circulation: tuple[_Space, ...],
    floor_boundary: tuple[Point, ...],
    tolerance_m: float,
) -> tuple[list[_Space], list[str]]:
    if layout.basic_design is None:
        return [], []
    lobbies: list[_Space] = []
    reasons: list[str] = []
    for element in layout.basic_design.elements:
        if element.kind != "lobby":
            continue
        polygon, reason = _validated_polygon(element.footprint, tolerance_m)
        if reason is not None:
            reasons.append(f"{reason}:{element.element_id}")
            continue
        assert polygon is not None
        if not _polygon_within(polygon, floor_boundary, tolerance_m):
            reasons.append(f"geometry_out_of_boundary:{element.element_id}")
            continue
        if not any(
            _polygons_share_boundary(polygon, path.polygon, tolerance_m)
            for path in circulation
        ):
            reasons.append(f"lobby_connection_unresolved:{element.element_id}")
            continue
        lobbies.append(_Space(element.element_id, polygon, is_lobby=True))
    return lobbies, reasons


def _validated_openings(
    openings: list[OpeningSegment],
    rooms: dict[str, _Space],
    circulation: tuple[_Space, ...],
    occupied_room_ids: tuple[str, ...],
    tolerance_m: float,
) -> tuple[dict[str, tuple[OpeningSegment, ...]], tuple[str, ...]]:
    result: dict[str, list[OpeningSegment]] = {
        room_id: [] for room_id in occupied_room_ids
    }
    reasons: list[str] = []
    seen_ids: set[str] = set()
    circulation_by_id = {space.source_id: space for space in circulation}
    for opening in openings:
        connected_rooms = [
            room_id for room_id in occupied_room_ids if room_id in opening.connects
        ]
        if not connected_rooms:
            continue
        if opening.opening_id in seen_ids:
            reasons.append(f"duplicate_opening_id:{opening.opening_id}")
            continue
        seen_ids.add(opening.opening_id)
        room_id = connected_rooms[0]
        other_id = (
            opening.connects[1]
            if opening.connects[0] == room_id
            else opening.connects[0]
        )
        room = rooms.get(room_id)
        path = circulation_by_id.get(other_id)
        segment = (_point(opening.start), _point(opening.end))
        valid = (
            opening.kind == "door"
            and room is not None
            and path is not None
            and _positive_axis_segment(segment, tolerance_m)
            and _segment_on_polygon_boundary(
                segment,
                room.polygon,
                tolerance_m,
            )
            and _segment_on_polygon_boundary(
                segment,
                path.polygon,
                tolerance_m,
            )
        )
        if not valid:
            reasons.append(f"invalid_opening_portal:{opening.opening_id}")
            continue
        result[room_id].append(opening)
    return (
        {room_id: tuple(values) for room_id, values in result.items()},
        tuple(reasons),
    )


def _validated_exits(
    layout: LayoutCandidate,
    circulation: tuple[_Space, ...],
    floor_boundary: tuple[Point, ...],
    tolerance_m: float,
) -> tuple[tuple[PlanLine, ...], tuple[str, ...]]:
    if layout.basic_design is None:
        return (), ("protected_exit_portal_missing",)
    valid_targets = {
        element.element_id: tuple(element.footprint)
        for element in layout.basic_design.elements
        if element.kind == "stair"
    }
    core_hosts = {
        room.room_id: tuple(room.polygon)
        for room in layout.rooms
        if room.space_type == "core"
    } | {
        element.element_id: tuple(element.footprint)
        for element in layout.basic_design.elements
        if element.kind in {"core", "stair"}
    }
    exits: list[PlanLine] = []
    reasons: list[str] = []
    seen_ids: set[str] = set()
    for line in layout.basic_design.lines:
        if line.kind != "protected_exit":
            continue
        if line.line_id in seen_ids:
            reasons.append(f"duplicate_protected_exit_id:{line.line_id}")
            continue
        seen_ids.add(line.line_id)
        if len(line.points) != 2:
            reasons.append(f"invalid_protected_exit_portal:{line.line_id}")
            continue
        segment = (_point(line.points[0]), _point(line.points[1]))
        tied_polygons = tuple(
            polygon
            for polygon in (
                valid_targets.get(line.target_id or ""),
                core_hosts.get(line.host_id or ""),
            )
            if polygon is not None
        )
        valid = (
            line.target_id in valid_targets
            and _positive_axis_segment(segment, tolerance_m)
            and all(
                _point_in_or_on_polygon(point, floor_boundary, tolerance_m)
                for point in (segment[0], _midpoint(*segment), segment[1])
            )
            and any(
                _segment_on_polygon_boundary(
                    segment,
                    space.polygon,
                    tolerance_m,
                )
                for space in circulation
            )
            and any(
                _segment_on_polygon_boundary(
                    segment,
                    polygon,
                    tolerance_m,
                )
                for polygon in tied_polygons
            )
        )
        if not valid:
            reasons.append(f"invalid_protected_exit_portal:{line.line_id}")
            continue
        exits.append(line)
    return tuple(exits), tuple(reasons)


def _add_space_graph(
    graph: _Graph,
    spaces: tuple[_Space, ...],
    point_specs: dict[Point, _PointSpec],
    *,
    prefix: str,
    default_kind: RouteNodeKind,
    default_edge_kind: RouteEdgeKind,
    tolerance_m: float,
) -> None:
    xs = sorted(
        {
            point[0]
            for space in spaces
            for point in space.polygon
        }
        | {point[0] for point in point_specs}
    )
    ys = sorted(
        {
            point[1]
            for space in spaces
            for point in space.polygon
        }
        | {point[1] for point in point_specs}
    )
    node_by_point: dict[Point, str] = {}
    for x in xs:
        for y in ys:
            point = (x, y)
            hosts = _point_hosts(point, spaces, tolerance_m)
            if not hosts:
                continue
            spec = point_specs.get(point)
            if spec is None:
                spec = _PointSpec(
                    node_id=f"{prefix}:vertex:{_coordinate_id(point)}",
                    kind=(
                        "lobby_vertex"
                        if all(host.is_lobby for host in hosts)
                        else default_kind
                    ),
                    host_id="|".join(
                        sorted(host.source_id for host in hosts)
                    ),
                )
            graph.add_node(
                RouteNode(
                    node_id=spec.node_id,
                    kind=spec.kind,
                    point=point,
                    host_id=spec.host_id,
                )
            )
            node_by_point[point] = spec.node_id
    for x in xs:
        points = sorted(
            (point for point in node_by_point if point[0] == x),
            key=lambda point: point[1],
        )
        _add_axis_edges(
            graph,
            points,
            node_by_point,
            spaces,
            default_edge_kind,
            tolerance_m,
        )
    for y in ys:
        points = sorted(
            (point for point in node_by_point if point[1] == y),
            key=lambda point: point[0],
        )
        _add_axis_edges(
            graph,
            points,
            node_by_point,
            spaces,
            default_edge_kind,
            tolerance_m,
        )


def _add_axis_edges(
    graph: _Graph,
    points: list[Point],
    node_by_point: dict[Point, str],
    spaces: tuple[_Space, ...],
    default_edge_kind: RouteEdgeKind,
    tolerance_m: float,
) -> None:
    for start, end in zip(points, points[1:]):
        sources = _segment_hosts((start, end), spaces, tolerance_m)
        if not sources:
            continue
        source_ids = tuple(sorted(space.source_id for space in sources))
        edge_kind: RouteEdgeKind = (
            "inside_lobby"
            if all(space.is_lobby for space in sources)
            else default_edge_kind
        )
        graph.add_edge(
            RouteEdge(
                source_id=node_by_point[start],
                target_id=node_by_point[end],
                kind=edge_kind,
                length_m=math.dist(start, end),
                polyline=(start, end),
                source_geometry_ids=source_ids,
            )
        )


def _farthest_room_route(
    graph: _Graph,
    candidate_node_ids: tuple[str, ...],
    exit_node_to_id: dict[str, str],
    tolerance_m: float,
) -> tuple[_RoomRoute | None, str | None]:
    candidate_routes: list[_RoomRoute] = []
    for candidate_node_id in candidate_node_ids:
        paths = _shortest_paths(graph, candidate_node_id, tolerance_m)
        reachable = [
            (
                paths[exit_node_id][0],
                exit_id,
                paths[exit_node_id][1],
            )
            for exit_node_id, exit_id in exit_node_to_id.items()
            if exit_node_id in paths
        ]
        if not reachable:
            room_id = graph.nodes[candidate_node_id].host_id
            return None, f"unreachable_occupied_room:{room_id}"
        distance, exit_id, node_ids = min(
            reachable,
            key=lambda item: (item[0], item[1], item[2]),
        )
        polyline = _simplified_polyline(
            tuple(graph.nodes[node_id].point for node_id in node_ids),
            tolerance_m,
        )
        candidate_routes.append(
            _RoomRoute(
                candidate_point=graph.nodes[candidate_node_id].point,
                exit_id=exit_id,
                distance_m=distance,
                node_ids=node_ids,
                polyline=polyline,
            )
        )
    return (
        min(
            candidate_routes,
            key=lambda route: (
                -route.distance_m,
                route.candidate_point[0],
                route.candidate_point[1],
                route.exit_id,
            ),
        ),
        None,
    )


def _shortest_paths(
    graph: _Graph,
    start_id: str,
    tolerance_m: float,
) -> dict[str, tuple[float, tuple[str, ...]]]:
    best: dict[str, tuple[float, tuple[str, ...]]] = {
        start_id: (0.0, (start_id,))
    }
    queue: list[tuple[float, tuple[str, ...], str]] = [
        (0.0, (start_id,), start_id)
    ]
    while queue:
        distance, path, node_id = heapq.heappop(queue)
        recorded = best.get(node_id)
        if recorded is None or distance > recorded[0] + tolerance_m:
            continue
        for neighbor_id, edge_length in sorted(graph.adjacency[node_id]):
            candidate_distance = distance + edge_length
            candidate_path = path + (neighbor_id,)
            existing = best.get(neighbor_id)
            if existing is None or candidate_distance < existing[0] - tolerance_m:
                best[neighbor_id] = (candidate_distance, candidate_path)
                heapq.heappush(
                    queue,
                    (candidate_distance, candidate_path, neighbor_id),
                )
            elif (
                math.isclose(
                    candidate_distance,
                    existing[0],
                    abs_tol=tolerance_m,
                )
                and candidate_path < existing[1]
            ):
                best[neighbor_id] = (candidate_distance, candidate_path)
                heapq.heappush(
                    queue,
                    (candidate_distance, candidate_path, neighbor_id),
                )
    return best


def _unsupported_result(
    floor_index: int,
    occupied_room_ids: tuple[str, ...],
    reasons: tuple[str, ...],
) -> FloorEgressGraphResult:
    return FloorEgressGraphResult(
        floor_index=floor_index,
        status="not_checked",
        nodes=(),
        edges=(),
        room_results=tuple(
            _not_checked_room(floor_index, room_id, reasons)
            for room_id in occupied_room_ids
        ),
        governing_room_id=None,
        governing_distance_m=None,
        governing_exit_id=None,
        common_path_distance_m=None,
        common_path_status="not_checked",
        dead_end_distance_m=None,
        dead_end_status="not_checked",
        unresolved_facts=reasons,
    )


def _not_checked_room(
    floor_index: int,
    room_id: str,
    reasons: tuple[str, ...],
) -> RoomTravelEvidence:
    return RoomTravelEvidence(
        floor_index=floor_index,
        room_id=room_id,
        farthest_point=None,
        nearest_exit_id=None,
        distance_m=None,
        route_node_ids=(),
        route_polyline=(),
        status="not_checked",
        unresolved_facts=reasons,
    )


def _point_hosts(
    point: Point,
    spaces: tuple[_Space, ...],
    tolerance_m: float,
) -> tuple[_Space, ...]:
    return tuple(
        space
        for space in spaces
        if _point_in_or_on_polygon(point, space.polygon, tolerance_m)
    )


def _segment_hosts(
    segment: tuple[Point, Point],
    spaces: tuple[_Space, ...],
    tolerance_m: float,
) -> tuple[_Space, ...]:
    start, end = segment
    midpoint = _midpoint(start, end)
    return tuple(
        space
        for space in spaces
        if all(
            _point_in_or_on_polygon(point, space.polygon, tolerance_m)
            for point in (start, midpoint, end)
        )
    )


def _polygon_within(
    polygon: tuple[Point, ...],
    boundary: tuple[Point, ...],
    tolerance_m: float,
) -> bool:
    return all(
        _segment_covered_by_polygon(edge, boundary, tolerance_m)
        for edge in _polygon_edges(polygon)
    )


def _segment_covered_by_polygon(
    segment: tuple[Point, Point],
    polygon: tuple[Point, ...],
    tolerance_m: float,
) -> bool:
    start, end = segment
    horizontal = abs(start[1] - end[1]) <= tolerance_m
    vertical = abs(start[0] - end[0]) <= tolerance_m
    if not horizontal and not vertical:
        return False
    axis = 0 if horizontal else 1
    fixed_axis = 1 - axis
    fixed_value = (start[fixed_axis] + end[fixed_axis]) / 2
    lower, upper = sorted((start[axis], end[axis]))
    breaks = [lower, upper]
    for boundary_start, boundary_end in _polygon_edges(polygon):
        boundary_horizontal = (
            abs(boundary_start[1] - boundary_end[1]) <= tolerance_m
        )
        boundary_axis = 0 if boundary_horizontal else 1
        boundary_fixed_axis = 1 - boundary_axis
        boundary_fixed = (
            boundary_start[boundary_fixed_axis]
            + boundary_end[boundary_fixed_axis]
        ) / 2
        boundary_lower, boundary_upper = sorted(
            (boundary_start[boundary_axis], boundary_end[boundary_axis])
        )
        if boundary_axis != axis:
            crossing = boundary_fixed
            boundary_spans_fixed = (
                boundary_lower - tolerance_m
                <= fixed_value
                <= boundary_upper + tolerance_m
            )
            if (
                boundary_spans_fixed
                and lower - tolerance_m <= crossing <= upper + tolerance_m
            ):
                breaks.append(min(max(crossing, lower), upper))
        elif abs(boundary_fixed - fixed_value) <= tolerance_m:
            overlap_lower = max(lower, boundary_lower)
            overlap_upper = min(upper, boundary_upper)
            if overlap_lower <= overlap_upper + tolerance_m:
                breaks.extend((overlap_lower, overlap_upper))
    cells = _unique_coordinates(breaks, tolerance_m)
    points = tuple(
        (
            (coordinate, fixed_value)
            if horizontal
            else (fixed_value, coordinate)
        )
        for coordinate in cells
    )
    if not all(
        _point_in_or_on_polygon(point, polygon, tolerance_m)
        for point in points
    ):
        return False
    return all(
        _point_in_or_on_polygon(
            _midpoint(cell_start, cell_end),
            polygon,
            tolerance_m,
        )
        for cell_start, cell_end in zip(points, points[1:])
        if math.dist(cell_start, cell_end) > tolerance_m
    )


def _point_in_or_on_polygon(
    point: Point,
    polygon: tuple[Point, ...],
    tolerance_m: float,
) -> bool:
    if any(
        _point_on_segment(point, edge, tolerance_m)
        for edge in _polygon_edges(polygon)
    ):
        return True
    x, y = point
    inside = False
    for start, end in _polygon_edges(polygon):
        if (start[1] > y) != (end[1] > y):
            intersection_x = start[0] + (y - start[1]) * (
                end[0] - start[0]
            ) / (end[1] - start[1])
            if x < intersection_x:
                inside = not inside
    return inside


def _segment_on_polygon_boundary(
    segment: tuple[Point, Point],
    polygon: tuple[Point, ...],
    tolerance_m: float,
) -> bool:
    return any(
        _segment_within_segment(segment, edge, tolerance_m)
        for edge in _polygon_edges(polygon)
    )


def _segment_within_segment(
    inner: tuple[Point, Point],
    outer: tuple[Point, Point],
    tolerance_m: float,
) -> bool:
    return all(_point_on_segment(point, outer, tolerance_m) for point in inner)


def _point_on_segment(
    point: Point,
    segment: tuple[Point, Point],
    tolerance_m: float,
) -> bool:
    start, end = segment
    cross = (point[0] - start[0]) * (end[1] - start[1]) - (
        point[1] - start[1]
    ) * (end[0] - start[0])
    if abs(cross) > tolerance_m:
        return False
    return (
        min(start[0], end[0]) - tolerance_m
        <= point[0]
        <= max(start[0], end[0]) + tolerance_m
        and min(start[1], end[1]) - tolerance_m
        <= point[1]
        <= max(start[1], end[1]) + tolerance_m
    )


def _polygons_share_boundary(
    first: tuple[Point, ...],
    second: tuple[Point, ...],
    tolerance_m: float,
) -> bool:
    for left in _polygon_edges(first):
        for right in _polygon_edges(second):
            if not (
                _axis_aligned(*left, tolerance_m)
                and _axis_aligned(*right, tolerance_m)
            ):
                continue
            if abs(left[0][0] - left[1][0]) <= tolerance_m and abs(
                right[0][0] - right[1][0]
            ) <= tolerance_m:
                if abs(left[0][0] - right[0][0]) > tolerance_m:
                    continue
                overlap = min(
                    max(left[0][1], left[1][1]),
                    max(right[0][1], right[1][1]),
                ) - max(
                    min(left[0][1], left[1][1]),
                    min(right[0][1], right[1][1]),
                )
            elif abs(left[0][1] - left[1][1]) <= tolerance_m and abs(
                right[0][1] - right[1][1]
            ) <= tolerance_m:
                if abs(left[0][1] - right[0][1]) > tolerance_m:
                    continue
                overlap = min(
                    max(left[0][0], left[1][0]),
                    max(right[0][0], right[1][0]),
                ) - max(
                    min(left[0][0], left[1][0]),
                    min(right[0][0], right[1][0]),
                )
            else:
                continue
            if overlap > tolerance_m:
                return True
    return False


def _positive_axis_segment(
    segment: tuple[Point, Point],
    tolerance_m: float,
) -> bool:
    return (
        math.dist(*segment) > tolerance_m
        and _axis_aligned(*segment, tolerance_m)
    )


def _axis_aligned(
    start: Point,
    end: Point,
    tolerance_m: float,
) -> bool:
    return (
        abs(start[0] - end[0]) <= tolerance_m
        or abs(start[1] - end[1]) <= tolerance_m
    )


def _is_rectangle(
    polygon: tuple[Point, ...],
    tolerance_m: float,
) -> bool:
    if len(polygon) != 4:
        return False
    xs = _unique_coordinates(
        (point[0] for point in polygon),
        tolerance_m,
    )
    ys = _unique_coordinates(
        (point[1] for point in polygon),
        tolerance_m,
    )
    return (
        len(xs) == 2
        and len(ys) == 2
        and set(polygon)
        == {
            (xs[0], ys[0]),
            (xs[0], ys[1]),
            (xs[1], ys[0]),
            (xs[1], ys[1]),
        }
    )


def _unique_coordinates(values, tolerance_m: float) -> list[float]:
    result: list[float] = []
    for value in sorted(values):
        if not result or abs(value - result[-1]) > tolerance_m:
            result.append(value)
    return result


def _circulation_id(
    opening: OpeningSegment,
    room_id: str,
) -> str:
    return (
        opening.connects[1]
        if opening.connects[0] == room_id
        else opening.connects[0]
    )


def _coordinate_id(point: Point) -> str:
    return f"{point[0]:.12g}:{point[1]:.12g}"


def _point(point: Point) -> Point:
    return (float(point[0]), float(point[1]))


def _midpoint(start: Point, end: Point) -> Point:
    return ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)


def _polygon_edges(
    polygon: tuple[Point, ...],
):
    return zip(polygon, polygon[1:] + polygon[:1])


def _signed_area(polygon: tuple[Point, ...]) -> float:
    return sum(
        start[0] * end[1] - end[0] * start[1]
        for start, end in _polygon_edges(polygon)
    ) / 2


def _simplified_polyline(
    points: tuple[Point, ...],
    tolerance_m: float,
) -> tuple[Point, ...]:
    simplified: list[Point] = []
    for point in points:
        if simplified and math.dist(simplified[-1], point) <= tolerance_m:
            continue
        if len(simplified) >= 2:
            first, second = simplified[-2:]
            if (
                abs(first[0] - second[0]) <= tolerance_m
                and abs(second[0] - point[0]) <= tolerance_m
                and (second[1] - first[1]) * (point[1] - second[1]) >= 0
            ) or (
                abs(first[1] - second[1]) <= tolerance_m
                and abs(second[1] - point[1]) <= tolerance_m
                and (second[0] - first[0]) * (point[0] - second[0]) >= 0
            ):
                simplified[-1] = point
                continue
        simplified.append(point)
    if len(simplified) == 1:
        simplified.append(simplified[0])
    return tuple(simplified)


def _polyline_length(points: tuple[Point, ...]) -> float:
    return sum(math.dist(start, end) for start, end in zip(points, points[1:]))
