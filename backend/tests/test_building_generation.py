import backend.app.modules.generation_loop.service as generation_service
from dataclasses import replace
import math

import pytest

from backend.app.modules.layout_generator.service import generate_core_aligned_layout
from backend.app.modules.mass_analyzer.service import analyze_mass
from backend.app.modules.program_prior.service import generate_program_graph
from backend.app.schemas.llm import FloorAssignment
from backend.app.schemas.mass import MassInput
from engine.geometry import orthogonal_min_width, shared_boundary_segments
from engine.geometry.polygon import (
    polygon_area,
    shared_boundary_length,
    shared_boundary_with_segments_length,
)


def test_building_generation_assigns_all_floors_and_aligns_vertical_core():
    mass = MassInput(
        project_id="five-floor-mixed-use",
        floors=5,
        footprint_polygon=[(0, 0), (30, 0), (30, 10), (0, 10)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"neighborhood_commercial": 0.2, "office": 0.8},
    )

    result = generation_service.run_building_generation(mass)

    assert [
        (assignment.floor_index, assignment.use_type)
        for assignment in result.floor_assignments
    ] == [
        (1, "neighborhood_commercial"),
        (2, "office"),
        (3, "office"),
        (4, "office"),
        (5, "office"),
    ]
    assert len(result.floor_results) == mass.floors
    assert [
        (floor.program.floor_index, floor.program.use_type)
        for floor in result.floor_results
    ] == [
        (1, "neighborhood_commercial"),
        (2, "office"),
        (3, "office"),
        (4, "office"),
        (5, "office"),
    ]

    core_polygons = [
        next(
            room.polygon
            for room in floor.layout.rooms
            if room.space_type == "core"
        )
        for floor in result.floor_results
    ]
    assert all(polygon == core_polygons[0] for polygon in core_polygons[1:])

    assert result.total_area == 1500
    assert result.use_type_areas == {
        "neighborhood_commercial": 300,
        "office": 1200,
    }
    assert result.accepted
    assert all(floor.validation.accepted for floor in result.floor_results)
    assert all(
        len(floor.layout.openings) == len(floor.layout.rooms)
        for floor in result.floor_results
    )
    for floor in result.floor_results:
        room_ids = {room.room_id for room in floor.layout.rooms}
        circulation_ids = {path.room_id for path in floor.layout.circulation}
        assert {
            opening.connects[0]
            for opening in floor.layout.openings
        } == room_ids
        assert all(
            opening.kind == "door"
            and opening.clear_width == pytest.approx(0.9)
            and opening.connects[1] in circulation_ids
            for opening in floor.layout.openings
        )


def test_building_generation_accepts_complete_structured_floor_assignments():
    mass = MassInput(
        project_id="llm-planned",
        floors=3,
        footprint_polygon=[(0, 0), (24, 0), (24, 12), (0, 12)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"neighborhood_commercial": 1 / 3, "office": 2 / 3},
    )

    result = generation_service.run_building_generation(
        mass,
        floor_assignments=[
            FloorAssignment(3, "office"),
            FloorAssignment(1, "neighborhood_commercial"),
            FloorAssignment(2, "office"),
        ],
    )

    assert [item.floor_index for item in result.floor_assignments] == [1, 2, 3]
    assert result.assignment_source == "structured"
    assert result.accepted
    commercial = result.floor_results[0]
    rooms = {room.room_id: room for room in commercial.layout.rooms}
    assert set(rooms) == {"sales", "checkout", "stock", "staff", "restroom", "core", "utility"}
    assert all(metric.within_range for metric in commercial.validation.room_areas)
    assert all(metric.minimum_width_passed and metric.aspect_ratio_passed for metric in commercial.validation.room_shapes)
    assert shared_boundary_with_segments_length(rooms["sales"].polygon, [((0, 0), (24, 0))]) > 0
    assert shared_boundary_with_segments_length(rooms["stock"].polygon, [((0, 0), (24, 0))]) == 0
    assert shared_boundary_with_segments_length(rooms["staff"].polygon, [((0, 0), (24, 0))]) == 0
    assert len(commercial.layout.openings) == len(rooms)
    assert len(commercial.layout.circulation) == 2
    circulation = {path.room_id: path for path in commercial.layout.circulation}
    assert shared_boundary_length(*[path.polygon for path in circulation.values()]) >= 1.2
    assert all(orthogonal_min_width(path.polygon) >= 1.2 for path in circulation.values())
    for opening in commercial.layout.openings:
        assert opening.clear_width == pytest.approx(0.9)
        room = rooms[opening.connects[0]]
        path = circulation[opening.connects[1]]
        segments = shared_boundary_segments(room.polygon, path.polygon)
        start, end = max(segments, key=lambda segment: (math.dist(*segment), segment))
        midpoint = tuple((start[index] + end[index]) / 2 for index in range(2))
        door_midpoint = tuple((opening.start[index] + opening.end[index]) / 2 for index in range(2))
        assert door_midpoint == pytest.approx(midpoint)
        assert math.dist(opening.start, opening.end) == pytest.approx(0.9)
        assert math.dist(start, opening.start) == pytest.approx(
            (math.dist(start, end) - 0.9) / 2
        )


@pytest.mark.parametrize(
    "assignments",
    [
        [FloorAssignment(1, "office")],
        [
            FloorAssignment(1, "neighborhood_commercial"),
            FloorAssignment(1, "office"),
            FloorAssignment(3, "office"),
        ],
        [
            FloorAssignment(1, "neighborhood_commercial"),
            FloorAssignment(2, "office"),
            FloorAssignment(4, "office"),
        ],
    ],
)
def test_building_generation_rejects_incomplete_duplicate_or_out_of_range_assignments(
    assignments,
):
    mass = MassInput(
        project_id="invalid-assignments",
        floors=3,
        footprint_polygon=[(0, 0), (24, 0), (24, 12), (0, 12)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[],
        use_mix={"neighborhood_commercial": 1 / 3, "office": 2 / 3},
    )

    with pytest.raises(ValueError, match="floor assignments"):
        generation_service.run_building_generation(
            mass,
            floor_assignments=assignments,
        )


def test_building_generation_rejects_unsupported_or_empty_use_mix():
    base = dict(
        project_id="invalid-mix",
        floors=2,
        footprint_polygon=[(0, 0), (20, 0), (20, 10), (0, 10)],
        site_edges=[],
        access_candidates=[],
    )

    with pytest.raises(ValueError, match="use_mix"):
        generation_service.run_building_generation(MassInput(**base, use_mix={}))
    with pytest.raises(ValueError, match="unsupported"):
        generation_service.run_building_generation(
            MassInput(**base, use_mix={"hotel": 1.0})
        )


def test_role_driven_profiles_generate_exact_rooms_and_valid_30x12_layouts():
    mass = MassInput(
        project_id="role-driven-30x12",
        floors=5,
        footprint_polygon=[(0, 0), (30, 0), (30, 12), (0, 12)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"neighborhood_commercial": 0.2, "office": 0.8},
    )

    result = generation_service.run_building_generation(mass)

    expected = {
        "neighborhood_commercial": {
            "sales", "checkout", "stock", "staff", "restroom", "core", "utility"
        },
        "office": {
            "open_work", "meeting", "reception", "focus", "pantry", "restroom",
            "core", "it_storage",
        },
    }
    street = [((0, 0), (30, 0))]
    for floor in result.floor_results:
        rooms = {room.room_id: room for room in floor.layout.rooms}
        assert set(rooms) == expected[floor.program.use_type]
        assert floor.validation.accepted
        assert len(floor.layout.openings) == len(rooms)
        assert all(opening.clear_width == pytest.approx(0.9) for opening in floor.layout.openings)
        assert all(metric.within_range for metric in floor.validation.room_areas)
        assert all(
            metric.minimum_width_passed and metric.aspect_ratio_passed
            for metric in floor.validation.room_shapes
        )

        if floor.program.use_type == "neighborhood_commercial":
            assert shared_boundary_with_segments_length(rooms["sales"].polygon, street) > 0
            assert shared_boundary_with_segments_length(rooms["stock"].polygon, street) == 0
            assert shared_boundary_with_segments_length(rooms["staff"].polygon, street) == 0
        else:
            areas = {room_id: polygon_area(room.polygon) for room_id, room in rooms.items()}
            assert areas["open_work"] == max(areas.values())


def test_role_driven_generation_rejects_missing_street_frontage():
    mass = MassInput(
        project_id="missing-street",
        floors=1,
        footprint_polygon=[(0, 0), (30, 0), (30, 12), (0, 12)],
        site_edges=[],
        access_candidates=[],
        use_mix={"neighborhood_commercial": 1.0},
    )

    with pytest.raises(ValueError, match="street"):
        generation_service.run_building_generation(mass)


def test_role_driven_generation_rejects_non_bottom_street_frontage():
    mass = MassInput(
        project_id="side-street",
        floors=1,
        footprint_polygon=[(0, 0), (30, 0), (30, 12), (0, 12)],
        site_edges=[{"edge_index": 1, "kind": "street"}],
        access_candidates=[],
        use_mix={"neighborhood_commercial": 1.0},
    )

    with pytest.raises(ValueError, match="y=min_y"):
        generation_service.run_building_generation(mass)


@pytest.mark.parametrize(
    ("nodes", "match"),
    [
        (lambda nodes: nodes[1:], "missing="),
        (lambda nodes: [*nodes, nodes[0]], "duplicate="),
        (
            lambda nodes: [replace(nodes[0], space_type="unexpected") , *nodes[1:]],
            "extra=",
        ),
    ],
)
def test_role_driven_layout_rejects_invalid_profile_roles(nodes, match):
    mass = MassInput(
        project_id="role-contract",
        floors=1,
        footprint_polygon=[(0, 0), (30, 0), (30, 12), (0, 12)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[],
        use_mix={"neighborhood_commercial": 1.0},
    )
    analysis = analyze_mass(mass)
    program = generate_program_graph(analysis, 1, "neighborhood_commercial")
    invalid = replace(program, nodes=nodes(program.nodes))

    with pytest.raises(ValueError, match=match):
        generate_core_aligned_layout(
            analysis,
            invalid,
            core_polygon=[(24, 0), (30, 0), (30, 7.2), (24, 7.2)],
            service_band_width=6,
        )


@pytest.mark.parametrize(
    "core_polygon",
    [
        [(24, 0), (30, 0), (30, 7.2), (27, 3.6)],
        [(24, 0), (30, 0), (30, 7.2), (24, 7.2), (24, 3.6)],
    ],
)
def test_role_driven_layout_rejects_malformed_shared_core(core_polygon):
    mass = MassInput(
        project_id="core-contract",
        floors=1,
        footprint_polygon=[(0, 0), (30, 0), (30, 12), (0, 12)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[],
        use_mix={"neighborhood_commercial": 1.0},
    )
    analysis = analyze_mass(mass)
    program = generate_program_graph(analysis, 1, "neighborhood_commercial")

    with pytest.raises(ValueError, match="shared core"):
        generate_core_aligned_layout(
            analysis,
            program,
            core_polygon=core_polygon,
            service_band_width=6,
        )
