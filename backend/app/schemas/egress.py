from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
import math

from backend.app.schemas.layout import Point

RouteNodeKind = Literal[
    "room_farthest_candidate",
    "room_door_portal",
    "circulation_vertex",
    "lobby_vertex",
    "protected_exit_portal",
]
RouteEdgeKind = Literal[
    "inside_room",
    "through_opening",
    "inside_circulation",
    "inside_lobby",
    "through_protected_exit",
]
EgressMeasurementStatus = Literal["checked", "not_checked"]

_NODE_KINDS = {
    "room_farthest_candidate",
    "room_door_portal",
    "circulation_vertex",
    "lobby_vertex",
    "protected_exit_portal",
}
_EDGE_KINDS = {
    "inside_room",
    "through_opening",
    "inside_circulation",
    "inside_lobby",
    "through_protected_exit",
}
_ZERO_LENGTH_EDGE_KINDS = {"through_opening", "through_protected_exit"}
_LENGTH_TOLERANCE = 1e-9


@dataclass(frozen=True)
class RouteNode:
    node_id: str
    kind: RouteNodeKind
    point: Point
    host_id: str

    def __post_init__(self) -> None:
        _require_id(self.node_id, "node_id")
        _require_id(self.host_id, "host_id")
        if self.kind not in _NODE_KINDS:
            raise ValueError("route node kind is invalid")
        _require_point(self.point, "route node point")


@dataclass(frozen=True)
class RouteEdge:
    source_id: str
    target_id: str
    kind: RouteEdgeKind
    length_m: float
    polyline: tuple[Point, ...]
    source_geometry_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_id(self.source_id, "source_id")
        _require_id(self.target_id, "target_id")
        if self.source_id == self.target_id:
            raise ValueError("route edge endpoints must be distinct nodes")
        if self.kind not in _EDGE_KINDS:
            raise ValueError("route edge kind is invalid")
        if (
            not isinstance(self.length_m, (int, float))
            or isinstance(self.length_m, bool)
            or not math.isfinite(self.length_m)
            or self.length_m < 0
        ):
            raise ValueError("route edge length_m must be finite and nonnegative")
        if self.length_m == 0 and self.kind not in _ZERO_LENGTH_EDGE_KINDS:
            raise ValueError("only portal transitions may have zero length")
        if not isinstance(self.polyline, tuple) or len(self.polyline) < 2:
            raise TypeError("route edge polyline must be an immutable point tuple")
        for point in self.polyline:
            _require_point(point, "route edge polyline point")
        if any(
            not _orthogonal_or_zero(start, end)
            for start, end in zip(self.polyline, self.polyline[1:])
        ):
            raise ValueError("route edge polyline must be orthogonal")
        recomputed = _polyline_length(self.polyline)
        if not math.isclose(
            float(self.length_m),
            recomputed,
            rel_tol=_LENGTH_TOLERANCE,
            abs_tol=_LENGTH_TOLERANCE,
        ):
            raise ValueError("route edge polyline length does not match length_m")
        _require_ids(
            self.source_geometry_ids,
            "source_geometry_ids",
            allow_empty=False,
        )


@dataclass(frozen=True)
class RoomTravelEvidence:
    floor_index: int
    room_id: str
    farthest_point: Point | None
    nearest_exit_id: str | None
    distance_m: float | None
    route_node_ids: tuple[str, ...]
    route_polyline: tuple[Point, ...]
    status: EgressMeasurementStatus
    unresolved_facts: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_floor_index(self.floor_index)
        _require_id(self.room_id, "room_id")
        if self.status not in {"checked", "not_checked"}:
            raise ValueError("room travel status must be checked or not_checked")
        _require_ids(self.unresolved_facts, "unresolved_facts", allow_empty=True)
        if self.status == "checked":
            if self.farthest_point is None:
                raise ValueError("checked room travel requires a farthest_point")
            _require_point(self.farthest_point, "farthest_point")
            if self.nearest_exit_id is None:
                raise ValueError("checked room travel requires nearest_exit_id")
            _require_id(self.nearest_exit_id, "nearest_exit_id")
            if (
                self.distance_m is None
                or isinstance(self.distance_m, bool)
                or not math.isfinite(self.distance_m)
                or self.distance_m < 0
            ):
                raise ValueError("checked room travel requires finite distance_m")
            _require_ids(
                self.route_node_ids,
                "route_node_ids",
                allow_empty=False,
            )
            if not isinstance(self.route_polyline, tuple) or len(
                self.route_polyline
            ) < 2:
                raise ValueError("checked room travel requires a route_polyline")
            for point in self.route_polyline:
                _require_point(point, "room route point")
            if any(
                not _orthogonal_or_zero(start, end)
                for start, end in zip(
                    self.route_polyline,
                    self.route_polyline[1:],
                )
            ):
                raise ValueError("room route polyline must be orthogonal")
            if not math.isclose(
                self.distance_m,
                _polyline_length(self.route_polyline),
                rel_tol=_LENGTH_TOLERANCE,
                abs_tol=_LENGTH_TOLERANCE,
            ):
                raise ValueError(
                    "room route polyline length does not match distance_m"
                )
            if self.unresolved_facts:
                raise ValueError("checked room travel cannot have unresolved facts")
        elif any(
            value is not None
            for value in (
                self.farthest_point,
                self.nearest_exit_id,
                self.distance_m,
            )
        ) or self.route_node_ids or self.route_polyline:
            raise ValueError(
                "not_checked room travel cannot expose governing route values"
            )


@dataclass(frozen=True)
class FloorEgressGraphResult:
    floor_index: int
    status: EgressMeasurementStatus
    nodes: tuple[RouteNode, ...]
    edges: tuple[RouteEdge, ...]
    room_results: tuple[RoomTravelEvidence, ...]
    governing_room_id: str | None
    governing_distance_m: float | None
    governing_exit_id: str | None
    common_path_distance_m: float | None
    common_path_status: EgressMeasurementStatus
    dead_end_distance_m: float | None
    dead_end_status: EgressMeasurementStatus
    unresolved_facts: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_floor_index(self.floor_index)
        if self.status not in {"checked", "not_checked"}:
            raise ValueError("floor egress status must be checked or not_checked")
        if not isinstance(self.nodes, tuple) or not all(
            isinstance(node, RouteNode) for node in self.nodes
        ):
            raise TypeError("nodes must be an immutable RouteNode tuple")
        if not isinstance(self.edges, tuple) or not all(
            isinstance(edge, RouteEdge) for edge in self.edges
        ):
            raise TypeError("edges must be an immutable RouteEdge tuple")
        if not isinstance(self.room_results, tuple) or not all(
            isinstance(room, RoomTravelEvidence) for room in self.room_results
        ):
            raise TypeError(
                "room_results must be an immutable RoomTravelEvidence tuple"
            )
        node_ids = tuple(node.node_id for node in self.nodes)
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("route node ids must be unique within a floor")
        node_id_set = set(node_ids)
        nodes_by_id = {node.node_id: node for node in self.nodes}
        if any(
            edge.source_id not in node_id_set or edge.target_id not in node_id_set
            for edge in self.edges
        ):
            raise ValueError("route edges must reference existing nodes")
        for edge in self.edges:
            source_point = nodes_by_id[edge.source_id].point
            target_point = nodes_by_id[edge.target_id].point
            if not (
                _points_close(edge.polyline[0], source_point)
                and _points_close(edge.polyline[-1], target_point)
            ):
                raise ValueError(
                    "route edge polyline endpoints must match referenced nodes"
                )
        room_ids = tuple(room.room_id for room in self.room_results)
        if len(room_ids) != len(set(room_ids)):
            raise ValueError("room travel ids must be unique within a floor")
        if any(room.floor_index != self.floor_index for room in self.room_results):
            raise ValueError("room travel floor indexes must match floor result")
        if any(
            node_id not in node_id_set
            for room in self.room_results
            for node_id in room.route_node_ids
        ):
            raise ValueError("room routes must reference existing nodes")
        for room in self.room_results:
            if room.status == "checked":
                _validate_checked_room_graph_route(
                    room,
                    nodes_by_id,
                    self.edges,
                )
        _require_ids(self.unresolved_facts, "unresolved_facts", allow_empty=True)
        _validate_optional_measurement(
            self.common_path_status,
            self.common_path_distance_m,
            "common path",
        )
        _validate_optional_measurement(
            self.dead_end_status,
            self.dead_end_distance_m,
            "dead end",
        )
        if self.status == "checked":
            if not self.room_results or any(
                room.status != "checked" for room in self.room_results
            ):
                raise ValueError(
                    "checked floor requires every occupied room to be checked"
                )
            governing = max(
                self.room_results,
                key=lambda room: (
                    room.distance_m,
                    room.room_id,
                ),
            )
            if (
                self.governing_room_id != governing.room_id
                or self.governing_exit_id != governing.nearest_exit_id
                or self.governing_distance_m is None
                or not math.isclose(
                    self.governing_distance_m,
                    governing.distance_m or 0.0,
                    rel_tol=_LENGTH_TOLERANCE,
                    abs_tol=_LENGTH_TOLERANCE,
                )
            ):
                raise ValueError(
                    "floor governing route must match maximum checked room route"
                )
        elif any(
            value is not None
            for value in (
                self.governing_room_id,
                self.governing_distance_m,
                self.governing_exit_id,
            )
        ):
            raise ValueError(
                "not_checked floor cannot expose governing route values"
            )


def _require_id(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{label} must be a non-empty string")


def _require_ids(
    values: tuple[str, ...],
    label: str,
    *,
    allow_empty: bool,
) -> None:
    if not isinstance(values, tuple):
        raise TypeError(f"{label} must be an immutable tuple")
    if not allow_empty and not values:
        raise ValueError(f"{label} must not be empty")
    for value in values:
        _require_id(value, label)
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must contain unique values")


def _require_point(point: Point, label: str) -> None:
    if (
        not isinstance(point, tuple)
        or len(point) != 2
        or any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            for value in point
        )
    ):
        raise TypeError(f"{label} must contain two finite coordinates")


def _require_floor_index(floor_index: int) -> None:
    if (
        not isinstance(floor_index, int)
        or isinstance(floor_index, bool)
        or floor_index < 1
    ):
        raise ValueError("floor_index must be a positive integer")


def _orthogonal_or_zero(start: Point, end: Point) -> bool:
    return start == end or start[0] == end[0] or start[1] == end[1]


def _polyline_length(points: tuple[Point, ...]) -> float:
    return sum(math.dist(start, end) for start, end in zip(points, points[1:]))


def _validate_optional_measurement(
    status: EgressMeasurementStatus,
    value: float | None,
    label: str,
) -> None:
    if status not in {"checked", "not_checked"}:
        raise ValueError(f"{label} status must be checked or not_checked")
    if status == "checked":
        if (
            value is None
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError(f"checked {label} requires finite distance")
    elif value is not None:
        raise ValueError(f"not_checked {label} cannot expose a distance")


def _validate_checked_room_graph_route(
    room: RoomTravelEvidence,
    nodes_by_id: dict[str, RouteNode],
    edges: tuple[RouteEdge, ...],
) -> None:
    first_node = nodes_by_id[room.route_node_ids[0]]
    final_node = nodes_by_id[room.route_node_ids[-1]]
    if not _points_close(room.farthest_point, first_node.point):
        raise ValueError(
            "checked room farthest_point must match its first route node"
        )
    if final_node.kind != "protected_exit_portal":
        raise ValueError(
            "checked room route must end at a protected_exit_portal"
        )
    nearest_exit_id = room.nearest_exit_id or ""
    if not (
        final_node.node_id == nearest_exit_id
        or final_node.host_id == nearest_exit_id
        or final_node.node_id.endswith(f":{nearest_exit_id}")
    ):
        raise ValueError(
            "checked room nearest_exit_id must match its final exit portal"
        )

    edge_lookup: dict[frozenset[str], list[RouteEdge]] = {}
    for edge in edges:
        edge_lookup.setdefault(
            frozenset((edge.source_id, edge.target_id)),
            [],
        ).append(edge)
    states: set[tuple[Point, ...]] = {()}
    for source_id, target_id in zip(
        room.route_node_ids,
        room.route_node_ids[1:],
    ):
        candidates = edge_lookup.get(frozenset((source_id, target_id)), ())
        if not candidates:
            raise ValueError(
                "checked room route_node_ids must follow contiguous graph edges"
            )
        next_states: set[tuple[Point, ...]] = set()
        for composed in sorted(states):
            for edge in sorted(candidates, key=_route_edge_sort_key):
                oriented = (
                    edge.polyline
                    if (
                        edge.source_id == source_id
                        and edge.target_id == target_id
                    )
                    else tuple(reversed(edge.polyline))
                )
                if composed and not _points_close(composed[-1], oriented[0]):
                    continue
                combined = _simplify_polyline(
                    (
                        composed + oriented[1:]
                        if composed
                        else oriented
                    )
                )
                prefix = _polyline_prefix(
                    room.route_polyline,
                    _polyline_length(combined),
                )
                if prefix is not None and _polylines_close(combined, prefix):
                    next_states.add(combined)
        states = next_states
        if not states:
            break
    if not any(
        _polylines_close(composed, room.route_polyline)
        for composed in states
    ):
        raise ValueError(
            "checked room route_polyline must compose graph edges"
        )


def _points_close(left: Point | None, right: Point) -> bool:
    return left is not None and math.dist(left, right) <= _LENGTH_TOLERANCE


def _polylines_close(
    left: tuple[Point, ...],
    right: tuple[Point, ...],
) -> bool:
    return len(left) == len(right) and all(
        _points_close(left_point, right_point)
        for left_point, right_point in zip(left, right)
    )


def _simplify_polyline(points: tuple[Point, ...]) -> tuple[Point, ...]:
    simplified: list[Point] = []
    for point in points:
        if simplified and _points_close(simplified[-1], point):
            continue
        if len(simplified) >= 2:
            first, second = simplified[-2:]
            same_vertical_direction = (
                abs(first[0] - second[0]) <= _LENGTH_TOLERANCE
                and abs(second[0] - point[0]) <= _LENGTH_TOLERANCE
                and (second[1] - first[1]) * (point[1] - second[1]) >= 0
            )
            same_horizontal_direction = (
                abs(first[1] - second[1]) <= _LENGTH_TOLERANCE
                and abs(second[1] - point[1]) <= _LENGTH_TOLERANCE
                and (second[0] - first[0]) * (point[0] - second[0]) >= 0
            )
            if same_vertical_direction or same_horizontal_direction:
                simplified[-1] = point
                continue
        simplified.append(point)
    if len(simplified) == 1:
        simplified.append(simplified[0])
    return tuple(simplified)


def _route_edge_sort_key(edge: RouteEdge) -> tuple:
    return (
        edge.length_m,
        edge.polyline,
        edge.kind,
        edge.source_geometry_ids,
        edge.source_id,
        edge.target_id,
    )


def _polyline_prefix(
    points: tuple[Point, ...],
    distance: float,
) -> tuple[Point, ...] | None:
    if not points or distance < 0:
        return None
    remaining = distance
    prefix = [points[0]]
    for start, end in zip(points, points[1:]):
        segment_length = math.dist(start, end)
        if remaining >= segment_length - _LENGTH_TOLERANCE:
            prefix.append(end)
            remaining = max(0.0, remaining - segment_length)
            continue
        if segment_length <= _LENGTH_TOLERANCE:
            continue
        ratio = remaining / segment_length
        prefix.append(
            (
                start[0] + (end[0] - start[0]) * ratio,
                start[1] + (end[1] - start[1]) * ratio,
            )
        )
        remaining = 0.0
        break
    if remaining > _LENGTH_TOLERANCE:
        return None
    return _simplify_polyline(tuple(prefix))
