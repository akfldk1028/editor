from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import math

import pytest

from backend.app.modules.generation_loop.service import run_building_generation
from backend.app.modules.basic_design.service import generate_basic_design
from backend.app.schemas.layout import BasicDesignFeatures, PlanElement, PlanLine, RoomPolygon
from backend.app.schemas.mass import MassInput
from engine.geometry.polygon import polygon_area, polygon_overlap_area


def test_basic_design_records_are_typed_frozen_and_reject_non_finite_values() -> None:
    element = PlanElement(
        element_id="core-stair-1",
        category="vertical",
        kind="stair",
        host_id="core",
        label="UP",
        footprint=((1.0, 2.0), (2.2, 2.0), (2.2, 4.4), (1.0, 4.4)),
    )
    line = PlanLine(
        line_id="exit-1",
        category="egress",
        kind="protected_exit",
        points=((1.0, 2.0), (1.9, 2.0)),
        clear_width=0.9,
    )
    features = BasicDesignFeatures(elements=(element,), lines=(line,))

    assert features.elements == (element,)
    assert features.lines == (line,)
    with pytest.raises(FrozenInstanceError):
        element.kind = "elevator"  # type: ignore[misc]
    with pytest.raises(ValueError, match="finite"):
        PlanLine(
            line_id="bad-exit",
            category="egress",
            kind="protected_exit",
            points=((float("nan"), 0.0), (1.0, 0.0)),
        )


def test_building_generation_adds_complete_deterministic_basic_design_features() -> None:
    mass = MassInput(
        project_id="basic-design-contract",
        floors=5,
        footprint_polygon=[(0, 0), (30, 0), (30, 12), (0, 12)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"neighborhood_commercial": 0.2, "office": 0.8},
    )

    result = run_building_generation(mass)

    first = result.floor_results[0].layout.basic_design
    assert first is not None
    for floor in result.floor_results:
        layout = floor.layout
        features = layout.basic_design
        assert features is not None
        assert features.policy_version == "concept-basic-v1"
        assert all(
            math.isfinite(value)
            for feature in (*features.elements, *features.lines)
            for point in (feature.footprint if isinstance(feature, PlanElement) else feature.points)
            for value in point
        )
        vertical = [element for element in features.elements if element.category == "vertical"]
        assert {element.kind for element in vertical} == {"stair", "elevator", "lobby", "shaft"}
        assert sum(element.kind == "stair" for element in vertical) == 2
        stairs = [element for element in vertical if element.kind == "stair"]
        assert all(
            sorted(
                (
                    max(point[0] for point in stair.footprint)
                    - min(point[0] for point in stair.footprint),
                    max(point[1] for point in stair.footprint)
                    - min(point[1] for point in stair.footprint),
                )
            )
            == pytest.approx([2.8, 4.8])
            for stair in stairs
        )
        assert all(
            polygon_overlap_area(left.footprint, right.footprint) == pytest.approx(0.0)
            for index, left in enumerate(features.elements)
            for right in features.elements[index + 1 :]
        )
        exits = [line for line in features.lines if line.kind == "protected_exit"]
        assert len(exits) == 2
        assert {line.clear_width for line in exits} == {0.9}
        assert exits[0].points != exits[1].points
        stair_doors = [line for line in features.lines if line.kind == "stair_door"]
        lobby_routes = [line for line in features.lines if line.kind == "lobby_route"]
        lobby = next(element for element in vertical if element.kind == "lobby")
        assert len(stair_doors) == 2
        assert len(lobby_routes) == 2
        assert {line.target_id for line in stair_doors} == {
            stair.element_id for stair in stairs
        }
        assert {line.target_id for line in lobby_routes} == {
            line.line_id for line in stair_doors
        }
        for route in lobby_routes:
            exit_line = next(
                line
                for line in exits
                if line.target_id
                == next(
                    door.target_id
                    for door in stair_doors
                    if door.line_id == route.target_id
                )
            )
            stair_door = next(
                line for line in stair_doors if line.line_id == route.target_id
            )
            assert route.points[0] == pytest.approx(
                _midpoint(exit_line.points[0], exit_line.points[-1])
            )
            assert route.points[-1] == pytest.approx(
                _midpoint(stair_door.points[0], stair_door.points[-1])
            )
            assert all(
                _axis_aligned_segment(start, end)
                and _segment_in_polygon(start, end, lobby.footprint)
                for start, end in zip(route.points, route.points[1:])
            )
        door_midpoints = {
            opening.connects[0]: tuple(
                (opening.start[index] + opening.end[index]) / 2 for index in range(2)
            )
            for opening in layout.openings
        }
        non_core_rooms = [room for room in layout.rooms if room.space_type != "core"]
        routes = [line for line in features.lines if line.kind == "egress_route"]
        for room in non_core_rooms:
            room_routes = [route for route in routes if route.host_id == room.room_id]
            assert len(room_routes) == 2
            assert {route.target_id for route in room_routes} == {line.line_id for line in exits}
            assert all(route.points[0] == pytest.approx(door_midpoints[room.room_id]) for route in room_routes)
            assert all(
                _axis_aligned_segment(start, end)
                and _segment_in_circulation_union(start, end, layout.circulation)
                for route in room_routes
                for start, end in zip(route.points, route.points[1:])
            )
        grids = [line for line in features.lines if line.kind == "grid"]
        columns = [element for element in features.elements if element.kind == "column"]
        assert grids and columns
        assert all(
            abs(element.footprint[1][0] - element.footprint[0][0]) == pytest.approx(0.4)
            and abs(element.footprint[2][1] - element.footprint[1][1]) == pytest.approx(0.4)
            for element in columns
        )
        assert {line.kind for line in features.lines if line.category == "dimension"} == {
            "overall_width", "overall_depth", "circulation_width"
        }
        assert {"street", "north_arrow", "scale_line"} <= {
            line.kind for line in features.lines if line.category == "site"
        }
        if floor.program.use_type == "office":
            required = {
                "open_work": {"workstation"}, "meeting": {"meeting_table"},
                "reception": {"reception_desk"}, "focus": {"focus_desk"},
                "pantry": {"pantry_counter", "sink"}, "restroom": {"wc", "lavatory"},
                "it_storage": {"it_rack"},
            }
        else:
            required = {
                "sales": {"sales_shelf"}, "checkout": {"checkout_counter"},
                "stock": {"stock_rack"}, "staff": {"staff_table"},
                "restroom": {"wc", "lavatory"}, "utility": {"utility_equipment"},
            }
            assert len([line for line in features.lines if line.kind == "entrance"]) == 1
        for room_id, kinds in required.items():
            assert kinds <= {
                element.kind for element in features.elements if element.host_id == room_id
            }
        assert [
            (element.element_id, element.footprint) for element in features.elements
            if element.category in {"vertical", "structure"}
        ] == [
            (element.element_id, element.footprint) for element in first.elements
            if element.category in {"vertical", "structure"}
        ]


def test_primary_room_furniture_density_scales_with_area() -> None:
    result = run_building_generation(_mixed_use_mass())

    expected_kinds = {
        "sales": "sales_shelf",
        "open_work": "workstation",
    }
    for floor in result.floor_results:
        layout = floor.layout
        features = layout.basic_design
        assert features is not None
        primary = next(
            room for room in layout.rooms if room.space_type in expected_kinds
        )
        expected_count = max(2, math.floor(polygon_area(primary.polygon) / 30.0))
        actual = [
            element
            for element in features.elements
            if element.host_id == primary.room_id
            and element.kind == expected_kinds[primary.space_type]
        ]

        assert expected_count >= 5
        assert len(actual) >= expected_count
        assert all(
            polygon_overlap_area(left.footprint, right.footprint)
            == pytest.approx(0.0)
            for index, left in enumerate(actual)
            for right in actual[index + 1 :]
        )
        centers = [
            (
                sum(point[0] for point in element.footprint) / len(element.footprint),
                sum(point[1] for point in element.footprint) / len(element.footprint),
            )
            for element in actual
        ]
        room_width = max(point[0] for point in primary.polygon) - min(
            point[0] for point in primary.polygon
        )
        room_depth = max(point[1] for point in primary.polygon) - min(
            point[1] for point in primary.polygon
        )
        assert max(center[0] for center in centers) - min(
            center[0] for center in centers
        ) >= room_width * 0.3
        assert max(center[1] for center in centers) - min(
            center[1] for center in centers
        ) >= room_depth * 0.3
        clearance_segments = [
            (opening.start, opening.end)
            for opening in layout.openings
        ] + [
            segment
            for line in features.lines
            if line.kind in {"egress_route", "entrance"}
            for segment in zip(line.points, line.points[1:])
        ]
        assert all(
            not _rectangle_near_segment(
                element.footprint,
                segment,
                clearance=0.59,
            )
            for element in actual
            for segment in clearance_segments
        )


def test_primary_objects_form_interior_banks_with_clear_access_strips() -> None:
    result = run_building_generation(_mixed_use_mass())

    policy = {
        "sales": ("sales_shelf", (2.4, 3.0), (0.8, 0.9), "GONDOLA"),
        "open_work": ("workstation", (2.4, 3.0), (1.4, 1.6), "WORK BENCH"),
    }
    for floor in result.floor_results:
        layout = floor.layout
        features = layout.basic_design
        assert features is not None
        room = next(item for item in layout.rooms if item.space_type in policy)
        kind, long_range, short_range, label = policy[room.space_type]
        objects = [
            element
            for element in features.elements
            if element.host_id == room.room_id and element.kind == kind
        ]
        assert len(objects) >= 5

        room_min_x = min(point[0] for point in room.polygon)
        room_min_y = min(point[1] for point in room.polygon)
        room_max_x = max(point[0] for point in room.polygon)
        room_max_y = max(point[1] for point in room.polygon)
        center = (
            (room_min_x + room_max_x) / 2,
            (room_min_y + room_max_y) / 2,
        )
        for element in objects:
            min_x = min(point[0] for point in element.footprint)
            min_y = min(point[1] for point in element.footprint)
            max_x = max(point[0] for point in element.footprint)
            max_y = max(point[1] for point in element.footprint)
            width, depth = max_x - min_x, max_y - min_y
            assert long_range[0] - 1e-7 <= width <= long_range[1] + 1e-7
            assert short_range[0] - 1e-7 <= depth <= short_range[1] + 1e-7
            assert element.label == label
            assert min_x - room_min_x >= 0.8
            assert min_y - room_min_y >= 0.8
            assert room_max_x - max_x >= 0.8
            assert room_max_y - max_y >= 0.8

        x_values = sorted(
            {
                round(min(point[0] for point in element.footprint), 6)
                for element in objects
            }
        )
        y_values = sorted(
            {
                round(min(point[1] for point in element.footprint), 6)
                for element in objects
            }
        )
        assert len(x_values) >= 2
        assert len(y_values) >= 2
        _assert_regular_lattice(x_values)
        _assert_regular_lattice(y_values)

        room_door = next(
            opening
            for opening in layout.openings
            if room.room_id in opening.connects
        )
        door_midpoint = (
            (room_door.start[0] + room_door.end[0]) / 2,
            (room_door.start[1] + room_door.end[1]) / 2,
        )
        access_segments = _orthogonal_path_segments(door_midpoint, center)
        entrance = next(
            (
                line
                for line in features.lines
                if line.kind == "entrance" and line.host_id == room.room_id
            ),
            None,
        )
        if entrance is not None:
            entrance_midpoint = (
                (entrance.points[0][0] + entrance.points[-1][0]) / 2,
                (entrance.points[0][1] + entrance.points[-1][1]) / 2,
            )
            access_segments.extend(
                _orthogonal_path_segments(entrance_midpoint, center)
            )
        window_segments = [
            (line.points[0], line.points[-1])
            for line in features.lines
            if line.kind == "window" and line.host_id == room.room_id
        ]
        assert all(
            not _rectangle_near_segment(
                element.footprint,
                segment,
                clearance=0.59,
            )
            for element in objects
            for segment in [*access_segments, *window_segments]
        )

        for left in objects:
            for right in objects:
                if left.element_id >= right.element_id:
                    continue
                left_box = _footprint_bounds(left.footprint)
                right_box = _footprint_bounds(right.footprint)
                if left_box[1] == pytest.approx(right_box[1]):
                    assert _axis_gap(left_box[0], left_box[2], right_box[0], right_box[2]) >= 1.19
                if left_box[0] == pytest.approx(right_box[0]):
                    assert _axis_gap(left_box[1], left_box[3], right_box[1], right_box[3]) >= 1.19


def test_basic_design_rejects_non_axis_aligned_circulation() -> None:
    mass = _mixed_use_mass()
    layout = run_building_generation(mass).floor_results[0].layout
    first, *rest = layout.circulation
    malformed = replace(
        first,
        polygon=[
            first.polygon[0],
            (first.polygon[1][0], first.polygon[1][1] + 0.25),
            *first.polygon[2:],
        ],
    )

    with pytest.raises(ValueError, match="axis-aligned rectilinear"):
        generate_basic_design(
            replace(layout, circulation=[malformed, *rest]),
            boundary=mass.footprint_polygon,
            street_segments=[((0, 0), (30, 0))],
        )


def test_sales_window_is_disjoint_from_the_commercial_entrance() -> None:
    result = run_building_generation(_mixed_use_mass())
    features = result.floor_results[0].layout.basic_design
    assert features is not None
    entrance = next(line for line in features.lines if line.kind == "entrance")
    sales_window = next(
        line for line in features.lines
        if line.kind == "window" and line.host_id == "sales"
    )

    assert _collinear_overlap_length(entrance.points, sales_window.points) == pytest.approx(0.0)
    assert min(
        math.dist(entrance_point, window_point)
        for entrance_point in entrance.points
        for window_point in sales_window.points
    ) > 0.05


def test_basic_design_rejects_duplicate_and_nonrectangular_cores() -> None:
    mass = _mixed_use_mass()
    layout = run_building_generation(mass).floor_results[0].layout
    core = next(room for room in layout.rooms if room.space_type == "core")
    duplicate = replace(core, room_id="core-duplicate")

    with pytest.raises(ValueError, match="exactly one core"):
        generate_basic_design(
            replace(layout, rooms=[*layout.rooms, duplicate]),
            boundary=mass.footprint_polygon,
            street_segments=[((0, 0), (30, 0))],
        )

    nonrectangular = RoomPolygon(
        room_id=core.room_id,
        space_type="core",
        polygon=[(24, 0), (30, 0), (30, 4), (27, 4), (27, 7.2), (24, 7.2)],
    )
    with pytest.raises(ValueError, match="axis-aligned rectangle"):
        generate_basic_design(
            replace(
                layout,
                rooms=[nonrectangular if room.room_id == core.room_id else room for room in layout.rooms],
            ),
            boundary=mass.footprint_polygon,
            street_segments=[((0, 0), (30, 0))],
        )


def test_office_basic_design_requires_exactly_one_street_edge() -> None:
    mass = MassInput(
        project_id="office-without-street",
        floors=1,
        footprint_polygon=[(0, 0), (30, 0), (30, 12), (0, 12)],
        site_edges=[],
        access_candidates=[],
        use_mix={"office": 1.0},
    )

    with pytest.raises(ValueError, match="exactly one supplied street edge"):
        run_building_generation(mass)


def test_building_generation_uses_one_shared_structure_for_different_circulation_layouts() -> None:
    result = run_building_generation(_mixed_use_mass())
    commercial, office = (item.layout for item in result.floor_results[:2])
    assert commercial.circulation != office.circulation
    commercial_features = commercial.basic_design
    office_features = office.basic_design
    assert commercial_features is not None and office_features is not None

    def structure(features: BasicDesignFeatures):
        return [
            (element.element_id, element.footprint)
            for element in features.elements
            if element.category == "structure"
        ], [
            (line.line_id, line.points)
            for line in features.lines
            if line.category == "structure"
        ]

    assert structure(commercial_features) == structure(office_features)


def _mixed_use_mass() -> MassInput:
    return MassInput(
        project_id="basic-design-mixed-use",
        floors=2,
        footprint_polygon=[(0, 0), (30, 0), (30, 12), (0, 12)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"neighborhood_commercial": 0.5, "office": 0.5},
    )


def _collinear_overlap_length(first, second) -> float:
    (ax, ay), (bx, by) = first
    (cx, cy), (dx, dy) = second
    if ax == bx == cx == dx:
        return max(0.0, min(max(ay, by), max(cy, dy)) - max(min(ay, by), min(cy, dy)))
    if ay == by == cy == dy:
        return max(0.0, min(max(ax, bx), max(cx, dx)) - max(min(ax, bx), min(cx, dx)))
    return 0.0


def _axis_aligned_segment(start, end) -> bool:
    return start[0] == pytest.approx(end[0]) or start[1] == pytest.approx(end[1])


def _segment_in_circulation_union(start, end, circulation) -> bool:
    distance = math.dist(start, end)
    samples = max(2, math.ceil(distance / 0.05))
    return all(
        any(
            _point_in_polygon_or_boundary(
                (
                    start[0] + (end[0] - start[0]) * index / samples,
                    start[1] + (end[1] - start[1]) * index / samples,
                ),
                path.polygon,
            )
            for path in circulation
        )
        for index in range(samples + 1)
    )


def _segment_in_polygon(start, end, polygon) -> bool:
    distance = math.dist(start, end)
    samples = max(2, math.ceil(distance / 0.05))
    return all(
        _point_in_polygon_or_boundary(
            (
                start[0] + (end[0] - start[0]) * index / samples,
                start[1] + (end[1] - start[1]) * index / samples,
            ),
            polygon,
        )
        for index in range(samples + 1)
    )


def _midpoint(start, end):
    return (
        (start[0] + end[0]) / 2,
        (start[1] + end[1]) / 2,
    )


def _point_in_polygon_or_boundary(point, polygon) -> bool:
    x, y = point
    inside = False
    for start, end in zip(polygon, [*polygon[1:], polygon[0]]):
        cross = (end[0] - start[0]) * (y - start[1]) - (end[1] - start[1]) * (
            x - start[0]
        )
        if (
            abs(cross) <= 1e-7
            and min(start[0], end[0]) - 1e-7 <= x <= max(start[0], end[0]) + 1e-7
            and min(start[1], end[1]) - 1e-7 <= y <= max(start[1], end[1]) + 1e-7
        ):
            return True
        if (start[1] > y) != (end[1] > y):
            intersection_x = start[0] + (y - start[1]) * (
                end[0] - start[0]
            ) / (end[1] - start[1])
            if x < intersection_x:
                inside = not inside
    return inside


def _rectangle_near_segment(rectangle, segment, *, clearance) -> bool:
    min_x = min(point[0] for point in rectangle)
    min_y = min(point[1] for point in rectangle)
    max_x = max(point[0] for point in rectangle)
    max_y = max(point[1] for point in rectangle)
    start, end = segment
    return not (
        max_x < min(start[0], end[0]) - clearance
        or min_x > max(start[0], end[0]) + clearance
        or max_y < min(start[1], end[1]) - clearance
        or min_y > max(start[1], end[1]) + clearance
    )


def _assert_regular_lattice(values) -> None:
    if len(values) < 3:
        return
    gaps = [
        right - left
        for left, right in zip(values, values[1:])
        if right - left > 1e-7
    ]
    base = min(gaps)
    assert all(abs(gap / base - round(gap / base)) <= 1e-6 for gap in gaps)


def _orthogonal_path_segments(start, end):
    bend = (end[0], start[1])
    return [
        segment
        for segment in ((start, bend), (bend, end))
        if math.dist(*segment) > 1e-7
    ]


def _footprint_bounds(footprint):
    return (
        min(point[0] for point in footprint),
        min(point[1] for point in footprint),
        max(point[0] for point in footprint),
        max(point[1] for point in footprint),
    )


def _axis_gap(first_min, first_max, second_min, second_max):
    return max(first_min, second_min) - min(first_max, second_max)
