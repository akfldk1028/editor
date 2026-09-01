from __future__ import annotations

from dataclasses import FrozenInstanceError
import math

import pytest

from backend.app.modules.area_ledger.service import (
    build_building_area_ledger,
    compute_floor_area_ledger,
)
from backend.app.schemas.area import AreaGeometry


def _shape(source_id: str, *points: tuple[float, float]) -> AreaGeometry:
    return AreaGeometry(source_id=source_id, polygon=points)


def _rect(
    source_id: str,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> AreaGeometry:
    return _shape(source_id, (x1, y1), (x2, y1), (x2, y2), (x1, y2))


def _ledger20(*, core_top: float = 4.0):
    return compute_floor_area_ledger(
        floor_index=1,
        gross=_rect("floor-boundary", 0, 0, 20, 12),
        core=(_rect("core", 0, 0, 4, core_top),),
        circulation=(_rect("corridor", 0, 5, 20, 7),),
        remote_stair=(_rect("remote-stair", 4, 0, 7, 4),),
        service=(_rect("service", 7, 0, 11, 4),),
        primary=(
            _rect("primary-top", 0, 7, 20, 12),
            _rect("primary-lower", 11, 0, 20, 4),
        ),
        classification_rule="closed-program-v1",
    )


def test_rectangular_ledger_closes_all_eight_buckets_with_provenance() -> None:
    ledger = _ledger20()

    assert ledger.status == "pass"
    assert ledger.overlap_area_m2 == pytest.approx(0.0)
    assert ledger.out_of_boundary_area_m2 == pytest.approx(0.0)
    assert [entry.bucket for entry in ledger.entries] == [
        "gross",
        "core",
        "circulation",
        "remote_stair",
        "service",
        "primary",
        "net",
        "unassigned",
    ]
    values = {entry.bucket: entry.area_m2 for entry in ledger.entries}
    assert values == {
        "gross": 240.0,
        "core": 16.0,
        "circulation": 40.0,
        "remote_stair": 12.0,
        "service": 16.0,
        "primary": 136.0,
        "net": 152.0,
        "unassigned": 20.0,
    }
    assert values["gross"] == pytest.approx(
        values["core"]
        + values["circulation"]
        + values["remote_stair"]
        + values["service"]
        + values["primary"]
        + values["unassigned"]
    )
    assert values["net"] == pytest.approx(values["service"] + values["primary"])
    for entry in ledger.entries:
        assert entry.provenance.method
        assert entry.provenance.classification_rule
        assert entry.provenance.formula
    with pytest.raises(FrozenInstanceError):
        ledger.status = "fail"


def test_union_does_not_double_count_overlap_inside_one_bucket() -> None:
    gross = _rect("gross", 0, 0, 10, 10)
    ledger = compute_floor_area_ledger(
        floor_index=1,
        gross=gross,
        core=(
            _rect("core-a", 0, 0, 4, 4),
            _rect("core-b", 2, 0, 6, 4),
        ),
    )

    values = {entry.bucket: entry.area_m2 for entry in ledger.entries}
    assert ledger.status == "pass"
    assert values["core"] == pytest.approx(24.0)
    assert values["unassigned"] == pytest.approx(76.0)
    assert ledger.overlap_area_m2 == pytest.approx(0.0)


def test_cross_bucket_overlap_and_boundary_excess_are_exact_failures() -> None:
    overlap = compute_floor_area_ledger(
        floor_index=1,
        gross=_rect("gross", 0, 0, 10, 10),
        core=(_rect("core", 0, 0, 4, 4),),
        circulation=(_rect("corridor", 2, 0, 6, 4),),
    )
    outside = compute_floor_area_ledger(
        floor_index=1,
        gross=_rect("gross", 0, 0, 10, 10),
        primary=(_rect("outside-room", 9, 0, 11, 2),),
    )

    assert overlap.status == "fail"
    assert overlap.overlap_area_m2 == pytest.approx(8.0)
    assert "cross_category_overlap" in overlap.unresolved_facts
    assert (
        "cross_category_overlap_sources:core,corridor"
        in overlap.unresolved_facts
    )
    assert outside.status == "fail"
    assert outside.out_of_boundary_area_m2 == pytest.approx(2.0)
    assert "geometry_out_of_boundary" in outside.unresolved_facts
    assert (
        "geometry_out_of_boundary_sources:outside-room"
        in outside.unresolved_facts
    )
    overlap_unassigned = next(
        entry for entry in overlap.entries if entry.bucket == "unassigned"
    )
    outside_unassigned = next(
        entry for entry in outside.entries if entry.bucket == "unassigned"
    )
    assert overlap_unassigned.area_m2 == pytest.approx(76.0)
    assert outside_unassigned.area_m2 == pytest.approx(98.0)
    assert overlap_unassigned.provenance.formula == (
        "area(gross boundary minus union(classified geometry intersect gross))"
    )
    assert "signed_residual" not in overlap_unassigned.provenance.formula


def test_l_shaped_polygon_uses_exact_union_not_bounding_box() -> None:
    l_shape = _shape(
        "l-boundary",
        (0, 0),
        (10, 0),
        (10, 4),
        (4, 4),
        (4, 10),
        (0, 10),
    )
    ledger = compute_floor_area_ledger(
        floor_index=1,
        gross=l_shape,
        primary=(_shape("l-primary", *l_shape.polygon),),
    )

    values = {entry.bucket: entry.area_m2 for entry in ledger.entries}
    assert ledger.status == "pass"
    assert values["gross"] == pytest.approx(64.0)
    assert values["primary"] == pytest.approx(64.0)
    assert values["unassigned"] == pytest.approx(0.0)
    assert values["gross"] != 100.0


def test_tiny_sloped_edge_is_not_silently_treated_as_rectilinear() -> None:
    nearly_axis_aligned = _shape(
        "tiny-slope",
        (0, 0),
        (10, 5e-10),
        (10, 10),
        (0, 10),
    )

    ledger = compute_floor_area_ledger(
        floor_index=1,
        gross=nearly_axis_aligned,
    )

    assert ledger.status == "not_checked"
    assert "non_axis_aligned_polygon" in ledger.unresolved_facts
    assert all(entry.area_m2 is None for entry in ledger.entries)


def test_overlap_equal_to_tolerance_is_numerically_normalized() -> None:
    tolerance = 1e-6
    ledger = compute_floor_area_ledger(
        floor_index=1,
        gross=_rect("gross", 0, 0, 10, 10),
        core=(_rect("core", 0, 0, 1, 1),),
        circulation=(
            _rect("corridor", 1 - tolerance, 0, 2, 1),
        ),
        tolerance_m2=tolerance,
    )

    assert ledger.status == "pass"
    assert ledger.overlap_area_m2 == 0.0


def test_overlap_500x_tolerance_is_not_masked_by_boundary_roundoff() -> None:
    tolerance = 1e-6
    overlap_width = 500 * tolerance
    ledger = compute_floor_area_ledger(
        floor_index=1,
        gross=_rect("gross", 0, 0, 10, 10),
        core=(_rect("core", 0, 0, 1, 1),),
        circulation=(
            _rect("corridor", 1 - overlap_width, 0, 2, 1),
        ),
        tolerance_m2=tolerance,
    )

    assert ledger.status == "fail"
    assert ledger.overlap_area_m2 > tolerance
    assert "cross_category_overlap" in ledger.unresolved_facts


@pytest.mark.parametrize(
    "tolerance",
    [
        5e-7,
        1.000001,
        2 * math.ulp(0.0),
        1e300 * (1 + 5e-10),
    ],
)
def test_tolerance_outside_supported_architectural_range_is_rejected(
    tolerance: float,
) -> None:
    with pytest.raises(ValueError, match="supported architectural range"):
        compute_floor_area_ledger(
            floor_index=1,
            gross=_rect("gross", 0, 0, 10, 10),
            tolerance_m2=tolerance,
        )


@pytest.mark.parametrize(
    ("geometry", "reason"),
    [
        (
            _shape("diagonal", (0, 0), (10, 0), (9, 10), (0, 10)),
            "non_axis_aligned_polygon",
        ),
        (
            _shape(
                "self-crossing",
                (0, 0),
                (4, 0),
                (4, 4),
                (2, 4),
                (2, -1),
                (1, -1),
                (1, 3),
                (3, 3),
                (3, 1),
                (0, 1),
            ),
            "self_intersecting_polygon",
        ),
        (
            AreaGeometry(
                source_id="with-hole",
                polygon=((0, 0), (10, 0), (10, 10), (0, 10)),
                holes=(((2, 2), (4, 2), (4, 4), (2, 4)),),
            ),
            "polygon_holes_unsupported",
        ),
    ],
)
def test_unsupported_geometry_is_not_checked_without_fabricated_areas(
    geometry: AreaGeometry,
    reason: str,
) -> None:
    ledger = compute_floor_area_ledger(floor_index=1, gross=geometry)

    assert ledger.status == "not_checked"
    assert reason in ledger.unresolved_facts
    assert len(ledger.entries) == 8
    assert all(entry.area_m2 is None for entry in ledger.entries)


def test_unclassified_room_stays_in_unassigned_with_visible_provenance() -> None:
    ledger = compute_floor_area_ledger(
        floor_index=1,
        gross=_rect("gross", 0, 0, 10, 10),
        unclassified=(_rect("unknown-room", 0, 0, 2, 5),),
    )
    unassigned = next(
        entry for entry in ledger.entries if entry.bucket == "unassigned"
    )

    assert ledger.status == "pass"
    assert unassigned.area_m2 == pytest.approx(100.0)
    assert "unknown-room" in unassigned.provenance.source_ids
    assert "unclassified_room:unknown-room" in ledger.unresolved_facts


def test_malformed_coordinate_shape_is_stable_not_checked() -> None:
    malformed = AreaGeometry(
        source_id="malformed",
        polygon=((0, 0), (10,), (10, 10), (0, 10)),
    )

    ledger = compute_floor_area_ledger(floor_index=1, gross=malformed)

    assert ledger.status == "not_checked"
    assert "invalid_polygon" in ledger.unresolved_facts
    assert all(entry.area_m2 is None for entry in ledger.entries)


def test_repeated_consecutive_vertex_is_not_checked() -> None:
    repeated = _shape(
        "repeated",
        (0, 0),
        (10, 0),
        (10, 0),
        (10, 10),
        (0, 10),
    )

    ledger = compute_floor_area_ledger(floor_index=1, gross=repeated)

    assert ledger.status == "not_checked"
    assert "repeated_consecutive_vertex" in ledger.unresolved_facts


def test_bool_floor_index_is_rejected() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        compute_floor_area_ledger(
            floor_index=True,
            gross=_rect("gross", 0, 0, 10, 10),
        )


def test_core_delta_changes_only_exact_residual() -> None:
    baseline = _ledger20(core_top=4.0)
    expanded = _ledger20(core_top=5.0)
    baseline_values = {
        entry.bucket: entry.area_m2 for entry in baseline.entries
    }
    expanded_values = {
        entry.bucket: entry.area_m2 for entry in expanded.entries
    }

    assert expanded.status == "pass"
    assert expanded_values["core"] - baseline_values["core"] == pytest.approx(4.0)
    assert (
        expanded_values["unassigned"] - baseline_values["unassigned"]
        == pytest.approx(-4.0)
    )


def test_building_totals_sum_actual_distinct_floor_ledgers() -> None:
    first = _ledger20()
    second = compute_floor_area_ledger(
        floor_index=2,
        gross=_rect("floor-2", 0, 0, 10, 10),
        primary=(_rect("floor-2-primary", 0, 0, 8, 10),),
    )

    building = build_building_area_ledger((first, second))
    totals = {entry.bucket: entry.area_m2 for entry in building.totals}

    assert building.status == "pass"
    assert [floor.floor_index for floor in building.floors] == [1, 2]
    assert totals["gross"] == pytest.approx(340.0)
    assert totals["primary"] == pytest.approx(216.0)
    assert totals["unassigned"] == pytest.approx(40.0)


def test_building_ledger_rejects_missing_middle_floor() -> None:
    first = _ledger20()
    third = compute_floor_area_ledger(
        floor_index=3,
        gross=_rect("floor-3", 0, 0, 10, 10),
    )

    with pytest.raises(ValueError, match="consecutive"):
        build_building_area_ledger((first, third))
