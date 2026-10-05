"""Verbs whose transform varies with height: a matrix per storey band.

A single 4x4 is linear, so a taper, a twist or a stair cannot be one matrix -
but each *band* of one can. The old implementations knew that and built the
bands by hand: read the volume's bounds, compute a width, a centre and an
offset, and ask the frame for new boxes. Every coordinate bug this package has
had came out of exactly that arithmetic - `_bounds_of` measured on world axes,
`_taper` and `_twist` handing world corners to `stack` after the axes changed,
`_grade` rebuilding from an axis-aligned box and inflating with the parcel's
bearing, `_shear` forgetting to add a volume's own position back and
teleporting it to the frame centre.

None of that arithmetic exists here. A band is derived from the volume's own
matrix in unit space - slice the unit cube, then let the matrix it already
carries put the slice where the volume already is:

    band_i  =  slab(i, n) . item.matrix

and the shaping transform is composed either in unit space (scales, which then
act along the volume's own axes whatever the parcel's bearing - rotation
invariance by construction) or in world space about a pivot taken from the
volume's own matrix (rotations, which must preserve angles and therefore
cannot be composed in a normalized space).

Which volumes, which operator, about what point. Same contract as `affine`.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Callable

from shapely import affinity

from backend.app.modules.design.generation.maas.floor_viability import DEFAULT_MINIMUM_CLEAR_DEPTH_M
from backend.app.modules.design.generation.maas.source_geometry.ir import MAX_CREASED_PROFILE_POINTS
from backend.app.modules.design.generation.maas.geometry_language.affine_matrix import Matrix4, compose_matrix4, rotation_matrix4, scale_matrix4, shear_matrix4, transform_point3, translation_matrix4, validate_matrix4

from backend.app.modules.design.generation.maas.massv2.form import MAXIMUM_ROOF_SHARE, Placement


def _clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


# How many times a top may fold and still be drawn as folds. A fold profile
# takes 2n+1 points and the renderer reads anything past the crease limit as a
# sampled curve, so a fourth fold would be drawn as a barrel vault.
_MAX_FOLD_PEAKS = max(1, (MAX_CREASED_PROFILE_POINTS - 1) // 2)

# A roof is a storey or two, never the building. One owner: this number was
# hand-copied into five verbs, and a cap applied in five places is a cap
# applied in one of them.
ROOF_CAP_STOREYS = 1.5


def _roof_share(drop_m: float, body_m: float, storey_m: float) -> float:
    """An authored drop as a share of its body, with the cap kept in charge.

    The old form - clamp(min(drop, cap_m)/body, 0.15, 0.95) - applied the cap
    in METRES and then a floor in SHARE, and the floor ran last. On any body
    wider than cap/0.15 (34 m at a 3.4 m storey) the floor silently overrode
    the cap: an authored 5.1 m fold arrived 6.88 m deep, +35%, and the whole
    audited family of bodiless sails follows from it. The floor's purpose -
    a roof too shallow to read is not worth drawing - survives, but it may
    never exceed what the cap allows.
    """

    body = max(body_m, 1e-6)
    cap_m = ROOF_CAP_STOREYS * storey_m
    floor = min(0.15, cap_m / body)
    return _clamp(min(drop_m, cap_m) / body, floor, MAXIMUM_ROOF_SHARE)


def _slab(index: int, count: int, axis: int = 2) -> Matrix4:
    """The i-th of n equal bands of the unit cube along one axis, in unit space.

    Axis 2 slices by height, which is what a taper or a twist wants. Axis 0
    slices by length, which is what the book's Bend and Pinch want - both act
    along a bar, not up it. Same discipline either way: the band is a piece of
    the unit cube and the volume's own matrix puts it where the volume already
    is, so nothing here knows or cares which way the parcel faces.
    """

    scale = [1.0, 1.0, 1.0]
    scale[axis] = 1.0 / count
    offset = [0.0, 0.0, 0.0]
    offset[axis] = index / count
    return compose_matrix4(
        scale_matrix4(tuple(scale)),
        translation_matrix4(tuple(offset)),
    )


def _about_unit(pivot: tuple[float, float, float], operator: Matrix4) -> Matrix4:
    """An operator applied about a unit-space point."""

    return compose_matrix4(
        translation_matrix4((-pivot[0], -pivot[1], -pivot[2])),
        operator,
        translation_matrix4(pivot),
    )


def _banded(
    item: Placement,
    count: int,
    shape: Callable[[int, float], Matrix4 | None],
    axis: int = 2,
) -> list[Placement]:
    """Slice one volume into bands and shape each with its own matrix.

    `shape` receives the band index and its midpoint as a 0..1 share of the
    volume's height, and returns a unit-space matrix - or None to end the
    series, which is how a stair stops when the building runs out of plan.
    """

    made: list[Placement] = []
    for index in range(count):
        t = (index + 0.5) / count
        shaping = shape(index, t)
        if shaping is None:
            break
        matrix = compose_matrix4(_slab(index, count, axis), shaping, item.matrix)
        banded = replace(item, matrix=validate_matrix4(matrix))
        # A section belongs to the TOP slice alone. `replace` copied the
        # gable onto every band, so a cantilevered house grew a ridge at
        # every storey - the compiler then emitted a body+roof pair per band
        # and the sub-storey fragments behind the audit's zero-floor piles.
        # The top slice keeps the roof, re-read in its own terms the way the
        # relational splitter already does; the slices under it are storeys.
        if axis == 2 and count > 1 and index < count - 1:
            banded = replace(
                banded, top_drop=0.0, drop_toward=None,
                ridge_along=None, top_profile=None, profile_across=None,
            )
        elif axis == 2 and count > 1 and index == count - 1:
            drop = float(banded.top_drop or 0.0)
            if drop > 0.0:
                kept = 1.0 / count
                profile = banded.top_profile
                if profile is not None:
                    window = 1.0 - kept
                    profile = tuple(
                        (u, min(1.0, max(0.0, (h - window) / kept)))
                        for u, h in profile
                    )
                banded = replace(
                    banded,
                    top_drop=min(1.0, drop / kept),
                    top_profile=profile,
                )
        made.append(banded)
    return made


def _storeys(item: Placement, storey_m: float, low: int, high: int) -> int:
    """How many bands to cut this piece into, none of them under a storey.

    The floor used to be taken literally: `taper` asked for at least two bands
    and `twist` for at least three, so a one-storey object was cut in half or
    in thirds whatever its height. On the 의정부 sheet that is where the trays
    came from - nishizawa_nishinoyama is an aggregate of one-storey houses and
    a taper turned it into 52 volumes, 31 of them between 0.50 and 0.90 m, and
    the drawing reads as a stack of paper rather than the ten low houses its
    sentence describes. `plausibility` did not catch it because
    `viable_band_share` asks whether a band's *plan* is wide enough to be a
    room and never whether it is tall enough to be one.

    A band under a storey is not a floor of anything, so the request is capped
    by how many whole storeys the piece actually holds. A short piece comes
    back as one band, which means the verb has nothing to say about it - and
    the silence gate is the right place for that to surface, not the renderer.
    """

    z0, z1 = item.z_span()
    deep = z1 - z0
    fits = max(1, int(deep / max(storey_m, 1e-6)))
    return int(_clamp(round(deep / max(storey_m, 1.0)), min(low, fits), min(high, fits)))


def _span_along_unit_axis(item: Placement, axis: int) -> float:
    """The volume's own width along one of its own axes, in metres.

    Read off the matrix, not off a bounding box: the length of the image of a
    unit step along that axis. This is what makes every threshold here mean
    the same thing at any bearing.
    """

    origin = transform_point3(item.matrix, (0.0, 0.0, 0.0))
    step = [0.0, 0.0, 0.0]
    step[axis] = 1.0
    tip = transform_point3(item.matrix, tuple(step))
    return sum((a - b) ** 2 for a, b in zip(tip, origin)) ** 0.5


def _primaries(picked: list[Placement]) -> list[Placement]:
    """The volumes a verb is really aimed at, without their attachments.

    A verb's derived bodies carry the scope's role as a prefix - a lift's legs
    are `plate_support`, a gable's bays are `bar_bay0` - and they are not
    tiers of the thing they belong to. `shear` records what counts them as
    such: Maison Bordeaux's four legs took stair indices 0-3, each slid a
    different amount, and the plate slid off all of them. 3 of 22 occupiable
    fell to 0 of 18 the day the legs learned to follow.
    """

    return [
        item for item in picked
        if not any(
            other is not item and item.role.startswith(other.role + "_")
            for other in picked
        )
    ]


# How close a volume's base must sit to another's top to be standing on it.
_BEARING_CONTACT_M = 0.3


def _plan_box(item: Placement) -> tuple[float, float, float, float]:
    xs = [x for x, _y, _z in item.corners()]
    ys = [y for _x, y, _z in item.corners()]
    return min(xs), min(ys), max(xs), max(ys)


def _box_area(a) -> float:
    return max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])


def _plan_overlap_m2(a, b) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) \
        * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def _carrying_nothing(frame, op, picked, rest):
    """A roof goes on the volume nothing stands on.

    An unscoped section verb reached every additive placement, so on a
    `stack` each tier became its own full-height gable, vault or fold - and
    the tier above went on resting on the ridge line. The contact tests
    (`structure._touching`, `bands_of`) read footprints, never the section,
    so the pile passed as grounded while the sheet showed a box floating over
    a roof (sweepx_0465 stack+gable, sweep03_0053 stack+fold, sweep03_0176
    stack+vault). A verb aimed with `on:` still gets exactly what it named;
    left unscoped, it keeps only the volumes that carry nothing - the roofs.
    """

    if str(op.params.get("on") or "").strip():
        return picked, rest
    from backend.app.modules.design.generation.maas.massv2.compile import _plan
    standing = [item for item in (*picked, *rest) if item.kind == "additive"]
    # True plans, not world axis-aligned boxes: on a bearing of 35 degrees a
    # box inflates ~40% and two diagonal neighbours at different levels
    # would register as carried and lose their roof.
    plans = {id(item): _plan(item) for item in standing}
    free, covered = [], []
    for item in picked:
        if item.kind != "additive":
            free.append(item)
            continue
        top = item.z_span()[1]
        mine = plans[id(item)]
        carried = any(
            other is not item
            and abs(other.z_span()[0] - top) < _BEARING_CONTACT_M
            and mine.intersection(plans[id(other)]).area
            > min(1.0, 0.5 * min(mine.area, plans[id(other)].area))
            for other in standing
        )
        (covered if carried else free).append(item)
    return free, rest + covered


def _section_turned(item: Placement, angle_degrees: float) -> Placement:
    """A volume's section vectors, turned with the body.

    `ridge_along`, `drop_toward` and `profile_across` are world unit
    vectors; a band rotated by twist or bend has to carry its ridge round
    with it or the roof keeps facing the way the body used to.
    """

    if abs(angle_degrees) < 1e-9:
        return item
    angle = math.radians(angle_degrees)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    fields = {}
    for name in ("ridge_along", "drop_toward", "profile_across"):
        vector = getattr(item, name)
        if vector is not None:
            fields[name] = (vector[0] * cos_a - vector[1] * sin_a,
                            vector[0] * sin_a + vector[1] * cos_a)
    return replace(item, **fields) if fields else item


def _unit_axis_toward(item: Placement, ux: float, uy: float) -> int:
    """Which of the volume's own plan axes a world direction runs along.

    `axis = 0 if abs(ux) >= abs(uy) else 1` compared a WORLD direction against
    world x and y and then indexed the volume's UNIT axes with the answer -
    right only when the volume happens to be posed square to north. For
    street bearings between 45 and 135 degrees `shear toward: long` read the
    short axis (a 40 x 10 m bar slid 3 m instead of 12) and the gap guard
    measured the wrong width. The volume's own axes are in its matrix.
    """

    origin = transform_point3(item.matrix, (0.0, 0.0, 0.0))
    ex = transform_point3(item.matrix, (1.0, 0.0, 0.0))
    ey = transform_point3(item.matrix, (0.0, 1.0, 0.0))
    dx = (ex[0] - origin[0], ex[1] - origin[1])
    dy = (ey[0] - origin[0], ey[1] - origin[1])
    lx = (dx[0] ** 2 + dx[1] ** 2) ** 0.5 or 1e-9
    ly = (dy[0] ** 2 + dy[1] ** 2) ** 0.5 or 1e-9
    along_x = abs(dx[0] * ux + dx[1] * uy) / lx
    along_y = abs(dy[0] * ux + dy[1] * uy) / ly
    return 0 if along_x >= along_y else 1


def _along_is_x(params: dict) -> bool:
    named = str(params.get("toward") or params.get("along") or "long").lower()
    return named not in ("cross", "short", "side")


def taper(frame, op) -> None:
    """Draw the plan in as it rises, about each volume's own centre.

    The taper runs over the picked set as a whole - each volume takes the part
    of the ramp its own z-range spans, so a tall object narrows more than a
    short one beside it and both belong to one silhouette.
    """

    ratio = _clamp(float(op.params.get("ratio", 0.7)), 0.3, 0.95)
    picked, rest = frame.pick(op)
    if not picked:
        return
    base = min(item.z_span()[0] for item in picked)
    crest = max(item.z_span()[1] for item in picked)
    span = max(crest - base, 1e-6)

    made: list[Placement] = []
    for item in picked:
        z0, z1 = item.z_span()
        # No guard against a one-band volume here, on purpose: the ramp runs
        # over the picked SET, so a one-storey band of a twisted tower takes
        # the ramp at its own station and the tower still tapers - a guard
        # tried on 09-02 silenced `taper` on the spiral, Glasir and Teshima.
        count = _storeys(item, frame.storey, 2, 8)

        def shape(index: int, t: float, z0=z0, z1=z1, count=count) -> Matrix4:
            z = z0 + (z1 - z0) * t
            scale = 1.0 + (ratio - 1.0) * _clamp((z - base) / span, 0.0, 1.0)
            return _about_unit(
                (0.5, 0.5, 0.0), scale_matrix4((scale, scale, 1.0))
            )

        made.extend(_banded(item, count, shape))
    frame.placements = rest + made


def twist(frame, op) -> None:
    """Turn the plan progressively as it rises, about each volume's own axis.

    The turn is composed in world space, because rotation is the one transform
    a normalized space would distort - a turn in unit coordinates of a bar is
    a smear. The pivot is the volume's own plan centre, read off its matrix.
    """

    turn = _clamp(float(op.params.get("degrees", 30.0)), 5.0, 90.0)
    picked, rest = frame.pick(op)
    if not picked:
        return

    made: list[Placement] = []
    for item in picked:
        # A turn is only smooth at the resolution it is cut. Capped at ten
        # bands, a forty-metre tower turned in five-metre slabs and read as a
        # pile of blocks rather than a twist - the cap, not the verb, was the
        # blunt thing. One band per storey is the finest cut the storey gate
        # will still call occupiable.
        count = _storeys(item, frame.storey, 3, 24)
        if count < 2:
            # One band is not a twist. `_storeys` caps the request by the whole
            # storeys the piece holds, so a volume under two storeys comes back
            # as a single band - and turning a single band about its own centre
            # is `rotate`, uniformly, by half the angle asked for. Two blind
            # judges caught `big_the_twist` declaring ninety degrees and
            # delivering a placement bearing of exactly 제1종, and the ablation
            # check passed it because `changed_share` reads 0.33: something was
            # done, just not the thing the word names.
            #
            # So it says nothing rather than saying a different word, and the
            # silence gate reports it. Same rule `cantilever` follows for a body
            # too short to fly, and `align` for a volume standing askew.
            made.append(item)
            continue
        pivot = transform_point3(item.matrix, (0.5, 0.5, 0.0))

        def shape(index: int, t: float) -> Matrix4:
            return compose_matrix4()  # identity; the turn is world-side below

        for index, band in enumerate(_banded(item, count, shape)):
            angle = turn * ((index + 0.5) / count)
            world = compose_matrix4(
                translation_matrix4((-pivot[0], -pivot[1], 0.0)),
                rotation_matrix4((0.0, 0.0, angle)),
                translation_matrix4((pivot[0], pivot[1], 0.0)),
            )
            made.append(_section_turned(replace(
                band, matrix=validate_matrix4(compose_matrix4(band.matrix, world))
            ), angle))
    frame.placements = rest + made


# An oblique cutter needs no tuck. A graft grips what it grows from because two
# solids sharing a face exactly merge in mathematics and split in floating
# point; this plane is vertical only at the single height where it meets the
# face and crosses the interior everywhere above it, so there is no coincident
# face to defend against. Tucking anyway cost a flat 1% - 19.2 m3 of a 1,920 m3
# body at every angle, the grip times the whole flank - on top of the wedge the
# angle actually asks for.
_CUT_GRIP = 0.0


def shear(frame, op) -> None:
    """One oblique plane through the volume - the BOOK's Shear, p.32.

    Recorded there as Subtract on a Single Volume with one variation
    parameter, `angle`, and that is the whole of it: a half-space whose
    boundary makes an angle with the vertical, differenced from the body. It is
    not `grade`, which is a monotone staircase cut into a face (p.29), and it
    is not `taper`, which scales the two axes normal to a third (p.33). It is
    one cut with one plane, and what it leaves is a battered flank.

    The affine shear of the same name lives in this grammar as `skew`, where
    Barr (1984) and every package put it. Volume is preserved there and spent
    here, which is exactly the difference the two senses of the word carry.

    The cutter is a slab standing outside one face, sheared so it enters
    nothing at the bottom and has eaten `tan(angle) x height` of the length by
    the top. Written in the host's own unit space, so the plane is oblique to
    the building rather than to the parcel, on any bearing.
    """

    picked, rest = frame.pick(op)
    hosts = [item for item in picked if item.kind == "additive"]
    if not hosts:
        return
    # One parameter, as p.32 records it. `degrees` was accepted as an alias for
    # a moment and taken straight back out: `skew` next door is the affine
    # shear and its parameter IS `degrees`, so two words a page apart would
    # have read the same key to mean two different geometries.
    angle = _clamp(float(op.params.get("angle", 20.0)), 5.0, 45.0)
    across = str(op.params.get("toward") or "long").lower() in (
        "cross", "short", "side")
    # Which face the plane leans away from. The default takes the far one, so
    # `shear` on a bar reads as a raking end rather than as a lean into the
    # street.
    near = str(op.params.get("side") or "far").lower() in ("near", "front", "first")
    made = list(picked)
    for host in hosts:
        axis = 1 if across else 0
        length = _span_along_unit_axis(host, axis)
        rise = _span_along_unit_axis(host, 2)
        if length <= 1e-6 or rise <= 1e-6:
            continue
        # In the host's own unit terms: how much of its length the plane has
        # taken by the time it reaches the top.
        reach = _clamp(math.tan(math.radians(angle)) * rise / length, 0.02, 0.9)
        lean = shear_matrix4("y" if across else "x", "z",
                             reach if near else -reach)
        if near:
            low = (-1.0, 0.0, 0.0) if not across else (0.0, -1.0, 0.0)
            high = (_CUT_GRIP, 1.0, 1.0) if not across else (1.0, _CUT_GRIP, 1.0)
        else:
            low = (1.0 - _CUT_GRIP, 0.0, 0.0) if not across else (0.0, 1.0 - _CUT_GRIP, 0.0)
            high = (2.0, 1.0, 1.0) if not across else (1.0, 2.0, 1.0)
        size = tuple(max(1e-6, b - a) for a, b in zip(low, high))
        matrix = compose_matrix4(
            scale_matrix4(size), translation_matrix4(low), lean, host.matrix)
        made.append(replace(
            host, role=f"{host.role}_shear", kind="subtractive", occupiable=False,
            plan="square", matrix=validate_matrix4(matrix),
            top_surface=None, bottom_surface=None, plan_region=None,
            top_drop=0.0, drop_toward=None, ridge_along=None,
            top_profile=None, profile_across=None, warp=None,
        ))
    frame.placements = rest + made


def grade(frame, op) -> None:
    """Cut it back a step at a time, holding one face still.

    The scale is composed in unit space, so it acts along the volume's own
    axis whatever the parcel's bearing - the fault the old implementation had
    to be taught out of twice, once for the stride and once for the bbox. The
    stair simply stops where the building runs out of room: a terrace narrower
    than a room is not a terrace.
    """

    run = _clamp(float(op.params.get("run", 0.6)), 0.2, 0.9)
    # `walk: true` - the slope is public ground, the roof as landscape.
    walk = bool(op.params.get("walk"))
    picked, rest = _carrying_nothing(frame, op, *frame.pick(op))
    if not picked:
        return
    along_x = _along_is_x(op.params)
    axis = 0 if along_x else 1

    # `smooth: true` keeps the volume whole and tilts its top instead of
    # cutting steps. This is the word CopenHill's sentence needed from the
    # start - "지붕이 정상에서 지면까지 끊기지 않고 내려온다" - and a staircase
    # could only approximate it, worse the finer it stepped. The tilt is a
    # term on the volume (`top_drop`, along the volume's own axis said in
    # world), the compiler carries it to the top band, the renderer draws it,
    # and the law still counts the full prism, which is the stricter reading.
    if bool(op.params.get("smooth")):
        # Signed, so "toward: back" tilts the other way - the first version
        # used the unsigned axis and a roof asked to rise toward the
        # neighbours fell toward them instead. "corner" is the diagonal: BIG's
        # most frequent single move (the survey counted corner pull five times
        # in sixteen works) is one corner drawn up while the plan stays
        # orthogonal, and a planar top through the diagonal is exactly that.
        fx, fy = frame.direction(op.params.get("toward"))
        direction = frame.out(fx, fy)
        length = (direction[0] ** 2 + direction[1] ** 2) ** 0.5 or 1.0
        unit = (direction[0] / length, direction[1] / length)
        additive = [item for item in picked if item.kind == "additive"]
        if len(additive) > 1:
            # One plane over the whole figure, not one per volume. Stamped
            # per volume, each body renormalized the drop over its OWN
            # extent - so a courtyard ring's four bars wore four different
            # planes that crossed over the corners they share, and the
            # audit read a roof slicing the court. The global incline is
            # computed once over the union's extent; each volume carries the
            # two-point profile of ITS slice of that plane, so the surfaces
            # meet where the bodies do.
            stations = [
                (min(x * unit[0] + y * unit[1] for x, y, _z in item.corners()),
                 max(x * unit[0] + y * unit[1] for x, y, _z in item.corners()),
                 item)
                for item in picked
            ]
            lo = min(a for a, _b, _i in stations)
            hi = max(b for _a, b, _i in stations)
            span = max(hi - lo, 1e-9)

            def plane(s: float) -> float:
                return 1.0 - run * (s - lo) / span

            shaped = []
            for a, b, item in stations:
                if item.kind != "additive":
                    shaped.append(item)
                    continue
                ha, hb = plane(a), plane(b)
                shaped.append(replace(
                    item,
                    top_drop=1.0 - min(ha, hb),
                    drop_toward=None,
                    ridge_along=None,
                    top_profile=((0.0, ha), (1.0, hb)),
                    profile_across=unit,
                    top_walkable=walk,
                ))
            frame.placements = rest + shaped
            return
        frame.placements = rest + [
            replace(item, top_drop=run, drop_toward=unit, top_walkable=walk)
            for item in picked
        ]
        return

    made: list[Placement] = []
    for item in picked:
        # `steps` is a ceiling on how many terraces the author wants, not a
        # floor under how thin they may be: clamping up to two here put the
        # storey rule in `_storeys` back where it started, and timmerhuis kept
        # a five-metre plate cut into 2.5 m treads.
        asked = int(_clamp(float(op.params.get("steps", 6)), 2, 8))
        count = min(_storeys(item, frame.storey, 2, 8), asked)
        full = _span_along_unit_axis(item, axis)
        across = _span_along_unit_axis(item, 1 - axis)

        def shape(index: int, t: float, count=count) -> Matrix4 | None:
            keep = 1.0 - run * index / max(count - 1, 1)
            if full * keep <= DEFAULT_MINIMUM_CLEAR_DEPTH_M or across <= DEFAULT_MINIMUM_CLEAR_DEPTH_M:
                return None
            # The high side stands still: pivot on the face at unit 0 of the
            # graded axis, so the low side is what steps back.
            vector = (keep, 1.0, 1.0) if along_x else (1.0, keep, 1.0)
            return _about_unit((0.0, 0.0, 0.0), scale_matrix4(vector))

        made.extend(_banded(item, count, shape))
    frame.placements = rest + made


def _slid_no_further_than_the_gap(frame, op, picked, rest, ratio, clearance):
    """Per volume, the largest share of the asked slide that keeps its gap.

    `shear` slides a volume sideways and had no idea what stood beside it.
    Measured, `kr_anseong_bathhouse_makes_the_mass`: its two splits open the
    2.43 m the sentence declares, then the shear on the bathhouse pushes it
    into the assembly hall and the gap is 0.00. `big_sluishuis_amsterdam` is
    the same fault - a 5.32 m gap opened by a split and shut by the next line.
    Both sentences stood refused for `gap_closed`, and raising the declared gap
    does not help: at 4.86 m and 7.60 m the shear still closes it entirely.

    Only volumes that share a height band are counted. A stack slipping past
    the tier below is what this verb is *for*, and those two overlap in plan
    whatever it does; the gate reads a gap the same way, level by level.

    The slide is shortened rather than refused. A shear that cannot travel its
    whole distance has still done what it says - the volume is displaced, just
    as far as there is room for - and refusing it would silence a sentence for
    a neighbour it was never told about.
    """

    from backend.app.modules.design.generation.maas.massv2.compile import _plan

    others = [item for item in rest if item.kind == "additive"]
    movers = [item for item in picked if item.kind == "additive"]
    shares: dict[str, float] = {}
    if not others or not movers or ratio <= 0.0:
        return shares

    ux, uy = frame.out(*frame.direction(op.params.get("toward")))
    plans_other = [(item.z_span(), _plan(item)) for item in others]

    for item in movers:
        span = item.z_span()
        plan = _plan(item)
        beside = [
            other for (low, high), other in plans_other
            # Shares a storey, and was standing clear of this one.
            if not (high <= span[0] + 1e-6 or low >= span[1] - 1e-6)
            and plan.distance(other) > 1e-6
        ]
        if not beside:
            continue
        kept = min(plan.distance(other) for other in beside)
        floor = min(kept, clearance)
        width = _span_along_unit_axis(item, _unit_axis_toward(item, ux, uy))

        def clear_at(share: float) -> float:
            reach = share * ratio * width
            slid = affinity.translate(plan, ux * reach, uy * reach)
            return min(slid.distance(other) for other in beside)

        if clear_at(1.0) >= floor - 1e-6:
            continue
        # Per volume, not one share for the whole verb. Clamping the verb as a
        # whole shortens the slides that were *opening* a gap alongside the one
        # that was closing it: `big_noma_refshaleoen` lost all 22 of its
        # standing masses that way, its own declared 4.56 m falling to 2.18.
        best = 0.0
        for step in range(1, 21):
            if clear_at(step / 20.0) >= floor - 1e-6:
                best = step / 20.0
            else:
                break
        shares[item.role] = best
    return shares


def stagger(frame, op) -> None:
    """Displace the upper volumes, each by a step of its own dimension.

    This was called `shear` and is not one. In graphics the word has a settled
    meaning - Maya's transform node calls it Shear, 3ds Max's modifier calls it
    Skew, and they are the same affine transform, which this grammar already
    says as `skew`. The BOOK gives the word a third meaning on p.32, an oblique
    cut, and that is the one it is owed: the BOOK is the language. What this
    function does - stepping stacked volumes past one another - is a real move
    that 212 authored sentences depend on, and `stagger` is what a set of
    progressively offset elements is called.


    One translation per volume, composed onto the matrix it already carries -
    so a volume keeps where it stood, which is the invariant the old
    implementation broke by rebuilding through `frame.box` without adding the
    volume's own offset back. The anchor rule is unchanged: a stack slips past
    the volume it stands on; a set standing at one level has nothing above it
    to slip past, so everything picked moves.
    """

    from backend.app.modules.design.generation.maas.massv2.grammar import MAX_OFFSET_RATIO, MIN_OFFSET_RATIO

    ratio = _clamp(float(op.params.get("ratio", 0.26)), MIN_OFFSET_RATIO, MAX_OFFSET_RATIO)
    picked, rest = frame.pick(op)
    if not picked:
        return
    # A space, not a joint. `ablation.GAP_IS_A_SPACE_M` is this same number and
    # says why: a gap narrower than a room is not a street, a lane or a court,
    # it is the line where two volumes failed to touch. What this verb must not
    # do is turn a space into that line.
    held = _slid_no_further_than_the_gap(frame, op, picked, rest, ratio,
                                         DEFAULT_MINIMUM_CLEAR_DEPTH_M)
    ux, uy = frame.out(*frame.direction(op.params.get("toward")))
    # A derived body is not a tier. Verbs name what they make after the volume
    # they made it for - `tier_2_support`, `bar_nested` - and the scope brings
    # those bodies along, which is right. But this verb grades displacement by
    # stacking order, and counted as steps of the stair the four legs under
    # Maison Bordeaux's raised tier took indices 0-3, each slid a different
    # amount, and the plate slid off all of them: 3 of 22 occupiable fell to
    # 0 of 18 the day the legs learned to follow. An attachment rides its
    # owner rigidly - the grading is over owners alone.
    primary = _primaries(picked)
    primary_ids = {id(item) for item in primary}
    ordered = sorted(primary, key=lambda item: item.z_span()[0])
    levels = {round(item.z_span()[0], 3) for item in ordered}
    anchored = 0 if len(levels) > 1 else -1

    moved: list[Placement] = []
    slides: dict[str, tuple[float, float]] = {}
    for index, item in enumerate(ordered):
        if index == anchored:
            moved.append(item)
            slides.setdefault(item.role, (0.0, 0.0))
            continue
        axis = _unit_axis_toward(item, ux, uy)
        reach = (ratio * held.get(item.role, 1.0)
                 * _span_along_unit_axis(item, axis) * (index - anchored))
        slides.setdefault(item.role, (ux * reach, uy * reach))
        slide = translation_matrix4((ux * reach, uy * reach, 0.0))
        moved.append(replace(
            item, matrix=validate_matrix4(compose_matrix4(item.matrix, slide))
        ))
    for item in picked:
        if id(item) in primary_ids:
            continue
        owner = max(
            (role for role in slides if item.role.startswith(role + "_")),
            key=len,
        )
        dx, dy = slides[owner]
        if abs(dx) < 1e-12 and abs(dy) < 1e-12:
            moved.append(item)
            continue
        slide = translation_matrix4((dx, dy, 0.0))
        moved.append(replace(
            item, matrix=validate_matrix4(compose_matrix4(item.matrix, slide))
        ))
    frame.placements = rest + moved


def bend(frame, op) -> None:
    """Kink the bar while keeping it connected - the book's Bend.

    "연결을 유지하며 방향을 꺾음". The volume is sliced along its own length and
    each segment turns a little further about the joint it shares with the one
    before, a forward-kinematic chain: the joint's world position is read off
    the chain built so far, so the pieces stay connected by construction. Two
    segments are the book's single kink; more approach an arc.

    This is the verb `big_vm_houses_orestad` needed all along - its sentence
    says "each part is bent off the axis" and the corpus had to say it with a
    `rotate`, which turns a part in place but cannot kink one.
    """

    turn = _clamp(float(op.params.get("degrees", 25.0)), -60.0, 60.0)
    picked, rest = frame.pick(op)
    if not picked:
        return
    count = int(_clamp(float(op.params.get("segments", 2)), 2, 6))

    made: list[Placement] = []
    for item in picked:
        chain = compose_matrix4()  # identity: the first segment holds still
        step = turn / max(count - 1, 1)
        for index in range(count):
            band = compose_matrix4(_slab(index, count, 0), item.matrix, chain)
            made.append(_section_turned(
                replace(item, matrix=validate_matrix4(band)), step * index))
            # The hinge is on the edge the kink opens away from, not down the
            # middle of the shared face. Turning about mid-depth swings half of
            # each segment into the one before it and the union absorbs the
            # wedge: measured on a 20x12x8 bar the loss runs with the angle -
            # -1.31% at ten degrees, -2.62% at twenty, -5.3% at forty - and it
            # does not fall with more segments, which is what says the joint
            # rather than the sampling. A rigid chain cannot lose volume; a
            # chain hinged through its own body can.
            #
            # `bend` is Barr's deformation in the BOOK's hands (p.14, Displace)
            # and Barr's arc preserves volume exactly. Hinged on the edge the
            # kink turns away from, this measures 0.00% at ten, twenty and
            # forty degrees - the chain is rigid and now the delivery says so.
            # Which edge: the one the kink turns AWAY from. Hinging on the
            # other opened the wedge inward and quadrupled the loss (-5.25% at
            # ten degrees), which is the same defect said backwards.
            side = 1.0 if step >= 0.0 else 0.0
            joint = transform_point3(
                compose_matrix4(item.matrix, chain),
                ((index + 1) / count, side, 0.0),
            )
            chain = compose_matrix4(
                chain,
                translation_matrix4((-joint[0], -joint[1], 0.0)),
                rotation_matrix4((0.0, 0.0, step)),
                translation_matrix4((joint[0], joint[1], 0.0)),
            )
    frame.placements = rest + made


def pinch(frame, op) -> None:
    """Narrow the middle from both sides - the book's Pinch.

    "중앙 양측을 깎아 좁힘". Sliced along the length, each segment scaled across
    itself about its own centreline, deepest at the middle of the run - a
    triangular waist, which is what a prism language can say of one. Eight
    House is pinched across its waist and not around it: this is the verb that
    sentence used `compress` as a stand-in for.
    """

    # Up to 0.9: at 0.7 a ring's bars pull toward each other and stop short,
    # which is a waist; past ~0.8 their inner faces cross and the figure closes
    # into two courts, which is what 8 House's sentence actually claims.
    depth = _clamp(float(op.params.get("ratio", 0.4)), 0.15, 0.9)
    picked, rest = frame.pick(op)
    if not picked:
        return
    across_y = _along_is_x(op.params)

    # The composition's own centreline and run, for the bow below. Thinning
    # each volume about itself is a notch, and two judges called it exactly
    # that - "the waist pressed to ground is barely a notch, not a split". A
    # waist is the whole figure drawing in: every band is also pulled toward
    # the centreline by how deep the waist is at its station along the run,
    # so a ring's long sides bow together at the middle the way 8 House's do.
    # A single centred volume has no offset from the centreline, so the bow
    # is silently the old pure thinning there.
    solid = [item for item in picked if item.kind == "additive"] or picked
    corners = [corner for item in solid for corner in item.corners()]
    run_dir = frame.out(1.0, 0.0) if across_y else frame.out(0.0, 1.0)
    across_dir = (-run_dir[1], run_dir[0])
    stations = [x * run_dir[0] + y * run_dir[1] for x, y, _z in corners]
    run_lo, run_hi = min(stations), max(stations)
    run_span = max(run_hi - run_lo, 1e-9)
    centre_across = sum(
        x * across_dir[0] + y * across_dir[1] for x, y, _z in corners
    ) / max(len(corners), 1)

    made: list[Placement] = []
    for item in picked:
        # Only volumes that actually run with the waist are banded. A ring's
        # end bars lie across the run: banding them slices them across their
        # own width and the waist thins them along the run, which punched four
        # pinholes into the corners of the drawing. Direction cannot tell the
        # bars apart - every box a frame poses has its unit-x on the frame's
        # long axis and the bars differ by proportion, not bearing - so the
        # test is proportion: a volume is banded when it is longer along the
        # run than across it. The end bars are held anyway by the bowing bars
        # meeting them, since the pull is zero at the run's ends.
        along_run = _span_along_unit_axis(item, 0 if across_y else 1)
        across_run = _span_along_unit_axis(item, 1 if across_y else 0)
        if along_run < across_run:
            made.append(item)
            continue
        # A bar standing off the centreline bows; a bar standing on it thins.
        # Both at once cancel: thinned to 0.15 of its width at the waist, a
        # bowed bar's inner face retreats as fast as its centre advances, and
        # a ring asked to close into two courts still read one - measured at
        # 0.85 with the peak on a boundary, gap 3.96 m. 8 House's bars keep
        # their width and bend; a bowtie's single centred slab keeps its place
        # and narrows. The volume's own offset says which it is.
        item_centre = transform_point3(item.matrix, (0.5, 0.5, 0.0))
        item_offset = abs(
            (item_centre[0] * across_dir[0] + item_centre[1] * across_dir[1])
            - centre_across
        )
        bows = item_offset > 0.25 * max(across_run, 1e-9)
        count = int(_clamp(float(op.params.get("segments", 6)), 3, 8))
        # An even count, always: the waist's deepest point is t = 0.5, and the
        # bow interpolates linearly inside each band, so the peak is only
        # reached if a band boundary lands on it. Five segments put t = 0.5
        # mid-band and the chord undershot the pull by a fifth - a ring asked
        # to close into two courts at 0.85 still read one court.
        count += count % 2

        def shape(index: int, t: float, bows=bows) -> Matrix4:
            waist = 1.0 if bows else 1.0 - depth * (1.0 - abs(2.0 * t - 1.0))
            # A hair of overlap along the run, so adjacent segments share a
            # face in floating point and not only in mathematics - a rotated
            # pinch union came back as pieces split by 1e-9 slivers. About each
            # band's OWN centre: scaled about the shared centre the joint edges
            # of both neighbours land on the same line and still only touch.
            grip = 1.002
            vector = (grip, waist, 1.0) if across_y else (waist, grip, 1.0)
            pivot = (t, 0.5, 0.0) if across_y else (0.5, t, 0.0)
            return _about_unit(pivot, scale_matrix4(vector))

        a_run, a_across = (0, 1) if across_y else (1, 0)
        for band in _banded(item, count, shape, axis=a_run):
            # The bow varies linearly WITHIN the band, so neighbouring bands
            # meet exactly - a per-band translation stepped the pull 4 m at a
            # joint and the ring came apart into corner-touching pieces. A
            # shear whose lateral term interpolates the pull between the
            # band's own two end stations is C0-continuous by construction,
            # and at the run's ends the waist is 1 so the pull is 0 and the
            # ring's corner bars stay attached without being told to.
            ends = []
            if not bows:
                made.append(band)
                continue
            for x_unit in (0.0, 1.0):
                point = [0.5, 0.5, 0.0]
                point[a_run] = x_unit
                world = transform_point3(band.matrix, tuple(point))
                station = (
                    (world[0] * run_dir[0] + world[1] * run_dir[1]) - run_lo
                ) / run_span
                waist = 1.0 - depth * (1.0 - abs(2.0 * station - 1.0))
                offset = (
                    world[0] * across_dir[0] + world[1] * across_dir[1]
                ) - centre_across
                ends.append(-(1.0 - waist) * offset)
            breadth = max(_span_along_unit_axis(band, a_across), 1e-6)
            slope = (ends[1] - ends[0]) / breadth
            base = ends[0] / breadth
            bow = [
                [1.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ]
            bow[a_across][a_run] = slope
            bow[a_across][3] = base
            made.append(replace(
                band,
                matrix=validate_matrix4(compose_matrix4(
                    tuple(tuple(row) for row in bow), band.matrix
                )),
            ))
    frame.placements = rest + made


def gable(frame, op) -> None:
    """A pitched roof: two wedges meeting at a ridge - Herzog's house profile.

    This verb existed once as a staircase and was reverted by measurement: the
    stepped approximation read worse the finer it was cut (5 steps 0.29
    articulation, 24 steps 0.09), and the memory of that revert is why the
    corpus said 박공 with nothing for two sessions. With `top_drop` in the IR
    the roof is two real planes: the volume is halved across the ridge in its
    own unit space and each half's top descends outward from the ridge, so the
    silhouette is the triangle a person draws when asked for a house.

    The ridge runs along the volume's own long axis unless `along: "cross"`.
    Legal counting stays on the full prisms - stricter, as everywhere.

    `pitch` is a slope - rise per unit of run, 1.0 is 45 degrees - not a share
    of the volume's height. As a height share it drew a 45-degree roof on a
    six-metre house bar and a five-degree tilt on a twenty-metre slab from the
    same word: the fused-gables sentence spoke 박공 and delivered a plane. The
    house unit already converts its geometry to a height share before calling
    `gabled_halves` ((d/2)/h); this verb now does the same per volume, capped
    at what the body can hold. And "long" means the volume's actually longer
    world axis, read off its matrix - as a fixed unit axis, a bar built
    deep-in-y wore its ridge across its own body.
    """

    pitch = _clamp(float(op.params.get("pitch", 0.5)), 0.15, 1.2)
    # A wide body wearing ONE ridge is a nearly flat tent; the roof a wide
    # body actually wears is a row of ridges - M-roofs, sawtooth gables,
    # terraced housing. `bays` splits the body across the ridge into that
    # many strips, each a whole primitive with its own ridge, so the row
    # survives every later transform the way one ridge does.
    bays = int(_clamp(float(op.params.get("bays", 1)), 1, 6))
    # Where the ridge sits across the body. 0.5 is the symmetric gable and
    # stays on the ridge primitive; anywhere else is a saltbox - same pitch
    # both sides, the longer side reaching lower - said as a top profile.
    at = _clamp(float(op.params.get("at", 0.5)), 0.15, 0.85)
    picked, rest = _carrying_nothing(frame, op, *frame.pick(op))
    if not picked:
        return
    long_named = _along_is_x({"along": op.params.get("along", "long")})

    def _pitched(volume, across_w: float, body: float, ridge_x: bool) -> list:
        # The mansard's cap, for the same reason: a roof is a storey or two,
        # never the building. On a forty-metre body an honest slope wants
        # eight metres of roof and leaves one metre of wall - a tent, not a
        # house. The slope yields to the eave when they conflict; a body that
        # wide should be saying `bays`.
        cap_m = ROOF_CAP_STOREYS * frame.storey
        if abs(at - 0.5) < 1e-6:
            share = _roof_share((across_w / 2.0) * pitch, body, frame.storey)
            return gabled_halves(frame, volume, share, ridge_x=ridge_x)
        origin = transform_point3(volume.matrix, (0.0, 0.0, 0.0))
        tip = transform_point3(
            volume.matrix, (0.0, 1.0, 0.0) if ridge_x else (1.0, 0.0, 0.0)
        )
        ax, ay = tip[0] - origin[0], tip[1] - origin[1]
        norm = (ax * ax + ay * ay) ** 0.5 or 1.0
        left = _clamp(
            min(pitch * at * across_w, cap_m) / body, 0.0, MAXIMUM_ROOF_SHARE)
        right = _clamp(
            min(pitch * (1.0 - at) * across_w, cap_m) / body,
            0.0, MAXIMUM_ROOF_SHARE)
        return [replace(
            volume,
            top_drop=max(left, right),
            drop_toward=None,
            ridge_along=None,
            top_profile=((0.0, 1.0 - left), (at, 1.0), (1.0, 1.0 - right)),
            profile_across=(ax / norm, ay / norm),
        )]

    made: list[Placement] = []
    for item in picked:
        if item.kind != "additive":
            made.append(item)
            continue
        origin = transform_point3(item.matrix, (0.0, 0.0, 0.0))
        tip_x = transform_point3(item.matrix, (1.0, 0.0, 0.0))
        tip_y = transform_point3(item.matrix, (0.0, 1.0, 0.0))
        span_x = ((tip_x[0] - origin[0]) ** 2 + (tip_x[1] - origin[1]) ** 2) ** 0.5
        span_y = ((tip_y[0] - origin[0]) ** 2 + (tip_y[1] - origin[1]) ** 2) ** 0.5
        ridge_x = (span_x >= span_y) if long_named else (span_x < span_y)
        across = span_y if ridge_x else span_x
        low, high = item.z_span()
        body = max(high - low, 1e-6)
        # A slice of a circle is not a smaller circle, so only the square
        # plan family splits into bays; anything else keeps its one ridge.
        rows = bays if bays > 1 and item.plan == "square" else 1
        if rows == 1:
            made.extend(_pitched(item, across, body, ridge_x))
            continue
        axis = 1 if ridge_x else 0
        size = [1.0, 1.0, 1.0]
        size[axis] = 1.0 / rows
        for k in range(rows):
            low_corner = [0.0, 0.0, 0.0]
            low_corner[axis] = k / rows
            strip = replace(
                item,
                role=f"{item.role}_bay{k}",
                matrix=validate_matrix4(compose_matrix4(
                    scale_matrix4(tuple(size)),
                    translation_matrix4(tuple(low_corner)),
                    item.matrix,
                )),
            )
            made.extend(_pitched(strip, across / rows, body, ridge_x))
    frame.placements = rest + made


def _profile_axes(item, long_named: bool):
    """The fold axis choice for a section verb, on the volume's own matrix.

    Returns (ridge_x, across_metres, across_unit_world, body_metres): which
    unit axis the fold runs along, how wide the volume is across it, the
    world direction stations are measured along, and the volume's height.
    """

    origin = transform_point3(item.matrix, (0.0, 0.0, 0.0))
    tip_x = transform_point3(item.matrix, (1.0, 0.0, 0.0))
    tip_y = transform_point3(item.matrix, (0.0, 1.0, 0.0))
    span_x = ((tip_x[0] - origin[0]) ** 2 + (tip_x[1] - origin[1]) ** 2) ** 0.5
    span_y = ((tip_y[0] - origin[0]) ** 2 + (tip_y[1] - origin[1]) ** 2) ** 0.5
    ridge_x = (span_x >= span_y) if long_named else (span_x < span_y)
    tip = tip_y if ridge_x else tip_x
    ax, ay = tip[0] - origin[0], tip[1] - origin[1]
    norm = (ax * ax + ay * ay) ** 0.5 or 1.0
    low, high = item.z_span()
    return ridge_x, (span_y if ridge_x else span_x), (ax / norm, ay / norm), max(high - low, 1e-6)


def butterfly(frame, op) -> None:
    """Two planes falling to an inner valley - the V roof.

    Breuer's Geller House, the section drawn when a house wants its rain in
    the middle and its eyes up at both edges. The valley runs along the
    volume's own long axis unless `along: "cross"`; `at` places it. Said as
    a top profile - the primitive the gable's ridge generalised into - so it
    survives every later transform whole.
    """

    pitch = _clamp(float(op.params.get("pitch", 0.5)), 0.15, 1.2)
    at = _clamp(float(op.params.get("at", 0.5)), 0.2, 0.8)
    picked, rest = _carrying_nothing(frame, op, *frame.pick(op))
    if not picked:
        return
    long_named = _along_is_x({"along": op.params.get("along", "long")})
    made: list[Placement] = []
    for item in picked:
        if item.kind != "additive":
            made.append(item)
            continue
        _rx, across, unit, body = _profile_axes(item, long_named)
        # One valley has one depth: the shorter run sets it, so the declared
        # pitch is the steeper side's and the longer side lies back. Capped
        # like the mansard and the gable - a roof is never half the building.
        depth = _roof_share(pitch * min(at, 1.0 - at) * across, body, frame.storey)
        made.append(replace(
            item,
            top_drop=depth,
            drop_toward=None,
            ridge_along=None,
            top_profile=((0.0, 1.0), (at, 1.0 - depth), (1.0, 1.0)),
            profile_across=unit,
        ))
    frame.placements = rest + made


def mansard(frame, op) -> None:
    """Steep shoulders, a near-flat crown - the Haussmann section.

    `shoulder` is how far in from each eave the steep face runs before the
    crown; the crown itself stays level. Four breakpoints of the same top
    profile the gable and the butterfly use.
    """

    pitch = _clamp(float(op.params.get("pitch", 0.8)), 0.15, 1.2)
    shoulder = _clamp(float(op.params.get("shoulder", 0.25)), 0.1, 0.4)
    picked, rest = _carrying_nothing(frame, op, *frame.pick(op))
    if not picked:
        return
    long_named = _along_is_x({"along": op.params.get("along", "long")})
    made: list[Placement] = []
    for item in picked:
        if item.kind != "additive":
            made.append(item)
            continue
        _rx, across, unit, body = _profile_axes(item, long_named)
        # The fold lives at the cornice: a mansard's roof is a storey or two,
        # never half the building. On a wide body a shoulder fraction of the
        # width is tens of metres of run, and the crown collapsed to a tent -
        # so the drop is capped at two storeys and the shoulder is re-read
        # from the declared pitch, which the steep face actually keeps.
        share = _roof_share(pitch * shoulder * across, body, frame.storey)
        shoulder_u = min(0.45, max(0.02, (share * body / pitch) / max(across, 1e-6)))
        made.append(replace(
            item,
            top_drop=share,
            drop_toward=None,
            ridge_along=None,
            top_profile=(
                (0.0, 1.0 - share), (shoulder_u, 1.0),
                (1.0 - shoulder_u, 1.0), (1.0, 1.0 - share),
            ),
            profile_across=unit,
        ))
    frame.placements = rest + made


def vault(frame, op) -> None:
    """A curved top: the barrel, Kahn's cycloid at Kimbell.

    The corpus has said 볼트 twice and delivered a pitched roof both times,
    and the IR was blamed for it - the note on `top_profile` said hips and
    vaults were outside the primitive. Half of that was wrong. A profile is a
    polyline, and a polyline with enough vertices IS a curve; only the hip is
    genuinely two-axis. So the vault costs no new geometry, only the word.

    Sampled rather than fitted: sixteen stations across the span carry the
    arc, which reads as curved at every size the sheet draws and still
    interpolates exactly like every other profile downstream. `rise` is the
    crown's height above the springing as a slope, read the way `pitch` is,
    and capped at the same storey and a half - a roof is not the building.
    """

    rise = _clamp(float(op.params.get("rise", 0.6)), 0.15, 1.2)
    bays = int(_clamp(float(op.params.get("bays", 1)), 1, 6))
    picked, rest = _carrying_nothing(frame, op, *frame.pick(op))
    if not picked:
        return
    long_named = _along_is_x({"along": op.params.get("along", "long")})
    steps = 16

    def _arched(item, across_w: float, body: float, unit) -> list:
        share = _roof_share(rise * across_w / 2.0, body, frame.storey)
        points = tuple(
            (
                index / steps,
                1.0 - share * (1.0 - math.sin(math.pi * index / steps)),
            )
            for index in range(steps + 1)
        )
        return [replace(
            item,
            top_drop=share,
            drop_toward=None,
            ridge_along=None,
            top_profile=points,
            profile_across=unit,
        )]

    made: list[Placement] = []
    for item in picked:
        if item.kind != "additive":
            made.append(item)
            continue
        ridge_x, across, unit, body = _profile_axes(item, long_named)
        rows = bays if bays > 1 and item.plan == "square" else 1
        if rows == 1:
            made.extend(_arched(item, across, body, unit))
            continue
        axis = 1 if ridge_x else 0
        size = [1.0, 1.0, 1.0]
        size[axis] = 1.0 / rows
        for k in range(rows):
            low_corner = [0.0, 0.0, 0.0]
            low_corner[axis] = k / rows
            strip = replace(
                item,
                role=f"{item.role}_bay{k}",
                matrix=validate_matrix4(compose_matrix4(
                    scale_matrix4(tuple(size)),
                    translation_matrix4(tuple(low_corner)),
                    item.matrix,
                )),
            )
            made.extend(_arched(strip, across / rows, body, unit))
    frame.placements = rest + made


def cantilever(frame, op) -> None:
    """An upper body reaching out past the one that holds it.

    The section language cannot say this. `top_profile` is a height across the
    volume's own plan, so it can tilt a top and never push one past a wall -
    which is why this is a banding verb like `shear` rather than a roof verb
    like `gable`. Bands are slices of the volume's own unit cube, and the
    flight is a world translation composed onto the matrix each band already
    carries, so a volume keeps where it stood.

    The heel holds still. `aggregate`'s `reach` records why - a flight needs
    something under it - and every band steps the same amount past the one
    below, so the ratio the structure gate reads is constant however many
    levels are asked for.

    `reach` is bounded by the gate, not by taste. `structure` refuses a
    cantilever past `CANTILEVER_BACKSPAN_RATIO` of its backspan, which inverts
    to a step of r/(1+r) of the run; the ceiling here is two thirds of that,
    because the gate judges the *delivered* mass and the growth loop moves it.
    Measured on `aggregate`'s own `reach`: 0.28 came through delivery clean and
    0.35 measured 1.61 after growth, against a limit of 1.60.

    A second bound, on the composition rather than the member: n bands each
    stepping s put the centre of mass s*(n-1)/2 of the plan past its middle,
    and the ground contact reaches half a plan, so s*(n-1) must stay under 1.

    The flying band stays a room. Marked structure it would fall out of
    `plausibility`'s room count and into its holding weight, and a scheme whose
    upper half is a cantilever would be refused for being mostly structure -
    which is the one thing the word is for. VitraHaus, the Balancing Barn and
    Milstein Hall all put rooms in the air.
    """

    from backend.app.modules.design.generation.maas.massv2.grammar import MIN_OFFSET_RATIO
    from backend.app.modules.design.generation.maas.massv2.structure import CANTILEVER_BACKSPAN_RATIO

    ceiling = 0.65 * CANTILEVER_BACKSPAN_RATIO / (1.0 + CANTILEVER_BACKSPAN_RATIO)
    asked_reach = _clamp(
        float(op.params.get("reach", 0.28)), MIN_OFFSET_RATIO, ceiling
    )
    picked, rest = frame.pick(op)
    if not picked:
        return
    fx, fy = frame.direction(op.params.get("toward"))
    ux, uy = frame.out(fx, fy)
    length = (ux * ux + uy * uy) ** 0.5 or 1.0
    ux, uy = ux / length, uy / length
    asked = int(_clamp(float(op.params.get("levels", 2)), 2, 4))
    primary_ids = {id(item) for item in _primaries(picked)}

    made: list[Placement] = []
    for item in picked:
        if item.kind != "additive" or id(item) not in primary_ids:
            made.append(item)
            continue
        count = min(_storeys(item, frame.storey, 2, 4), asked)
        if count < 2:
            # Too short to hold two floors, so there is nothing to fly. The
            # silence gate is the right place for that to surface.
            made.append(item)
            continue
        axis = _unit_axis_toward(item, ux, uy)
        run = _span_along_unit_axis(item, axis)
        step = min(asked_reach, 0.7 / (count - 1))

        def shape(_index: int, _t: float) -> Matrix4:
            return compose_matrix4()

        for index, band in enumerate(_banded(item, count, shape)):
            if index == 0:
                made.append(band)
                continue
            flight = step * run * index
            made.append(replace(band, matrix=validate_matrix4(compose_matrix4(
                band.matrix,
                translation_matrix4((ux * flight, uy * flight, 0.0)),
            ))))
    frame.placements = rest + made


def fold(frame, op) -> None:
    """A folded plate: one top that runs down and up again across the body.

    The sawtooth, the concertina, the folded slab. It is the same primitive the
    gable and the mansard are - a piecewise-linear top across one axis - with
    more breaks in it, so it costs no new geometry either.

    One volume, not a row of them. `gable`'s `bays` cuts the body into separate
    strips with a ridge each, which is a different building: strips have gaps
    between them and a plate has creases in it. `gabled_halves` records what
    splitting a section costs - the coverage retarget scales each volume about
    its own centre and pulls the pieces apart.

    `folds` is capped by the drawing, not by taste. A profile with more points
    than `MAX_CREASED_PROFILE_POINTS` is read as a sampled curve and drawn
    without its seams, which is right for the vault's sixteen samples and would
    turn a concertina into a barrel. Folds take 2n+1 points, so the cap is what
    the renderer will still crease.

    The declared pitch is one facet's slope, so a body that folds three times
    does not get a roof three times as deep - the run per facet shrinks with
    the count, which is what a real folded plate does.
    """

    pitch = _clamp(float(op.params.get("pitch", 0.5)), 0.15, 1.2)
    folds = int(_clamp(float(op.params.get("folds", 2)), 1, _MAX_FOLD_PEAKS))
    picked, rest = _carrying_nothing(frame, op, *frame.pick(op))
    if not picked:
        return
    long_named = _along_is_x({"along": op.params.get("along", "long")})
    made: list[Placement] = []
    for item in picked:
        if item.kind != "additive":
            made.append(item)
            continue
        _rx, across, unit, body = _profile_axes(item, long_named)
        facets = 2 * folds
        # The same cap the gable and the mansard hold: a roof is a storey or
        # two, never the building.
        depth = _roof_share(pitch * across / facets, body, frame.storey)
        made.append(replace(
            item,
            top_drop=depth,
            drop_toward=None,
            ridge_along=None,
            # Valleys at the eaves and at every even station, ridges between,
            # so the volume's own top is reached (`max` is exactly 1.0) and
            # `top_drop` is exactly 1 - min, which is what compile re-reads the
            # profile against when it cuts the roof band.
            top_profile=tuple(
                (index / facets, 1.0 if index % 2 else 1.0 - depth)
                for index in range(facets + 1)
            ),
            profile_across=unit,
        ))
    frame.placements = rest + made


def gabled_halves(frame, item, pitch: float, *, ridge_x: bool = True) -> list:
    """A volume as the archetypal house: ONE volume whose top is a ridge.

    Two earlier representations failed in sequence and both are worth
    remembering. Halving the whole volume made each half a sliver the storey
    gate refused. Keeping the body whole and splitting only the roof drew
    correctly out of the executor - and then a coverage retarget, which
    scales every volume about its own centre, pulled the two roof wedges
    apart into a slot along the ridge. A section is a base shape, not an
    assembly: `ridge_along` says the pentagon on one volume, and one volume
    survives every later transform whole.
    """

    # The ridge runs along the VOLUME's own axis, read off its matrix - a
    # turned bar's ridge turns with it. Read off the frame instead, every
    # unit of a crosswise pile wore a ridge diagonal to its own body, and
    # three gates downstream measured the diagonal and objected in three
    # different vocabularies before the cause was found once.
    origin = transform_point3(item.matrix, (0.0, 0.0, 0.0))
    tip = transform_point3(
        item.matrix, (1.0, 0.0, 0.0) if ridge_x else (0.0, 1.0, 0.0)
    )
    along = (tip[0] - origin[0], tip[1] - origin[1])
    length = (along[0] ** 2 + along[1] ** 2) ** 0.5 or 1.0
    return [replace(
        item,
        top_drop=pitch,
        ridge_along=(along[0] / length, along[1] / length),
        drop_toward=None,
    )]


SWEPT_VERBS: dict[str, Callable] = {
    "taper": taper,
    "twist": twist,
    "grade": grade,
    "stagger": stagger,
    "shear": shear,
    "cantilever": cantilever,
    "bend": bend,
    "pinch": pinch,
    "gable": gable,
    "butterfly": butterfly,
    "mansard": mansard,
    "vault": vault,
    "fold": fold,
}


__all__ = ["SWEPT_VERBS"]
