import json
from pathlib import Path

from shapely.geometry import Polygon

from backend.app.modules.core_planner.service import (
    _geometry_fingerprint,
    generate_shared_core_candidates,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = (
    REPOSITORY_ROOT
    / "datasets"
    / "manifests"
    / "sample_mass_irregular_12v_setback_office.json"
)


def _is_axis_aligned(boundary: tuple[tuple[float, float], ...]) -> bool:
    return all(
        start[0] == end[0] or start[1] == end[1]
        for start, end in zip(boundary, boundary[1:] + boundary[:1], strict=True)
    )


def test_irregular_setback_office_has_shared_structural_core_candidates() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    boundaries = tuple(
        tuple((float(x), float(y)) for x, y in floor["footprint_polygon"])
        for floor in manifest["floor_footprints"]
    )

    candidates = generate_shared_core_candidates(
        boundaries,
        required_area=72.0,
        minimum_width=7.6,
        minimum_depth=5.2,
    )

    assert len(boundaries) == 3
    assert all(len(boundary) == 12 for boundary in boundaries)
    assert all(len(set(boundary)) == 12 for boundary in boundaries)
    assert all(not _is_axis_aligned(boundary) for boundary in boundaries)
    assert all(
        Polygon(boundary).is_valid
        and not Polygon(boundary).equals(Polygon(boundary).convex_hull)
        for boundary in boundaries
    )
    assert len(candidates) >= 2
    assert len({candidate.fingerprint for candidate in candidates}) == len(candidates)
    assert len({candidate.strategy for candidate in candidates}) == len(candidates)
    assert all(len(candidate.fingerprint) == 64 for candidate in candidates)
    assert all(
        all(Polygon(boundary).covers(Polygon(candidate.polygon)) for boundary in boundaries)
        for candidate in candidates
    )
    assert all(Polygon(candidate.polygon).area >= 72.0 for candidate in candidates)
    assert all(len(candidate.polygon) == 4 for candidate in candidates)
    assert all(_dimensions(candidate.polygon)[0] >= 5.2 for candidate in candidates)
    assert all(_dimensions(candidate.polygon)[1] >= 7.6 for candidate in candidates)
    assert {candidate.strategy for candidate in candidates} <= {
        "central",
        "notch_adjacent",
        "long_edge_adjacent",
    }
    assert all(candidate.contained_floor_indices == (0, 1, 2) for candidate in candidates)


def test_shared_core_supports_rotated_minimum_dimension_elongated_core() -> None:
    floor = ((0.0, 0.0), (5.3, 0.0), (5.3, 14.0), (0.0, 14.0))

    candidates = generate_shared_core_candidates(
        (floor, floor),
        required_area=72.0,
        minimum_width=7.6,
        minimum_depth=5.2,
    )

    assert candidates
    assert all(Polygon(floor).covers(Polygon(candidate.polygon)) for candidate in candidates)
    assert any(
        _dimensions(candidate.polygon)[0] == 5.2
        and _dimensions(candidate.polygon)[1] >= 72.0 / 5.2
        for candidate in candidates
    )


def test_shared_core_samples_intermediate_feasible_dimensions() -> None:
    floor = ((0.0, 0.0), (8.2, 0.0), (8.2, 8.8), (0.0, 8.8))

    candidates = generate_shared_core_candidates(
        (floor, floor),
        required_area=72.0,
        minimum_width=7.6,
        minimum_depth=5.2,
    )

    assert candidates
    assert all(Polygon(floor).covers(Polygon(candidate.polygon)) for candidate in candidates)
    assert any(_dimensions(candidate.polygon) == (8.2, 8.780488) for candidate in candidates)


def test_shared_core_revalidates_returned_decimal_boundary_coordinates() -> None:
    floor = (
        (0.0000004, 0.0),
        (8.4852824, 0.0),
        (8.4852824, 20.0),
        (0.0000004, 20.0),
    )

    candidates = generate_shared_core_candidates(
        (floor, floor),
        required_area=72.0,
        minimum_width=7.6,
        minimum_depth=5.2,
    )

    assert candidates
    assert all(Polygon(floor).covers(Polygon(candidate.polygon)) for candidate in candidates)


def test_geometry_fingerprint_is_invariant_to_ring_start_and_direction() -> None:
    polygon = ((1.25, 2.5), (7.75, 2.5), (7.75, 9.0), (1.25, 9.0))

    assert _geometry_fingerprint(polygon) == _geometry_fingerprint(polygon[1:] + polygon[:1])
    assert _geometry_fingerprint(polygon) == _geometry_fingerprint(tuple(reversed(polygon)))


def _dimensions(polygon: tuple[tuple[float, float], ...]) -> tuple[float, float]:
    min_x, min_y, max_x, max_y = Polygon(polygon).bounds
    return tuple(sorted((round(max_x - min_x, 6), round(max_y - min_y, 6))))
