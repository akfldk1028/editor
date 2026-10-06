from __future__ import annotations

import pytest
from shapely.geometry import Polygon
from shapely.ops import unary_union

from backend.engine.geometry.orthogonal import (
    common_floor_region,
    orthogonal_rectangle_cells,
    shared_core_candidates,
)


def test_l_shaped_floorplate_decomposes_without_bbox_fill() -> None:
    boundary = (
        (0, 0),
        (30, 0),
        (30, 10),
        (14, 10),
        (14, 22),
        (0, 22),
    )

    cells = orthogonal_rectangle_cells(boundary)
    merged = unary_union([Polygon(cell) for cell in cells])

    assert len(cells) == 3
    assert merged.equals(Polygon(boundary))
    assert merged.area == 468
    assert not merged.covers(Polygon([(20, 12), (22, 12), (22, 14), (20, 14)]))


def test_orthogonal_decomposition_is_orientation_invariant() -> None:
    boundary = (
        (0, 0),
        (24, 0),
        (24, 8),
        (18, 8),
        (18, 18),
        (8, 18),
        (8, 8),
        (0, 8),
    )

    forward = orthogonal_rectangle_cells(boundary)
    reversed_cells = orthogonal_rectangle_cells(tuple(reversed(boundary)))

    assert forward == reversed_cells
    assert unary_union([Polygon(cell) for cell in forward]).equals(Polygon(boundary))


def test_orthogonal_decomposition_rejects_diagonal_boundaries() -> None:
    with pytest.raises(ValueError, match="axis-aligned"):
        orthogonal_rectangle_cells(((0, 0), (20, 0), (18, 12), (0, 12)))


def test_common_floor_region_and_core_candidates_cover_every_floor() -> None:
    floors = (
        ((0, 0), (30, 0), (30, 20), (0, 20)),
        ((0, 0), (26, 0), (26, 16), (14, 16), (14, 20), (0, 20)),
        ((0, 0), (22, 0), (22, 14), (12, 14), (12, 18), (0, 18)),
    )

    common = common_floor_region(floors)
    candidates = shared_core_candidates(
        floors,
        width=7.6,
        depth=5.4,
    )

    assert Polygon(common).area == 356
    assert candidates
    for candidate in candidates:
        assert all(Polygon(floor).covers(Polygon(candidate)) for floor in floors)


def test_common_floor_region_rejects_disconnected_overlap() -> None:
    floors = (
        (
            (0, 0),
            (30, 0),
            (30, 20),
            (20, 20),
            (20, 8),
            (10, 8),
            (10, 20),
            (0, 20),
        ),
        ((5, 12), (25, 12), (25, 18), (5, 18)),
    )

    with pytest.raises(ValueError, match="one connected polygon"):
        common_floor_region(floors)
