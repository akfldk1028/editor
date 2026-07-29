from __future__ import annotations

import json
from pathlib import Path

import pytest
from shapely import union_all
from shapely.geometry import Polygon

from backend.app.modules.circulation_planner.service import (
    generate_circulation_candidate,
)
from backend.app.modules.core_planner.service import generate_shared_core_candidates
from backend.app.modules.layout_generator.orthogonal import (
    generate_orthogonal_office_layout,
)
from backend.app.modules.mass_analyzer.service import analyze_mass
from backend.app.modules.program_prior.service import generate_program_graph
from backend.app.schemas.mass import MassInput


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = (
    REPOSITORY_ROOT
    / "datasets"
    / "manifests"
    / "sample_mass_irregular_12v_setback_office.json"
)
MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
BOUNDARIES = tuple(
    tuple((float(x), float(y)) for x, y in floor["footprint_polygon"])
    for floor in MANIFEST["floor_footprints"]
)
CORE_CANDIDATES = generate_shared_core_candidates(
    BOUNDARIES,
    required_area=72.0,
    minimum_width=7.6,
    minimum_depth=5.2,
)
STREETS = ((BOUNDARIES[0][0], BOUNDARIES[0][1]),)


@pytest.mark.parametrize("core_index", [0, 1])
def test_circulation_connects_entrance_core_and_remote_stair(core_index) -> None:
    candidate = generate_circulation_candidate(
        floor_boundary=BOUNDARIES[0],
        core=CORE_CANDIDATES[core_index],
        street_segments=STREETS,
        minimum_width=1.2,
        stair_dimensions=((2.8, 4.92), (4.92, 2.8)),
    )

    assert candidate.entrance_connected
    assert candidate.core_connected
    assert candidate.stair_connected
    assert Polygon(BOUNDARIES[0]).covers(Polygon(candidate.remote_stair_polygon))


def test_different_core_families_produce_different_circulation_fingerprints() -> None:
    first = generate_circulation_candidate(
        floor_boundary=BOUNDARIES[0],
        core=CORE_CANDIDATES[0],
        street_segments=STREETS,
        minimum_width=1.2,
        stair_dimensions=((2.8, 4.92), (4.92, 2.8)),
    )
    second = generate_circulation_candidate(
        floor_boundary=BOUNDARIES[0],
        core=CORE_CANDIDATES[1],
        street_segments=STREETS,
        minimum_width=1.2,
        stair_dimensions=((2.8, 4.92), (4.92, 2.8)),
    )

    assert first.fingerprint != second.fingerprint


def test_fixed_circulation_candidate_supports_irregular_floor_residual() -> None:
    core = CORE_CANDIDATES[0]
    candidate = generate_circulation_candidate(
        floor_boundary=BOUNDARIES[0],
        core=core,
        street_segments=STREETS,
        minimum_width=1.2,
        stair_dimensions=((2.8, 4.92), (4.92, 2.8)),
    )

    layout = generate_orthogonal_office_layout(
        BOUNDARIES[0],
        _office_program(BOUNDARIES[0]),
        core_polygon=core.polygon,
        circulation_candidate=candidate,
        frontage_segments=STREETS,
    )

    boundary = Polygon(BOUNDARIES[0])
    residual = boundary.difference(
        Polygon(core.polygon)
        .union(union_all([Polygon(polygon) for polygon in candidate.polygons]))
        .union(Polygon(candidate.remote_stair_polygon))
    )
    assert tuple(tuple(path.polygon) for path in layout.circulation) == candidate.polygons
    assert layout.remote_stair_footprint == candidate.remote_stair_polygon
    assert all(boundary.covers(Polygon(room.polygon)) for room in layout.rooms)
    assert all(
        residual.covers(Polygon(room.polygon))
        for room in layout.rooms
        if room.space_type != "core"
    )
    assert len(layout.rooms) == len(_office_program(BOUNDARIES[0]).nodes)


def test_fixed_circulation_candidate_rejects_separate_stair_polygon() -> None:
    core = CORE_CANDIDATES[0]
    candidate = generate_circulation_candidate(
        floor_boundary=BOUNDARIES[0],
        core=core,
        street_segments=STREETS,
        minimum_width=1.2,
        stair_dimensions=((2.8, 4.92), (4.92, 2.8)),
    )

    with pytest.raises(ValueError, match="conflicts"):
        generate_orthogonal_office_layout(
            BOUNDARIES[0],
            _office_program(BOUNDARIES[0]),
            core_polygon=core.polygon,
            remote_stair_polygon=candidate.remote_stair_polygon,
            circulation_candidate=candidate,
        )


def test_explicit_none_circulation_candidate_preserves_default_layout() -> None:
    boundary = ((0.0, 0.0), (30.0, 0.0), (30.0, 16.0), (0.0, 16.0))
    core = ((11.0, 4.0), (19.0, 4.0), (19.0, 12.0), (11.0, 12.0))
    program = _office_program(boundary)

    default = generate_orthogonal_office_layout(
        boundary,
        program,
        core_polygon=core,
    )
    explicit_none = generate_orthogonal_office_layout(
        boundary,
        program,
        core_polygon=core,
        circulation_candidate=None,
    )

    assert explicit_none == default


def test_none_circulation_candidate_rejects_slightly_non_rectangular_core() -> None:
    boundary = ((0.0, 0.0), (30.0, 0.0), (30.0, 16.0), (0.0, 16.0))
    slightly_non_rectangular_core = (
        (11.0, 4.0),
        (19.0, 4.0),
        (19.0, 12.0000000005),
        (11.0, 12.0),
    )

    with pytest.raises(ValueError, match="axis-aligned rectangle"):
        generate_orthogonal_office_layout(
            boundary,
            _office_program(boundary),
            core_polygon=slightly_non_rectangular_core,
            circulation_candidate=None,
        )


def _office_program(boundary):
    mass = MassInput(
        project_id="circulation-adapter",
        floors=1,
        footprint_polygon=list(boundary),
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[],
        use_mix={"office": 1.0},
    )
    return generate_program_graph(
        analyze_mass(mass),
        floor_index=1,
        use_type="office",
    )
