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


def test_orthogonal_min_width_measures_non_orthogonal_polygon_by_inscribed_circle():
    # a room whose outer wall follows a slanted facade: its width is the widest circle inside it, not the
    # knife-edge slice at the clipped corner (planm 09-27)
    # the widest disk that sweeps the whole shape (opening keeps >= 92% of the area, one piece): the oblique
    # corner of this trapezoid is lost early, so it reads well under its 2 m height but far above a knife edge
    width = orthogonal_min_width([(0, 0), (3, 0), (2, 2), (0, 2)])
    assert 1.0 < width <= 2.0 + 1e-6
    # a dumbbell measures its neck, not its halves
    neck = orthogonal_min_width([(0, 0), (4, 0), (4, 1.8), (4.4, 1.8), (4.4, 0), (8.4, 0), (8.4, 4), (4.4, 4.001),
                                 (4.4, 2.2), (4, 2.2), (4, 4.002), (0, 4.003)])
    assert 0.35 < neck < 0.5
    # a rectangle still measures its short side
    assert abs(orthogonal_min_width([(0, 0), (4, 0), (4, 1.5), (0, 1.5)]) - 1.5) < 1e-6
