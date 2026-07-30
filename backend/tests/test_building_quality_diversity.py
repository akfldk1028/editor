from __future__ import annotations

from dataclasses import replace

from backend.app.modules.building_quality import (
    DEFAULT_QUALITY_POLICY,
    compare_building_diversity,
)
from backend.app.schemas.layout import LayoutCandidate, RoomPolygon
from backend.app.schemas.mass import MassAnalysis
from backend.app.schemas.metrics import ValidationReport
from backend.app.schemas.program import ProgramEdge, ProgramGraph, ProgramNode
from backend.app.schemas.result import (
    BuildingGenerationResult,
    GenerationResult,
    PlannerProvenance,
)


def test_coordinate_order_only_does_not_create_diversity() -> None:
    first = _building()
    second = _same_building_with_reversed_polygon_rings(first)

    report = compare_building_diversity(first, second)

    assert report.first_fingerprint == report.second_fingerprint
    assert report.total_distance == 0.0
    assert report.nonzero_component_count == 0
    assert report.quality_distinct is False


def test_core_and_circulation_change_is_quality_distinct() -> None:
    first = _building(core_offset=(0.0, 0.0), corridor="horizontal")
    second = _building(core_offset=(8.0, 0.0), corridor="vertical")

    report = compare_building_diversity(first, second)

    assert report.core_distance > 0
    assert report.circulation_distance > 0
    assert report.nonzero_component_count >= 2
    assert report.total_distance >= DEFAULT_QUALITY_POLICY.minimum_pairwise_diversity
    assert report.quality_distinct is True


def test_custom_policy_threshold_controls_quality_distinction() -> None:
    first = _building(core_offset=(0.0, 0.0), corridor="horizontal")
    second = _building(core_offset=(8.0, 0.0), corridor="vertical")
    strict_policy = replace(DEFAULT_QUALITY_POLICY, minimum_pairwise_diversity=0.8)

    report = compare_building_diversity(first, second, policy=strict_policy)

    assert report.nonzero_component_count >= 2
    assert report.total_distance < strict_policy.minimum_pairwise_diversity
    assert report.quality_distinct is False


def test_program_room_ids_do_not_change_topology_or_diversity() -> None:
    first = _building()
    second = _same_building_with_renamed_room_ids(first)

    report = compare_building_diversity(first, second)

    assert report.topology_distance == 0.0
    assert report.total_distance == 0.0


def _building(
    *,
    core_offset: tuple[float, float] = (0.0, 0.0),
    corridor: str = "horizontal",
) -> BuildingGenerationResult:
    core_x, core_y = 2.0 + core_offset[0], 2.0 + core_offset[1]
    circulation_polygon = (
        [(0.0, 6.0), (20.0, 6.0), (20.0, 8.0), (0.0, 8.0)]
        if corridor == "horizontal"
        else [(8.0, 0.0), (12.0, 0.0), (12.0, 10.0), (8.0, 10.0)]
    )
    nodes = [
        ProgramNode(node_id="core-1", space_type="core", target_area=16.0),
        ProgramNode(node_id="office-1", space_type="office", target_area=80.0),
        ProgramNode(node_id="meeting-1", space_type="meeting", target_area=40.0),
    ]
    program = ProgramGraph(
        project_id="diversity",
        floor_index=1,
        use_type="office",
        nodes=nodes,
        edges=[
            ProgramEdge("office-1", "meeting-1", "adjacent"),
            ProgramEdge("office-1", "core-1", "near"),
        ],
        source="test",
    )
    layout = LayoutCandidate(
        candidate_id="candidate",
        project_id="diversity",
        floor_index=1,
        rooms=[
            RoomPolygon(
                room_id="core-1",
                space_type="core",
                polygon=[
                    (core_x, core_y),
                    (core_x + 4.0, core_y),
                    (core_x + 4.0, core_y + 4.0),
                    (core_x, core_y + 4.0),
                ],
            ),
            RoomPolygon(
                room_id="office-1",
                space_type="office",
                polygon=[(0.0, 0.0), (10.0, 0.0), (10.0, 6.0), (0.0, 6.0)],
            ),
            RoomPolygon(
                room_id="meeting-1",
                space_type="meeting",
                polygon=[(10.0, 0.0), (20.0, 0.0), (20.0, 6.0), (10.0, 6.0)],
            ),
        ],
        circulation=[
            RoomPolygon(
                room_id="corridor-1",
                space_type="circulation",
                polygon=circulation_polygon,
            )
        ],
        score=1.0,
    )
    mass = MassAnalysis(
        project_id="diversity",
        area=200.0,
        floor_area=200.0,
        floors=1,
        edge_count=4,
        street_edge_indices=[],
        access_edge_indices=[],
        bounds=(0.0, 0.0, 20.0, 10.0),
    )
    floor = GenerationResult(
        mass=mass,
        program=program,
        layout=layout,
        validation=_validation_report(),
    )
    return BuildingGenerationResult(
        mass=mass,
        floor_assignments=(),
        floor_results=(floor,),
        total_area=200.0,
        use_type_areas={"office": 200.0},
        assignment_source="test",
        vertical_core_aligned=True,
        vertical_basic_design_aligned=True,
        vertical_structure_aligned=True,
        planner_provenance=PlannerProvenance("test", "test", None, None, ()),
    )


def _same_building_with_reversed_polygon_rings(
    building: BuildingGenerationResult,
) -> BuildingGenerationResult:
    floor = building.floor_results[0]
    layout = replace(
        floor.layout,
        rooms=[
            replace(room, polygon=list(reversed(room.polygon)))
            for room in floor.layout.rooms
        ],
        circulation=[
            replace(path, polygon=list(reversed(path.polygon)))
            for path in floor.layout.circulation
        ],
    )
    return replace(building, floor_results=(replace(floor, layout=layout),))


def _same_building_with_renamed_room_ids(
    building: BuildingGenerationResult,
) -> BuildingGenerationResult:
    floor = building.floor_results[0]
    room_ids = {
        room.room_id: f"alternative-{index}"
        for index, room in enumerate(floor.layout.rooms, start=1)
    }
    program = replace(
        floor.program,
        nodes=[
            replace(node, node_id=room_ids[node.node_id])
            for node in floor.program.nodes
        ],
        edges=[
            replace(
                edge,
                source=room_ids[edge.source],
                target=room_ids[edge.target],
            )
            for edge in floor.program.edges
        ],
    )
    layout = replace(
        floor.layout,
        rooms=[
            replace(room, room_id=room_ids[room.room_id])
            for room in floor.layout.rooms
        ],
    )
    return replace(
        building,
        floor_results=(replace(floor, program=program, layout=layout),),
    )


def _validation_report() -> ValidationReport:
    return ValidationReport(
        is_valid=True,
        accepted=True,
        hard_violation_count=0,
        violation_score=0.0,
        violations=[],
        room_areas=[],
        area_score=1.0,
        overlap_score=1.0,
        boundary_score=1.0,
        circulation_score=1.0,
        efficiency_score=1.0,
        adjacency_score=1.0,
        frontage_score=1.0,
        coverage_score=1.0,
        compactness_score=1.0,
        total_score=1.0,
        messages=[],
        policy_version="test",
    )
