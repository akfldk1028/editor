import backend.app.modules.generation_loop.service as generation_service
import pytest

from backend.app.schemas.llm import FloorAssignment
from backend.app.schemas.mass import MassInput
from engine.geometry.polygon import polygon_area, shared_boundary_with_segments_length


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
