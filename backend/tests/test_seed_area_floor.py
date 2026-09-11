"""Subdivision has an upper area bound but no lower one.

``bounded_area_limits`` makes the splitter keep going until every room can be
served by a rectangle no bigger than its max_area.  Nothing stops it splitting
past the point where a room can still be served by a rectangle as big as its
min_area, so meeting asked for 125.1 m2 on the sample office and was handed
19.7 -- 84% short -- and the area it did not get ended up in open work.
"""

import pytest

from backend.app.modules.layout_generator.orthogonal import (
    _has_banded_seed_capacity,
)


def _rects(*areas):
    """Square-ish rectangles of the given areas, laid out in a row."""
    out, x = [], 0.0
    for area in areas:
        side = area ** 0.5
        out.append(((x, 0.0), (x + side, 0.0), (x + side, side), (x, side)))
        x += side
    return out


def test_capacity_holds_when_every_room_has_a_rectangle_in_its_band():
    assert _has_banded_seed_capacity(
        _rects(120.0, 60.0, 25.0), ((100.0, 140.0), (50.0, 70.0), (20.0, 30.0))
    )


def test_capacity_fails_when_a_room_only_has_rectangles_below_its_band():
    assert not _has_banded_seed_capacity(
        _rects(20.0, 19.0, 18.0), ((100.0, 140.0), (15.0, 25.0), (15.0, 25.0))
    )


def test_capacity_fails_when_a_room_only_has_rectangles_above_its_band():
    assert not _has_banded_seed_capacity(_rects(500.0), ((20.0, 30.0),))


def test_one_rectangle_cannot_serve_two_rooms():
    assert not _has_banded_seed_capacity(
        _rects(120.0), ((100.0, 140.0), (100.0, 140.0))
    )


def test_the_greedy_match_does_not_waste_a_large_rectangle_on_a_small_room():
    """25 m2 must take the 25 m2 tile, leaving the 120 for the big room."""
    assert _has_banded_seed_capacity(
        _rects(120.0, 25.0), ((20.0, 30.0), (100.0, 140.0))
    )


def test_no_rooms_always_has_capacity():
    assert _has_banded_seed_capacity(_rects(10.0), ())


def test_no_rectangles_cannot_serve_a_room():
    assert not _has_banded_seed_capacity([], ((20.0, 30.0),))
