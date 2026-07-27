import backend.app.modules.generation_loop.service as generation_service
import pytest

from backend.app.schemas.llm import FloorAssignment
from backend.app.schemas.mass import MassInput


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
