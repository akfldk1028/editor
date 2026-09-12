"""Rasterise a region to a cell grid and back.  From MANSION's procthor_adapter (Apache-2.0, see NOTICE)."""

from __future__ import annotations

import numpy as np
from shapely.geometry import MultiPolygon, Point, Polygon, box
from shapely.ops import unary_union

EMPTY_ROOM_ID = -1  # outside the region
FREE_CELL = 0  # inside, not yet assigned


def polygon_to_grid(region, grid_size: float = 1.0) -> tuple[np.ndarray, tuple[int, int]]:
    """Grid of the region: -1 outside, 0 free inside.  Returns (grid, (min_i, min_j)).

    ``region`` is a shapely Polygon or MultiPolygon, or a coordinate list.
    A cell is inside when its centre is.
    """
    geometry = region if isinstance(region, (Polygon, MultiPolygon)) else Polygon(region)
    minx, miny, maxx, maxy = geometry.bounds
    min_i = int(np.floor(minx / grid_size))
    min_j = int(np.floor(miny / grid_size))
    max_i = int(np.ceil(maxx / grid_size))
    max_j = int(np.ceil(maxy / grid_size))
    width, height = max_i - min_i, max_j - min_j
    grid = np.full((height, width), EMPTY_ROOM_ID, dtype=int)
    prepared = geometry.buffer(1e-9)
    for j in range(height):
        for i in range(width):
            centre = Point((min_i + i + 0.5) * grid_size, (min_j + j + 0.5) * grid_size)
            if prepared.covers(centre):
                grid[j, i] = FREE_CELL
    return grid, (min_i, min_j)


def grid_to_polygons(grid: np.ndarray, grid_size: float, offset: tuple[int, int]) -> dict[int, Polygon]:
    """Union of each room id's cells.  Returns room_id -> shapely geometry (may be a MultiPolygon)."""
    min_i, min_j = offset
    polygons: dict[int, Polygon] = {}
    for room_id in np.unique(grid):
        if room_id in (EMPTY_ROOM_ID, FREE_CELL):
            continue
        cells = [
            box((min_i + i) * grid_size, (min_j + j) * grid_size,
                (min_i + i + 1) * grid_size, (min_j + j + 1) * grid_size)
            for j, i in np.argwhere(grid == room_id)
        ]
        union = unary_union(cells)
        if not union.is_empty:
            polygons[int(room_id)] = union
    return polygons
