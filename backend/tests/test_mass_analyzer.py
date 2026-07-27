from backend.app.schemas.mass import MassInput
from backend.app.modules.mass_analyzer.service import analyze_mass


def test_analyze_rectangular_mass_reports_area_edges_and_access_edges():
    mass = MassInput(
        project_id="sample-office",
        floors=5,
        footprint_polygon=[(0, 0), (20, 0), (20, 10), (0, 10)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"neighborhood_commercial": 0.2, "office": 0.8},
    )

    analysis = analyze_mass(mass)

    assert analysis.area == 200
    assert analysis.floor_area == 1000
    assert analysis.edge_count == 4
    assert analysis.street_edge_indices == [0]
    assert analysis.access_edge_indices == [0]
    assert analysis.bounds == (0, 0, 20, 10)


def test_analyze_mass_rejects_open_or_tiny_polygon():
    mass = MassInput(
        project_id="bad",
        floors=1,
        footprint_polygon=[(0, 0), (1, 0)],
        site_edges=[],
        access_candidates=[],
        use_mix={"office": 1.0},
    )

    try:
        analyze_mass(mass)
    except ValueError as exc:
        assert "at least 3 points" in str(exc)
    else:
        raise AssertionError("expected invalid mass polygon to fail")
