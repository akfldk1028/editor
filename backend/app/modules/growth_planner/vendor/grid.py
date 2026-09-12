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


def rectilinear_lines(anchors: list[float], step: float) -> np.ndarray:
    """Grid lines through every anchor, each span subdivided into equal parts no longer than ``step``."""
    lines = sorted({round(float(a), 6) for a in anchors})
    out = [lines[0]]
    for a, b in zip(lines, lines[1:]):
        parts = max(1, int(np.ceil((b - a) / step - 1e-9)))
        out.extend(round(a + (b - a) * k / parts, 6) for k in range(1, parts + 1))
    return np.array(out)


def region_to_cells(region, xs: np.ndarray, ys: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Grid over the lines ``xs``/``ys``: -1 outside the region, 0 free inside; plus each cell's area.

    Lines through the region's own edges make every cell either inside or
    outside, so the rooms grown on it meet the corridor, core and outline
    exactly.
    """
    geometry = region if isinstance(region, (Polygon, MultiPolygon)) else Polygon(region)
    prepared = geometry.buffer(1e-9)
    height, width = len(ys) - 1, len(xs) - 1
    grid = np.full((height, width), EMPTY_ROOM_ID, dtype=int)
    area = np.zeros((height, width), dtype=float)
    for j in range(height):
        for i in range(width):
            centre = Point((xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2)
            if prepared.covers(centre):
                grid[j, i] = FREE_CELL
            area[j, i] = (xs[i + 1] - xs[i]) * (ys[j + 1] - ys[j])
    return grid, area


def cells_to_polygons(grid: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> dict[int, Polygon]:
    """Union of each room id's cells on a rectilinear grid."""
    polygons: dict[int, Polygon] = {}
    for room_id in np.unique(grid):
        if room_id in (EMPTY_ROOM_ID, FREE_CELL):
            continue
        cells = [box(xs[i], ys[j], xs[i + 1], ys[j + 1]) for j, i in np.argwhere(grid == room_id)]
        union = unary_union(cells)
        if not union.is_empty:
            polygons[int(room_id)] = union
    return polygons


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
