from __future__ import annotations

from dataclasses import FrozenInstanceError
import math

import pytest

from backend.app.modules.egress_graph import measure_traversable_egress
from backend.app.schemas.egress import (
    FloorEgressGraphResult,
    RoomTravelEvidence,
    RouteEdge,
    RouteNode,
)
from backend.app.schemas.layout import (
    BasicDesignFeatures,
    LayoutCandidate,
    OpeningSegment,
    PlanElement,
    PlanLine,
    RoomPolygon,
)


def _rect(
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
) -> list[tuple[float, float]]:
    return [
        (min_x, min_y),
        (max_x, min_y),
        (max_x, max_y),
        (min_x, max_y),
    ]


def _exit(
    line_id: str,
    points: tuple[tuple[float, float], tuple[float, float]],
    *,
    target_id: str,
    measured_value: float | None = None,
) -> PlanLine:
    return PlanLine(
        line_id=line_id,
        category="egress",
        kind="protected_exit",
        points=points,
        host_id="corridor",
        target_id=target_id,
        measured_value=measured_value,
        clear_width=1.0,
    )


def _layout(
    *,
    rooms: list[RoomPolygon],
    circulation: list[RoomPolygon],
    openings: list[OpeningSegment],
    exits: tuple[PlanLine, ...],
) -> LayoutCandidate:
    stairs = []
    for exit_line in exits:
        start, end = exit_line.points
        if start[0] == end[0]:
            x = start[0]
            min_x, max_x = (x, x + 1.0) if x <= 15.0 else (x - 1.0, x)
            footprint = _rect(
                min_x,
                min(start[1], end[1]),
                max_x,
                max(start[1], end[1]),
            )
        else:
            y = start[1]
            footprint = _rect(
                min(start[0], end[0]),
                y,
                max(start[0], end[0]),
                y + 1.0,
            )
        stairs.append(
            PlanElement(
                element_id=exit_line.target_id or "",
                category="vertical",
                kind="stair",
                host_id="floor",
                label="UP",
                footprint=tuple(footprint),
            )
        )
    return LayoutCandidate(
        candidate_id="candidate",
        project_id="egress-test",
        floor_index=1,
        rooms=rooms,
        circulation=circulation,
        score=0.0,
        openings=openings,
        basic_design=BasicDesignFeatures(
            elements=tuple(stairs),
            lines=exits,
        ),
    )


def _base_30x12(
    *,
    door_y: float = 7.0,
    exits: tuple[PlanLine, ...] | None = None,
) -> tuple[
    LayoutCandidate,
    tuple[tuple[float, float], ...],
]:
    room = RoomPolygon("room-far", "open_work", _rect(25.0, 7.0, 29.0, 12.0))
    corridor = RoomPolygon("corridor", "circulation", _rect(0.0, 5.0, 30.0, 7.0))
    door = OpeningSegment(
        opening_id="door-far",
        kind="door",
        connects=("room-far", "corridor"),
        start=(26.5, door_y),
        end=(27.5, door_y),
        clear_width=1.0,
    )
    if exits is None:
        exits = (
            _exit(
                "exit-west",
                ((0.0, 5.5), (0.0, 6.5)),
                target_id="stair-west",
            ),
        )
    return (
        _layout(
            rooms=[room],
            circulation=[corridor],
            openings=[door],
            exits=exits,
        ),
        tuple(_rect(0.0, 0.0, 30.0, 12.0)),
    )


def _measure(
    layout: LayoutCandidate,
    floor_boundary: tuple[tuple[float, float], ...],
):
    return measure_traversable_egress(
        layout=layout,
        floor_boundary=floor_boundary,
        occupied_room_ids=tuple(room.room_id for room in layout.rooms),
    )


def _polyline_length(points: tuple[tuple[float, float], ...]) -> float:
    return sum(math.dist(start, end) for start, end in zip(points, points[1:]))


def test_typed_route_contracts_are_frozen_and_recompute_edge_length() -> None:
    node = RouteNode("node", "circulation_vertex", (1.0, 2.0), "corridor")
    with pytest.raises(FrozenInstanceError):
        node.node_id = "changed"  # type: ignore[misc]

    with pytest.raises(ValueError, match="polyline length"):
        RouteEdge(
            source_id="a",
            target_id="b",
            kind="inside_circulation",
            length_m=1.0,
            polyline=((0.0, 0.0), (2.0, 0.0)),
            source_geometry_ids=("corridor",),
        )


def test_checked_room_distance_rejects_bool() -> None:
    with pytest.raises(ValueError, match="distance_m"):
        RoomTravelEvidence(
            floor_index=1,
            room_id="room",
            farthest_point=(0.0, 0.0),
            nearest_exit_id="exit",
            distance_m=True,  # type: ignore[arg-type]
            route_node_ids=("origin", "exit:exit"),
            route_polyline=((0.0, 0.0), (1.0, 0.0)),
            status="checked",
            unresolved_facts=(),
        )


@pytest.mark.parametrize(
    ("field_name", "status_name"),
    [
        ("common_path_distance_m", "common_path_status"),
        ("dead_end_distance_m", "dead_end_status"),
    ],
)
def test_optional_floor_measurements_reject_bool(
    field_name: str,
    status_name: str,
) -> None:
    values = {
        "floor_index": 1,
        "status": "not_checked",
        "nodes": (),
        "edges": (),
        "room_results": (),
        "governing_room_id": None,
        "governing_distance_m": None,
        "governing_exit_id": None,
        "common_path_distance_m": None,
        "common_path_status": "not_checked",
        "dead_end_distance_m": None,
        "dead_end_status": "not_checked",
        "unresolved_facts": ("unsupported",),
    }
    values[field_name] = True
    values[status_name] = "checked"

    with pytest.raises(ValueError, match=field_name.split("_distance")[0].replace("_", " ")):
        FloorEgressGraphResult(**values)  # type: ignore[arg-type]


def _coherent_floor_result(
    *,
    edge_polyline: tuple[tuple[float, float], ...] = (
        (0.0, 0.0),
        (1.0, 0.0),
    ),
    route_node_ids: tuple[str, ...] = ("origin", "exit:west"),
    route_polyline: tuple[tuple[float, float], ...] = (
        (0.0, 0.0),
        (1.0, 0.0),
    ),
    farthest_point: tuple[float, float] = (0.0, 0.0),
    nearest_exit_id: str = "west",
) -> FloorEgressGraphResult:
    nodes = (
        RouteNode(
            "origin",
            "room_farthest_candidate",
            (0.0, 0.0),
            "room",
        ),
        RouteNode(
            "exit:west",
            "protected_exit_portal",
            (1.0, 0.0),
            "stair-west",
        ),
        RouteNode(
            "orphan",
            "circulation_vertex",
            (0.0, 1.0),
            "corridor",
        ),
    )
    edge = RouteEdge(
        source_id="origin",
        target_id="exit:west",
        kind="inside_room",
        length_m=_polyline_length(edge_polyline),
        polyline=edge_polyline,
        source_geometry_ids=("room",),
    )
    room = RoomTravelEvidence(
        floor_index=1,
        room_id="room",
        farthest_point=farthest_point,
        nearest_exit_id=nearest_exit_id,
        distance_m=_polyline_length(route_polyline),
        route_node_ids=route_node_ids,
        route_polyline=route_polyline,
        status="checked",
        unresolved_facts=(),
    )
    return FloorEgressGraphResult(
        floor_index=1,
        status="checked",
        nodes=nodes,
        edges=(edge,),
        room_results=(room,),
        governing_room_id="room",
        governing_distance_m=room.distance_m,
        governing_exit_id=nearest_exit_id,
        common_path_distance_m=None,
        common_path_status="not_checked",
        dead_end_distance_m=None,
        dead_end_status="not_checked",
        unresolved_facts=(),
    )


def test_floor_rejects_edge_polyline_that_does_not_end_at_target_node() -> None:
    with pytest.raises(ValueError, match="edge polyline endpoints"):
        _coherent_floor_result(
            edge_polyline=((0.0, 0.0), (2.0, 0.0)),
            route_polyline=((0.0, 0.0), (2.0, 0.0)),
        )


def test_floor_rejects_route_node_sequence_without_graph_edge() -> None:
    with pytest.raises(ValueError, match="contiguous graph edges"):
        _coherent_floor_result(
            route_node_ids=("origin", "orphan", "exit:west")
        )


def test_floor_rejects_route_polyline_not_composed_from_graph_edges() -> None:
    with pytest.raises(ValueError, match="compose graph edges"):
        _coherent_floor_result(
            route_polyline=((0.0, 0.0), (0.0, 1.0), (1.0, 1.0)),
        )


def test_floor_rejects_farthest_point_not_matching_first_route_node() -> None:
    with pytest.raises(ValueError, match="farthest_point"):
        _coherent_floor_result(farthest_point=(0.0, 1.0))


def test_floor_rejects_nearest_exit_not_matching_final_portal() -> None:
    with pytest.raises(ValueError, match="nearest_exit_id"):
        _coherent_floor_result(nearest_exit_id="east")


def _parallel_edge(
    source_id: str,
    target_id: str,
    polyline: tuple[tuple[float, float], ...],
    source_id_suffix: str,
) -> RouteEdge:
    return RouteEdge(
        source_id=source_id,
        target_id=target_id,
        kind="inside_circulation",
        length_m=_polyline_length(polyline),
        polyline=polyline,
        source_geometry_ids=(f"geometry-{source_id_suffix}",),
    )


def _parallel_floor_result(
    *,
    edges: tuple[RouteEdge, ...],
    route_node_ids: tuple[str, ...],
    route_polyline: tuple[tuple[float, float], ...],
) -> FloorEgressGraphResult:
    nodes = (
        RouteNode(
            "origin",
            "room_farthest_candidate",
            (0.0, 0.0),
            "room",
        ),
        RouteNode(
            "mid",
            "circulation_vertex",
            (2.0, 0.0),
            "corridor",
        ),
        RouteNode(
            "exit:west",
            "protected_exit_portal",
            (4.0, 0.0),
            "stair-west",
        ),
    )
    room = RoomTravelEvidence(
        floor_index=1,
        room_id="room",
        farthest_point=(0.0, 0.0),
        nearest_exit_id="west",
        distance_m=_polyline_length(route_polyline),
        route_node_ids=route_node_ids,
        route_polyline=route_polyline,
        status="checked",
        unresolved_facts=(),
    )
    return FloorEgressGraphResult(
        floor_index=1,
        status="checked",
        nodes=nodes,
        edges=edges,
        room_results=(room,),
        governing_room_id="room",
        governing_distance_m=room.distance_m,
        governing_exit_id="west",
        common_path_distance_m=None,
        common_path_status="not_checked",
        dead_end_distance_m=None,
        dead_end_status="not_checked",
        unresolved_facts=(),
    )


@pytest.mark.parametrize(
    ("edge_order", "route_polyline"),
    [
        (
            ("detour", "direct"),
            ((0.0, 0.0), (4.0, 0.0)),
        ),
        (
            ("direct", "detour"),
            (
                (0.0, 0.0),
                (0.0, 1.0),
                (4.0, 1.0),
                (4.0, 0.0),
            ),
        ),
    ],
)
def test_parallel_edge_choice_is_independent_of_insertion_order(
    edge_order: tuple[str, str],
    route_polyline: tuple[tuple[float, float], ...],
) -> None:
    variants = {
        "direct": _parallel_edge(
            "origin",
            "exit:west",
            ((0.0, 0.0), (4.0, 0.0)),
            "direct",
        ),
        "detour": _parallel_edge(
            "origin",
            "exit:west",
            (
                (0.0, 0.0),
                (0.0, 1.0),
                (4.0, 1.0),
                (4.0, 0.0),
            ),
            "detour",
        ),
    }

    result = _parallel_floor_result(
        edges=tuple(variants[name] for name in edge_order),
        route_node_ids=("origin", "exit:west"),
        route_polyline=route_polyline,
    )

    assert result.status == "checked"


@pytest.mark.parametrize(
    "route_polyline",
    [
        (
            (0.0, 0.0),
            (0.0, 1.0),
            (2.0, 1.0),
            (2.0, 0.0),
            (4.0, 0.0),
        ),
        (
            (0.0, 0.0),
            (2.0, 0.0),
            (2.0, -1.0),
            (4.0, -1.0),
            (4.0, 0.0),
        ),
        (
                (0.0, 0.0),
                (0.0, 1.0),
                (2.0, 1.0),
                (2.0, -1.0),
                (4.0, -1.0),
                (4.0, 0.0),
        ),
    ],
)
def test_parallel_edges_search_all_multi_hop_combinations(
    route_polyline: tuple[tuple[float, float], ...],
) -> None:
    first_direct = _parallel_edge(
        "origin",
        "mid",
        ((0.0, 0.0), (2.0, 0.0)),
        "first-direct",
    )
    first_detour = _parallel_edge(
        "origin",
        "mid",
        ((0.0, 0.0), (0.0, 1.0), (2.0, 1.0), (2.0, 0.0)),
        "first-detour",
    )
    second_direct = _parallel_edge(
        "mid",
        "exit:west",
        ((2.0, 0.0), (4.0, 0.0)),
        "second-direct",
    )
    second_detour = _parallel_edge(
        "mid",
        "exit:west",
        ((2.0, 0.0), (2.0, -1.0), (4.0, -1.0), (4.0, 0.0)),
        "second-detour",
    )

    result = _parallel_floor_result(
        edges=(
            first_direct,
            first_detour,
            second_direct,
            second_detour,
        ),
        route_node_ids=("origin", "mid", "exit:west"),
        route_polyline=route_polyline,
    )

    assert result.status == "checked"


def test_rectangular_fixture_recomputes_exact_35m_governing_path() -> None:
    layout, boundary = _base_30x12()

    result = _measure(layout, boundary)

    assert result.status == "checked"
    assert result.governing_room_id == "room-far"
    assert result.governing_exit_id == "exit-west"
    assert result.governing_distance_m == pytest.approx(35.0)
    room = result.room_results[0]
    assert room.farthest_point == (25.0, 12.0)
    assert room.route_polyline[0] == room.farthest_point
    assert room.route_polyline[-1] == (0.0, 6.0)
    assert _polyline_length(room.route_polyline) == pytest.approx(room.distance_m)
    assert result.common_path_status == "not_checked"
    assert result.dead_end_status == "not_checked"
    assert all(
        start[0] == pytest.approx(end[0])
        or start[1] == pytest.approx(end[1])
        for start, end in zip(room.route_polyline, room.route_polyline[1:])
    )


def test_declared_egress_route_measurement_is_not_used() -> None:
    declared = PlanLine(
        line_id="declared-route",
        category="egress",
        kind="egress_route",
        points=((27.0, 7.0), (0.0, 6.0)),
        measured_value=999.0,
    )
    layout, boundary = _base_30x12()
    assert layout.basic_design is not None
    layout = LayoutCandidate(
        **{
            **layout.__dict__,
            "basic_design": BasicDesignFeatures(
                elements=layout.basic_design.elements,
                lines=layout.basic_design.lines + (declared,),
            ),
        }
    )

    result = _measure(layout, boundary)

    assert result.governing_distance_m == pytest.approx(35.0)
    assert result.governing_distance_m != declared.measured_value


def test_declared_connects_without_shared_boundary_is_invalid() -> None:
    layout, boundary = _base_30x12(door_y=8.0)

    result = _measure(layout, boundary)

    assert result.status == "not_checked"
    assert result.governing_distance_m is None
    assert result.room_results[0].status == "not_checked"
    assert "invalid_opening_portal:door-far" in result.unresolved_facts


def test_room_with_valid_door_on_disconnected_corridor_is_not_checked() -> None:
    room = RoomPolygon("room", "open_work", _rect(20.0, 7.0, 24.0, 12.0))
    west = RoomPolygon("west", "circulation", _rect(0.0, 5.0, 8.0, 7.0))
    east = RoomPolygon("east", "circulation", _rect(18.0, 5.0, 30.0, 7.0))
    layout = _layout(
        rooms=[room],
        circulation=[west, east],
        openings=[
            OpeningSegment(
                "door",
                "door",
                ("room", "east"),
                (21.5, 7.0),
                (22.5, 7.0),
                1.0,
            )
        ],
        exits=(
            PlanLine(
                "exit",
                "egress",
                "protected_exit",
                ((0.0, 5.5), (0.0, 6.5)),
                host_id="west",
                target_id="stair",
                clear_width=1.0,
            ),
        ),
    )

    result = _measure(layout, tuple(_rect(0.0, 0.0, 30.0, 12.0)))

    assert result.status == "not_checked"
    assert "unreachable_occupied_room:room" in result.unresolved_facts


def test_l_shaped_circulation_uses_orthogonal_route_without_room_shortcut() -> None:
    room = RoomPolygon("room", "open_work", _rect(6.0, 12.0, 10.0, 16.0))
    shortcut_room = RoomPolygon("shortcut", "meeting", _rect(0.0, 6.0, 8.0, 12.0))
    corridor = [
        RoomPolygon("corridor-west", "circulation", _rect(0.0, 4.0, 10.0, 6.0)),
        RoomPolygon("corridor-north", "circulation", _rect(8.0, 4.0, 10.0, 12.0)),
    ]
    layout = _layout(
        rooms=[room, shortcut_room],
        circulation=corridor,
        openings=[
            OpeningSegment(
                "door-room",
                "door",
                ("room", "corridor-north"),
                (8.5, 12.0),
                (9.5, 12.0),
                1.0,
            )
        ],
        exits=(
            PlanLine(
                "exit-west",
                "egress",
                "protected_exit",
                ((0.0, 4.5), (0.0, 5.5)),
                host_id="corridor-west",
                target_id="stair-west",
                clear_width=1.0,
            ),
        ),
    )

    result = measure_traversable_egress(
        layout=layout,
        floor_boundary=(
            (0.0, 0.0),
            (12.0, 0.0),
            (12.0, 16.0),
            (6.0, 16.0),
            (6.0, 12.0),
            (0.0, 12.0),
        ),
        occupied_room_ids=("room",),
    )

    assert result.status == "checked"
    room_result = result.room_results[0]
    assert room_result.distance_m == pytest.approx(23.0)
    assert any(
        start[0] == pytest.approx(end[0])
        and min(start[1], end[1]) <= 6.0
        and max(start[1], end[1]) >= 12.0
        for start, end in zip(
            room_result.route_polyline,
            room_result.route_polyline[1:],
        )
    )
    assert not any(
        0.0 < point[0] < 8.0 and 6.0 < point[1] < 12.0
        for point in room_result.route_polyline
    )


def test_multiple_exits_select_nearest_reachable_exit_per_candidate() -> None:
    exits = (
        _exit(
            "exit-west",
            ((0.0, 5.5), (0.0, 6.5)),
            target_id="stair-west",
        ),
        _exit(
            "exit-east",
            ((30.0, 5.5), (30.0, 6.5)),
            target_id="stair-east",
        ),
    )
    layout, boundary = _base_30x12(exits=exits)

    result = _measure(layout, boundary)

    assert result.status == "checked"
    assert result.governing_exit_id == "exit-east"
    assert result.governing_distance_m == pytest.approx(11.0)
    assert result.common_path_status == "not_checked"
    assert "common_path_unique_route_unverified" in result.unresolved_facts


def test_multiple_room_doors_remain_not_checked_until_candidate_completeness() -> None:
    layout, boundary = _base_30x12()
    layout.openings.append(
        OpeningSegment(
            opening_id="door-far-2",
            kind="door",
            connects=("room-far", "corridor"),
            start=(25.25, 7.0),
            end=(26.25, 7.0),
            clear_width=1.0,
        )
    )

    result = _measure(layout, boundary)

    assert result.status == "not_checked"
    assert (
        "multiple_room_doors_farthest_candidates_unsupported:room-far"
        in result.unresolved_facts
    )


def test_axis_aligned_l_shaped_floor_is_supported() -> None:
    room = RoomPolygon("room", "office", _rect(6.0, 8.0, 10.0, 12.0))
    circulation = [
        RoomPolygon("horizontal", "circulation", _rect(0.0, 4.0, 10.0, 6.0)),
        RoomPolygon("vertical", "circulation", _rect(8.0, 4.0, 10.0, 8.0)),
    ]
    layout = _layout(
        rooms=[room],
        circulation=circulation,
        openings=[
            OpeningSegment(
                "door",
                "door",
                ("room", "vertical"),
                (8.5, 8.0),
                (9.5, 8.0),
                1.0,
            )
        ],
        exits=(
            PlanLine(
                "exit",
                "egress",
                "protected_exit",
                ((0.0, 4.5), (0.0, 5.5)),
                host_id="horizontal",
                target_id="stair",
                clear_width=1.0,
            ),
        ),
    )

    result = _measure(
        layout,
        (
            (0.0, 0.0),
            (12.0, 0.0),
            (12.0, 12.0),
            (6.0, 12.0),
            (6.0, 8.0),
            (0.0, 8.0),
        ),
    )

    assert result.status == "checked"
    assert "non_axis_aligned_polygon" not in result.unresolved_facts


def test_unsupported_diagonal_floor_is_stably_not_checked() -> None:
    layout, _ = _base_30x12()

    result = _measure(
        layout,
        ((0.0, 0.0), (30.0, 0.0), (29.0, 12.0), (0.0, 12.0)),
    )

    assert result.status == "not_checked"
    assert result.governing_distance_m is None
    assert result.unresolved_facts == ("non_axis_aligned_polygon",)


def test_narrow_concave_notch_crossing_is_not_contained() -> None:
    layout, _ = _base_30x12()
    floor_with_narrow_notch = (
        (0.0, 0.0),
        (30.0, 0.0),
        (30.0, 12.0),
        (2.2, 12.0),
        (2.2, 6.0),
        (2.0, 6.0),
        (2.0, 12.0),
        (0.0, 12.0),
    )

    result = _measure(layout, floor_with_narrow_notch)

    assert result.status == "not_checked"
    assert "geometry_out_of_boundary:corridor" in result.unresolved_facts
    assert result.governing_distance_m is None


def test_missing_basic_design_protected_exits_is_not_checked() -> None:
    layout, boundary = _base_30x12()
    layout = LayoutCandidate(
        **{
            **layout.__dict__,
            "basic_design": None,
        }
    )

    result = _measure(layout, boundary)

    assert result.status == "not_checked"
    assert "protected_exit_portal_missing" in result.unresolved_facts


def test_protected_exit_must_touch_its_stair_or_core_host() -> None:
    layout, boundary = _base_30x12()
    assert layout.basic_design is not None
    detached_stair = PlanElement(
        element_id="stair-west",
        category="vertical",
        kind="stair",
        host_id="floor",
        label="UP",
        footprint=tuple(_rect(10.0, 0.0, 11.0, 1.0)),
    )
    layout = LayoutCandidate(
        **{
            **layout.__dict__,
            "basic_design": BasicDesignFeatures(
                elements=(detached_stair,),
                lines=layout.basic_design.lines,
            ),
        }
    )

    result = _measure(layout, boundary)

    assert result.status == "not_checked"
    assert "invalid_protected_exit_portal:exit-west" in result.unresolved_facts


@pytest.mark.parametrize(
    "occupied_room_ids",
    [(), ("missing",), ("room-far", "room-far")],
)
def test_occupied_room_ids_must_be_explicit_and_valid(
    occupied_room_ids: tuple[str, ...],
) -> None:
    layout, boundary = _base_30x12()

    with pytest.raises(ValueError, match="occupied_room_ids"):
        measure_traversable_egress(
            layout=layout,
            floor_boundary=boundary,
            occupied_room_ids=occupied_room_ids,
        )
