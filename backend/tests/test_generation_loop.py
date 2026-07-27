from backend.app.modules.generation_loop.service import run_generation_loop
from backend.app.schemas.mass import MassInput


def test_generation_loop_returns_program_layout_and_validation_report():
    mass = MassInput(
        project_id="loop",
        floors=3,
        footprint_polygon=[(0, 0), (30, 0), (30, 10), (0, 10)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"neighborhood_commercial": 0.34, "office": 0.66},
    )

    result = run_generation_loop(mass, floor_index=1, use_type="neighborhood_commercial")

    assert result.mass.project_id == "loop"
    assert result.program.use_type == "neighborhood_commercial"
    assert result.layout.project_id == "loop"
    assert result.validation.total_score >= 0


def test_office_generation_loop_reaches_structured_validation():
    mass = MassInput(
        project_id="office-loop",
        floors=3,
        footprint_polygon=[(0, 0), (30, 0), (30, 10), (0, 10)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"office": 1.0},
    )

    result = run_generation_loop(mass, floor_index=2, use_type="office")

    assert result.program.use_type == "office"
    assert not result.validation.accepted
    assert "circulation_missing" in {
        violation.code for violation in result.validation.violations
    }
