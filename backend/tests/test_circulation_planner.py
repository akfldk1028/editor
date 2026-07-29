from __future__ import annotations

import json
from pathlib import Path

import pytest
from shapely.geometry import Polygon

from backend.app.modules.circulation_planner.service import (
    generate_circulation_candidate,
)
from backend.app.modules.core_planner.service import generate_shared_core_candidates


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
