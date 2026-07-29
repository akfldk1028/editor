import backend.app.modules.generation_loop.service as generation_service
from dataclasses import replace
import math

import pytest

from backend.app.modules.layout_generator.service import generate_core_aligned_layout
from backend.app.modules.mass_analyzer.service import analyze_mass
from backend.app.modules.program_prior.service import generate_program_graph
from backend.app.schemas.llm import FloorAssignment
from backend.app.schemas.mass import FloorFootprint, MassInput
from backend.app.modules.generation_loop.operators import layout_fingerprint
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
        next(room.polygon for room in floor.layout.rooms if room.space_type == "core")
        for floor in result.floor_results
    ]
    assert all(polygon == core_polygons[0] for polygon in core_polygons[1:])

    assert result.total_area == 1500
    assert result.use_type_areas == {
        "neighborhood_commercial": 300,
        "office": 1200,
    }
    assert result.accepted
    assert result.vertical_basic_design_aligned
    assert result.vertical_structure_aligned
    assert result.planner_provenance.provider == "deterministic"
    assert result.planner_provenance.planner_mode == "deterministic"
    assert result.planner_provenance.validated_assignments == result.floor_assignments


def test_building_generation_accepts_floor_program_override_for_polygonal_mass():
    mass = MassInput(
        project_id="program-override-polygon",
        floors=1,
        footprint_polygon=[
            (0, 0),
            (42, 0),
            (42, 16),
            (36, 22),
            (6, 22),
            (0, 16),
        ],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"office": 1.0},
    )
    baseline = generate_program_graph(analyze_mass(mass), 1, "office")
    override = replace(
        baseline,
        nodes=list(reversed(baseline.nodes)),
        source="local_qwen_topology:topology-1",
    )

    result = generation_service.run_building_generation(
        mass,
        program_overrides={1: override},
    )

    floor = result.floor_results[0]
    assert "local_qwen_topology:topology-1" in floor.program.source
    assert floor.validation.accepted
    assert floor.floor_boundary == tuple(mass.footprint_polygon)
    assert all(floor.validation.accepted for floor in result.floor_results)
    assert all(
        len(floor.layout.openings) == len(floor.layout.rooms)
        for floor in result.floor_results
    )
    for floor in result.floor_results:
        room_ids = {room.room_id for room in floor.layout.rooms}
        circulation_ids = {path.room_id for path in floor.layout.circulation}
        assert {opening.connects[0] for opening in floor.layout.openings} == room_ids
        assert all(
            opening.kind == "door"
            and opening.clear_width == pytest.approx(0.9)
            and opening.connects[1] in circulation_ids
            for opening in floor.layout.openings
        )


def test_rectangular_building_generation_respects_local_topology_order():
    mass = MassInput(
        project_id="rectangular-local-topology",
        floors=1,
        footprint_polygon=[(0, 0), (30, 0), (30, 12), (0, 12)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"office": 1.0},
    )
    baseline = generate_program_graph(analyze_mass(mass), 1, "office")
    reversed_program = replace(
        baseline,
        nodes=list(reversed(baseline.nodes)),
        source="local_qwen_topology:topology-2",
    )

    baseline_result = generation_service.run_building_generation(
        mass,
        program_overrides={
            1: replace(
                baseline,
                source="local_qwen_topology:topology-1",
            )
        },
    )
    reversed_result = generation_service.run_building_generation(
        mass,
        program_overrides={1: reversed_program},
    )

    assert layout_fingerprint(
        baseline_result.floor_results[0].layout
    ) != layout_fingerprint(reversed_result.floor_results[0].layout)
    assert baseline_result.accepted
    assert reversed_result.accepted


def test_polygonal_commercial_building_generation_accepts_program_override():
    mass = MassInput(
        project_id="polygonal-commercial-topology",
        floors=1,
        footprint_polygon=[
            (0, 0),
            (30, 0),
            (30, 12),
            (18, 12),
            (18, 20),
            (0, 20),
        ],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"neighborhood_commercial": 1.0},
    )
    program = generate_program_graph(
        analyze_mass(mass),
        1,
        "neighborhood_commercial",
    )
    override = replace(
        program,
        nodes=list(reversed(program.nodes)),
        source="local_qwen_topology:topology-1",
    )

    result = generation_service.run_building_generation(
        mass,
        program_overrides={1: override},
    )

    assert result.accepted
    assert result.floor_results[0].program.use_type == "neighborhood_commercial"
    sales_rooms = [
        room
        for room in result.floor_results[0].layout.rooms
        if room.space_type == "sales"
    ]
    assert len(sales_rooms) == 2
    assert all(orthogonal_min_width(room.polygon) >= 2.8 for room in sales_rooms)


def test_building_generation_uses_each_setback_floor_boundary():
    floor_boundaries = (
        ((0, 0), (30, 0), (30, 18), (0, 18)),
        ((0, 0), (28, 0), (28, 17), (0, 17)),
        ((0, 0), (26, 0), (26, 16), (0, 16)),
    )
    mass = MassInput(
        project_id="three-floor-setback-office",
        floors=3,
        footprint_polygon=list(floor_boundaries[0]),
        floor_footprints=tuple(
            FloorFootprint(
                floor_index=index,
                footprint_polygon=boundary,
            )
            for index, boundary in enumerate(floor_boundaries, start=1)
        ),
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[],
        use_mix={"office": 1.0},
    )

    result = generation_service.run_building_generation(mass)

    assert result.total_area == 1432
    assert result.use_type_areas == {"office": 1432}
    assert result.vertical_core_aligned
    assert result.accepted
    cores = []
    for floor, expected_boundary in zip(
        result.floor_results,
        floor_boundaries,
    ):
        assert floor.floor_boundary == expected_boundary
        assert floor.floor_boundary_source == "explicit_floor_footprint"
        for shape in (*floor.layout.rooms, *floor.layout.circulation):
            assert generation_service.contains_polygon(
                expected_boundary,
                shape.polygon,
            )
        cores.append(
            next(
                room.polygon for room in floor.layout.rooms if room.space_type == "core"
            )
        )
    assert all(core == cores[0] for core in cores[1:])


def test_building_generation_supports_l_shaped_floor_setbacks():
    floor_boundaries = (
        ((0, 0), (30, 0), (30, 10), (14, 10), (14, 22), (0, 22)),
        ((0, 0), (28, 0), (28, 10), (14, 10), (14, 20), (0, 20)),
        ((0, 0), (26, 0), (26, 10), (14, 10), (14, 18), (0, 18)),
    )
    mass = MassInput(
        project_id="three-floor-l-setback-office",
        floors=3,
        footprint_polygon=list(floor_boundaries[0]),
        floor_footprints=tuple(
            FloorFootprint(floor_index=index, footprint_polygon=boundary)
            for index, boundary in enumerate(floor_boundaries, start=1)
        ),
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[],
        use_mix={"office": 1.0},
    )

    result = generation_service.run_building_generation(mass)

    assert result.total_area == 1260
    assert result.use_type_areas == {"office": 1260}
    assert result.accepted
    assert result.vertical_core_aligned
    assert result.vertical_basic_design_aligned
    assert result.vertical_structure_aligned
    cores = []
    remote_stairs = []
    for floor, expected_boundary in zip(
        result.floor_results,
        floor_boundaries,
    ):
        assert floor.floor_boundary == expected_boundary
        assert floor.validation.accepted
        for shape in (*floor.layout.rooms, *floor.layout.circulation):
            assert generation_service.contains_polygon(
                expected_boundary,
                shape.polygon,
            )
        cores.append(
            next(
                room.polygon for room in floor.layout.rooms if room.space_type == "core"
            )
        )
        remote_stairs.append(floor.layout.remote_stair_footprint)
    assert all(core == cores[0] for core in cores[1:])
    assert all(stair == remote_stairs[0] for stair in remote_stairs[1:])


@pytest.mark.parametrize(
    "floor_boundaries",
    [
        (
            ((0, 0), (42, 0), (39, 24), (6, 24), (0, 12)),
            ((1, 0), (40, 0), (37, 22), (7, 22), (2, 11)),
        ),
        (
            ((0, 0), (42, 0), (42, 16), (36, 22), (6, 22), (0, 16)),
            ((1, 0), (40, 0), (40, 15), (35, 20), (7, 20), (1, 15)),
        ),
    ],
)
def test_building_generation_supports_sloped_polygon_floor_setbacks(
    floor_boundaries,
):
    mass = MassInput(
        project_id="two-floor-polygon-setback-office",
        floors=2,
        footprint_polygon=list(floor_boundaries[0]),
        floor_footprints=tuple(
            FloorFootprint(floor_index=index, footprint_polygon=boundary)
            for index, boundary in enumerate(floor_boundaries, start=1)
        ),
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[],
        use_mix={"office": 1.0},
    )

    result = generation_service.run_building_generation(mass)

    assert result.accepted
    assert result.vertical_core_aligned
    assert result.vertical_basic_design_aligned
    assert result.vertical_structure_aligned
    cores = []
    remote_stairs = []
    for floor, expected_boundary in zip(
        result.floor_results,
        floor_boundaries,
    ):
        assert floor.floor_boundary == expected_boundary
        assert floor.validation.accepted
        for shape in (*floor.layout.rooms, *floor.layout.circulation):
            assert generation_service.contains_polygon(
                expected_boundary,
                shape.polygon,
            )
        cores.append(
            next(
                room.polygon
                for room in floor.layout.rooms
                if room.space_type == "core"
            )
        )
        remote_stairs.append(floor.layout.remote_stair_footprint)
    assert all(core == cores[0] for core in cores[1:])
    assert all(stair == remote_stairs[0] for stair in remote_stairs[1:])


def test_vertical_alignment_detects_changed_core_subspace_and_structure():
    mass = MassInput(
        project_id="misaligned-building",
        floors=2,
        footprint_polygon=[(0, 0), (30, 0), (30, 12), (0, 12)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[],
        use_mix={"office": 1.0},
    )
    result = generation_service.run_building_generation(mass)
    floor = result.floor_results[1]
    basic_design = floor.layout.basic_design
    assert basic_design is not None
    elements = list(basic_design.elements)
    stair_index = next(
        index for index, element in enumerate(elements) if element.kind == "stair"
    )
    stair = elements[stair_index]
    elements[stair_index] = replace(
        stair,
        footprint=tuple((x + 0.1, y) for x, y in stair.footprint),
    )
    lines = list(basic_design.lines)
    grid_index = next(
        index
        for index, line in enumerate(lines)
        if line.category == "structure" and line.kind == "grid"
    )
    grid = lines[grid_index]
    lines[grid_index] = replace(
        grid,
        points=tuple((x + 0.1, y) for x, y in grid.points),
    )
    changed_floor = replace(
        floor,
        layout=replace(
            floor.layout,
            basic_design=replace(
                basic_design,
                elements=tuple(elements),
                lines=tuple(lines),
            ),
        ),
    )

    basic_aligned, structure_aligned = (
        generation_service._vertical_basic_design_alignment(
            (result.floor_results[0], changed_floor)
        )
    )

    assert basic_aligned is False
    assert structure_aligned is False
    mismatched = replace(
        result,
        floor_results=(result.floor_results[0], changed_floor),
        vertical_basic_design_aligned=basic_aligned,
        vertical_structure_aligned=structure_aligned,
    )
    assert mismatched.accepted is False


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
    assert result.planner_provenance.provider == "manual"
    assert result.planner_provenance.planner_mode == "structured"
    assert result.accepted
    commercial = result.floor_results[0]
    rooms = {room.room_id: room for room in commercial.layout.rooms}
    assert set(rooms) == {
        "sales_a",
        "sales_b",
        "checkout",
        "stock",
        "staff",
        "restroom",
        "core",
        "utility",
    }
    assert all(metric.within_range for metric in commercial.validation.room_areas)
    assert all(
        metric.minimum_width_passed and metric.aspect_ratio_passed
        for metric in commercial.validation.room_shapes
    )
    assert all(
        shared_boundary_with_segments_length(rooms[tenant].polygon, [((0, 0), (24, 0))])
        > 0
        for tenant in ("sales_a", "sales_b")
    )
    assert (
        shared_boundary_with_segments_length(
            rooms["stock"].polygon, [((0, 0), (24, 0))]
        )
        == 0
    )
    assert (
        shared_boundary_with_segments_length(
            rooms["staff"].polygon, [((0, 0), (24, 0))]
        )
        == 0
    )
    assert len(commercial.layout.openings) == len(rooms)
    assert len(commercial.layout.circulation) == 2
    circulation = {path.room_id: path for path in commercial.layout.circulation}
    assert (
        shared_boundary_length(*[path.polygon for path in circulation.values()])
        >= 1.2 - 1e-7
    )
    assert all(
        orthogonal_min_width(path.polygon) >= 1.2 - 1e-7
        for path in circulation.values()
    )
    for opening in commercial.layout.openings:
        assert opening.clear_width == pytest.approx(0.9)
        room = rooms[opening.connects[0]]
        path = circulation[opening.connects[1]]
        segments = shared_boundary_segments(room.polygon, path.polygon)
        start, end = max(segments, key=lambda segment: (math.dist(*segment), segment))
        midpoint = tuple((start[index] + end[index]) / 2 for index in range(2))
        door_midpoint = tuple(
            (opening.start[index] + opening.end[index]) / 2 for index in range(2)
        )
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
            "sales_a",
            "sales_b",
            "checkout",
            "stock",
            "staff",
            "restroom",
            "core",
            "utility",
        },
        "office": {
            "open_work",
            "meeting",
            "reception",
            "focus",
            "pantry",
            "restroom",
            "core",
            "it_storage",
        },
    }
    street = [((0, 0), (30, 0))]
    for floor in result.floor_results:
        rooms = {room.room_id: room for room in floor.layout.rooms}
        assert set(rooms) == expected[floor.program.use_type]
        assert floor.validation.accepted
        assert len(floor.layout.openings) == len(rooms)
        assert all(
            opening.clear_width == pytest.approx(0.9)
            for opening in floor.layout.openings
        )
        assert all(metric.within_range for metric in floor.validation.room_areas)
        assert all(
            metric.minimum_width_passed and metric.aspect_ratio_passed
            for metric in floor.validation.room_shapes
        )

        if floor.program.use_type == "neighborhood_commercial":
            assert all(
                shared_boundary_with_segments_length(rooms[tenant].polygon, street) > 0
                for tenant in ("sales_a", "sales_b")
            )
            assert (
                shared_boundary_with_segments_length(rooms["stock"].polygon, street)
                == 0
            )
            assert (
                shared_boundary_with_segments_length(rooms["staff"].polygon, street)
                == 0
            )
        else:
            areas = {
                room_id: polygon_area(room.polygon) for room_id, room in rooms.items()
            }
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
            lambda nodes: [replace(nodes[0], space_type="unexpected"), *nodes[1:]],
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

    with pytest.raises(ValueError, match="commercial role contract"):
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
