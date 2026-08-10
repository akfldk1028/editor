import math

import pytest

from backend.engine.geometry.polygon import (
    contains_polygon,
    polygon_overlap_area,
    shared_boundary_length,
    union_area,
    union_polygon,
    validate_polygon,
)


def test_concave_container_rejects_polygon_in_missing_corner():
    boundary = [(0, 0), (4, 0), (4, 1), (1, 1), (1, 4), (0, 4)]
    room = [(2, 2), (3, 2), (3, 3), (2, 3)]

    assert not contains_polygon(boundary, room)


def test_disjoint_triangles_with_overlapping_bounding_boxes_have_no_overlap():
    lower_left = [(0, 0), (2, 0), (0, 2)]
    upper_right = [(1.2, 1.2), (2, 1.2), (1.2, 2)]

    assert polygon_overlap_area(lower_left, upper_right) == 0


def test_shared_wall_has_length_without_positive_area_overlap():
    left = [(0, 0), (2, 0), (2, 2), (0, 2)]
    right = [(2, 0), (4, 0), (4, 2), (2, 2)]

    assert polygon_overlap_area(left, right) == 0
    assert shared_boundary_length(left, right) == 2


def test_overlap_and_union_use_polygon_interiors():
    first = [(0, 0), (2, 0), (2, 2), (0, 2)]
    second = [(1, 1), (3, 1), (3, 3), (1, 3)]

    assert polygon_overlap_area(first, second) == 1
    assert union_area([first, second]) == 7


def test_union_polygon_returns_one_connected_hole_free_outline():
    left = [(0, 0), (2, 0), (2, 2), (0, 2)]
    right = [(2, 0), (4, 0), (4, 1), (2, 1)]

    merged = union_polygon([left, right])

    assert union_area([merged]) == pytest.approx(6.0)
    validate_polygon(merged, label="merged")


def test_union_polygon_rejects_disconnected_result():
    first = [(0, 0), (1, 0), (1, 1), (0, 1)]
    second = [(2, 0), (3, 0), (3, 1), (2, 1)]

    with pytest.raises(ValueError, match="one connected polygon"):
        union_polygon([first, second])


def test_union_polygon_rejects_result_with_hole():
    top = [(0, 3), (4, 3), (4, 4), (0, 4)]
    bottom = [(0, 0), (4, 0), (4, 1), (0, 1)]
    left = [(0, 1), (1, 1), (1, 3), (0, 3)]
    right = [(3, 1), (4, 1), (4, 3), (3, 3)]

    with pytest.raises(ValueError, match="holes"):
        union_polygon([top, bottom, left, right])


def test_closed_clockwise_ring_is_valid():
    polygon = [(0, 0), (0, 2), (2, 2), (2, 0), (0, 0)]

    validate_polygon(polygon)
    assert contains_polygon(polygon, [(0, 0), (1, 0), (1, 1), (0, 1)])


def test_finite_coordinates_with_non_finite_derived_area_are_rejected():
    huge = 1e200

    with pytest.raises(ValueError, match="finite area and perimeter"):
        validate_polygon([(0, 0), (huge, 0), (huge, huge), (0, huge)])


@pytest.mark.parametrize(
    ("polygon", "message"),
    [
        ([(0, 0), (2, 2), (0, 2), (2, 0)], "self-intersecting"),
        ([(0, 0), (1, 0), (2, 0)], "positive area"),
        ([(0, 0), (1, 0), (1, math.nan)], "finite"),
        ([(0, 0), (1, 0), (1, math.inf)], "finite"),
    ],
)
def test_invalid_polygons_raise_value_error(polygon, message):
    with pytest.raises(ValueError, match=message):
        validate_polygon(polygon, label="room")
