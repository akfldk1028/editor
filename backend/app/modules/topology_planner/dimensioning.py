"""Room widths along a band from a linear program.

Per room i in a band of fixed depth d:
    min_area_i <= w_i * d <= max_area_i
    w_i >= min_width_i
    d / r_i <= w_i <= r_i * d          (aspect ratio <= r_i, both orientations)
    sum w_i (+ residual) == band length
minimising sum |w_i * d - target_i| through slack variables.  The residual room,
if any, takes whatever length remains and is bounded only by its min_width.
Infeasibility is reported with the offending constraints and is the caller's
problem to solve by changing the band or the program -- never by widening a
gate here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import math

import numpy as np
from scipy.optimize import linprog

from backend.app.modules.topology_planner.slicing import Band
from backend.app.schemas.program import ProgramNode


_EPS = 1e-9


class TopologyInfeasible(ValueError):
    def __init__(self, constraints: Sequence[str]) -> None:
        self.constraints = tuple(constraints)
        super().__init__(
            "band cannot be dimensioned: " + "; ".join(self.constraints)
        )


@dataclass(frozen=True)
class RoomWidth:
    room_id: str
    width: float


def dimension_band(
    band: Band,
    nodes: Sequence[ProgramNode],
    *,
    residual_room_id: str | None,
    fill: bool = False,
) -> tuple[RoomWidth, ...]:
    """``fill`` makes the rooms span the band exactly when there is no residual.

    Used on a flank beside the core that would otherwise leave the primary a
    strip narrower than its minimum: the rooms stretch within their own area
    bands to close it, or the LP reports that they cannot.
    """
    d = band.depth
    fixed = [node for node in nodes if node.node_id != residual_room_id]
    residual = next((node for node in nodes if node.node_id == residual_room_id), None)
    n = len(fixed)
    has_res = residual is not None
    # Variables: w_0..w_{n-1}, s_0..s_{n-1} (|w_i d - t_i| <= s_i), then w_res.
    m = 2 * n + (1 if has_res else 0)

    labels: list[str] = []
    bounds: list[tuple[float, float | None]] = []
    for node in fixed:
        lo, hi = _width_bounds(node, d, labels)
        if hi is not None and lo > hi + _EPS:
            raise TopologyInfeasible(labels or [f"{node.node_id}: contradictory width bounds"])
        bounds.append((lo, hi))
    bounds.extend([(0.0, None)] * n)
    if has_res:
        bounds.append((float(residual.min_width or 0.0), None))

    c = np.zeros(m)
    c[n : 2 * n] = 1.0  # minimise total absolute deviation from target

    a_ub: list[np.ndarray] = []
    b_ub: list[float] = []
    for i, node in enumerate(fixed):
        target = float(node.target_area)
        row = np.zeros(m)
        row[i], row[n + i] = d, -1.0  # w_i d - s_i <= t_i
        a_ub.append(row)
        b_ub.append(target)
        row = np.zeros(m)
        row[i], row[n + i] = -d, -1.0  # -w_i d - s_i <= -t_i
        a_ub.append(row)
        b_ub.append(-target)

    total = np.zeros(m)
    total[:n] = 1.0
    if has_res:
        total[-1] = 1.0
        a_eq, b_eq = np.array([total]), np.array([band.length])
    elif fill:
        a_eq, b_eq = np.array([total]), np.array([band.length])
    else:
        a_ub.append(total)
        b_ub.append(band.length)
        a_eq, b_eq = None, None

    result = linprog(
        c,
        A_ub=np.array(a_ub) if a_ub else None,
        b_ub=np.array(b_ub) if b_ub else None,
        A_eq=a_eq,
        b_eq=b_eq,
        bounds=bounds,
        method="highs",
    )
    if not result.success:
        raise TopologyInfeasible(
            labels
            + [
                f"band length {band.length:.2f} m cannot hold the program: "
                f"{result.message}"
            ]
        )
    widths = [
        RoomWidth(node.node_id, float(round(result.x[i], 6)))
        for i, node in enumerate(fixed)
    ]
    if has_res:
        widths.append(RoomWidth(residual.node_id, float(round(result.x[-1], 6))))
    # Return in the caller's order so band placement follows the program.
    by_id = {item.room_id: item for item in widths}
    return tuple(by_id[node.node_id] for node in nodes)


def _width_bounds(
    node: ProgramNode, d: float, labels: list[str]
) -> tuple[float, float | None]:
    target = float(node.target_area)
    min_area = float(node.min_area) if node.min_area else target * 0.85
    max_area = float(node.max_area) if node.max_area else target * 1.15
    # A hair inside the band, so a width that lands on the bound does not read
    # as outside it after the validator's own rounding.
    lo = max(min_area * (1 + 1e-7) / d, float(node.min_width or 0.0))
    hi: float = max_area * (1 - 1e-7) / d
    r = float(node.max_aspect_ratio) if node.max_aspect_ratio else math.inf
    if math.isfinite(r):
        lo = max(lo, d / r)
        hi = min(hi, r * d)
        if lo > hi + _EPS:
            labels.append(
                f"{node.node_id}: aspect <= {r:g} at depth {d:.2f} m needs width in "
                f"[{d / r:.2f}, {r * d:.2f}] but the area band needs "
                f"[{min_area / d:.2f}, {max_area / d:.2f}]"
            )
    if float(node.min_width or 0.0) > hi + _EPS:
        labels.append(
            f"{node.node_id}: min width {float(node.min_width):.2f} m exceeds "
            f"max width {hi:.2f} m"
        )
    return lo, hi
