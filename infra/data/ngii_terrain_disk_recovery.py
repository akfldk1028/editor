"""Bounded exact fallback for unresolved TIN queries; no vertex decimation.

A radius-R circumcircle containing q lies within distance 2R of q. Thus
every potentially supported simplex and its empty-circle witnesses occur in
the complete 2R disk. Its Delaunay result has the same radius-R support test
as the full source set. A source read boundary cutting this disk is not proof.
"""
import numpy as np
from scipy.spatial import cKDTree
from ngii_terrain_candidate import supported_tin


def recover_disk_queries(points, queries, read_bounds, *, point_budget=250_000, radius=1000):
    points = np.asarray(points, dtype='float64')
    queries = np.asarray(queries, dtype='float64')
    points = points[np.isfinite(points).all(axis=1)]
    tree = cKDTree(points[:, :2])
    values = np.full(len(queries), np.nan)
    resolved = np.zeros(len(queries), dtype=bool)
    counts = []
    left, bottom, right, top = read_bounds
    halo = 2 * radius
    for index, query in enumerate(queries):
        if not (left <= query[0]-halo and query[0]+halo <= right
                and bottom <= query[1]-halo and query[1]+halo <= top):
            counts.append(None)
            continue
        ids = tree.query_ball_point(query, halo)
        counts.append(len(ids))
        if len(ids) > point_budget:
            continue
        answer, _ = supported_tin(points[ids], query[None, :], radius=radius)
        values[index] = answer[0]
        resolved[index] = True
    return values, resolved, {'method': 'complete-query-disk-2R-v1',
        'pointBudget': point_budget, 'sourceCounts': counts,
        'resolvedCells': int(resolved.sum()), 'budgetLimitedCells': int((~resolved).sum())}
