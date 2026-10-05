"""
Floor MCTS — Monte Carlo Tree Search 기반 평면 생성.

그리드 셀에 방을 순차 배치, UCB 탐색으로 최적 배치 탐색.
참조: clone/RL-Floorplan/MCTS.py (fixed grid 적응 버전).
"""

import math
import random
import time
from copy import deepcopy

import numpy as np

from backend.app.modules.design.generation.services.floor_packer import create_grid, evaluate_floor_plan, assignment_to_geojson


def mcts_floor_plan(footprint, rooms_def, cell_size=3.0, options=None):
    """
    MCTS-based floor plan generation.

    Args:
        footprint: Shapely Polygon
        rooms_def: [{"name": str, "area": float, "adjacency": [str]}]
        cell_size: grid cell size in meters
        options: {"num_iterations": int, "num_runs": int, "explore_rate": float}

    Returns:
        dict compatible with FloorPlanResult
    """
    options = options or {}
    num_iterations = options.get("num_iterations", 300)
    num_runs = options.get("num_runs", 5)
    explore_rate = options.get("explore_rate", 2.0)
    time_limit = options.get("time_limit", 5.0)

    grid_info = create_grid(footprint, cell_size)
    rows, cols = grid_info["rows"], grid_info["cols"]
    mask = grid_info["mask"]

    if not rooms_def:
        return _empty_result(grid_info, rooms_def)

    num_rooms = len(rooms_def)
    cons = _build_constraint_matrix(rooms_def)
    room_ids = list(range(1, num_rooms + 1))

    # Build initial state from mask (0 = empty active, -1 = inactive)
    init_state = np.zeros((rows, cols), dtype=int)
    for r in range(rows):
        for c in range(cols):
            if not mask[r][c]:
                init_state[r][c] = -1

    candidates = []
    for run_idx in range(num_runs):
        state = _run_mcts(
            init_state, room_ids, cons, rooms_def, grid_info,
            num_iterations, explore_rate, time_limit,
        )
        if state is not None:
            assignment = _state_to_assignment(state, rows, cols)
            metrics = evaluate_floor_plan(assignment, grid_info, rooms_def)
            score = metrics["adjacency_score"] + metrics["compactness"] - metrics["area_error"]
            candidates.append((score, assignment, metrics))

    if not candidates:
        # Fallback: random assignment
        assignment = _random_assignment(grid_info, num_rooms)
        metrics = evaluate_floor_plan(assignment, grid_info, rooms_def)
        candidates.append((0, assignment, metrics))

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


def _build_constraint_matrix(rooms_def):
    """Build adjacency constraint matrix from rooms_def.

    Returns numpy array: +1 = must be adjacent, 0 = no constraint.
    """
    n = len(rooms_def)
    name_to_idx = {r["name"]: i for i, r in enumerate(rooms_def)}
    cons = np.zeros((n, n), dtype=int)
    for i, r in enumerate(rooms_def):
        for adj_name in r.get("adjacency", []):
            j = name_to_idx.get(adj_name)
            if j is not None:
                cons[i][j] = 1
                cons[j][i] = 1
    return cons


def _run_mcts(init_state, room_ids, cons, rooms_def, grid_info,
              num_iterations, explore_rate, time_limit):
    """Run one MCTS search to place rooms on the grid."""
    rows, cols = init_state.shape
    active_cells = []
    for r in range(rows):
        for c in range(cols):
            if init_state[r][c] == 0:
                active_cells.append((r, c))

    if not active_cells or not room_ids:
        return None

    # Target cells per room based on area
    cell_area = grid_info["cell_size"] ** 2
    total_area = sum(r.get("area", cell_area) for r in rooms_def)
    total_active = len(active_cells)
    target_cells = {}
    for i, r in enumerate(rooms_def):
        ratio = r.get("area", cell_area) / total_area if total_area > 0 else 1 / len(rooms_def)
        target_cells[i + 1] = max(1, round(ratio * total_active))

    root = _MCTSNode(
        state=init_state.copy(),
        remaining_rooms=list(room_ids),
        target_cells=target_cells,
    )

    start_time = time.time()
    best_state = None
    best_reward = -float("inf")

    for iteration in range(num_iterations):
        if time.time() - start_time > time_limit:
            break

        # Selection + Expansion + Simulation
        node = root
        path = [node]

        while node.children and not node.is_terminal:
            node = _ucb_select(node, explore_rate)
            path.append(node)

        if not node.is_terminal and not node.children:
            _expand(node)
            if node.children:
                node = random.choice(node.children)
                path.append(node)

        # Simulation (random rollout)
        sim_state = _simulate(node)

        # Evaluate
        reward = _compute_reward(sim_state, cons, rooms_def, grid_info)

        if reward > best_reward:
            best_reward = reward
            best_state = sim_state.copy()

        # Backpropagation
        for n in path:
            n.visits += 1
            n.total_reward += reward
            if reward > n.best_q:
                n.best_q = reward

    return best_state


class _MCTSNode:
    __slots__ = [
        "state", "remaining_rooms", "target_cells",
        "children", "visits", "total_reward", "best_q", "is_terminal",
    ]

    def __init__(self, state, remaining_rooms, target_cells):
        self.state = state
        self.remaining_rooms = remaining_rooms
        self.target_cells = target_cells
        self.children = []
        self.visits = 0
        self.total_reward = 0.0
        self.best_q = -float("inf")
        self.is_terminal = len(remaining_rooms) == 0


def _expand(node):
    """Expand node by trying to place the next room in different positions."""
    if not node.remaining_rooms:
        node.is_terminal = True
        return

    room_id = node.remaining_rooms[0]
    remaining = node.remaining_rooms[1:]
    target = node.target_cells.get(room_id, 1)
    rows, cols = node.state.shape

    # Find empty cells
    empty_cells = []
    for r in range(rows):
        for c in range(cols):
            if node.state[r][c] == 0:
                empty_cells.append((r, c))

    if not empty_cells:
        node.is_terminal = True
        return

    # Generate children by placing room starting from different seed cells
    # Use a subset of positions to keep branching manageable
    seed_positions = _sample_seed_positions(empty_cells, max_seeds=6)

    for seed_r, seed_c in seed_positions:
        new_state = node.state.copy()
        # Flood-fill from seed to claim `target` cells
        _flood_fill_room(new_state, seed_r, seed_c, room_id, target)
        child = _MCTSNode(new_state, remaining, node.target_cells)
        node.children.append(child)


def _sample_seed_positions(empty_cells, max_seeds=6):
    """Sample diverse seed positions from empty cells."""
    if len(empty_cells) <= max_seeds:
        return empty_cells

    # Pick evenly spaced positions
    step = len(empty_cells) // max_seeds
    seeds = [empty_cells[i * step] for i in range(max_seeds)]
    return seeds


def _flood_fill_room(state, start_r, start_c, room_id, target_cells):
    """BFS flood-fill to assign target_cells cells to room_id."""
    rows, cols = state.shape
    if state[start_r][start_c] != 0:
        return

    queue = [(start_r, start_c)]
    state[start_r][start_c] = room_id
    filled = 1
    qi = 0

    while qi < len(queue) and filled < target_cells:
        r, c = queue[qi]
        qi += 1
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < cols and state[nr][nc] == 0:
                state[nr][nc] = room_id
                filled += 1
                queue.append((nr, nc))
                if filled >= target_cells:
                    break


def _ucb_select(node, explore_rate):
    """Select child using UCB1."""
    total_visits = node.visits
    best_child = None
    best_ucb = -float("inf")

    for child in node.children:
        if child.visits == 0:
            return child  # Always explore unvisited
        q = child.total_reward / child.visits
        ucb = q + explore_rate * math.sqrt(math.log(total_visits) / child.visits)
        if ucb > best_ucb:
            best_ucb = ucb
            best_child = child

    return best_child or (node.children[0] if node.children else node)


def _simulate(node):
    """Random rollout from node: place remaining rooms randomly."""
    state = node.state.copy()
    rows, cols = state.shape

    for room_id in node.remaining_rooms:
        target = node.target_cells.get(room_id, 1)
        empty = [(r, c) for r in range(rows) for c in range(cols) if state[r][c] == 0]
        if not empty:
            break
        seed_r, seed_c = random.choice(empty)
        _flood_fill_room(state, seed_r, seed_c, room_id, target)

    return state


def _compute_reward(state, cons, rooms_def, grid_info):
    """Combined reward: adjacency satisfaction + area accuracy."""
    rows, cols = state.shape
    n = len(rooms_def)

    # Adjacency reward (from RL-Floorplan total_return)
    connect = np.zeros((n, n), dtype=int)
    for r in range(rows):
        for c in range(cols):
            val = state[r][c]
            if val <= 0:
                continue
            # Check right neighbor
            if c + 1 < cols and state[r][c + 1] > 0 and state[r][c + 1] != val:
                a, b = val - 1, state[r][c + 1] - 1
                connect[a][b] = 1
                connect[b][a] = 1
            # Check bottom neighbor
            if r + 1 < rows and state[r + 1][c] > 0 and state[r + 1][c] != val:
                a, b = val - 1, state[r + 1][c] - 1
                connect[a][b] = 1
                connect[b][a] = 1

    adj_total = max(1, np.sum(cons > 0))
    adj_satisfied = np.sum((cons > 0) & (connect > 0))
    adj_reward = adj_satisfied / adj_total

    # Area reward
    cell_area = grid_info["cell_size"] ** 2
    total_target = sum(r.get("area", 0) for r in rooms_def)
    if total_target > 0:
        area_error = 0.0
        for i, rdef in enumerate(rooms_def):
            room_id = i + 1
            actual = np.sum(state == room_id) * cell_area
            required = rdef.get("area", 0)
            area_error += abs(actual - required)
        area_penalty = area_error / total_target
    else:
        area_penalty = 0.0

    return 0.7 * adj_reward + 0.3 * (1.0 - min(1.0, area_penalty))


def _state_to_assignment(state, rows, cols):
    """Convert numpy 2D state to flat assignment list."""
    assignment = []
    for r in range(rows):
        for c in range(cols):
            val = int(state[r][c])
            assignment.append(max(0, val))  # -1 (inactive) → 0
    return assignment


def _random_assignment(grid_info, num_rooms):
    """Fallback: assign cells to rooms randomly."""
    rows, cols = grid_info["rows"], grid_info["cols"]
    mask = grid_info["mask"]
    assignment = []
    for r in range(rows):
        for c in range(cols):
            if mask[r][c]:
                assignment.append(random.randint(1, num_rooms))
            else:
                assignment.append(0)
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
