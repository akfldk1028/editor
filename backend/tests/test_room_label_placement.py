"""Room labels have to land inside the room they name.

Labels were placed at the polygon centroid.  The centroid of a concave room is
not necessarily inside it, and the open work area wraps the service core on
every sample floor -- so "업무공간 862.341 m2" was drawn on top of the corridor
line on alternative-01 floor 1, and the lift label collided with it.
"""

import pytest
from shapely.geometry import Point, Polygon

from backend.app.modules.visual_review.service import _label_point


# A plate wrapped around a service block on its right, which is the shape the
# open work area takes: a simple polygon, no holes, deeply concave.
U_SHAPED_ROOM = (
    (0.0, 0.0),
    (30.0, 0.0),
    (30.0, 4.0),
    (8.0, 4.0),
    (8.0, 16.0),
    (30.0, 16.0),
    (30.0, 20.0),
    (0.0, 20.0),
)


def test_the_fixture_is_concave_enough_that_the_centroid_escapes():
    room = Polygon(U_SHAPED_ROOM)

    assert not room.contains(room.centroid)


def test_a_concave_rooms_label_lands_inside_it():
    room = Polygon(U_SHAPED_ROOM)

    assert room.covers(Point(*_label_point(U_SHAPED_ROOM)))


def test_a_convex_room_still_labels_near_its_middle():
    square = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))

    x, y = _label_point(square)

    assert x == pytest.approx(5.0, abs=0.6)
    assert y == pytest.approx(5.0, abs=0.6)


def test_an_l_shaped_room_labels_inside_its_wider_arm():
    l_shape = (
        (0.0, 0.0),
        (20.0, 0.0),
        (20.0, 4.0),
        (6.0, 4.0),
        (6.0, 18.0),
        (0.0, 18.0),
    )

    assert Polygon(l_shape).covers(Point(*_label_point(l_shape)))


def test_a_degenerate_polygon_falls_back_to_the_centroid_without_raising():
    sliver = ((0.0, 0.0), (10.0, 0.0), (10.0, 0.0), (0.0, 0.0))

    x, y = _label_point(sliver)

    assert x == pytest.approx(5.0)
    assert y == pytest.approx(0.0)


def test_a_strip_labels_along_its_own_centre_line():
    """Adjacent strips must not all push their labels to a shared edge."""
    strip = ((0.0, 0.0), (3.0, 0.0), (3.0, 15.0), (0.0, 15.0))

    x, _ = _label_point(strip)

    assert x == pytest.approx(1.5, abs=0.3)
