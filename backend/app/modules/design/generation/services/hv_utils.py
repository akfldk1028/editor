"""
Hypervolume Utilities (Phase 2 — Code Review extracted from bayesian_optimization + typology_benchmark)

2D maximization HV — Pareto front 가 ref_point 기준으로 dominate 하는 면적.
"""

import numpy as np


def hypervolume_2obj_max(points: np.ndarray, ref_point: np.ndarray) -> float:
    """2-objective MAXIMIZATION hypervolume.

    Args:
        points: (N, 2) array. 두 obj 모두 maximize.
        ref_point: (2,) — *worst* corner (보통 min - epsilon).

    Returns:
        Pareto front 가 ref 기준 dominate 하는 면적.

    Note:
        Boundary 포함 (`>=`) — Pareto 정확히 ref_point 위에 있는 점도 보존.
    """
    if len(points) == 0:
        return 0.0
    # Code review: `>=` 로 boundary 포함 (Pareto 점 정확히 ref 위에 있을 때)
    mask = (points[:, 0] >= ref_point[0]) & (points[:, 1] >= ref_point[1])
    pts = points[mask]
    if len(pts) == 0:
        return 0.0
    pts = pts[np.argsort(-pts[:, 0])]
    pareto = []
    best_y = -np.inf
    for x, y in pts:
        if y > best_y:
            pareto.append((x, y))
            best_y = y
    pareto = np.asarray(pareto)
    hv = 0.0
    last_y = ref_point[1]
    for x, y in pareto:
        hv += (x - ref_point[0]) * (y - last_y)
        last_y = y
    return float(hv)


__all__ = ["hypervolume_2obj_max"]
