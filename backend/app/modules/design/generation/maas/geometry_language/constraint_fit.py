"""Rank-aware numeric fitting of explicitly editable impose placement dimensions.

Independent damped least-squares implementation. REA establishes complete-QR
linear solves and a scalar line search; this implementation uses finite
differences and accepted backtracking, not vendor code or its golden search.
"""

from dataclasses import dataclass
from math import hypot, sqrt

import numpy as np
from scipy.linalg import lstsq
from shapely.affinity import affine_transform, translate
from shapely.geometry import Point, Polygon


@dataclass(frozen=True)
class ConstraintPose:
    scale: float
    x: float
    y: float
    evidence: dict


def _boundary_points(geometry):
    polygons = list(geometry.geoms) if hasattr(geometry, 'geoms') else [geometry]
    points = []
    for polygon in polygons:
        for ring in [polygon.exterior, *polygon.interiors]:
            coordinates = list(ring.coords)
            for a, b in zip(coordinates, coordinates[1:]):
                points.extend((a, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)))
    return points


def solve_imposed_pose(constraints, *, minimum_scale=.22, max_evaluations=192):
    """Fit actual occupied bands; only XY translation and uniform scale vary.

    The minimum scale retains the previous explicit-impose search floor. It
    is a computational policy, not legal capacity or an architectural norm.
    """
    if not 0 < minimum_scale <= 1 or type(max_evaluations) is not int or max_evaluations < 1:
        raise ValueError('invalid impose constraint budget or scale bounds')
    evidence = {'algorithm': 'rank_aware_impose_constraints.v1', 'accepted': False,
                'minimum_scale': minimum_scale, 'maximum_scale': 1.0,
                'minimum_scale_authority': 'existing_explicit_impose_search_floor',
                'editable': ['translation_x', 'translation_y', 'uniform_xy_scale'],
                'locked': ['facing', 'physical_z', 'authored_internal_geometry'],
                'linear_solver': 'complete_orthogonal_least_squares_gelsy',
                'step_objective': 'minimum_norm_local_least_squares_increment',
                'optimality': 'best_scale_among_bounded_geometric_starts; global_maximum_scale_not_certified',
                'line_search': 'strict_residual_decrease_backtracking',
                'evaluation_count': 0, 'max_evaluations': max_evaluations,
                'iterations': [], 'stop_reason': 'no_constraints'}
    failed = lambda: ConstraintPose(1.0, 0.0, 0.0, evidence)
    if not constraints or any(p.is_empty or h.is_empty or not p.is_valid or not h.is_valid for p, h, _ in constraints):
        return failed()
    unit = max(hypot(p.bounds[2] - p.bounds[0], p.bounds[3] - p.bounds[1]) for p, _h, _ in constraints)
    if unit <= 1e-9:
        return failed()
    hosts = [host.buffer(1e-7) for _polygon, host, _weight in constraints]
    points = [_boundary_points(polygon) for polygon, _host, _weight in constraints]
    interior_hosts = [host.buffer(-1e-6) for _p, host, _w in constraints]
    hole_witnesses = []
    for _polygon, host, _weight in constraints:
        parts = list(host.geoms) if hasattr(host, 'geoms') else [host]
        hole_witnesses.append([Point(point) for part in parts for ring in part.interiors
                               for point in _boundary_points(Polygon(ring))])

    def evaluate(state):
        if evidence['evaluation_count'] >= max_evaluations:
            return None
        evidence['evaluation_count'] += 1
        x, y, factor = float(state[0]) * unit, float(state[1]) * unit, float(state[2])
        residual = []
        contained = True
        outside_area = 0.0
        for index, (polygon, host, _weight) in enumerate(constraints):
            moved = affine_transform(polygon, [factor, 0, 0, factor, x, y])
            contained &= hosts[index].covers(moved)
            outside = float(moved.difference(host).area)
            outside_area += outside
            boundary_host = interior_hosts[index] if not interior_hosts[index].is_empty else host
            residual.extend(Point(px * factor + x, py * factor + y).distance(boundary_host) / unit
                            for px, py in points[index])
            # A hole wholly inside the figure is invisible to vertex distances.
            residual.append(outside / max(unit * sqrt(float(polygon.area)), 1e-12))
            # Constant overlap area has zero derivative while a hole is fully
            # enclosed. Penetration depths supply a real escape direction.
            residual.extend(point.distance(moved.boundary) / unit if moved.contains(point) else 0.0
                            for point in hole_witnesses[index])
        return np.asarray(residual), bool(contained), outside_area

    starts = []
    for polygon, host, _weight in constraints:
        # A global representative point may lie in a large, thin component.
        # Separate legal components must contribute geometric starts too.
        parts = list(host.geoms) if hasattr(host, 'geoms') else []
        centers = [host.centroid, host.representative_point()]
        centers.extend(center for part in parts for center in (part.centroid, part.representative_point()))
        for center in centers:
            state = np.array([(center.x - polygon.centroid.x) / unit,
                              (center.y - polygon.centroid.y) / unit, 1.0])
            if not any(np.linalg.norm(state - other) < 1e-9 for other in starts):
                starts.append(state)
    initial = []
    for state in starts[:8]:
        measured = evaluate(state)
        if measured is None:
            break
        if 'initial_outside_area_m2' not in evidence:
            evidence['initial_outside_area_m2'] = measured[2]
        initial.append((state, measured))
    if not initial:
        return failed()

    def finish(state, measured):
        # Hull-vertex translation domains are necessary conditions only. Every
        # accepted candidate still covers actual occupied bands, including holes.
        state = state.copy()
        upper = 1.0
        intersections = 0
        refinement_steps = 0
        for _ in range(12):
            if upper - state[2] <= 1e-7 or evidence['evaluation_count'] >= max_evaluations:
                break
            factor = (state[2] + upper) / 2
            domain = None
            exhausted = False
            for polygon, host, _weight in constraints:
                for px, py in list(polygon.convex_hull.exterior.coords)[:-1]:
                    if intersections >= 4096:
                        exhausted = True
                        break
                    shifted = translate(host, xoff=-px * factor, yoff=-py * factor)
                    domain = shifted if domain is None else domain.intersection(shifted)
                    intersections += 1
                    if domain.is_empty:
                        break
                if exhausted or domain.is_empty:
                    break
            if exhausted:
                break
            refinement_steps += 1
            improved = False
            if domain is not None and not domain.is_empty:
                parts = [domain, *(list(domain.geoms) if hasattr(domain, 'geoms') else [])]
                centers = [point for part in parts for point in (part.centroid, part.representative_point())]
                for center in centers[:8]:
                    probe = np.array([center.x / unit, center.y / unit, factor])
                    trial = evaluate(probe)
                    if trial is None:
                        break
                    if trial[1]:
                        state, measured, improved = probe, trial, True
                        break
            if not improved:
                upper = factor
        evidence['translation_domain_refinement'] = {'iterations': refinement_steps,
            'host_intersections': intersections, 'max_intersections': 4096,
            'authority': 'necessary_hull_vertex_translation_domains_plus_exact_occupied_band_covers'}
        evidence.update(accepted=True, stop_reason='exact_band_containment',
                        final_outside_area_m2=measured[2], final_residual_norm=float(np.linalg.norm(measured[0])),
                        preserved_plan_area_ratio=float(state[2] ** 2),
                        solution={'uniform_xy_scale': float(state[2]), 'translation_x': float(state[0] * unit),
                                  'translation_y': float(state[1] * unit)})
        return ConstraintPose(float(state[2]), float(state[0] * unit), float(state[1] * unit), evidence)

    initial.sort(key=lambda pair: float(np.linalg.norm(pair[1][0])))
    evidence['geometric_start_count'] = len(initial)
    for state, measured in initial:
        if measured[1]:
            return finish(state, measured)
    best_feasible = None
    best_measure = initial[0][1]
    for start_index, (start_state, start_measure) in enumerate(initial):
        state, measured = start_state.copy(), start_measure
        for editable in ((0, 1), (2,), (0, 1, 2)):
            if 2 in editable and minimum_scale == 1:
                continue
            # A translation-only solve can enter a flat hole-overlap region.
            # Joint scale/translation must retain its independent geometric start.
            state, measured = start_state.copy(), start_measure
            for iteration in range(4 if len(editable) == 2 else 16):
                if evidence['evaluation_count'] + len(editable) + 1 > (max_evaluations - 32 if best_feasible is not None else max_evaluations):
                    evidence['stop_reason'] = 'evaluation_budget'
                    return finish(*best_feasible) if best_feasible is not None else failed()
                residual = measured[0]
                columns = []
                perturbation = min(1e-5, max(1e-8, float(np.linalg.norm(residual)) * .01))
                for dimension in editable:
                    step = -perturbation if dimension == 2 and state[2] + perturbation > 1 else perturbation
                    probe = state.copy()
                    probe[dimension] += step
                    columns.append((evaluate(probe)[0] - residual) / step)
                jacobian = np.column_stack(columns)
                # Truncate numerically unresolved directions before they
                # dominate the trust step with a false null-space motion.
                delta, _sums, rank, _singular = lstsq(jacobian, -residual, cond=1e-5, lapack_driver='gelsy')
                norm = float(np.linalg.norm(delta))
                record = {'phase': 'translation' if len(editable) == 2 else ('scale' if len(editable) == 1 else 'translation_and_scale'),
                          'start_index': start_index, 'iteration': iteration,
                          'rank': int(rank), 'editable_count': len(editable),
                          'difference_step': perturbation,
                          'residual_norm_before': float(np.linalg.norm(residual)), 'accepted': False}
                evidence['iterations'].append(record)
                if not np.all(np.isfinite(delta)) or norm <= 1e-12 or rank == 0:
                    evidence['stop_reason'] = 'stationary_or_rank_zero'
                    break
                delta *= min(1.0, .35 / norm)
                for line_step in range(10):
                    proposal = state.copy()
                    proposal[list(editable)] += delta * (0.5 ** line_step)
                    proposal[2] = min(1.0, max(minimum_scale, proposal[2]))
                    trial = evaluate(proposal)
                    if trial is None:
                        evidence['stop_reason'] = 'evaluation_budget'
                        return finish(*best_feasible) if best_feasible is not None else failed()
                    merit = float(np.linalg.norm(trial[0]))
                    if merit < record['residual_norm_before'] - 1e-12 or trial[1]:
                        record.update(accepted=True, step_fraction=0.5 ** line_step,
                                      residual_norm_after=merit, scale=float(proposal[2]))
                        state, measured = proposal, trial
                        if merit < float(np.linalg.norm(best_measure[0])):
                            best_measure = measured
                        if measured[1]:
                            if best_feasible is None or state[2] > best_feasible[0][2]:
                                best_feasible = (state.copy(), measured)
                        break
                if measured[1]:
                    break
                if not record['accepted']:
                    evidence['stop_reason'] = 'line_search_stalled'
                    break
            else:
                evidence['stop_reason'] = 'iteration_budget'
            if measured[1]:
                break
    if best_feasible is not None:
        return finish(*best_feasible)
    evidence['final_outside_area_m2'] = best_measure[2]
    return failed()
