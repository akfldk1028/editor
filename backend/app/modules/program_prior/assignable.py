"""Assignable floor area: what a plate leaves for rooms.

The office sizing basis (국토교통부, 업무시설 적정 공간면적 설계기준) measures
workplace area as total minus core minus *primary circulation*, and every
layout generator here draws axis-aligned rooms, so the chamfered corners of
an outline never become room either.  A program that sums to the gross
plate therefore starves its residual room by exactly those two amounts on
every plan.  Both are properties of the plate, so they are taken off before
sizing rather than discovered after layout.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from shapely.geometry import Polygon, box
from shapely.ops import unary_union
from shapely.prepared import prep

Point = tuple[float, float]

# The spine every generator draws.  건축법 시행령 제48조 asks 1.5 m or more of
# a corridor serving office rooms on one side; the planners use 1.6.
CORRIDOR_WIDTH_M = 1.6


@dataclass(frozen=True)
class AssignableArea:
    gross_m2: float
    # Union of the axis-aligned cells of the outline's own coordinate grid
    # that lie inside it: the plane rooms are actually fitted to.
    cover_m2: float
    # A double-loaded spine across the plate's longer extent.
    corridor_m2: float

    @property
    def assignable_m2(self) -> float:
        return self.cover_m2 - self.corridor_m2

    @property
    def allowance_m2(self) -> float:
        """Gross area the program does not distribute: corner loss plus corridor."""
        return self.gross_m2 - self.assignable_m2


def rectilinear_cover(polygon: Polygon) -> Polygon:
    """The union of axis-aligned grid cells of the polygon's own coordinates inside it."""
    xs = sorted({float(x) for x, _ in polygon.exterior.coords})
    ys = sorted({float(y) for _, y in polygon.exterior.coords})
    prepared = prep(polygon.buffer(1e-9))
    cells = [
        box(x0, y0, x1, y1)
        for x0, x1 in zip(xs, xs[1:])
        for y0, y1 in zip(ys, ys[1:])
        if prepared.covers(box(x0, y0, x1, y1))
    ]
    if not cells:
        return Polygon()
    cover = unary_union(cells)
    if cover.geom_type != "Polygon":
        cover = max(cover.geoms, key=lambda g: g.area)
    return cover


def assignable_area(
    footprint: Iterable[Point],
    *,
    gross_m2: float | None = None,
    bounds: tuple[float, float, float, float] | None = None,
    corridor_width: float = CORRIDOR_WIDTH_M,
) -> AssignableArea:
    """Assignable area of a floor plate.

    Without a footprint (legacy analyses carry only an area and bounds) the
    plate is taken as its bounding rectangle: no corner loss, corridor along
    the longer side.
    """
    points = [tuple(map(float, p)) for p in footprint]
    if len(points) >= 3:
        plate = Polygon(points)
        gross = plate.area if gross_m2 is None else float(gross_m2)
        cover = rectilinear_cover(plate).area
        min_x, min_y, max_x, max_y = plate.bounds
    else:
        if gross_m2 is None or bounds is None:
            raise ValueError("a plate without a footprint needs its area and bounds")
        gross = float(gross_m2)
        cover = gross
        min_x, min_y, max_x, max_y = bounds
    # A plate too small to hold a corridor beside its rooms is not all
    # corridor: the spine takes at most half of what the outline covers.
    corridor = min(corridor_width * max(max_x - min_x, max_y - min_y), cover / 2.0)
    return AssignableArea(gross_m2=gross, cover_m2=cover, corridor_m2=corridor)
