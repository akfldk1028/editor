"""The base shape a matrix carries, when a square is not what the plan is.

A 4x4 affine can pose anything, but it can only pose what it was given: with a
unit square as the only primitive the vocabulary can say tower, bar and slab and
nothing else. Qatar National Library is a folded plate, the Kunsthal a wedge,
Kanazawa a circle - those are different base shapes, not different transforms.

So a placement carries a normalized unit plan and the matrix does the rest. The
profiles are the repo's own `PROFILED_PRISM_FAMILIES`, normalized into the unit
square so `scale_matrix4((w, d, h))` means the same thing for every one of them.
Nine shapes already agreed on inside this project beats nine invented here.
"""

from __future__ import annotations

from backend.app.modules.design.generation.maas.geometry_language.base_seeds import PROFILED_PRISM_FAMILIES


UnitPlan = tuple[tuple[float, float], ...]

# The square every other profile is measured against, and the default.
_SQUARE: UnitPlan = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))


def _normalized(ring) -> UnitPlan:
    """Fit a ring into the unit square, keeping its shape.

    Each family is authored at its own size, so scaling by `(w, d, h)` would
    otherwise mean a different footprint per profile and a bar authored as
    `triangular` would come out a different size from the same bar as a box.
    """

    xs = [float(x) for x, _y in ring]
    ys = [float(y) for _x, y in ring]
    span_x = max(max(xs) - min(xs), 1e-9)
    span_y = max(max(ys) - min(ys), 1e-9)
    return tuple(
        ((float(x) - min(xs)) / span_x, (float(y) - min(ys)) / span_y) for x, y in ring
    )


UNIT_PLANS: dict[str, UnitPlan] = {
    "square": _SQUARE,
    **{name: _normalized(ring) for name, ring in PROFILED_PRISM_FAMILIES},
}


def cut_plan(parent: str, *, along_x: bool, low: float, high: float) -> str:
    """The piece of a plan between two stations on one axis, as a plan name.

    `split` used to hand every piece a rectangle, and said why: a piece cut from
    a plan is not a copy of that plan - halve a circular museum and you get two
    half-circles, not two circles - and this vocabulary had no half-circle, so
    the rectangle was the honest piece. The vocabulary can have one. A ring
    clipped and re-normalized is the half-circle, and it costs a name rather
    than a new primitive, because everything downstream reads a plan by name.

    Registered under a name derived from the cut, so the same cut asked for
    twice is the same plan and the table does not grow with the corpus.
    Falls back to the parent when the piece is degenerate or when the parent is
    already a square, where a piece of it is a square and a new name would say
    nothing.
    """

    if parent == "square" or high - low <= 1e-6:
        return parent
    key = f"{parent}|{'x' if along_x else 'y'}|{low:.4f}|{high:.4f}"
    if key in UNIT_PLANS:
        return key
    ring = UNIT_PLANS.get(parent)
    if not ring:
        return parent
    from shapely.geometry import Polygon, box

    try:
        whole = Polygon(ring)
        if not whole.is_valid:
            whole = whole.buffer(0)
        window = box(low, 0.0, high, 1.0) if along_x else box(0.0, low, 1.0, high)
        piece = whole.intersection(window)
    except Exception:
        return parent
    if piece.is_empty or piece.geom_type != "Polygon" or piece.area <= 1e-6:
        return parent
    UNIT_PLANS[key] = _normalized(tuple(piece.exterior.coords)[:-1])
    # What the clip actually took, as a share of the parent's own unit square.
    # The caller needs it because `_normalized` stretches the piece's bounding
    # box back out to [0, 1]^2 - which is what makes every profile scale the
    # same way - and that stretch throws away how much of the parent this piece
    # was. Without the number a half-oval is rebuilt at the size of a whole one.
    _CUT_AREAS[key] = float(piece.area)
    return key


_CUT_AREAS: dict[str, float] = {}


def cut_area(name: str) -> float | None:
    """The unit area a `cut_plan` piece took from its parent, or None."""

    return _CUT_AREAS.get(name)


def plan_fill(name: str) -> float:
    """How much of its own unit square a plan's ring covers."""

    ring = UNIT_PLANS.get(name)
    if not ring or len(ring) < 3:
        return 1.0
    total = 0.0
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + (ring[0],)):
        total += x0 * y1 - x1 * y0
    return max(abs(total) / 2.0, 1e-9)


def unit_plan(name: str) -> UnitPlan:
    """The named plan, or the square - an unknown name is not worth a crash."""

    return UNIT_PLANS.get(str(name).lower(), _SQUARE)


def plan_names() -> tuple[str, ...]:
    return tuple(sorted(UNIT_PLANS))
