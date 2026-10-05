"""The BOOK's aggregation layer: four words massv2 never had.

Pages 50 to 58 of the BOOK are not base operatives. They are the layer where a
word takes an operative and repeats or joins it - `reflect` with expand and
skew on 50 and 51, `pack` with inflate and branch on 51 to 53, `array` with
rotate, taper and pinch on 55 to 57, `join` with pinch and split on 57 and 58 -
and this grammar could say none of them. Thirty-one of the BOOK's thirty-five
words had a massv2 implementation and these four had nothing, which is not a
category of word that cannot be reconciled; it is four words nobody wrote.

Each is the standard operation its own file names, and none of them is exotic:

    array     one transform applied n times, each instance the accumulated image
    reflect   a 4x4 with determinant -1 about a plane - volume preserved,
              handedness reversed
    pack      n solids placed inside a container without overlap
    join      a union of two solids plus the connector between them, so what
              was two components comes back one

They are written here rather than in `relational` because the BOOK keeps them
apart, and because what they take is a whole composition rather than a host and
a guest.
"""

from __future__ import annotations

from typing import Callable

from backend.app.modules.design.generation.maas.geometry_language.affine_matrix import transform_point3

from backend.app.modules.design.generation.maas.massv2.form import Placement
from backend.app.modules.design.generation.maas.massv2.ops.grafting import _GRIP, _region
from backend.app.modules.design.generation.maas.massv2.ops.swept import _clamp


def _bodies(picked: list[Placement]) -> list[Placement]:
    return [item for item in picked if item.kind == "additive"]


def array(frame, op) -> None:
    """One move repeated: the same body n times along one accumulated step.

    BOOK p.55-57, where it pairs with rotate, taper and pinch - the operative
    is what gets repeated, and the repetition is this word. An affine array in
    any package: instance k is the seed under the step transform applied k
    times, so the family reads as one decision rather than n placements.
    """

    picked, rest = frame.pick(op)
    bodies = _bodies(picked)
    if not bodies:
        return
    count = int(_clamp(float(op.params.get("n", 3)), 2, 6))
    step = _clamp(float(op.params.get("step", 1.15)), 1.05, 2.0)
    # Shrinking each copy would be a taper said badly. The step is a
    # displacement along the body's own length, so the run reads as a rhythm.
    made: list[Placement] = []
    for body in bodies:
        for index in range(count):
            reach = index * step
            made.append(_region(
                body, body.role if index == 0 else f"{body.role}_{index}",
                (reach, 0.0, _GRIP), (reach + 1.0, 1.0, 1.0),
            ))
    frame.placements = rest + made


def reflect(frame, op) -> None:
    """The composition mirrored about one of its own planes.

    BOOK p.50-51. A reflection is a 4x4 whose determinant is -1: volume is
    preserved exactly and handedness reverses, which is the whole content of
    the word. Mirroring a symmetric body about its own centre returns the body,
    so the plane is offset by `about` - the mirror stands beside the thing it
    doubles.
    """

    picked, rest = frame.pick(op)
    bodies = _bodies(picked)
    if not bodies:
        return
    # `clear`, not `about`. `about` is a universal parameter on every verb and
    # it names a regulating line - a string, read as one by `affine._pivot` -
    # so reading it as a float here both stole the name and would raise on
    # `reflect about:"spine"`, which is a sentence the grammar allows.
    #
    # 1.0 stands the twin against its original; above that it steps clear, and
    # the gap between them is what `join` then has to bridge. Measured on the
    # comp18 round: with no way to say it, `reflect` always produced an
    # adjacent twin and the `join` after it was reported silent.
    about = _clamp(float(op.params.get("clear", 1.0)), 1.0, 1.6)
    across = str(op.params.get("across") or "long").lower() in (
        "cross", "short", "side")
    made: list[Placement] = []
    for body in bodies:
        made.append(body)
        # The image, on the far side of the plane at `about`. In unit space a
        # reflection about x = a maps [0, 1] to [2a - 1, 2a], which is the twin
        # standing clear of its original by 2(a - 1) of its own dimension.
        low = (0.0, 2.0 * about - 1.0, _GRIP) if across else (2.0 * about - 1.0, 0.0, _GRIP)
        high = (1.0, 2.0 * about, 1.0) if across else (2.0 * about, 1.0, 1.0)
        made.append(_region(body, f"{body.role}_mirror", low, high))
    frame.placements = rest + made


def pack(frame, op) -> None:
    """Smaller solids set inside the body without overlapping each other.

    BOOK p.51-53, where it pairs with inflate and branch. Bin packing rather
    than a deformation: the operation is the arrangement, and what makes it
    legible is that the pieces do not touch. A grid is the deterministic
    packing - anything cleverer would be an optimizer, and this grammar states
    figures rather than searching for them.
    """

    picked, rest = frame.pick(op)
    bodies = _bodies(picked)
    if not bodies:
        return
    count = int(_clamp(float(op.params.get("n", 4)), 2, 9))
    fill = _clamp(float(op.params.get("fill", 0.7)), 0.3, 0.9)
    columns = 2 if count <= 4 else 3
    rows = (count + columns - 1) // columns
    made: list[Placement] = []
    for body in bodies:
        cell_x, cell_y = 1.0 / columns, 1.0 / rows
        piece_x, piece_y = cell_x * fill, cell_y * fill
        gap_x, gap_y = (cell_x - piece_x) / 2.0, (cell_y - piece_y) / 2.0
        for index in range(count):
            column, row = index % columns, index // columns
            low = (column * cell_x + gap_x, row * cell_y + gap_y, _GRIP)
            made.append(_region(
                body, f"{body.role}_packed_{index}",
                low, (low[0] + piece_x, low[1] + piece_y, 1.0),
            ))
    # The container is given over to what it holds: the pieces ARE the mass,
    # and leaving the body standing behind them would deliver a solid block
    # with a pattern drawn on it.
    frame.placements = rest + made


def _unit_x_of(host: Placement, point: tuple[float, float, float]) -> float:
    """Where a world point falls along the host's own x axis, in host units.

    The same reading `_span_along_unit_axis` takes, kept as a coordinate rather
    than a length: the host's matrix carries its bearing, so this is 0 at the
    host's near face and 1 at its far one on any parcel.
    """

    origin = transform_point3(host.matrix, (0.0, 0.0, 0.0))
    tip = transform_point3(host.matrix, (1.0, 0.0, 0.0))
    axis = tuple(a - b for a, b in zip(tip, origin))
    length_sq = sum(value * value for value in axis)
    if length_sq < 1e-12:
        return 0.0
    return sum(a * b for a, b in zip(axis, (
        point[0] - origin[0], point[1] - origin[1], point[2] - origin[2]))) / length_sq


def join(frame, op) -> None:
    """Two bodies and the connector that makes them one.

    BOOK p.57-58, where it pairs with pinch and split - split cuts a body in
    two and this is the word that puts them back in contact without undoing
    the cut. A union with a bridging solid: what was two components comes back
    one, which is what `join_related` does in the BOOK's own executor and what
    every kernel calls a bridge.

    How far the bridge reaches is the gap, and it has to be asked for. Written
    with a fixed reach of one body-length it overran its neighbour and stood
    at x=22.00 on a 20 m plot - the clip took the surplus and the word came
    back having *lost* 19.2 m3. The neighbour's near face is read off its own
    corners in this body's unit space, so the bridge crosses the gap and stops.
    """

    picked, rest = frame.pick(op)
    bodies = _bodies(picked)
    if len(bodies) < 2:
        # Nothing to join. The silence gate reports it rather than this word
        # inventing a second body to bridge to.
        return
    width = _clamp(float(op.params.get("size", 0.25)), 0.1, 0.5)
    share = _clamp(float(op.params.get("height", 0.5)), 0.2, 1.0)
    level = _clamp(float(op.params.get("level", 0.25)), 0.0, 0.6)
    made = list(picked)
    for first, second in zip(bodies, bodies[1:]):
        reach = [_unit_x_of(first, corner) for corner in second.corners()]
        centre = 0.5 - width / 2.0
        beyond = sum(reach) / len(reach) >= 0.5
        # Half the bridge's own width is how far it tucks into each body, the
        # grip every graft here takes so the joint stays one solid in floating
        # point. Bodies that already touch get a collar at the joint rather
        # than a bar thrown past them: there is no gap, and saying so is the
        # honest delivery.
        tuck = width / 2.0
        if beyond:
            near = max(min(reach), 1.0)
            low_x, high_x = 1.0 - tuck, near + tuck
        else:
            near = min(max(reach), 0.0)
            low_x, high_x = near - tuck, tuck
        made.append(_region(
            first, f"{first.role}_bridge",
            (low_x, centre, level),
            (high_x, centre + width, level + share),
        ))
    frame.placements = rest + made


AGGREGATION_VERBS: dict[str, Callable] = {
    "array": array,
    "reflect": reflect,
    "pack": pack,
    "join": join,
}


__all__ = ["AGGREGATION_VERBS"]
