"""The vendored MANSION grid growth: rasterise, seed, grow, clean."""

import random

import numpy as np
import pytest
from shapely.geometry import MultiPolygon, Polygon, box

from backend.app.modules.growth_planner.vendor.grid import (
    EMPTY_ROOM_ID,
    FREE_CELL,
    grid_to_polygons,
    polygon_to_grid,
)
from backend.app.modules.growth_planner.vendor.mansion_growth import (
    RoomInfo,
    clean_and_fill_grid,
    detect_spurs,
    expand_rooms,
    fill_holes_components,
)


def test_a_rectangle_round_trips_through_the_grid():
    grid, offset = polygon_to_grid(box(0, 0, 10, 6), grid_size=0.5)

    assert grid.shape == (12, 20)
    assert (grid == FREE_CELL).all()
    grid[:, :] = 7
    polys = grid_to_polygons(grid, 0.5, offset)
    assert polys[7].equals(box(0, 0, 10, 6))


def test_a_multipolygon_region_leaves_the_gap_outside():
    region = MultiPolygon([box(0, 0, 4, 4), box(6, 0, 10, 4)])
    grid, _ = polygon_to_grid(region, grid_size=1.0)

    assert (grid[:, 4:6] == EMPTY_ROOM_ID).all()
    assert (grid[:, :4] == FREE_CELL).all() and (grid[:, 6:] == FREE_CELL).all()


def test_two_rooms_grow_as_rectangles_without_overlap_and_are_capped():
    grid, _ = polygon_to_grid(box(0, 0, 10, 6), grid_size=1.0)
    rooms = [RoomInfo(1, "a", target_cells=12, max_cells=12), RoomInfo(2, "b", target_cells=12, max_cells=12)]

    expand_rooms(rooms, grid, random.Random(0), seed_positions=[(1, 1), (8, 4)], seed_radius=1, l_shapes=False)

    for room in rooms:
        cells = int((grid == room.room_id).sum())
        assert 1 <= cells <= 12
        assert cells == room.width * room.height  # a rectangle
    assert ((grid == 1) & (grid == 2)).sum() == 0


def test_growth_is_reproducible_for_a_seed():
    def run(seed):
        grid, _ = polygon_to_grid(box(0, 0, 10, 6), grid_size=1.0)
        rooms = [RoomInfo(1, "a", target_cells=20), RoomInfo(2, "b", target_cells=20)]
        expand_rooms(rooms, grid, random.Random(seed), seed_positions=[(1, 1), (8, 4)])
        return grid

    assert np.array_equal(run(3), run(3))


def test_spurs_are_detected_removed_and_holes_filled():
    grid = np.full((5, 6), FREE_CELL, dtype=int)
    grid[1:4, 1:4] = 1  # 3x3 block
    grid[2, 4] = 1  # one-cell spur hanging off its right edge
    interior = np.ones_like(grid, dtype=bool)

    assert (2, 4, 1) in detect_spurs(grid)
    cleaned = clean_and_fill_grid(grid, interior, fill_id=9)
    assert cleaned[2, 4] == 9  # freed spur cell went to the filler
    assert (cleaned[1:4, 1:4] == 1).all()
    assert not detect_spurs(cleaned, skip_ids={9})


def test_holes_go_to_the_room_touching_them_most():
    grid = np.full((4, 4), FREE_CELL, dtype=int)
    grid[:, :2] = 1
    grid[0, 2:] = 2
    interior = np.ones_like(grid, dtype=bool)

    filled = fill_holes_components(grid, interior)

    assert (filled[1:, 2:] == 1).all()  # three cells of contact with room 1, two with room 2


def test_a_seed_block_never_starts_over_its_area_cap_where_cells_are_wider():
    """Cells differ across structure lines: a block sized from narrow cells must not land on wide ones over the cap."""
    from backend.app.modules.growth_planner.vendor.mansion_growth import sample_initial_positions

    grid = np.zeros((4, 10), dtype=int)
    cell_area = np.ones((4, 10))
    cell_area[:, 5:] = 2.0  # the right half's cells are twice as big
    room = RoomInfo(room_id=1, name="stock", target_cells=16, max_cells=None, target_area=16.0,
                    max_area=16.0, min_chunk=1, block_w=4, block_h=4)
    right_half = np.zeros_like(grid, dtype=bool)
    right_half[:, 5:] = True

    sample_initial_positions([room], grid, random.Random(0), allowed=right_half, cell_area=cell_area)

    assert float(cell_area[grid == 1].sum()) <= 16.0 + 1e-9
    assert (grid == 1).any()
