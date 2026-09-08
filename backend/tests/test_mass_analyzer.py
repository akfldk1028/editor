import pytest

from backend.app.schemas.mass import FloorFootprint, MassInput
from backend.app.modules.mass_analyzer.service import analyze_floor_mass, analyze_mass


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


def test_analyze_mass_supports_floor_specific_setbacks():
    mass = MassInput(
        project_id="stepped-office",
        floors=3,
        footprint_polygon=[(0, 0), (30, 0), (30, 20), (0, 20)],
        floor_footprints=(
            FloorFootprint(
                floor_index=1,
                footprint_polygon=(
                    (0, 0),
                    (30, 0),
                    (30, 20),
                    (0, 20),
                ),
            ),
            FloorFootprint(
                floor_index=2,
                footprint_polygon=(
                    (0, 0),
                    (24, 0),
                    (24, 16),
                    (0, 16),
                ),
            ),
            FloorFootprint(
                floor_index=3,
                footprint_polygon=(
                    (0, 0),
                    (18, 0),
                    (18, 12),
                    (0, 12),
                ),
            ),
        ),
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[],
        use_mix={"office": 1.0},
    )

    analysis = analyze_mass(mass)

    assert analysis.area == 600
    assert analysis.floor_area == 1200
    assert [plate.area for plate in analysis.floor_plates] == [600, 384, 216]
    assert analysis.floor_plates[1].bounds == (0, 0, 24, 16)
    assert analysis.floor_plates[1].source == "explicit_floor_footprint"
    assert analyze_floor_mass(mass, 3).area == 216
    assert mass.footprint_for_floor(1) == tuple(mass.footprint_polygon)
    assert mass.footprint_for_floor(3) == (
        (0, 0),
        (18, 0),
        (18, 12),
        (0, 12),
    )


def test_floor_footprints_reject_duplicate_or_out_of_range_floors():
    footprint = FloorFootprint(
        floor_index=2,
        footprint_polygon=((0, 0), (20, 0), (20, 10), (0, 10)),
    )
    with pytest.raises(ValueError, match="must be unique"):
        MassInput(
            project_id="duplicate",
            floors=3,
            footprint_polygon=[(0, 0), (30, 0), (30, 20), (0, 20)],
            floor_footprints=(footprint, footprint),
            site_edges=[],
            access_candidates=[],
            use_mix={"office": 1.0},
        )

    with pytest.raises(ValueError, match="outside supplied floors"):
        MassInput(
            project_id="outside",
            floors=1,
            footprint_polygon=[(0, 0), (30, 0), (30, 20), (0, 20)],
            floor_footprints=(footprint,),
            site_edges=[],
            access_candidates=[],
            use_mix={"office": 1.0},
        )


def test_floor_footprints_require_complete_coverage_and_reference_containment():
    with pytest.raises(ValueError, match="must cover every supplied floor"):
        MassInput(
            project_id="missing-floor",
            floors=2,
            footprint_polygon=[(0, 0), (30, 0), (30, 20), (0, 20)],
            floor_footprints=(
                FloorFootprint(
                    floor_index=2,
                    footprint_polygon=((0, 0), (20, 0), (20, 10), (0, 10)),
                ),
            ),
            site_edges=[],
            access_candidates=[],
            use_mix={"office": 1.0},
        )

    overhang = MassInput(
        project_id="overhang",
        floors=1,
        footprint_polygon=[(0, 0), (30, 0), (30, 20), (0, 20)],
        floor_footprints=(
            FloorFootprint(
                floor_index=1,
                footprint_polygon=((0, 0), (32, 0), (32, 20), (0, 20)),
            ),
        ),
        site_edges=[],
        access_candidates=[],
        use_mix={"office": 1.0},
    )
    with pytest.raises(ValueError, match="covered by reference envelope"):
        analyze_mass(overhang)


def test_floor_footprint_rejects_nonfinite_or_degenerate_polygon():
    with pytest.raises(ValueError, match="at least 3"):
        FloorFootprint(
            floor_index=1,
            footprint_polygon=((0, 0), (1, 0)),
        )
    with pytest.raises(ValueError, match="finite"):
        FloorFootprint(
            floor_index=1,
            footprint_polygon=((0, 0), (float("nan"), 0), (0, 1)),
        )
