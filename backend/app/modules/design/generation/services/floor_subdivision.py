"""
Floor Subdivision — 재귀 이진 분할로 평면 생성.

매스 footprint를 면적 비율에 따라 재귀적으로 분할하여 방 배치.
인접성(adjacency) 요구사항은 분할 순서로 제어.
"""

import random
from collections import deque

from shapely.geometry import Polygon

from backend.app.modules.design.generation.services.floor_packer import create_grid, evaluate_floor_plan, assignment_to_geojson


def subdivide_floor_plan(footprint, rooms_def, cell_size=3.0, options=None):
    """
    Recursive binary subdivision floor plan generation.

    Args:
        footprint: Shapely Polygon
        rooms_def: [{"name": str, "area": float, "adjacency": [str]}]
        cell_size: grid cell size in meters
        options: {"num_variants": int}

    Returns:
        dict compatible with FloorPlanResult
    """
    options = options or {}
    num_variants = options.get("num_variants", 8)

    grid_info = create_grid(footprint, cell_size)
    rows, cols = grid_info["rows"], grid_info["cols"]
    num_cells = rows * cols

    if not rooms_def:
        return _empty_result(grid_info, rooms_def)

    # Generate multiple variants with different orderings
    bfs_order = _adjacency_bfs_order(rooms_def)
    candidates = []
    for i in range(num_variants):
        if i == 0:
            ordering = list(bfs_order)
        else:
            # Keep first room fixed, shuffle rest for variety
            ordering = list(bfs_order)
            rest = ordering[1:]
            random.shuffle(rest)
            ordering[1:] = rest

        rects = _recursive_split(
            footprint.bounds, [rooms_def[idx] for idx in ordering], ordering,
        )
        assignment = _rects_to_assignment(rects, ordering, grid_info, footprint)
        metrics = evaluate_floor_plan(assignment, grid_info, rooms_def)
        score = metrics["adjacency_score"] + metrics["compactness"] - metrics["area_error"]
        candidates.append((score, assignment, metrics))

    # Sort by composite score descending, take top results
    candidates.sort(key=lambda x: x[0], reverse=True)
    num_results = min(5, len(candidates))

    results = []
    for idx in range(num_results):
        _, assignment, metrics = candidates[idx]
        geojson = assignment_to_geojson(assignment, grid_info, rooms_def)
        results.append({
            "design_id": idx,
            "metrics": metrics,
            "floor_plan": geojson,
        })

    return {
        "grid_info": {
            "rows": grid_info["rows"],
            "cols": grid_info["cols"],
            "cell_size": grid_info["cell_size"],
            "active_cells": grid_info["active_count"],
        },
        "rooms": rooms_def,
        "num_results": len(results),
        "results": results,
    }


def _adjacency_bfs_order(rooms_def):
    """BFS traversal from first room following adjacency links."""
    n = len(rooms_def)
    if n == 0:
        return []

    name_to_idx = {r["name"]: i for i, r in enumerate(rooms_def)}
    visited = set()
    order = []
    queue = deque([0])
    visited.add(0)

    while queue:
        idx = queue.popleft()
        order.append(idx)
        for adj_name in rooms_def[idx].get("adjacency", []):
            adj_idx = name_to_idx.get(adj_name)
            if adj_idx is not None and adj_idx not in visited:
                visited.add(adj_idx)
                queue.append(adj_idx)

    # Add any unvisited rooms (disconnected components)
    for i in range(n):
        if i not in visited:
            order.append(i)

    return order


def _recursive_split(bounds, rooms_ordered, ordering, depth=0):
    """
    Recursively split bounding box into room rectangles.

    Args:
        bounds: (minx, miny, maxx, maxy)
        rooms_ordered: rooms in split order
        ordering: original indices for each room

    Returns:
        list of (room_original_idx, (minx, miny, maxx, maxy))
    """
    if len(rooms_ordered) == 0:
        return []

    if len(rooms_ordered) == 1:
        return [(ordering[0], bounds)]

    minx, miny, maxx, maxy = bounds
    w = maxx - minx
    h = maxy - miny

    if w <= 0 or h <= 0:
        return [(ordering[0], bounds)]

    # Split into two groups by area ratio
    total_area = sum(r.get("area", 1) for r in rooms_ordered)
    split_point = len(rooms_ordered) // 2

    # Find split point that best matches area ratio
    best_split = split_point
    best_diff = float("inf")
    for sp in range(1, len(rooms_ordered)):
        left_area = sum(r.get("area", 1) for r in rooms_ordered[:sp])
        ratio = left_area / total_area if total_area > 0 else 0.5
        diff = abs(ratio - sp / len(rooms_ordered))
        if diff < best_diff:
            best_diff = diff
            best_split = sp

    left_rooms = rooms_ordered[:best_split]
    right_rooms = rooms_ordered[best_split:]
    left_ordering = ordering[:best_split]
    right_ordering = ordering[best_split:]

    left_area = sum(r.get("area", 1) for r in left_rooms)
    ratio = left_area / total_area if total_area > 0 else 0.5

    # Split along the longer axis
    if w >= h:
        # Vertical split (divide width)
        split_x = minx + w * ratio
        left_bounds = (minx, miny, split_x, maxy)
        right_bounds = (split_x, miny, maxx, maxy)
    else:
        # Horizontal split (divide height)
        split_y = miny + h * ratio
        left_bounds = (minx, miny, maxx, split_y)
        right_bounds = (minx, split_y, maxx, maxy)

    left_result = _recursive_split(left_bounds, left_rooms, left_ordering, depth + 1)
    right_result = _recursive_split(right_bounds, right_rooms, right_ordering, depth + 1)

    return left_result + right_result


def _rects_to_assignment(rects, ordering, grid_info, footprint):
    """Convert room rectangles to grid cell assignment."""
    rows, cols = grid_info["rows"], grid_info["cols"]
    mask = grid_info["mask"]
    cell_size = grid_info["cell_size"]
    ox, oy = grid_info["origin"]

    assignment = [0] * (rows * cols)

    for r in range(rows):
        for c in range(cols):
            if not mask[r][c]:
                continue

            cx = ox + (c + 0.5) * cell_size
            cy = oy + (r + 0.5) * cell_size

            # mask already encodes footprint containment (from create_grid)
            # Find which room rectangle contains this cell
            best_code = 0
            best_dist = float("inf")
            for room_idx, rect_bounds in rects:
                rx0, ry0, rx1, ry1 = rect_bounds
                if rx0 <= cx <= rx1 and ry0 <= cy <= ry1:
                    # Inside rectangle — assign directly
                    best_code = room_idx + 1  # 1-based
                    best_dist = -1
                    break
                else:
                    # Distance to rectangle center as fallback
                    rcx = (rx0 + rx1) / 2
                    rcy = (ry0 + ry1) / 2
                    dist = (cx - rcx) ** 2 + (cy - rcy) ** 2
                    if dist < best_dist:
                        best_dist = dist
                        best_code = room_idx + 1

            idx = r * cols + c
            assignment[idx] = best_code

    return assignment


def _empty_result(grid_info, rooms_def):
    return {
        "grid_info": {
            "rows": grid_info["rows"],
            "cols": grid_info["cols"],
            "cell_size": grid_info["cell_size"],
            "active_cells": grid_info["active_count"],
        },
        "rooms": rooms_def,
        "num_results": 0,
        "results": [],
    }
