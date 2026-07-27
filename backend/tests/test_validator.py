from backend.app.modules.layout_generator.service import generate_baseline_layout
from backend.app.modules.mass_analyzer.service import analyze_mass
from backend.app.modules.program_prior.service import generate_program_graph
from backend.app.modules.validator.service import validate_layout
from backend.app.schemas.layout import LayoutCandidate, RoomPolygon
from backend.app.schemas.mass import MassInput
from backend.app.schemas.program import ProgramGraph, ProgramNode


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
        use_mix={"office": 1.0},
    )
    analysis = analyze_mass(mass)
    program = generate_program_graph(analysis, floor_index=1, use_type="office")
    layout = generate_baseline_layout(analysis, program)

    report = validate_layout(layout, program, boundary=mass.footprint_polygon)

    assert not report.accepted
    assert "circulation_missing" in {violation.code for violation in report.violations}
