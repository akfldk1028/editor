"""
Floor Packing — 원 기반 물리 시뮬레이션으로 평면 생성.

각 방을 면적 비례 원으로 표현, 인접 방 인력 + 비인접 방 척력 시뮬.
수렴 후 그리드 셀을 nearest circle center에 할당.
참조: AUA/gh-packing-plan (Grasshopper agent packing 개념).
"""

import math
import random


from backend.app.modules.design.generation.services.floor_packer import create_grid, evaluate_floor_plan, assignment_to_geojson


def packing_floor_plan(footprint, rooms_def, cell_size=3.0, options=None):
    """
    Circle-packing physics simulation → grid assignment.

    Args:
        footprint: Shapely Polygon
        rooms_def: [{"name": str, "area": float, "adjacency": [str]}]
        cell_size: grid cell size in meters
        options: {"max_iterations": int, "num_runs": int,
                  "k_attract": float, "k_repel": float}

    Returns:
        dict compatible with FloorPlanResult
    """
    options = options or {}
    max_iterations = options.get("max_iterations", 200)
    num_runs = options.get("num_runs", 5)
    k_attract = options.get("k_attract", 0.3)
    k_repel = options.get("k_repel", 0.8)
    damping = options.get("damping", 0.85)
    seed = options.get("seed")

    grid_info = create_grid(footprint, cell_size)

    if not rooms_def:
        return _empty_result(grid_info, rooms_def)

    name_to_idx = {r["name"]: i for i, r in enumerate(rooms_def)}
    adj_pairs = _build_adjacency_pairs(rooms_def, name_to_idx)
    centroid = footprint.centroid

    rng = random.Random(seed) if seed is not None else random
    candidates = []
    for _ in range(num_runs):
        circles = _init_circles(rooms_def, centroid.x, centroid.y, footprint, rng=rng)
        circles = _simulate(
            circles, adj_pairs, footprint,
            max_iterations, k_attract, k_repel, damping,
        )
        assignment = _circles_to_assignment(circles, grid_info, footprint)
        metrics = evaluate_floor_plan(assignment, grid_info, rooms_def)
        score = metrics["adjacency_score"] + metrics["compactness"] - metrics["area_error"]
        candidates.append((score, assignment, metrics))

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


class _Circle:
    __slots__ = ["x", "y", "radius", "vx", "vy", "room_idx"]

    def __init__(self, x, y, radius, room_idx):
        self.x = x
        self.y = y
        self.radius = radius
        self.room_idx = room_idx
        self.vx = 0.0
        self.vy = 0.0


def _init_circles(rooms_def, cx, cy, footprint, rng=random):
    """Create circles at footprint centroid with random jitter."""
    bounds = footprint.bounds
    spread = min(bounds[2] - bounds[0], bounds[3] - bounds[1]) * 0.2

    circles = []
    for i, r in enumerate(rooms_def):
        area = max(r.get("area", 1), 0.1)
        radius = math.sqrt(area / math.pi)
        jx = cx + rng.uniform(-spread, spread)
        jy = cy + rng.uniform(-spread, spread)
        circles.append(_Circle(jx, jy, radius, i))
    return circles


def _build_adjacency_pairs(rooms_def, name_to_idx):
    """Build set of (i, j) pairs where i < j for adjacency."""
    pairs = set()
    for i, r in enumerate(rooms_def):
        for adj_name in r.get("adjacency", []):
            j = name_to_idx.get(adj_name)
            if j is not None:
                pairs.add((min(i, j), max(i, j)))
    return pairs


def _simulate(circles, adj_pairs, footprint, max_iters, k_attract, k_repel, damping):
    """Run force-directed physics simulation."""
    n = len(circles)
    all_pairs = set()
    for i in range(n):
        for j in range(i + 1, n):
            all_pairs.add((i, j))
    non_adj_pairs = all_pairs - adj_pairs

    bounds = footprint.bounds
    bx0, by0, bx1, by1 = bounds

    for iteration in range(max_iters):
        max_force = 0.0

        # Reset forces
        fx = [0.0] * n
        fy = [0.0] * n

        # Attraction between adjacent rooms
        for i, j in adj_pairs:
            ci, cj = circles[i], circles[j]
            dx = cj.x - ci.x
            dy = cj.y - ci.y
            dist = math.sqrt(dx * dx + dy * dy) + 1e-6
            ideal = ci.radius + cj.radius
            force = k_attract * (dist - ideal)
            ux, uy = dx / dist, dy / dist
            fx[i] += force * ux
            fy[i] += force * uy
            fx[j] -= force * ux
            fy[j] -= force * uy

        # Repulsion between non-adjacent rooms (only when overlapping)
        for i, j in non_adj_pairs:
            ci, cj = circles[i], circles[j]
            dx = cj.x - ci.x
            dy = cj.y - ci.y
            dist = math.sqrt(dx * dx + dy * dy) + 1e-6
            overlap = (ci.radius + cj.radius) - dist
            if overlap > 0:
                force = k_repel * overlap
                ux, uy = dx / dist, dy / dist
                fx[i] -= force * ux
                fy[i] -= force * uy
                fx[j] += force * ux
                fy[j] += force * uy

        # Boundary containment: push circles inside footprint bounds
        for i, c in enumerate(circles):
            margin = c.radius * 0.5
            if c.x - margin < bx0:
                fx[i] += k_repel * (bx0 - c.x + margin)
            if c.x + margin > bx1:
                fx[i] += k_repel * (bx1 - c.x - margin)
            if c.y - margin < by0:
                fy[i] += k_repel * (by0 - c.y + margin)
            if c.y + margin > by1:
                fy[i] += k_repel * (by1 - c.y - margin)

        # Apply forces with damping
        for i, c in enumerate(circles):
            c.vx = (c.vx + fx[i]) * damping
            c.vy = (c.vy + fy[i]) * damping
            c.x += c.vx
            c.y += c.vy
            f_mag = math.sqrt(fx[i] ** 2 + fy[i] ** 2)
            if f_mag > max_force:
                max_force = f_mag

        # Convergence check
        if max_force < 0.01:
            break

    return circles


def _circles_to_assignment(circles, grid_info, footprint):
    """Assign grid cells to nearest circle center (weighted by radius)."""
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
            best_code = 0
            best_score = float("inf")
            for circle in circles:
                dx = cx - circle.x
                dy = cy - circle.y
                dist = math.sqrt(dx * dx + dy * dy)
                # Weight by inverse radius: larger rooms claim more cells
                score = dist / max(circle.radius, 0.1)
                if score < best_score:
                    best_score = score
                    best_code = circle.room_idx + 1  # 1-based

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
