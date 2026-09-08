import pytest

from backend.engine.geometry.access import (
    orthogonal_min_width,
    shared_boundary_segments,
)


def test_shared_boundary_segments_returns_canonical_positive_segments():
    left = [(0, 0), (4, 0), (4, 4), (0, 4)]
    right = [(4, 1), (7, 1), (7, 3), (4, 3)]

    assert shared_boundary_segments(left, right) == [
        ((4.0, 1.0), (4.0, 3.0))
    ]


def test_shared_boundary_segments_ignores_point_contact():
    left = [(0, 0), (2, 0), (2, 2), (0, 2)]
    right = [(2, 2), (4, 2), (4, 4), (2, 4)]

    assert shared_boundary_segments(left, right) == []


@pytest.mark.parametrize(
    ("polygon", "expected"),
    [
        ([(0, 0), (10, 0), (10, 2), (0, 2)], 2.0),
        (
            [(0, 0), (4, 0), (4, 1), (1, 1), (1, 4), (0, 4)],
            1.0,
        ),
    ],
)
def test_orthogonal_min_width_measures_rectangle_and_l_throat(
    polygon, expected
):
    assert orthogonal_min_width(polygon) == expected


def test_orthogonal_min_width_rejects_non_orthogonal_polygon():
    with pytest.raises(ValueError, match="axis-aligned"):
        orthogonal_min_width([(0, 0), (3, 0), (2, 2), (0, 2)])
