"""Sizing helpers that keep generated rooms inside their proportion limits.

Each helper answers the same question from a different direction: given an area
and an aspect limit, what dimension keeps the rectangle acceptable? A generator
that ignores the limit produces a room the validator is right to reject, and the
alternative carrying it is lost for a reason no reviewer can act on.
"""

from __future__ import annotations

import math

import pytest

from backend.app.modules.layout_generator.service import (
    height_within_aspect_limit,
    rear_band_height,
    service_room_width,
)
from backend.app.schemas.program import ProgramGraph, ProgramNode


def _node(space_type: str, area: float, limit: float | None) -> ProgramNode:
    return ProgramNode(
        node_id=space_type,
        space_type=space_type,
        target_area=area,
        max_aspect_ratio=limit,
    )


def _program(*nodes: ProgramNode) -> ProgramGraph:
    return ProgramGraph(
        project_id="proportion",
        floor_index=1,
        use_type="office",
        nodes=list(nodes),
        edges=[],
        source="test",
    )


def test_core_height_is_capped_so_the_rectangle_can_meet_its_limit():
    area = 80.64
    height = height_within_aspect_limit(
        14.4,
        area=area,
        maximum_aspect_ratio=2.0,
        minimum_height=7.2,
    )

    assert height < 14.4
    assert height / (area / height) <= 2.0


def test_a_height_already_inside_the_limit_is_left_alone():
    assert (
        height_within_aspect_limit(
            8.0,
            area=80.0,
            maximum_aspect_ratio=2.0,
            minimum_height=7.2,
        )
        == 8.0
    )


def test_an_absent_limit_leaves_the_height_untouched():
    assert (
        height_within_aspect_limit(
            40.0,
            area=1.0,
            maximum_aspect_ratio=None,
            minimum_height=7.2,
        )
        == 40.0
    )


def test_service_width_widens_a_room_that_would_become_a_slot():
    node = _node("pantry", 12.0, 8.5)

    width = service_room_width(node, 12.0)

    assert width > 12.0 / 12.0
    assert (12.0 / width) / width <= 8.5


def test_service_width_still_honours_the_declared_minimum_width():
    node = ProgramNode(
        node_id="restroom",
        space_type="restroom",
        target_area=12.0,
        min_width=4.0,
        max_aspect_ratio=8.5,
    )

    assert service_room_width(node, 12.0) >= 4.0


def test_rear_band_leaves_the_open_work_area_a_usable_depth():
    program = _program(_node("open_work", 400.0, 6.5), _node("core", 60.0, 2.0))

    band = rear_band_height(
        program,
        plate_width=60.0,
        plate_depth=20.0,
        min_circulation_width=1.2,
        stair_long_side=5.0,
    )

    front_depth = 20.0 - 1.2 - band
    assert (60.0 - 1.2) / front_depth <= 6.5


def test_rear_band_never_drops_below_the_stair_enclosure():
    program = _program(_node("open_work", 400.0, 6.5), _node("core", 60.0, 2.0))

    band = rear_band_height(
        program,
        plate_width=200.0,
        plate_depth=20.0,
        min_circulation_width=1.2,
        stair_long_side=6.0,
    )

    assert band == pytest.approx(6.25)


def test_a_floor_without_an_open_work_area_uses_half_the_plate_depth():
    program = _program(_node("sales", 200.0, 6.5), _node("core", 60.0, 2.0))

    band = rear_band_height(
        program,
        plate_width=60.0,
        plate_depth=20.0,
        min_circulation_width=1.2,
        stair_long_side=5.0,
    )

    assert band == pytest.approx(10.0)
    assert math.isfinite(band)
