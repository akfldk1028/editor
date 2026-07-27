from backend.app.modules.validator.service import validate_layout
from backend.app.schemas.layout import LayoutCandidate, RoomPolygon
from backend.app.schemas.program import ProgramGraph, ProgramNode


def test_validate_layout_scores_valid_candidate():
    program = ProgramGraph(
        project_id="valid",
        floor_index=1,
        use_type="office",
        nodes=[
            ProgramNode(node_id="office", space_type="office_area", target_area=70),
            ProgramNode(node_id="core", space_type="core", target_area=30),
        ],
        edges=[],
        source="test",
    )
    layout = LayoutCandidate(
        candidate_id="ok",
        project_id="valid",
        floor_index=1,
        rooms=[
            RoomPolygon(room_id="office", space_type="office_area", polygon=[(0, 0), (7, 0), (7, 10), (0, 10)]),
            RoomPolygon(room_id="core", space_type="core", polygon=[(7, 0), (10, 0), (10, 10), (7, 10)]),
        ],
        circulation=[],
        score=0,
    )

    report = validate_layout(layout, program, boundary=[(0, 0), (10, 0), (10, 10), (0, 10)])

    assert report.is_valid
    assert report.boundary_score == 1
    assert report.overlap_score == 1
    assert report.area_score == 1


def test_validate_layout_detects_overlap_and_boundary_escape():
    program = ProgramGraph(
        project_id="bad",
        floor_index=1,
        use_type="office",
        nodes=[
            ProgramNode(node_id="a", space_type="office_area", target_area=50),
            ProgramNode(node_id="b", space_type="core", target_area=50),
        ],
        edges=[],
        source="test",
    )
    layout = LayoutCandidate(
        candidate_id="bad",
        project_id="bad",
        floor_index=1,
        rooms=[
            RoomPolygon(room_id="a", space_type="office_area", polygon=[(0, 0), (8, 0), (8, 8), (0, 8)]),
            RoomPolygon(room_id="b", space_type="core", polygon=[(4, 4), (12, 4), (12, 12), (4, 12)]),
        ],
        circulation=[],
        score=0,
    )

    report = validate_layout(layout, program, boundary=[(0, 0), (10, 0), (10, 10), (0, 10)])

    assert not report.is_valid
    assert report.boundary_score == 0
    assert report.overlap_score == 0
