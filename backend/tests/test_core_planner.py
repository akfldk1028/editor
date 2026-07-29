import json
from pathlib import Path

from shapely.geometry import Polygon

from backend.app.modules.core_planner.service import generate_shared_core_candidates


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
    assert all(len(candidate.fingerprint) == 64 for candidate in candidates)
    assert all(
        all(Polygon(boundary).covers(Polygon(candidate.polygon)) for boundary in boundaries)
        for candidate in candidates
    )
    assert all(Polygon(candidate.polygon).area >= 72.0 for candidate in candidates)
    assert all(len(candidate.polygon) == 4 for candidate in candidates)
    assert all(
        Polygon(candidate.polygon).bounds[2] - Polygon(candidate.polygon).bounds[0]
        >= 7.6
        and Polygon(candidate.polygon).bounds[3] - Polygon(candidate.polygon).bounds[1]
        >= 5.2
        for candidate in candidates
    )
    assert {candidate.strategy for candidate in candidates} <= {
        "central",
        "notch_adjacent",
        "long_edge_adjacent",
    }
    assert all(candidate.contained_floor_indices == (0, 1, 2) for candidate in candidates)
