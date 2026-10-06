"""
Floor Packer — 매스 footprint 내부를 그리드 분할 → 방 배치 + 평가.

Series gene (셀별 room 코드 0~N) 기반. GA/MCTS로 최적화.
0 = 빈 셀 (복도/공용), 1~N = room index.
"""

import math
import os
from copy import deepcopy

from collections import defaultdict

from shapely.geometry import Polygon, box, mapping, shape
from shapely.ops import unary_union


# ── Room colors for GeoJSON rendering ────────────────
_ROOM_COLORS = [
    "#94a3b8",  # 0: 빈 셀 (slate-400)
    "#f87171",  # 1: red
    "#fb923c",  # 2: orange
    "#facc15",  # 3: yellow
    "#4ade80",  # 4: green
    "#60a5fa",  # 5: blue
    "#a78bfa",  # 6: violet
    "#f472b6",  # 7: pink
    "#2dd4bf",  # 8: teal
    "#fbbf24",  # 9: amber
    "#818cf8",  # 10: indigo
]


def grid_dimensions(footprint, cell_size_m):
    """Reject unbounded grid allocation; this is a runtime, not design limit."""
    if isinstance(cell_size_m, bool) or not isinstance(cell_size_m, (float, int)) or not math.isfinite(cell_size_m) or cell_size_m <= 0:
        raise ValueError('cell_size must be a positive finite number')
    limit = int(os.environ.get('EDITOR_FLOOR_PLAN_MAX_CELLS', '50000'))
    if limit <= 0:
        raise ValueError('EDITOR_FLOOR_PLAN_MAX_CELLS must be positive')
    minx, miny, maxx, maxy = footprint.bounds
    width, height = (maxx - minx) / cell_size_m, (maxy - miny) / cell_size_m
    if not math.isfinite(width) or not math.isfinite(height) or width > limit or height > limit:
        raise ValueError(f'Floor-plan cell budget exceeded ({limit})')
    cols, rows = max(1, math.ceil(width)), max(1, math.ceil(height))
    if rows * cols > limit:
        raise ValueError(f'Floor-plan cell budget exceeded ({limit})')
    return rows, cols


def create_grid(footprint: Polygon, cell_size_m: float = 3.0) -> dict:
    """
    매스 footprint → N×M 그리드, footprint 밖 셀 마스킹.

    Args:
        footprint: Shapely Polygon (UTM or local coordinates)
        cell_size_m: 셀 크기 (미터). 기본 3m (일반적인 방 모듈)

    Returns:
        {
            "rows": int, "cols": int,
            "mask": list[list[bool]],  # True = footprint 안 (활성 셀)
            "cell_size": float,
            "origin": (minx, miny),
            "active_count": int,
        }
    """
    minx, miny, maxx, maxy = footprint.bounds
    rows, cols = grid_dimensions(footprint, cell_size_m)

    mask = []
    cell_areas = []
    active_count = 0
    for r in range(rows):
        row_mask = []
        row_areas = []
        for c in range(cols):
            x0, y0 = minx + c * cell_size_m, miny + r * cell_size_m
            area = footprint.intersection(
                box(x0, y0, x0 + cell_size_m, y0 + cell_size_m)
            ).area
            active = area > 0
            row_mask.append(active)
            row_areas.append(area)
            if active:
                active_count += 1
        mask.append(row_mask)
        cell_areas.append(row_areas)

    return {
        "rows": rows,
        "cols": cols,
        "mask": mask,
        "cell_size": cell_size_m,
        "origin": (minx, miny),
        "active_count": active_count,
        "footprint": mapping(footprint),
        "cell_areas": cell_areas,
        "active_area_m2": sum(map(sum, cell_areas)),
    }


def evaluate_floor_plan(
    assignment: list[int],
    grid_info: dict,
    rooms_def: list[dict],
) -> dict:
    """
    Series gene (셀별 room 코드) → 평면 평가.

    Args:
        assignment: flat list of room codes (length = rows * cols)
                    0 = 빈 셀, 1~N = room index (1-based)
        grid_info: create_grid() 결과
        rooms_def: [{"name": str, "area": float, "adjacency": [str]}]

    Returns:
        {
            "adjacency_score": float (0~1, 높을수록 좋음),
            "area_error": float (0~inf, 낮을수록 좋음),
            "compactness": float (0~1, 높을수록 좋음),
        }
    """
    rows, cols = grid_info["rows"], grid_info["cols"]
    mask = grid_info["mask"]
    cell_area = grid_info["cell_size"] ** 2
    num_rooms = len(rooms_def)

    # Build room name → index map (1-based)
    name_to_idx = {r["name"]: i + 1 for i, r in enumerate(rooms_def)}

    # Collect cells per room
    room_cells: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for r in range(rows):
        for c in range(cols):
            idx = r * cols + c
            if idx >= len(assignment):
                continue
            code = assignment[idx]
            if mask[r][c] and code > 0:
                room_cells[code].append((r, c))

    # 1. Adjacency score
    adjacency_score = _calc_adjacency(room_cells, rooms_def, name_to_idx)

    # 2. Area error (normalized)
    area_error = _calc_area_error(room_cells, rooms_def, cell_area, grid_info.get("cell_areas"))

    # 3. Compactness
    compactness = _calc_compactness(room_cells, rows, cols)

    return {
        "adjacency_score": adjacency_score,
        "area_error": area_error,
        "compactness": compactness,
    }


def _calc_adjacency(
    room_cells: dict[int, list[tuple]],
    rooms_def: list[dict],
    name_to_idx: dict[str, int],
) -> float:
    """인접 요구 충족 비율. 0~1."""
    total_required = 0
    total_satisfied = 0

    for i, rdef in enumerate(rooms_def):
        room_code = i + 1
        adj_names = rdef.get("adjacency", [])
        if not adj_names:
            continue

        cells_i = set(room_cells.get(room_code, []))
        if not cells_i:
            total_required += len(adj_names)
            continue

        for adj_name in adj_names:
            total_required += 1
            adj_code = name_to_idx.get(adj_name)
            if adj_code is None:
                continue
            cells_j = set(room_cells.get(adj_code, []))
            if not cells_j:
                continue
            # Check if any cell in room_i is neighbor of any cell in room_j
            if _rooms_adjacent(cells_i, cells_j):
                total_satisfied += 1

    if total_required == 0:
        return 1.0
    return total_satisfied / total_required


def _rooms_adjacent(cells_a: set, cells_b: set) -> bool:
    """Two rooms are adjacent if any cell in A is 4-neighbor of any cell in B."""
    for r, c in cells_a:
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            if (r + dr, c + dc) in cells_b:
                return True
    return False


def _calc_area_error(
    room_cells: dict[int, list[tuple]],
    rooms_def: list[dict],
    cell_area: float,
    cell_areas=None,
) -> float:
    """요구 면적 대비 배정 면적 오차. 낮을수록 좋음."""
    total_area_req = sum(r.get("area", 0) for r in rooms_def)
    if total_area_req == 0:
        return 0.0

    total_error = 0.0
    for i, rdef in enumerate(rooms_def):
        room_code = i + 1
        required = rdef.get("area", 0)
        cells = room_cells.get(room_code, [])
        actual = (sum(cell_areas[r][c] for r, c in cells) if cell_areas is not None
                  else len(cells) * cell_area)
        total_error += abs(actual - required)

    return total_error / total_area_req


def _calc_compactness(
    room_cells: dict[int, list[tuple]],
    rows: int,
    cols: int,
) -> float:
    """각 방의 셀 클러스터 뭉침 정도. 0~1."""
    if not room_cells:
        return 0.0

    scores = []
    for code, cells in room_cells.items():
        if not cells:
            continue
        n = len(cells)
        if n <= 1:
            scores.append(1.0)
            continue
        # Count internal edges (4-neighbor pairs)
        cell_set = set(cells)
        internal = 0
        for r, c in cells:
            for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                if (r + dr, c + dc) in cell_set:
                    internal += 1
        # Max internal edges for n cells = ~2*n (for a square block)
        max_internal = 2 * (2 * n - int(math.sqrt(n)) - int(math.sqrt(n)))
        if max_internal <= 0:
            max_internal = 1
        scores.append(min(1.0, internal / max_internal))

    return sum(scores) / len(scores) if scores else 0.0


def assignment_to_geojson(
    assignment: list[int],
    grid_info: dict,
    rooms_def: list[dict],
) -> dict:
    """셀 클러스터 → room별 GeoJSON polygon + 메타데이터."""
    rows, cols = grid_info["rows"], grid_info["cols"]
    mask = grid_info["mask"]
    cell_size = grid_info["cell_size"]
    ox, oy = grid_info["origin"]
    footprint = shape(grid_info["footprint"]) if "footprint" in grid_info else None

    # Collect cell boxes per room
    room_boxes: dict[int, list[Polygon]] = defaultdict(list)
    for r in range(rows):
        for c in range(cols):
            idx = r * cols + c
            if idx >= len(assignment):
                continue
            code = assignment[idx]
            if not mask[r][c] or code <= 0:
                continue
            x0 = ox + c * cell_size
            y0 = oy + r * cell_size
            cell = box(x0, y0, x0 + cell_size, y0 + cell_size)
            if footprint is not None:
                cell = cell.intersection(footprint)
            room_boxes[code].append(cell)

    features = []
    for code, boxes in sorted(room_boxes.items()):
        if not boxes:
            continue
        merged = unary_union(boxes)
        room_idx = code - 1
        name = rooms_def[room_idx]["name"] if room_idx < len(rooms_def) else f"Room {code}"
        color = _ROOM_COLORS[code % len(_ROOM_COLORS)]
        source = rooms_def[room_idx] if room_idx < len(rooms_def) else {}

        features.append({
            "type": "Feature",
            "properties": {
                "room_code": code,
                "room_name": name,
                "color": color,
                "area_m2": merged.area,
                **{key: deepcopy(source[key]) for key in ('space_id', 'area_basis', 'source_refs') if key in source},
            },
            "geometry": mapping(merged),
        })

    return {
        "type": "FeatureCollection",
        "features": features,
    }
