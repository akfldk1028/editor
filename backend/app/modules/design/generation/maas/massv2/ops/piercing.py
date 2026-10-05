"""The book's Intersect: a second volume driven through what is standing.

"관통 교차하다 - 두 볼륨을 서로 관통시킴". Both volumes stay solid - this is
not a cut. Puncture takes material away; Intersect adds a body that passes
through and sticks out both sides, which is Kunsthal's ramp, CCTV's sky lobby,
Vitra's stair bar. The corpus has wanted this word for three sessions: the
Kunsthal sentence wrote "경사로가 상자를 관통하며" and the screen flagged 관통
as a claim no verb could carry, so the sentence had to be rewritten to say
less than the building does.

The bar is aimed and sized off the target's own matrix corners - which
volumes, which operator, about what point - and built through `frame.box`,
which is already one matrix composition. A climbing pierce is banded along its
own length with the same `_slab(axis=0)` discipline as `bend`: each segment a
flight, translated up in the bar's own unit space, so the ramp is flats of
real floor rather than a smoothed lie. The stepping is honest: these are the
landings a built ramp has, not an approximation of a plane the language
cannot say.
"""

from __future__ import annotations

from dataclasses import replace
from math import asin, cos, degrees, radians, sin, tan
from typing import Callable

from backend.app.modules.design.generation.maas.geometry_language.affine_matrix import compose_matrix4, scale_matrix4, transform_point3, translation_matrix4, validate_matrix4

from backend.app.modules.design.generation.maas.floor_viability import DEFAULT_MINIMUM_CLEAR_DEPTH_M

from backend.app.modules.design.generation.maas.massv2.form import Placement
from backend.app.modules.design.generation.maas.massv2.ops.swept import _banded, _clamp


def intersect(frame, op) -> None:
    """Drive a bar through the picked volumes, out both sides."""

    picked, rest = frame.pick(op)
    if not picked:
        return

    # The target's own extent, from its corners. World coordinates, because
    # the bar is aimed across several volumes at once and their shared frame
    # is the world; the pose goes back through `frame.box`, which converts.
    #
    # Additive corners only. A subtractive cutter overshoots on purpose - carve
    # writes z=-height so its cut reaches cleanly through the ground face - and
    # measuring it put this bar's base at -12 m: the ramp pierced the basement
    # of a building that has none, and the diff gate read the whole compile
    # shifting by a storey. What a pierce crosses is what is standing.
    solid = [item for item in picked if item.kind == "additive"] or picked
    corners = [corner for item in solid for corner in item.corners()]
    xs = [x for x, _y, _z in corners]
    ys = [y for _x, y, _z in corners]
    zs = [z for _x, _y, z in corners]
    centre_x, centre_y = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    base, crest = min(zs), max(zs)

    turn = _clamp(float(op.params.get("degrees", 25.0)), -60.0, 60.0)
    bearing = radians(frame.rotation + turn)
    along = (cos(bearing), sin(bearing))
    across = (-along[1], along[0])

    def _extent(direction) -> float:
        values = [x * direction[0] + y * direction[1] for x, y in zip(xs, ys)]
        return max(values) - min(values)

    # Long enough to stick out both ends - a pierce that stops inside the mass
    # is an embed, which is a different word in the book.
    length = _extent(along) * 1.15
    width = _clamp(float(op.params.get("size", 0.25)), 0.12, 0.45) * _extent(across)
    thick = max(frame.storey, 0.5)

    # Where it passes, and whether it climbs. `level` is a share of the height
    # left after the bar's own thickness and rise are spent, so 0 grazes the
    # ground and 1 grazes the roof whatever the other two are.
    climb = _clamp(float(op.params.get("climb", 0.0)), 0.0, 1.0)
    rise = climb * max(0.0, (crest - base) - thick)
    level = _clamp(float(op.params.get("level", 0.35)), 0.0, 1.0)
    z_base = base + level * max(0.0, (crest - base) - thick - rise)

    role = str(op.params.get("first") or "pierce")
    dx, dy = frame.local(centre_x, centre_y)
    bar = frame.box(role, w=length, d=width, z=z_base, h=thick,
                    dx=dx, dy=dy, turn=turn)

    # p.19 files Intersect under Displace: the bar is driven THROUGH the mass,
    # so what it occupies inside is the mass's own material and only the ends
    # standing proud are new. massv2 delivered the pierced volumes untouched
    # plus the whole bar, which is an addition - measured, +3.4% on an uncut
    # seed. The hosts now give up what the bar stands outside them, the same
    # accounting `interlock` and `lodge` follow.
    #
    # How much the pierced bodies owe, solved rather than guessed. The bar runs
    # 1.15 of the crossing extent by design, so 0.15 of it sticks out at the
    # ends - but the ends are not all of what is new, because the bar is turned
    # by `degrees` and sweeps a wider channel than its own width. Sweeping the
    # coefficient on the bench's 20x12x8 seed:
    #
    #     0.00 -> +5.97%   0.15 -> +2.93%   0.30 -> -0.04%   0.50 -> -0.04%
    #
    # which conserves at 0.30 and saturates past it against the `max(0.7, ...)`
    # floor below. A Displace word conserves, so 0.30 is the number.
    span_across = _extent(across)
    owed = (0.30 * width) / span_across if span_across > 1e-6 else 0.0
    paid = [replace(item, matrix=compose_matrix4(
        item.matrix, scale_matrix4((max(0.7, 1.0 - owed), 1.0, 1.0))))
        for item in solid]
    untouched = [item for item in picked if item not in solid]

    if rise <= 1e-6:
        made = [bar]
    else:
        # Flights: the bar sliced along its own length, each segment lifted a
        # step further in its own unit space. One flight per storey of rise.
        flights = int(_clamp(round(rise / max(frame.storey, 1.0)) + 1, 2, 6))

        def shape(index: int, t: float):
            return translation_matrix4((0.0, 0.0, rise * (index / (flights - 1)) / thick))

        made = _banded(bar, flights, shape, axis=0)

    frame.placements = rest + untouched + paid + made


def fracture(frame, op) -> None:
    """Cut irregular leaning fissures through the mass - the book's Fracture.

    "불규칙 사선 틈을 절삭". Not a split: a split parts a volume along its own
    axes and the pieces stand plumb. A fracture drives thin subtractive slats
    through at a lean, so the crack wanders as it rises and the shards change
    shape storey by storey - the compiler already cuts a leaning volume at
    storeys, so the machinery was waiting for the word.

    Irregular but deterministic: the fissures alternate their turn and their
    lean by position, the same way `aggregate` drifts its objects - no
    randomness, because a resumable pipeline cannot roll dice.
    """

    picked, rest = frame.pick(op)
    solid = [item for item in picked if item.kind == "additive"]
    if not solid:
        return
    corners = [corner for item in solid for corner in item.corners()]
    xs = [x for x, _y, _z in corners]
    ys = [y for _x, y, _z in corners]
    zs = [z for _x, _y, z in corners]
    centre_x, centre_y = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    height = max(zs) - min(zs)

    count = int(_clamp(float(op.params.get("n", 2)), 1, 4))
    # The crack's width, in shares of the extent along the run. Named `slot`
    # and not `gap` on purpose: `ablation.gap_survived` reads a `gap` param off
    # every operation as a declared separation between bodies, and a fissure's
    # width is not that claim - naming it the same would put every fractured
    # sentence in front of a gate about a promise it never made.
    width = _clamp(float(op.params.get("slot", 0.06)), 0.03, 0.15)
    tilt = _clamp(float(op.params.get("degrees", 16.0)), 6.0, 30.0)
    turn0 = _clamp(float(op.params.get("turn", 12.0)), -45.0, 45.0)

    bearing = radians(frame.rotation)
    along = (cos(bearing), sin(bearing))
    run = max(x * along[0] + y * along[1] for x, y in zip(xs, ys)) - min(
        x * along[0] + y * along[1] for x, y in zip(xs, ys)
    )
    across = (-along[1], along[0])
    breadth = max(x * across[0] + y * across[1] for x, y in zip(xs, ys)) - min(
        x * across[0] + y * across[1] for x, y in zip(xs, ys)
    )

    dx0, dy0 = frame.local(centre_x, centre_y)
    # Fissures wander; they do not converge. The old form alternated the SIGN
    # of the whole angle, so adjacent cracks turned toward each other - +30
    # then -21 is a 51-degree scissor closing inside the body, and the audit's
    # razor shards are the space between its blades. A fracture field is
    # sub-parallel: one base direction, a bounded wobble. The bound is
    # geometric, from constants that already exist - over a slat's own half
    # length, two neighbouring cracks may close by no more than their spacing
    # less one clear room's depth, so a shard between them is never thinner
    # than a room.
    spacing = run / (count + 1.0)
    half_len = 0.8 * breadth
    allowance = max(0.0, spacing - DEFAULT_MINIMUM_CLEAR_DEPTH_M)
    max_wobble = degrees(asin(_clamp(allowance / max(half_len, 1e-6), 0.0, 1.0)))
    made: list[Placement] = []
    for index in range(count):
        # Spread along the run, off-centre on purpose; alternate the wander.
        station = (index + 1.0) / (count + 1.0) - 0.5
        wobble = (9.0 * index) * (1 if index % 2 else -1)
        wobble = max(-max_wobble / 2.0, min(max_wobble / 2.0, wobble))
        turn = turn0 + wobble
        lean = tilt * (1 if index % 2 else -1)
        slat = frame.box(
            f"fissure_{index}",
            w=width * run, d=breadth * 1.6,
            # Overshot on both ends, like carve's cutter, so the cut reaches
            # cleanly through the ground and roof faces.
            z=-height, h=3.0 * max(height, 1.0),
            dx=dx0 + station * run, dy=dy0,
            turn=turn, kind="subtractive", occupiable=False,
        )
        # The lean, as a world-space shear composed AFTER the slat's own
        # matrix: x drifts with z across the slat, about its base. Said in
        # unit space before the scale it was tan(lean) per unit of the slat's
        # HEIGHT over its WIDTH - a 30-degree lean on a 2.4 m slat 36 m tall
        # delivered 2.2 degrees, and the fissures stood plumb. `skew` and
        # `place(lean_degrees)` already do it this way.
        drift = tan(radians(lean))
        origin = transform_point3(slat.matrix, (0.0, 0.0, 0.0))
        tip = transform_point3(slat.matrix, (1.0, 0.0, 0.0))
        ax, ay = tip[0] - origin[0], tip[1] - origin[1]
        norm = (ax * ax + ay * ay) ** 0.5 or 1.0
        ax, ay = ax / norm, ay / norm
        base_z = origin[2]
        # p' = p + drift * (z - base_z) * (ax, ay, 0): rows 0 and 1 carry the
        # z coefficient and its base offset.
        wander = (
            (1.0, 0.0, drift * ax, -drift * ax * base_z),
            (0.0, 1.0, drift * ay, -drift * ay * base_z),
            (0.0, 0.0, 1.0, 0.0),
            (0.0, 0.0, 0.0, 1.0),
        )
        made.append(replace(
            slat, matrix=validate_matrix4(compose_matrix4(slat.matrix, wander))
        ))
    frame.placements = rest + picked + made


PIERCING_VERBS: dict[str, Callable] = {
    "intersect": intersect,
    "fracture": fracture,
}


__all__ = ["PIERCING_VERBS", "fracture", "intersect"]
