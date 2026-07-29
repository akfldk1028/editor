from __future__ import annotations

import json
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import pytest

from backend.app.modules.alternative_composer.contracts import (
    StructuralAlternative,
    StructuralAlternativeRejection,
)
from backend.app.modules.alternative_composer.service import (
    StructuralComposition,
    compose_structural_alternatives,
    deduplicate_structural_alternatives,
    room_structural_fingerprint,
)
from backend.app.modules.circulation_planner.service import (
    generate_circulation_candidate,
)
from backend.app.modules.core_planner.service import generate_shared_core_candidates
from backend.app.modules.generation_loop.service import run_building_generation
from backend.app.schemas.mass import FloorFootprint, MassInput


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = (
    REPOSITORY_ROOT
    / "datasets"
    / "manifests"
    / "sample_mass_irregular_12v_setback_office.json"
)


def test_irregular_mass_produces_two_accepted_structural_families() -> None:
    alternatives = _alternatives()

    assert len(alternatives) >= 2
    assert all(item.building.accepted for item in alternatives)
    assert len({item.core_fingerprint for item in alternatives}) >= 2
    assert len({item.circulation_fingerprint for item in alternatives}) >= 2
    assert len({item.room_fingerprint for item in alternatives}) >= 2
    assert len({item.structural_fingerprint for item in alternatives}) == len(
        alternatives
    )


def test_composition_keeps_one_result_per_core_and_typed_rejections() -> None:
    composition = _composition()

    assert {item.strategy for item in composition.alternatives} == {
        "notch_adjacent",
        "long_edge_adjacent",
    }
    assert len({item.strategy for item in composition.alternatives}) == len(
        composition.alternatives
    )
    assert composition.rejections
    assert all(
        isinstance(item, StructuralAlternativeRejection)
        and item.strategy == "central"
        and item.reason_type
        and item.reason
        for item in composition.rejections
    )


def test_room_label_swap_does_not_create_structural_family() -> None:
    original = _alternatives()[0]
    first_floor = original.building.floor_results[0]
    first, second, *remaining = first_floor.layout.rooms
    swapped_layout = replace(
        first_floor.layout,
        rooms=(
            replace(first, room_id=second.room_id),
            replace(second, room_id=first.room_id),
            *remaining,
        ),
    )
    label_swap_building = replace(
        original.building,
        floor_results=(
            replace(first_floor, layout=swapped_layout),
            *original.building.floor_results[1:],
        ),
    )
    label_swap = replace(
        original,
        building=label_swap_building,
        room_fingerprint=room_structural_fingerprint(label_swap_building),
    )

    assert label_swap.room_fingerprint == original.room_fingerprint
    assert deduplicate_structural_alternatives((original, label_swap)) == (original,)


def test_building_generation_uses_exact_floor_circulation_overrides() -> None:
    mass = _mass()
    core, circulation = _first_override_family()

    building = run_building_generation(
        mass,
        core_override=core,
        circulation_overrides=circulation,
    )

    assert building.vertical_core_aligned
    for floor in building.floor_results:
        expected = circulation[floor.program.floor_index]
        core_room = next(
            room for room in floor.layout.rooms if room.space_type == "core"
        )
        assert core_room.polygon == core.polygon
        assert tuple(tuple(path.polygon) for path in floor.layout.circulation) == (
            expected.polygons
        )
        assert floor.layout.remote_stair_footprint == expected.remote_stair_polygon
        assert floor.floor_boundary == mass.footprint_for_floor(
            floor.program.floor_index
        )


@pytest.mark.parametrize(
    ("core_transform", "circulation_transform", "match"),
    [
        (lambda core: object(), lambda values: values, "core override"),
        (
            lambda core: replace(
                core,
                polygon=tuple((x + 100.0, y) for x, y in core.polygon),
            ),
            lambda values: values,
            "contained",
        ),
        (
            lambda core: core,
            lambda values: {1: values[1], 2: values[2]},
            "every floor",
        ),
        (
            lambda core: core,
            lambda values: {
                **values,
                1: replace(values[1], strategy="different-core"),
            },
            "identity",
        ),
        (
            lambda core: core,
            lambda values: {
                **values,
                1: replace(
                    values[1],
                    polygons=(
                        tuple((x + 100.0, y) for x, y in values[1].polygons[0]),
                    ),
                ),
            },
            "contained",
        ),
    ],
)
def test_building_generation_rejects_invalid_structural_overrides(
    core_transform,
    circulation_transform,
    match,
) -> None:
    mass = _mass()
    core, circulation = _first_override_family()

    with pytest.raises((TypeError, ValueError), match=match):
        run_building_generation(
            mass,
            core_override=core_transform(core),
            circulation_overrides=circulation_transform(circulation),
        )


def test_structural_alternative_contract_rejects_mismatched_hash() -> None:
    original = _alternatives()[0]

    with pytest.raises(ValueError, match="structural fingerprint"):
        StructuralAlternative(
            strategy=original.strategy,
            building=original.building,
            core_fingerprint=original.core_fingerprint,
            circulation_fingerprint=original.circulation_fingerprint,
            room_fingerprint=original.room_fingerprint,
            structural_fingerprint="0" * 64,
        )


@lru_cache(maxsize=1)
def _first_override_family():
    mass = _mass()
    boundaries = tuple(
        mass.footprint_for_floor(index) for index in range(1, mass.floors + 1)
    )
    core = generate_shared_core_candidates(
        boundaries,
        required_area=72.0,
        minimum_width=7.6,
        minimum_depth=5.2,
    )[0]
    circulation = {
        floor_index: generate_circulation_candidate(
            floor_boundary=boundary,
            core=core,
            street_segments=((boundary[0], boundary[1]),),
            minimum_width=1.2,
            stair_dimensions=((2.8, 4.92), (4.92, 2.8)),
        )
        for floor_index, boundary in enumerate(boundaries, start=1)
    }
    return core, circulation


@lru_cache(maxsize=1)
def _alternatives() -> tuple[StructuralAlternative, ...]:
    return _composition().alternatives


@lru_cache(maxsize=1)
def _composition() -> StructuralComposition:
    return compose_structural_alternatives(_mass(), use_type="office", limit=3)


@lru_cache(maxsize=1)
def _mass() -> MassInput:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return MassInput(
        project_id=manifest["project_id"],
        floors=manifest["floors"],
        footprint_polygon=manifest["footprint_polygon"],
        floor_footprints=tuple(
            FloorFootprint(
                floor_index=floor["floor_index"],
                footprint_polygon=tuple(
                    (float(x), float(y)) for x, y in floor["footprint_polygon"]
                ),
            )
            for floor in manifest["floor_footprints"]
        ),
        site_edges=manifest["site_edges"],
        access_candidates=manifest["access_candidates"],
        use_mix=manifest["use_mix"],
    )
