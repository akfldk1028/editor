from __future__ import annotations

import json
import math
from itertools import product
from pathlib import Path

import pytest
from shapely import union_all
from shapely.geometry import Polygon, box

import backend.app.modules.circulation_planner.service as circulation_service
from backend.app.modules.circulation_planner.contracts import (
    CirculationCandidate,
    CirculationPlanningError,
)
from backend.app.modules.circulation_planner.service import (
    _MAX_AUXILIARY_INTERVALS_PER_AXIS,
    _MAX_CORRIDOR_NETWORK_CANDIDATES,
    _MAX_REMOTE_STAIR_CANDIDATES,
    _candidate_origins,
    _corridor_network_candidates,
    _maximum_doorway_separation,
    _remote_stair_candidates,
    _select_remote_stair,
    generate_circulation_candidate,
)
from backend.app.modules.core_planner.contracts import CoreCandidate
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
FLOOR_STREETS = tuple(((boundary[0], boundary[1]),) for boundary in BOUNDARIES)


def test_circulation_candidate_preserves_legacy_constructor_shapes() -> None:
    polygons = (((0.0, 0.0), (1.2, 0.0), (1.2, 2.0), (0.0, 2.0)),)
    stair = ((1.2, 0.0), (4.0, 0.0), (4.0, 4.92), (1.2, 4.92))
    positional = CirculationCandidate(
        "legacy",
        polygons,
        stair,
        "legacy-fingerprint",
        True,
        True,
        True,
    )
    keyword = CirculationCandidate(
        strategy="legacy",
        polygons=polygons,
        remote_stair_polygon=stair,
        fingerprint="legacy-fingerprint",
        entrance_connected=True,
        core_connected=True,
        stair_connected=True,
    )

    assert positional == keyword
    assert positional.core_fingerprint is None


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


@pytest.mark.parametrize(
    ("floor_index", "core_index"),
    tuple(product(range(len(BOUNDARIES)), range(len(CORE_CANDIDATES)))),
)
def test_all_irregular_floors_and_core_families_forward_rectilinear_circulation(
    floor_index: int,
    core_index: int,
) -> None:
    boundary = Polygon(BOUNDARIES[floor_index])
    core = CORE_CANDIDATES[core_index]
    candidate = generate_circulation_candidate(
        floor_boundary=BOUNDARIES[floor_index],
        core=core,
        street_segments=FLOOR_STREETS[floor_index],
        minimum_width=1.2,
        stair_dimensions=((2.8, 4.92), (4.92, 2.8)),
    )
    corridor = union_all([Polygon(polygon) for polygon in candidate.polygons])

    assert candidate.entrance_connected
    assert candidate.core_connected
    assert candidate.stair_connected
    assert all(
        boundary.covers(Polygon(polygon))
        and Polygon(polygon).equals(box(*Polygon(polygon).bounds))
        and min(
            Polygon(polygon).bounds[2] - Polygon(polygon).bounds[0],
            Polygon(polygon).bounds[3] - Polygon(polygon).bounds[1],
        )
        + 1e-8
        >= 1.2
        for polygon in candidate.polygons
    )
    assert corridor.intersection(Polygon(core.polygon)).area == pytest.approx(0)
    assert (
        Polygon(candidate.remote_stair_polygon)
        .boundary.intersection(corridor.boundary)
        .length
        >= 0.9
    )

    layout = generate_orthogonal_office_layout(
        BOUNDARIES[floor_index],
        _office_program(BOUNDARIES[floor_index]),
        core_polygon=core.polygon,
        circulation_candidate=candidate,
        frontage_segments=FLOOR_STREETS[floor_index],
    )

    assert tuple(tuple(path.polygon) for path in layout.circulation) == candidate.polygons
    assert layout.remote_stair_footprint == candidate.remote_stair_polygon


def test_notch_core_shared_circulation_meets_governing_exit_separation() -> None:
    core = next(
        candidate
        for candidate in CORE_CANDIDATES
        if candidate.strategy == "notch_adjacent"
    )
    governing_separation = max(
        _maximum_pairwise_distance(boundary) / 2.0
        for boundary in BOUNDARIES
    )
    candidate = generate_circulation_candidate(
        floor_boundary=BOUNDARIES[-1],
        core=core,
        street_segments=FLOOR_STREETS[-1],
        minimum_width=1.2,
        stair_dimensions=((2.8, 4.92), (4.92, 2.8)),
        minimum_exit_separation=governing_separation,
    )

    corridor = union_all([Polygon(polygon) for polygon in candidate.polygons])
    remote_stair = Polygon(candidate.remote_stair_polygon)
    assert all(
        Polygon(BOUNDARIES[-1]).covers(Polygon(polygon))
        and Polygon(polygon).equals(box(*Polygon(polygon).bounds))
        and min(
            Polygon(polygon).bounds[2] - Polygon(polygon).bounds[0],
            Polygon(polygon).bounds[3] - Polygon(polygon).bounds[1],
        )
        + 1e-8
        >= 1.2
        for polygon in candidate.polygons
    )
    assert corridor.intersection(Polygon(core.polygon)).area == pytest.approx(0)
    assert candidate.entrance_connected
    assert candidate.core_connected
    assert candidate.stair_connected
    separation = _maximum_doorway_separation(
        Polygon(core.polygon),
        corridor,
        remote_stair,
    )
    for boundary_points, street_segments in zip(BOUNDARIES, FLOOR_STREETS):
        layout = generate_orthogonal_office_layout(
            boundary_points,
            _office_program(boundary_points),
            core_polygon=core.polygon,
            circulation_candidate=candidate,
            frontage_segments=street_segments,
        )
        required = _maximum_pairwise_distance(boundary_points) / 2.0

        assert separation + 1e-8 >= required
        assert tuple(
            tuple(path.polygon) for path in layout.circulation
        ) == candidate.polygons
        assert layout.remote_stair_footprint == candidate.remote_stair_polygon
        core_door = next(opening for opening in layout.openings if opening.connects[0] == "core")
        assert core_door.start[1] == core.polygon[0][1]
        assert core_door.end[1] == core.polygon[0][1]


def test_optional_separation_candidate_search_is_coordinate_scale_bounded(
    monkeypatch,
) -> None:
    boundary = box(-1_000_000_000.0, -100.0, 1_000_000_000.0, 100.0)
    core = box(-50.0, 40.0, 50.0, 80.0)
    critical_origins = (
        -123.123456789123,
        234.123456789123,
    )
    origins = _candidate_origins(
        boundary,
        axis=0,
        extent=1.2,
        extra=critical_origins,
    )
    networks = _corridor_network_candidates(
        boundary,
        core,
        1.2,
        minimum_exit_separation=1_000.0,
    )
    counts = {"networks": 0, "stairs": 0}
    original_remote_stair_candidates = _remote_stair_candidates

    def counted_remote_stair_candidates(**kwargs):
        candidates = original_remote_stair_candidates(**kwargs)
        counts["networks"] += 1
        counts["stairs"] += len(candidates)
        return candidates

    monkeypatch.setattr(
        circulation_service,
        "_remote_stair_candidates",
        counted_remote_stair_candidates,
    )
    candidate = generate_circulation_candidate(
        floor_boundary=tuple(boundary.exterior.coords[:-1]),
        core=CoreCandidate(
            strategy="coordinate_scale_stress",
            polygon=tuple(core.exterior.coords[:-1]),
            fingerprint="coordinate-scale-stress",
            contained_floor_indices=(1,),
        ),
        street_segments=(
            ((-1_000_000_000.0, -100.0), (1_000_000_000.0, -100.0)),
        ),
        minimum_width=1.2,
        stair_dimensions=((2.8, 4.92), (4.92, 2.8)),
        minimum_exit_separation=1_000.0,
    )

    assert set(critical_origins) <= set(origins)
    assert len(origins) <= (
        _MAX_AUXILIARY_INTERVALS_PER_AXIS + 1 + len(critical_origins) + 4
    )
    assert len(networks) <= _MAX_CORRIDOR_NETWORK_CANDIDATES
    assert counts["networks"] <= _MAX_CORRIDOR_NETWORK_CANDIDATES
    assert counts["stairs"] <= (
        _MAX_CORRIDOR_NETWORK_CANDIDATES * _MAX_REMOTE_STAIR_CANDIDATES
    )
    assert Polygon(boundary).covers(Polygon(candidate.remote_stair_polygon))
    assert min(Polygon(polygon).bounds[0] for polygon in candidate.polygons) in {
        -1_050.0,
        -1_000.0,
        -950.0,
    }
    assert Polygon(candidate.remote_stair_polygon).bounds == pytest.approx(
        (-954.92, -100.0, -950.0, -97.2)
    )


def test_empty_free_reserve_restores_legacy_none_error() -> None:
    boundary = box(0.0, 0.0, 10.0, 10.0)
    core = box(2.0, 0.0, 10.0, 10.0)
    corridor = box(0.0, 0.0, 2.0, 10.0)

    with pytest.raises(
        CirculationPlanningError,
        match="^circulation leaves no remote stair reserve$",
    ):
        _select_remote_stair(
            boundary=boundary,
            core=core,
            corridor=corridor,
            corridor_rectangles=(corridor,),
            street_segments=(((0.0, 0.0), (10.0, 0.0)),),
            stair_dimensions=((2.8, 4.92),),
        )


def test_legacy_none_uses_pre_separation_full_quarter_meter_lattice() -> None:
    boundary = (
        (0.0, 0.0),
        (30.0, 0.0),
        (30.0, 20.0),
        (0.0, 20.0),
    )
    core = CoreCandidate(
        strategy="legacy-wide",
        polygon=(
            (11.0, 4.0),
            (19.0, 4.0),
            (19.0, 12.0),
            (11.0, 12.0),
        ),
        fingerprint="legacy-wide-core",
        contained_floor_indices=(1,),
    )

    candidate = generate_circulation_candidate(
        floor_boundary=boundary,
        core=core,
        street_segments=((boundary[0], boundary[1]),),
        minimum_width=1.2,
        stair_dimensions=((2.8, 4.92), (4.92, 2.8)),
        minimum_exit_separation=None,
    )

    assert candidate.polygons == (
        ((9.8, 0.0), (9.8, 12.0), (11.0, 12.0), (11.0, 0.0)),
    )
    assert candidate.remote_stair_polygon == (
        (4.880000000000001, 0.25),
        (4.880000000000001, 3.05),
        (9.8, 3.05),
        (9.8, 0.25),
    )
    assert (
        candidate.fingerprint
        == "efae93c031b646dfeee4c5103f5c844425d9ccfa954a46c6b9ef4ff0bceb8750"
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

def _maximum_pairwise_distance(points) -> float:
    return max(
        math.dist(first, second)
        for index, first in enumerate(points)
        for second in points[index + 1 :]
    )
