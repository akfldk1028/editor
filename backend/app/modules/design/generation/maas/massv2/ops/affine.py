"""Verbs that are one matrix applied to volumes that already stand.

Each of these says the same three things - which volumes, which operator, about
what pivot - and `_operate` does the rest. Nothing here computes a width or an
offset by hand, which is the whole point: the bug that lost the corpus its
articulation was one verb rebuilding a volume without adding its own position
back, and there is no place to make that mistake here because no verb rebuilds
anything.
"""

from __future__ import annotations

from dataclasses import replace
from math import cos, radians, sin, tan
from typing import Callable

from backend.app.modules.design.generation.maas.geometry_language.affine_matrix import compose_matrix4, matrix4_for_transform, validate_matrix4

from backend.app.modules.design.generation.maas.massv2.form import Placement


def _bounds(
    items: list[Placement], rotation_degrees: float = 0.0
) -> tuple[float, float, float, float, float, float]:
    """Centre and base in world coordinates; spans in the frame's own axes.

    A `shift` moves a volume by a share of its own dimension, and the spans
    have to be measured on the axes the volume is built on. The world
    axis-aligned box of a posed volume is larger than the volume by the
    cosine of the parcel's bearing on each side - the same inflation
    `execute._bounds_of` was rewritten for - so on Gangnam (35.5 degrees) a
    40 x 10 m bar read 31.4 m across and a quarter-share shift moved it
    7.9 m instead of 2.5. The direction was then turned correctly, which is
    why only the magnitude was wrong and nothing flagged it.
    """

    corners = [corner for item in items for corner in item.corners()]
    xs = [x for x, _y, _z in corners]
    ys = [y for _x, y, _z in corners]
    zs = [z for _x, _y, z in corners]
    cx, cy = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    if abs(rotation_degrees) < 1e-9:
        span_x, span_y = max(xs) - min(xs), max(ys) - min(ys)
    else:
        bearing = radians(-rotation_degrees)
        cos_b, sin_b = cos(bearing), sin(bearing)
        us = [(x - cx) * cos_b - (y - cy) * sin_b for x, y, _z in corners]
        vs = [(x - cx) * sin_b + (y - cy) * cos_b for x, y, _z in corners]
        span_x, span_y = max(us) - min(us), max(vs) - min(vs)
    return (cx, cy, min(zs), span_x, span_y, max(zs) - min(zs))


def _operate(
    items: list[Placement],
    operator: str,
    params: dict,
    pivot: tuple[float, float, float],
    rotation_degrees: float = 0.0,
) -> list[Placement]:
    """Compose an operator onto each volume's own matrix, about a shared pivot.

    The pivot is what makes this correct without any bookkeeping. A volume's
    matrix already carries where it stands, so composing about a point in world
    coordinates turns it in place; composing about the origin would swing it
    across the site, which is the class of mistake this module exists to remove.

    And the operator is conjugated into the frame's axes. `matrix4_for_transform`
    builds its scales and shears on the world's x and y, and every volume here
    is posed at the parcel's bearing - so a directional scale applied raw turns
    a rotated bar into a parallelogram, and a "toward the long axis" translate
    slides along world east instead. Measured on `oma_de_rotterdam`: a shift
    meant to run a tower along its row moved it across the row and closed a
    3.04 m gap to 0.00. R(θ) · M · R(-θ) about the same pivot makes the matrix
    mean what the sentence said, at any bearing. Rotations about z commute with
    R and pass through unchanged.
    """

    matrix = matrix4_for_transform(operator, {**params, "pivot": pivot})
    if abs(rotation_degrees) > 1e-9 and operator in ("scale", "shear", "translate"):
        if operator == "translate":
            # A vector, not a frame field: rotate it once instead of
            # conjugating the whole matrix.
            bearing = radians(rotation_degrees)
            cos_b, sin_b = cos(bearing), sin(bearing)
            x, y, z = params["vector"]
            matrix = matrix4_for_transform(
                operator,
                {**params, "vector": (x * cos_b - y * sin_b,
                                      x * sin_b + y * cos_b, z),
                 "pivot": pivot},
            )
        else:
            unturn = matrix4_for_transform(
                "rotate", {"axis": "z", "angle_degrees": -rotation_degrees,
                           "pivot": pivot},
            )
            turn = matrix4_for_transform(
                "rotate", {"axis": "z", "angle_degrees": rotation_degrees,
                           "pivot": pivot},
            )
            matrix = compose_matrix4(unturn, matrix, turn)
    turned = []
    for item in items:
        fields = {"matrix": validate_matrix4(compose_matrix4(item.matrix, matrix))}
        if operator == "rotate":
            # The section rides with the body. `ridge_along`, `drop_toward`
            # and `profile_across` are WORLD unit vectors, and a rotate that
            # replaced the matrix alone left them pointing where the volume
            # used to face: `extrude; gable; rotate 30` rendered its ridge
            # 30 degrees diagonal across the turned plan.
            angle = radians(float(params.get("angle_degrees") or 0.0))
            cos_a, sin_a = cos(angle), sin(angle)
            for name in ("ridge_along", "drop_toward", "profile_across"):
                vector = getattr(item, name)
                if vector is not None:
                    fields[name] = (vector[0] * cos_a - vector[1] * sin_a,
                                    vector[0] * sin_a + vector[1] * cos_a)
        turned.append(replace(item, **fields))
    return turned


def _verb(operator: str, build: Callable[[dict, tuple], dict]) -> Callable:
    """Turn an operator and a parameter reading into a verb the executor calls."""

    def run(frame, op) -> None:
        picked = [
            item for item in frame.placements
            if not str(op.params.get("on") or "").strip()
            or item.role.startswith(str(op.params["on"]).strip())
        ]
        if not picked:
            return
        rest = [item for item in frame.placements if item not in picked]
        cx, cy, base, span_x, span_y, span_z = _bounds(picked, frame.rotation)
        # `about:` names a regulating element the composition is already
        # holding - the line a `split` cut, the centre a `loop` made - and two
        # operations sharing one is the whole of what makes their volumes read
        # as related rather than as neighbours. Unnamed, the pivot is what it
        # has always been: the centre of what this operation picked.
        named = str(op.params.get("about") or "").strip()
        held = frame.centres.get(named)
        if held is not None:
            cx, cy = held.point
        else:
            line = frame.lines.get(named)
            if line is not None:
                cx, cy = line.origin
        params = build(dict(op.params), (span_x, span_y, span_z))
        frame.placements = rest + _operate(
            picked, operator, params, (cx, cy, base), frame.rotation
        )

    return run


def _clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


# How far a volume may be moved by a `shift` or an `offset`, as a share of its
# own dimension. Below the floor a move reads as a setting-out error rather than
# a decision, which is the corpus reading the offsets in `grammar` already carry.
_MIN_MOVE, _MAX_MOVE = 0.15, 0.5
# How much a volume may grow or shrink in plan. A building that doubles is a
# different building; a building that changes by a fifth has been adjusted.
_MIN_SIZE, _MAX_SIZE = 0.6, 1.6


def _axis_scale(params: dict, ratio: float) -> tuple[float, float, float]:
    """A scale vector that acts on the named axis only, or on both if unnamed."""

    named = str(params.get("toward") or "").strip().lower()
    if named in ("cross", "short", "side"):
        return (1.0, ratio, 1.0)
    if named in ("long", "back", "away", "off_open"):
        return (ratio, 1.0, 1.0)
    return (ratio, ratio, 1.0)


def _toward(params: dict) -> tuple[float, float]:
    name = str(params.get("toward") or "long").lower()
    if name in ("cross", "short", "side"):
        return (0.0, 1.0)
    if name in ("back", "away", "off_open"):
        return (-1.0, 0.0)
    return (1.0, 0.0)


AFFINE_VERBS: dict[str, Callable] = {
    # Move it. The book keeps `shift` and `offset` apart by what they are for -
    # a shift displaces a volume against its neighbours, an offset steps a whole
    # outline out - but both are one translation, and the difference is which
    # volumes the sentence aims at.
    # Into the ground. The parcel's ground is z = 0 and every opener was
    # born on it; a sunken court, a half-buried bar, a plinth cut into the
    # slope were unsayable - and nineteen of forty competition winners make
    # their parti there. `depth` is a share of the picked set's own height,
    # like every other move here. The compiler reads the lowest base as the
    # datum's depth, 용적률 leaves the buried floors out, 건축면적 counts only
    # what stands above ground, and the drawing opens a pit.
    "sink": _verb("translate", lambda p, span: {
        "vector": (0.0, 0.0, -_clamp(float(p.get("depth", 0.3)), 0.1, 0.6) * span[2]),
    }),
    "shift": _verb("translate", lambda p, span: {
        "vector": tuple(
            axis * _clamp(float(p.get("ratio", 0.25)), _MIN_MOVE, _MAX_MOVE)
            * (span[0] if abs(_toward(p)[0]) >= abs(_toward(p)[1]) else span[1])
            for axis in (*_toward(p), 0.0)
        ),
    }),
    # `offset` is not here any more. The BOOK reads it on p.12 as add on
    # multiple volumes - duplicate and translate a RELATED volume - and
    # `book_lowering_contract.py` names `translate` among its FORBIDDEN
    # operators, a page-reviewed statement that lowering offset to a plain move
    # is wrong. It was written here as the same expression as `shift` with a
    # different default, so the body moved and nothing was made. It now stands
    # beside `overlap` in `ops.relational`, where a twin is what it delivers.
    # Turn it. Progressive across a stack would need the stack's own order, so
    # that stays in the executor; this is the plain turn.
    "rotate": _verb("rotate", lambda p, span: {
        "axis": "z",
        "angle_degrees": _clamp(float(p.get("degrees", 20.0)), -45.0, 45.0),
    }),
    # Tilt it off vertical. A shear slides, a skew leans, and only the second
    # changes what the plan is at each storey - which is why the compiler cuts
    # a leaning volume at storeys and a shifted one at its own top and bottom.
    "skew": _verb("shear", lambda p, span: {
        "axis": "y" if str(p.get("toward", "long")).lower() in ("cross", "short", "side") else "x",
        "direction": "z",
        # The shear matrix takes the tangent of the lean, so this is the lean
        # itself. It used to be `degrees / 30`, under a comment claiming the
        # parameter "reads as the degrees an architect would say" - it did not:
        # Kunsthal wrote 24 and leaned 38.7, the Educatorium wrote 22 and
        # leaned 36.3. Both sentences are re-authored at the angle they were
        # already building, so the delivered masses do not move.
        "amount": tan(radians(_clamp(float(p.get("degrees", 20.0)), -45.0, 45.0))),
    }),
    # Grow or shrink it in plan. `expand` and `compress` are the book's pair and
    # they are one scale with the ratio either side of one; `inflate` is the
    # same move read as swelling rather than as pushing a boundary out.
    # Directional, because the buildings are. 8 House is pinched across its
    # waist and not around it: an isotropic squeeze makes a smaller block, and
    # what makes the bow-tie is that one dimension closes while the other does
    # not. Naming no direction squeezes both, which is the old behaviour.
    "expand": _verb("scale", lambda p, span: {
        "vector": _axis_scale(p, _clamp(float(p.get("ratio", 1.25)), 1.0, _MAX_SIZE)),
    }),
    "compress": _verb("scale", lambda p, span: {
        "vector": _axis_scale(p, _clamp(float(p.get("ratio", 0.8)), _MIN_SIZE, 1.0)),
    }),
    "inflate": _verb("scale", lambda p, span: {
        "vector": (_clamp(float(p.get("ratio", 1.2)), 1.0, _MAX_SIZE),
                   _clamp(float(p.get("ratio", 1.2)), 1.0, _MAX_SIZE),
                   _clamp(float(p.get("ratio", 1.2)), 1.0, _MAX_SIZE)),
    }),
    # `reflect` is not here, and measuring is what said so: mirroring a
    # rectangle about its own centre is the identity, and it reported a change
    # of exactly 0.000. The book files it under aggregation, not operation, and
    # the book is right - a reflect places a mirrored COPY beside the original,
    # which is a placement rule and belongs with array, join and pack.
}


__all__ = ["AFFINE_VERBS"]
