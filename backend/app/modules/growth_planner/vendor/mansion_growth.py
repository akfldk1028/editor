"""Seed-and-grow room partitioning.  From MANSION's llm_seed_expand (Apache-2.0, see NOTICE).

Rooms start as small blocks at their seeds and grow, one full edge at a
time, into free cells: first as rectangles, optionally then as L-shapes.
Spur cells are removed and holes are filled afterwards.  The grid convention
is that of ``grid.py``: -1 outside, 0 free, room ids >= 1.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

import numpy as np

from backend.app.modules.growth_planner.vendor.grid import EMPTY_ROOM_ID, FREE_CELL


@dataclass
class RoomInfo:
    room_id: int
    name: str
    target_cells: int
    # Growth stops once the room would exceed this many cells (None: no cap).
    max_cells: int | None = None
    # On a rectilinear grid cells differ in size; these are the same caps in
    # area, checked against the cell-area matrix passed to the growth.
    target_area: float | None = None
    max_area: float | None = None
    min_chunk: int = 1
    # Cells kept clear of later seeds around this room's first block, so
    # neighbours start about a room's width apart instead of boxing it in.
    spacing: int = 1
    max_w_allowed: int | None = None
    max_h_allowed: int | None = None
    min_x: int = field(default=0)
    max_x: int = field(default=0)
    min_y: int = field(default=0)
    max_y: int = field(default=0)
    seed_cell_x: int = field(default=0)
    seed_cell_y: int = field(default=0)

    @property
    def width(self) -> int:
        return self.max_x - self.min_x

    @property
    def height(self) -> int:
        return self.max_y - self.min_y


def _prelimit_on(room: RoomInfo, grid: np.ndarray, enabled: bool, start_ratio: float, cell_area=None) -> bool:
    if not enabled:
        return False
    if cell_area is not None and room.target_area:
        return float(cell_area[grid == room.room_id].sum()) >= max(0.0, start_ratio) * room.target_area
    if room.target_cells <= 0:
        return False
    return int((grid == room.room_id).sum()) >= max(0.0, start_ratio) * room.target_cells


def sample_initial_positions(
    rooms: list[RoomInfo],
    grid: np.ndarray,
    rng: random.Random,
    seed_positions: list[tuple[int, int]] | None = None,
    seed_radius: int = 2,
    allowed: np.ndarray | list[np.ndarray] | None = None,
) -> None:
    """Drop each room's first block at a free cell near its seed.

    ``allowed`` (a bool grid, or one per room) restricts where a room may
    start; rooms are placed in order, each excluding a one-cell ring around
    its block.
    """
    grid_weights = np.where(grid == FREE_CELL, 1.0, 0.0)
    for index, room in enumerate(rooms):
        if not (grid_weights > 0).any():
            raise ValueError("No empty cells available for room placement")
        weights = grid_weights.copy()
        mask = allowed[index] if isinstance(allowed, list) else allowed
        if mask is not None:
            weights = weights * np.where(mask, 1.0, 0.0)
        if seed_positions is not None and index < len(seed_positions):
            seed_x, seed_y = seed_positions[index]
            for radius in range(seed_radius, seed_radius + 5):
                local = weights.copy()
                for j in range(grid.shape[0]):
                    for i in range(grid.shape[1]):
                        if math.hypot(i - seed_x, j - seed_y) > radius:
                            local[j, i] = 0.0
                if (local > 0).any():
                    weights = local
                    break
        if not (weights > 0).any() and mask is not None:
            # The spacing of earlier rooms swallowed this room's whole zone;
            # its zone still binds, the spacing does not.
            weights = np.where((grid == FREE_CELL) & mask, 1.0, 0.0)
        if not (weights > 0).any():
            weights = grid_weights.copy()
        flat = weights.ravel()
        cell_index = rng.choices(range(flat.size), weights=flat.tolist(), k=1)[0]
        cell_y, cell_x = divmod(cell_index, grid.shape[1])
        room.seed_cell_x, room.seed_cell_y = int(cell_x), int(cell_y)

        k = max(1, int(room.min_chunk))
        placed = False
        for dy in range(-(k - 1), 1):
            if placed:
                break
            for dx in range(-(k - 1), 1):
                x0, y0 = cell_x + dx, cell_y + dy
                x1, y1 = x0 + k, y0 + k
                if x0 < 0 or y0 < 0 or x1 > grid.shape[1] or y1 > grid.shape[0]:
                    continue
                block = grid[y0:y1, x0:x1]
                if (block == FREE_CELL).all():
                    grid[y0:y1, x0:x1] = room.room_id
                    room.min_x, room.max_x, room.min_y, room.max_y = x0, x1, y0, y1
                    placed = True
                    break
        if not placed:
            room.min_x, room.max_x = cell_x, cell_x + 1
            room.min_y, room.max_y = cell_y, cell_y + 1
            grid[cell_y, cell_x] = room.room_id
        # Later seeds keep ``spacing`` cells away along the row (x) and one
        # cell across it, so rooms line up along the corridor without boxing
        # each other in.
        ring = max(1, int(room.spacing))
        grid_weights[
            max(0, room.min_y - 1): min(grid.shape[0], room.max_y + 1),
            max(0, room.min_x - ring): min(grid.shape[1], room.max_x + ring),
        ] = 0.0


def grow_rect(
    room: RoomInfo,
    grid: np.ndarray,
    rng: random.Random,
    *,
    prelimit_enabled: bool = False,
    prelimit_start_ratio: float = 0.6,
    cell_area: np.ndarray | None = None,
) -> bool:
    """Extend the room's rectangle by one strip on the side with the most free cells."""
    if room.max_cells is not None and room.width * room.height >= room.max_cells:
        return False
    k = max(1, int(room.min_chunk))
    w, h = room.width, room.height
    limit_on = _prelimit_on(room, grid, prelimit_enabled, prelimit_start_ratio, cell_area)
    sizes: dict[str, int] = {}

    def strip_free(strip: np.ndarray) -> bool:
        return strip.size > 0 and (strip == FREE_CELL).all()

    sizes["right"] = h if room.max_x + k <= grid.shape[1] and strip_free(grid[room.min_y:room.max_y, room.max_x:room.max_x + k]) else 0
    sizes["left"] = h if room.min_x - k >= 0 and strip_free(grid[room.min_y:room.max_y, room.min_x - k:room.min_x]) else 0
    sizes["down"] = w if room.max_y + k <= grid.shape[0] and strip_free(grid[room.max_y:room.max_y + k, room.min_x:room.max_x]) else 0
    sizes["up"] = w if room.min_y - k >= 0 and strip_free(grid[room.min_y - k:room.min_y, room.min_x:room.max_x]) else 0
    if limit_on and room.max_w_allowed is not None and w + k > room.max_w_allowed:
        sizes["right"] = sizes["left"] = 0
    if limit_on and room.max_h_allowed is not None and h + k > room.max_h_allowed:
        sizes["down"] = sizes["up"] = 0
    if room.max_cells is not None:
        for direction, gain in list(sizes.items()):
            if gain and w * h + gain * k > room.max_cells:
                sizes[direction] = 0
    if cell_area is not None and room.max_area is not None:
        current = float(cell_area[room.min_y:room.max_y, room.min_x:room.max_x].sum())
        strips = {
            "right": cell_area[room.min_y:room.max_y, room.max_x:room.max_x + k],
            "left": cell_area[room.min_y:room.max_y, max(0, room.min_x - k):room.min_x],
            "down": cell_area[room.max_y:room.max_y + k, room.min_x:room.max_x],
            "up": cell_area[max(0, room.min_y - k):room.min_y, room.min_x:room.max_x],
        }
        for direction, gain in list(sizes.items()):
            if gain and current + float(strips[direction].sum()) > room.max_area + 1e-9:
                sizes[direction] = 0

    best = max(sizes.values())
    if best == 0:
        return False
    direction = rng.choice([d for d, s in sizes.items() if s == best])
    if direction == "right":
        grid[room.min_y:room.max_y, room.max_x:room.max_x + k] = room.room_id
        room.max_x += k
    elif direction == "left":
        grid[room.min_y:room.max_y, room.min_x - k:room.min_x] = room.room_id
        room.min_x -= k
    elif direction == "down":
        grid[room.max_y:room.max_y + k, room.min_x:room.max_x] = room.room_id
        room.max_y += k
    else:
        grid[room.min_y - k:room.min_y, room.min_x:room.max_x] = room.room_id
        room.min_y -= k
    return True


def grow_l_shape(room: RoomInfo, grid: np.ndarray, rng: random.Random) -> bool:
    """Extend only the rows/columns of the room that can grow, so it may turn L-shaped."""
    k = max(1, int(room.min_chunk))
    cells: dict[str, list[int]] = {}
    if room.max_x + k <= grid.shape[1]:
        cells["right"] = [y for y in range(room.min_y, room.max_y)
                          if grid[y, room.max_x - 1] == room.room_id and (grid[y, room.max_x:room.max_x + k] == FREE_CELL).all()]
    if room.min_x - k >= 0:
        cells["left"] = [y for y in range(room.min_y, room.max_y)
                         if grid[y, room.min_x] == room.room_id and (grid[y, room.min_x - k:room.min_x] == FREE_CELL).all()]
    if room.max_y + k <= grid.shape[0]:
        cells["down"] = [x for x in range(room.min_x, room.max_x)
                         if grid[room.max_y - 1, x] == room.room_id and (grid[room.max_y:room.max_y + k, x] == FREE_CELL).all()]
    if room.min_y - k >= 0:
        cells["up"] = [x for x in range(room.min_x, room.max_x)
                       if grid[room.min_y, x] == room.room_id and (grid[room.min_y - k:room.min_y, x] == FREE_CELL).all()]
    best = max((len(v) for v in cells.values()), default=0)
    if best == 0:
        return False
    direction = rng.choice([d for d, v in cells.items() if len(v) == best])
    if direction == "right":
        for y in cells["right"]:
            grid[y, room.max_x:room.max_x + k] = room.room_id
        room.max_x += k
    elif direction == "left":
        for y in cells["left"]:
            grid[y, room.min_x - k:room.min_x] = room.room_id
        room.min_x -= k
    elif direction == "down":
        for x in cells["down"]:
            grid[room.max_y:room.max_y + k, x] = room.room_id
        room.max_y += k
    else:
        for x in cells["up"]:
            grid[room.min_y - k:room.min_y, x] = room.room_id
        room.min_y -= k
    return True


def select_room(rooms: list[RoomInfo], rng: random.Random, boost: dict[int, float] | None = None) -> RoomInfo:
    weights = [max(1e-6, float((boost or {}).get(r.room_id, 1.0))) for r in rooms]
    return rooms[rng.choices(range(len(rooms)), weights=weights, k=1)[0]]


def expand_rooms(
    rooms: list[RoomInfo],
    grid: np.ndarray,
    rng: random.Random,
    *,
    seed_positions: list[tuple[int, int]] | None = None,
    seed_radius: int = 2,
    allowed: np.ndarray | None = None,
    l_shapes: bool = True,
    prelimit_enabled: bool = False,
    prelimit_start_ratio: float = 0.6,
    boost: dict[int, float] | None = None,
    cell_area: np.ndarray | None = None,
) -> None:
    """Seed every room, grow rectangles until stuck, then (optionally) L-shapes.

    ``boost`` weights which room grows next; weighting by target size lets
    rooms grow in proportion instead of the first one blocking the rest.
    """
    sample_initial_positions(rooms, grid, rng, seed_positions, seed_radius=seed_radius, allowed=allowed)
    growing = list(rooms)
    while growing:
        room = select_room(growing, rng, boost)
        if not grow_rect(room, grid, rng, prelimit_enabled=prelimit_enabled,
                         prelimit_start_ratio=prelimit_start_ratio, cell_area=cell_area):
            growing = [r for r in growing if r is not room]
    if not l_shapes:
        return
    growing = list(rooms)
    while growing:
        room = select_room(growing, rng, boost)
        if not grow_l_shape(room, grid, rng):
            growing = [r for r in growing if r is not room]


def detect_spurs(grid: np.ndarray, skip_ids: set[int] | None = None) -> list[tuple[int, int, int]]:
    """Cells with at most one same-room neighbour that touch another room or the outside."""
    h, w = grid.shape
    skip = skip_ids or set()
    spurs = []
    for y in range(h):
        for x in range(w):
            rid = int(grid[y, x])
            if rid <= 0 or rid in skip:
                continue
            same, other, outside = 0, 0, 0
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if nx < 0 or nx >= w or ny < 0 or ny >= h or grid[ny, nx] <= 0:
                    outside += 1
                elif int(grid[ny, nx]) == rid:
                    same += 1
                else:
                    other += 1
            if same <= 1 and (other or outside >= 2):
                spurs.append((y, x, rid))
    return spurs


def fill_holes_components(grid: np.ndarray, interior: np.ndarray, fill_id: int | None = None) -> np.ndarray:
    """Give every free connected component to ``fill_id``, or to the room it touches most."""
    h, w = grid.shape
    filled = grid.copy()
    seen = np.zeros_like(filled, dtype=bool)
    for y in range(h):
        for x in range(w):
            if not interior[y, x] or filled[y, x] != FREE_CELL or seen[y, x]:
                continue
            component = []
            stack = [(y, x)]
            seen[y, x] = True
            while stack:
                cy, cx = stack.pop()
                component.append((cy, cx))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < w and 0 <= ny < h and interior[ny, nx] and filled[ny, nx] == FREE_CELL and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            target = fill_id
            if target is None:
                contact: dict[int, int] = {}
                for cy, cx in component:
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < w and 0 <= ny < h and filled[ny, nx] > 0:
                            rid = int(filled[ny, nx])
                            contact[rid] = contact.get(rid, 0) + 1
                if not contact:
                    continue
                target = max(contact.items(), key=lambda kv: kv[1])[0]
            for cy, cx in component:
                filled[cy, cx] = target
    return filled


def clean_and_fill_grid(
    grid: np.ndarray,
    interior: np.ndarray,
    skip_ids: set[int] | None = None,
    max_iter: int = 20,
    fill_id: int | None = None,
) -> np.ndarray:
    """Remove spurs, fill the freed and remaining holes, repeat until spur-free."""
    cleaned = grid.copy()
    for _ in range(max_iter):
        spurs = detect_spurs(cleaned, skip_ids=skip_ids)
        for y, x, _rid in spurs:
            cleaned[y, x] = FREE_CELL
        cleaned = fill_holes_components(cleaned, interior, fill_id=fill_id)
        if not detect_spurs(cleaned, skip_ids=skip_ids):
            break
    return cleaned
