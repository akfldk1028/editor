import math

import pytest

from backend.app.modules.layout_generator.service import generate_baseline_layout
from backend.app.modules.mass_analyzer.service import analyze_mass
from backend.app.modules.program_prior.service import generate_program_graph
from backend.app.modules.validator.service import validate_layout
from backend.app.schemas.layout import LayoutCandidate, RoomPolygon
from backend.app.schemas.mass import MassInput
from backend.app.schemas.program import ProgramEdge, ProgramGraph, ProgramNode


BOUNDARY = [(0, 0), (10, 0), (10, 12), (0, 12)]


def _program(*nodes: ProgramNode) -> ProgramGraph:
    return ProgramGraph(
        project_id="test",
        floor_index=1,
        use_type="office",
        nodes=list(nodes),
        edges=[],
        source="test",
    )


def _layout(
    rooms: list[RoomPolygon],
    circulation: list[RoomPolygon],
) -> LayoutCandidate:
    return LayoutCandidate(
        candidate_id="candidate",
        project_id="test",
        floor_index=1,
        rooms=rooms,
        circulation=circulation,
        score=0,
    )


def _room(room_id: str, polygon, space_type: str = "office_area") -> RoomPolygon:
    return RoomPolygon(room_id=room_id, space_type=space_type, polygon=polygon)


def _violation_subjects(report, code: str) -> set[str]:
    return {violation.subject for violation in report.violations if violation.code == code}


def test_validate_layout_scores_candidate_with_shared_wall_access():
    program = _program(
        ProgramNode(node_id="office", space_type="office_area", target_area=70),
        ProgramNode(node_id="core", space_type="core", target_area=30),
    )
    layout = _layout(
        rooms=[
            _room("office", [(0, 0), (7, 0), (7, 10), (0, 10)]),
            _room("core", [(7, 0), (10, 0), (10, 10), (7, 10)], "core"),
        ],
        circulation=[_room("hall", [(0, 10), (10, 10), (10, 12), (0, 12)], "circulation")],
    )

    report = validate_layout(layout, program, boundary=BOUNDARY)

    assert report.accepted
    assert report.is_valid
    assert report.hard_violation_count == 0
    assert report.boundary_score == 1
    assert report.overlap_score == 1
    assert report.area_score == 1
    assert report.circulation_score == 1
    assert report.policy_version == "exact-v1"


def test_per_room_area_errors_do_not_cancel():
    program = _program(
        ProgramNode(node_id="a", space_type="office_area", target_area=50, min_area=45, max_area=55),
        ProgramNode(node_id="b", space_type="core", target_area=50, min_area=45, max_area=55),
    )
    layout = _layout(
        rooms=[
            _room("a", [(0, 0), (6, 0), (6, 10), (0, 10)]),
            _room("b", [(6, 0), (10, 0), (10, 10), (6, 10)], "core"),
        ],
        circulation=[_room("hall", [(0, 10), (10, 10), (10, 12), (0, 12)], "circulation")],
    )

    report = validate_layout(layout, program, boundary=BOUNDARY)

    assert not report.accepted
    assert report.area_score < 1
    assert _violation_subjects(report, "room_area") == {"a", "b"}
    assert {metric.room_id: metric.within_range for metric in report.room_areas} == {
        "a": False,
        "b": False,
    }


def test_missing_extra_and_duplicate_room_ids_are_rejected():
    program = _program(
        ProgramNode(node_id="a", space_type="office_area", target_area=25),
        ProgramNode(node_id="b", space_type="core", target_area=25),
    )
    layout = _layout(
        rooms=[
            _room("a", [(0, 0), (5, 0), (5, 5), (0, 5)]),
            _room("a", [(5, 0), (10, 0), (10, 5), (5, 5)]),
            _room("extra", [(0, 5), (5, 5), (5, 10), (0, 10)]),
        ],
        circulation=[],
    )

    report = validate_layout(layout, program, boundary=BOUNDARY)

    assert not report.accepted
    assert _violation_subjects(report, "room_identity") == {"a", "b", "extra"}


def test_room_and_circulation_boundary_escape_are_rejected():
    program = _program(ProgramNode(node_id="a", space_type="office_area", target_area=110))
    layout = _layout(
        rooms=[_room("a", [(0, 0), (11, 0), (11, 10), (0, 10)])],
        circulation=[_room("hall", [(0, 10), (11, 10), (11, 11), (0, 11)], "circulation")],
    )

    report = validate_layout(layout, program, boundary=BOUNDARY)

    assert not report.accepted
    assert _violation_subjects(report, "boundary") == {"a", "hall"}
    assert report.boundary_score == 0


def test_overlap_and_invalid_geometry_are_structured_violations():
    program = _program(
        ProgramNode(node_id="a", space_type="office_area", target_area=64),
        ProgramNode(node_id="b", space_type="core", target_area=64),
        ProgramNode(node_id="broken", space_type="core", target_area=1),
    )
    layout = _layout(
        rooms=[
            _room("a", [(0, 0), (8, 0), (8, 8), (0, 8)]),
            _room("b", [(4, 4), (12, 4), (12, 12), (4, 12)], "core"),
            _room("broken", [(0, 0), (2, 2), (0, 2), (2, 0)], "core"),
        ],
        circulation=[],
    )

    report = validate_layout(layout, program, boundary=BOUNDARY)

    assert not report.is_valid
    assert "overlap" in {violation.code for violation in report.violations}
    assert "invalid_geometry" in {violation.code for violation in report.violations}
    assert report.overlap_score == 0


def test_missing_circulation_is_a_hard_failure():
    program = _program(ProgramNode(node_id="a", space_type="office_area", target_area=100))
    layout = _layout(
        rooms=[_room("a", [(0, 0), (10, 0), (10, 10), (0, 10)])],
        circulation=[],
    )

    report = validate_layout(layout, program, boundary=BOUNDARY)

    assert not report.accepted
    assert _violation_subjects(report, "circulation_missing") == {"circulation"}
    assert report.circulation_score == 0


def test_disconnected_circulation_is_rejected():
    program = _program(
        ProgramNode(node_id="a", space_type="office_area", target_area=50),
        ProgramNode(node_id="b", space_type="core", target_area=50),
    )
    layout = _layout(
        rooms=[
            _room("a", [(0, 0), (5, 0), (5, 10), (0, 10)]),
            _room("b", [(5, 0), (10, 0), (10, 10), (5, 10)], "core"),
        ],
        circulation=[
            _room("hall-a", [(0, 10), (4, 10), (4, 11), (0, 11)], "circulation"),
            _room("hall-b", [(6, 10), (10, 10), (10, 11), (6, 11)], "circulation"),
        ],
    )

    report = validate_layout(layout, program, boundary=BOUNDARY)

    assert not report.accepted
    assert _violation_subjects(report, "circulation_disconnected") == {"circulation"}


def test_room_without_positive_shared_wall_access_is_rejected():
    program = _program(
        ProgramNode(node_id="a", space_type="office_area", target_area=50),
        ProgramNode(node_id="b", space_type="core", target_area=50),
    )
    layout = _layout(
        rooms=[
            _room("a", [(0, 0), (5, 0), (5, 10), (0, 10)]),
            _room("b", [(5, 0), (10, 0), (10, 10), (5, 10)], "core"),
        ],
        circulation=[_room("hall", [(0, 10), (5, 10), (5, 12), (0, 12)], "circulation")],
    )

    report = validate_layout(layout, program, boundary=BOUNDARY)

    assert not report.accepted
    assert _violation_subjects(report, "room_inaccessible") == {"b"}


def test_generated_stripe_candidate_is_rejected_without_circulation():
    mass = MassInput(
        project_id="stripe",
        floors=1,
        footprint_polygon=[(0, 0), (30, 0), (30, 10), (0, 10)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"neighborhood_commercial": 1.0},
    )
    analysis = analyze_mass(mass)
    program = generate_program_graph(
        analysis,
        floor_index=1,
        use_type="neighborhood_commercial",
    )
    layout = generate_baseline_layout(analysis, program)

    report = validate_layout(layout, program, boundary=mass.footprint_polygon)

    assert not report.accepted
    assert "circulation_missing" in {violation.code for violation in report.violations}


def test_partial_room_access_ranks_better_than_missing_circulation():
    program = _program(
        *[
            ProgramNode(node_id=f"room-{index}", space_type="office_area", target_area=5)
            for index in range(5)
        ]
    )
    rooms = [
        _room(
            f"room-{index}",
            [(index, 0), (index + 1, 0), (index + 1, 5), (index, 5)],
        )
        for index in range(5)
    ]
    missing = validate_layout(_layout(rooms, []), program, boundary=[(0, 0), (5, 0), (5, 6), (0, 6)])
    partial = validate_layout(
        _layout(
            rooms,
            [_room("hall", [(0, 5), (1, 5), (1, 6), (0, 6)], "circulation")],
        ),
        program,
        boundary=[(0, 0), (5, 0), (5, 6), (0, 6)],
    )

    assert partial.hard_violation_count <= missing.hard_violation_count
    assert partial.violation_score < missing.violation_score
    assert partial.circulation_score > missing.circulation_score


def test_violation_score_is_invariant_to_connected_corridor_segmentation():
    program = _program(
        ProgramNode(
            node_id="a",
            space_type="office_area",
            target_area=40,
            min_area=39,
            max_area=41,
        )
    )
    rooms = [_room("a", [(0, 0), (10, 0), (10, 5), (0, 5)])]
    one_piece = [_room("hall", [(0, 5), (10, 5), (10, 6), (0, 6)], "circulation")]
    two_pieces = [
        _room("hall-a", [(0, 5), (5, 5), (5, 6), (0, 6)], "circulation"),
        _room("hall-b", [(5, 5), (10, 5), (10, 6), (5, 6)], "circulation"),
    ]

    single_report = validate_layout(
        _layout(rooms, one_piece),
        program,
        boundary=[(0, 0), (10, 0), (10, 6), (0, 6)],
    )
    segmented_report = validate_layout(
        _layout(rooms, two_pieces),
        program,
        boundary=[(0, 0), (10, 0), (10, 6), (0, 6)],
    )

    assert single_report.hard_violation_count == segmented_report.hard_violation_count == 1
    assert single_report.violation_score == segmented_report.violation_score


def test_coverage_counts_only_candidate_area_inside_footprint():
    program = _program(
        ProgramNode(node_id="a", space_type="office_area", target_area=101)
    )
    layout = _layout(
        rooms=[_room("a", [(-100, 0), (1, 0), (1, 1), (-100, 1)])],
        circulation=[],
    )

    report = validate_layout(
        layout,
        program,
        boundary=[(0, 0), (10, 0), (10, 10), (0, 10)],
    )

    assert report.coverage_score == 0.01


def test_adjacency_score_uses_positive_shared_wall():
    program = ProgramGraph(
        project_id="test",
        floor_index=1,
        use_type="office",
        nodes=[
            ProgramNode(node_id="a", space_type="office_area", target_area=20),
            ProgramNode(node_id="b", space_type="core", target_area=20),
        ],
        edges=[ProgramEdge(source="a", target="b", relation="adjacent")],
        source="test",
    )
    touching = _layout(
        rooms=[
            _room("a", [(0, 0), (4, 0), (4, 5), (0, 5)]),
            _room("b", [(4, 0), (8, 0), (8, 5), (4, 5)], "core"),
        ],
        circulation=[],
    )
    separated = _layout(
        rooms=[
            _room("a", [(0, 0), (4, 0), (4, 5), (0, 5)]),
            _room("b", [(5, 0), (9, 0), (9, 5), (5, 5)], "core"),
        ],
        circulation=[],
    )
    boundary = [(0, 0), (10, 0), (10, 10), (0, 10)]

    assert validate_layout(touching, program, boundary).adjacency_score == 1
    assert validate_layout(separated, program, boundary).adjacency_score == 0


def test_street_scores_only_contact_with_supplied_street_segments():
    program = ProgramGraph(
        project_id="test",
        floor_index=1,
        use_type="neighborhood_commercial",
        nodes=[
            ProgramNode(
                node_id="shop",
                space_type="shop_unit",
                target_area=20,
                frontage_required=True,
            )
        ],
        edges=[ProgramEdge(source="shop", target="street", relation="public_access")],
        source="test",
    )
    street_facing = _layout(
        rooms=[_room("shop", [(0, 0), (5, 0), (5, 4), (0, 4)], "shop_unit")],
        circulation=[_room("hall", [(0, 4), (5, 4), (5, 5), (0, 5)], "circulation")],
    )
    rear_facing = _layout(
        rooms=[_room("shop", [(0, 6), (5, 6), (5, 10), (0, 10)], "shop_unit")],
        circulation=[_room("hall", [(0, 5), (5, 5), (5, 6), (0, 6)], "circulation")],
    )
    boundary = [(0, 0), (10, 0), (10, 10), (0, 10)]
    street_segments = [((0, 0), (10, 0))]

    correct = validate_layout(
        street_facing,
        program,
        boundary,
        street_segments=street_segments,
    )
    wrong = validate_layout(
        rear_facing,
        program,
        boundary,
        street_segments=street_segments,
    )
    unspecified = validate_layout(street_facing, program, boundary)

    assert (correct.adjacency_score, correct.frontage_score) == (1, 1)
    assert (wrong.adjacency_score, wrong.frontage_score) == (0, 0)
    assert (unspecified.adjacency_score, unspecified.frontage_score) == (0, 0)


@pytest.mark.parametrize(
    "program",
    [
        ProgramGraph(
            project_id="test",
            floor_index=1,
            use_type="office",
            nodes=[ProgramNode(node_id="a", space_type="office_area", target_area=20)],
            edges=[ProgramEdge(source="a", target="missing", relation="adjacent")],
            source="test",
        ),
        ProgramGraph(
            project_id="test",
            floor_index=1,
            use_type="office",
            nodes=[ProgramNode(node_id="a", space_type="office_area", target_area=20)],
            edges=[ProgramEdge(source="a", target="street", relation="public_access", weight=math.nan)],
            source="test",
        ),
        ProgramGraph(
            project_id="test",
            floor_index=1,
            use_type="office",
            nodes=[
                ProgramNode(
                    node_id="a",
                    space_type="office_area",
                    target_area=20,
                    min_area=25,
                    max_area=15,
                )
            ],
            edges=[],
            source="test",
        ),
    ],
)
def test_invalid_program_is_rejected_before_candidate_evaluation(program):
    invalid_candidate = _layout(
        rooms=[_room("a", [(0, 0), (2, 2), (0, 2), (2, 0)])],
        circulation=[],
    )

    with pytest.raises(ValueError, match="program"):
        validate_layout(invalid_candidate, program, boundary=BOUNDARY)


def test_square_room_is_more_compact_than_thin_room():
    square_program = _program(
        ProgramNode(node_id="a", space_type="office_area", target_area=16)
    )
    square = _layout(
        rooms=[_room("a", [(0, 0), (4, 0), (4, 4), (0, 4)])],
        circulation=[],
    )
    thin = _layout(
        rooms=[_room("a", [(0, 0), (8, 0), (8, 2), (0, 2)])],
        circulation=[],
    )

    square_score = validate_layout(square, square_program, boundary=BOUNDARY).compactness_score
    thin_score = validate_layout(thin, square_program, boundary=BOUNDARY).compactness_score

    assert square_score > thin_score
