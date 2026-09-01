import pytest
from shapely.geometry import Polygon

from backend.engine.geometry.polygonal import (
    common_polygon_region,
    fixed_rectangle_candidates,
    largest_inscribed_axis_aligned_rectangle,
)


def test_sloped_floorplates_produce_common_core_candidates() -> None:
    floors = (
        ((0, 0), (30, 0), (27, 20), (4, 20)),
        ((1, 0), (28, 0), (25, 18), (5, 18)),
    )

    common = common_polygon_region(floors)
    candidates = fixed_rectangle_candidates(
        floors,
        width=7.6,
        depth=5.4,
    )

    assert Polygon(common).area > 400
    assert candidates
    assert all(
        all(Polygon(floor).covers(Polygon(candidate)) for floor in floors)
        for candidate in candidates
    )


def test_largest_planning_rectangle_stays_inside_sloped_boundary_and_requirements() -> None:
    boundary = ((0, 0), (30, 0), (27, 20), (4, 20))
    core = ((10, 10), (18, 10), (18, 16), (10, 16))
    stair = ((23, 1), (26, 1), (26, 6), (23, 6))

    rectangle = largest_inscribed_axis_aligned_rectangle(
        boundary,
        required_polygons=(core, stair),
        grid_step=0.5,
    )

    shape = Polygon(rectangle)
    assert Polygon(boundary).covers(shape)
    assert shape.covers(Polygon(core))
    assert shape.covers(Polygon(stair))
    assert shape.area >= 350


def test_common_polygon_region_rejects_disconnected_intersection() -> None:
    floors = (
        ((0, 0), (8, 0), (8, 8), (6, 8), (6, 2), (2, 2), (2, 8), (0, 8)),
        ((-1, 4), (9, 4), (9, 7), (-1, 7)),
    )

    with pytest.raises(ValueError, match="one connected polygon"):
        common_polygon_region(floors)
