"""Apply a parti to a site and get placed volumes.

The executor owns the metres. An author writes "stack three, shear toward the
open side, carve a court to the south" and never states a dimension, because
every dimension here is either the parcel's or a ratio the corpus fixes. That
split is the whole point of the grammar: the author supplies the sentence, and
the sentence is about this site; the executor supplies the syntax, and the
syntax is the same everywhere.

Which is why nothing here can be tuned into a house style. The offsets are
0.15-0.35 of the volume's own dimension because below that an offset reads as
a setting-out error and above it the volume stops reading as displaced. Tiers
contrast because three offices whose work looks nothing alike never once built
a mass of equal blocks. Volumes hold a joint instead of merging because that is
how two enclosures meet. What differs between two runs is which operations were
chosen and what they were aimed at, and both of those come from the parcel.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from math import ceil, cos, degrees, pi, sin, sqrt
from typing import Any

from shapely import affinity
from shapely.geometry import Polygon
from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.floor_viability import DEFAULT_MINIMUM_CLEAR_DEPTH_M
from backend.app.modules.design.generation.maas.geometry_language.affine_matrix import compose_matrix4, translation_matrix4, validate_matrix4
from backend.app.modules.design.generation.maas.massv2.plausibility import DAYLIT_DEPTH_PER_STOREY, MINIMUM_STOREY_WIDTH_M

from backend.app.modules.design.generation.maas.massv2.compile import _plan
from backend.app.modules.design.generation.maas.massv2.form import MatrixForm, Placement, place, stack
from backend.app.modules.design.generation.maas.massv2.ops import AFFINE_VERBS
from backend.app.modules.design.generation.maas.massv2.ops.aggregation import AGGREGATION_VERBS
from backend.app.modules.design.generation.maas.massv2.ops.relational import RELATIONAL_VERBS
from backend.app.modules.design.generation.maas.massv2.ops.swept import SWEPT_VERBS, gabled_halves
from backend.app.modules.design.generation.maas.massv2.ops.piercing import PIERCING_VERBS
from backend.app.modules.design.generation.maas.massv2.ops.grafting import GRAFTING_VERBS
from backend.app.modules.design.generation.maas.massv2.profiles import cut_area, cut_plan, plan_fill, plan_names
from backend.app.modules.design.generation.maas.massv2.grammar import JOINT_CLEARANCE_M, MAX_OFFSET_RATIO, MIN_OFFSET_RATIO, MIN_TIER_CONTRAST, STACK_CONTRAST_RANGE, DEFAULT_STACK_CONTRAST, Operation, Parti, seed_rectangle


def _clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


# How many volumes a field may hold. Six was a hardcoded table of corner slots
# and it was the ceiling on grade articulation for the entire grammar, because
# `split` divides a field rather than multiplying it. Korean competition winners
# average 3.4 separate masses, which six could reach; Moriyama's ten, Towada's
# one-per-artwork and Nishinoyama's ten dwellings could not be said at all.
MAX_FIELD_OBJECTS = 12

# How much the objects in a field may differ in size. The floor used to be
# MIN_TIER_CONTRAST, formerly also applied to every authored stack - but
# Nishizawa rejected volumes that were *identical*, not volumes that
# were *similar*, and at Moriyama and Towada the near-equality is the content:
# it is what makes the result read as a neighbourhood rather than as a house
# with outbuildings. Equal is still refused; close is now allowed.
MIN_FIELD_SPREAD = 1.05

# A house-section unit's depth as a share of its own height. Drop equals half
# the depth, so the roof planes stand at 45 degrees whatever the aspect; at
# 0.9 the roof takes 0.45 of the section, which is the pentagon a person
# draws when asked for a house - and the body under it stays wide enough for
# the storey gate, which a roof-dominated section is not.
HOUSE_ASPECT = 0.9

# How tall an undercroft may be, in storeys of the building it belongs to.
# The corpus lifts to let the ground run under a building, not to stand it on
# towers: Rolex, Zollverein, Grace Farms and Kaktus all clear a storey or two.
# This is the ceiling that matches the floor `_lift` already had, and both are
# metres for the same reason - the person walking under is the same size on
# every site.
MAX_UNDERCROFT_STOREYS = 2.0
# The unit diagonal, for the axis words "corner" and "diagonal".
_SQRT_HALF = math.sqrt(0.5)
# How far off a regulating line a volume may run and still be alignable to it.
# Past this the two are not parallel and sliding would put a corner on the line
# rather than a face, which is a touch and not an alignment.
_ALIGN_PARALLEL_DEG = 8.0


@dataclass(frozen=True)
class Line:
    """An alignment or symmetry axis the composition is holding onto."""

    origin: tuple[float, float]
    direction: tuple[float, float]
    born: str = "site"


@dataclass(frozen=True)
class Centre:
    """A point operations turn about, or a void is centred on."""

    point: tuple[float, float]
    born: str = "site"


# The BOOK's six fractions. A fraction is not a scalar on every axis at once -
# taking a quarter vertically is a tower and taking it across is a bar - so the
# orientation says which axis carries it, and the other two are left alone. The
# two fractions the BOOK draws as connected octant groups rather than boxes,
# 3/8 and 1/16, are taken here as their bounding extent: the L and the corner
# cluster need a plan figure this grammar cannot yet write, and pretending a
# box is an L would be worse than saying so.
_BASE_VOLUME_FRACTION = {
    "1/1": 1.0, "3/8": 0.375, "1/2": 0.5, "1/4": 0.25, "1/8": 0.125, "1/16": 0.0625,
}

def _base_volume_extent(width: float, depth: float, label, orientation):
    """(width, depth, height share) after taking the BOOK's fraction."""

    fraction = _BASE_VOLUME_FRACTION.get(str(label or "1/1"), 1.0)
    if fraction >= 1.0 - 1e-9:
        return width, depth, 1.0
    where = str(orientation or "long_axis")
    if where == "vertical":
        return width, depth, fraction
    if where == "short_axis":
        return width, depth * fraction, 1.0
    return width * fraction, depth, 1.0


class _Frame:
    """The site's own box, the volumes standing in it, and what regulates them.

    Akin & Moustapha (Design Studies 25(1), 2004) watched six architects mass a
    building for two hours each and found the mechanism that structured all of
    it: regulating elements - symmetry axes, centres of rotation, alignment
    lines. What they let an architect do is add and remove masses freely while
    the underlying structure survives, and that survival is what separates a
    composition from a pile.

    This grammar had the machinery and no vocabulary. `ops.affine` already says
    "which volumes, which operator, about what pivot", but the pivot was the
    bounding-box centre of whatever the operation happened to pick, recomputed
    per call and thrown away - so no two operations could share one, and a
    sentence had no way to say "turn this about the line the split just cut".
    """

    def __init__(
        self,
        buildable: Polygon,
        axis: tuple[float, float],
        height_m: float,
        storey_m: float = 0.0,
        base_volume: str | None = None,
        base_orientation: str | None = None,
    ):
        cx, cy, width, depth, rotation = seed_rectangle(buildable, axis)
        # The BOOK chooses what to act on before it acts. Its base operatives
        # are three parts - a relative base volume and an orientation, then one
        # action, then that action's bounded variations - and this grammar only
        # ever had the middle part: the seed was always the parcel's own
        # rectangle, so every mass began as the plot and the jury kept writing
        # "an object placed on the parcel rather than a building that has
        # reckoned with its edges". A quarter taken vertically is a tower; a
        # half taken across is a bar. Silence still gives the whole plot on the
        # open side, so nothing already written moves.
        width, depth, self.height_share = _base_volume_extent(
            width, depth, base_volume, base_orientation)
        # A vertical fraction below one storey cannot be said on this parcel.
        # `box` floors an occupiable body at a storey and is right to - nobody
        # stands in a 2 m room - but the floor silently turned `1/8 vertical`
        # and `1/16 vertical` into `1/4` on a 16 m envelope, so three different
        # base volumes delivered one building and the sentence was never told.
        # Recorded rather than corrected: which fractions are sayable depends on
        # the parcel, and a base volume the site cannot hold is the same kind of
        # refusal `split` makes for a piece narrower than a room.
        self.base_volume_too_short = bool(
            storey_m > 0.0
            and self.height_share < 1.0
            and height_m * self.height_share < storey_m - 1e-9
        )
        # Which edge faces the lane. `siting` computes it and the frame threw it
        # away, so `approach` - the one verb whose whole subject is the street -
        # had no way to ask.
        self.axis = axis
        self.cx, self.cy = cx, cy
        self.width, self.depth = width, depth
        self.rotation = rotation
        self.height = height_m * self.height_share
        # A room is at least a storey. Heights in a sentence are ratios of the
        # whole, and an author writing about a single-storey building writes a
        # small one - Louvre-Lens at 0.15 - which on a parcel affording four
        # storeys is 1.9 m, and after `aggregate` thins its later objects, 0.86.
        # That is a kerb, not a room: the diff check reported a `taper` aimed at
        # one of them as changing the mass by exactly 0.000.
        self.storey = max(0.0, storey_m)
        # The base shape this composition is made of, set once by the sentence.
        # A profile is a property of the building, not of one operation: a
        # circular museum is circular in every volume it is cut into.
        self.profile = "square"
        self.placements: list[Placement] = []
        # What the site gives, before any word is said. Nothing is invented
        # here: every one of these is already computed elsewhere in the package
        # and was being thrown away.
        along = (math.cos(math.radians(rotation)), math.sin(math.radians(rotation)))
        across = (-along[1], along[0])
        self.lines: dict[str, Line] = {
            "spine": Line((cx, cy), along, "site"),
            "cross": Line((cx, cy), across, "site"),
            "street": Line((cx, cy), axis, "site"),
        }
        self.centres: dict[str, Centre] = {"site": Centre((cx, cy), "site")}
        # Which volumes were sent to which line, kept so the alignment can be
        # re-asserted on the delivered mass. Measured, without this: a sentence
        # aligned at 4.00 parts per line arrives at 2.00, and at 1.00 once the
        # `dispersed` variant has had it - the growth loop, the coverage and
        # siting variants and the legal clip all move parts after the sentence
        # has finished, and none of them knows a line was named.
        self.alignments: list[dict] = []

    def regulates(self, name: str, element) -> None:
        """Record an axis or a centre an operation just brought into being.

        This is the half of the finding that matters. A regulating element is
        not drawn up front and obeyed - it is produced by a move and then
        honoured by the moves after it, which is how the structure survives
        being edited.
        """

        if isinstance(element, Line):
            self.lines[name] = element
        else:
            self.centres[name] = element

    def pick(self, op) -> tuple[list[Placement], list[Placement]]:
        """What this operation acts on, and the rest. See `_scope`."""

        return _scope(self, op)

    def direction(self, toward) -> tuple[float, float]:
        """Which way a name means, in the frame's own axes. See `_direction`."""

        return _direction(self, toward)

    def out(self, dx: float, dy: float) -> tuple[float, float]:
        """A displacement written in the frame's axes, said in world terms.

        The frame is the parcel's own rectangle and it is almost never square
        to north - Uijeongbu's bearing is -168.3 degrees, Gangnam's is 35.5.
        `_direction` returns its vectors in the frame's axes, and `box` was
        adding them straight onto a world centre, so a move written "along" ran
        along world east instead: at -168 degrees the cosine is -0.979 and the
        move went backwards.

        Both halves of a top-level `split` survive that, because they are
        symmetric about one centre and reversing the sides only swaps their
        names. A second `split` aimed at one of those halves does not: the
        parent's offset is a world quantity and the child's shift is a frame
        one, so the child crosses the gap the first cut opened. Measured on
        `kr_hansol_gym_is_its_own_body`, whose sentence cuts twice, `library`
        stood 0.00 m from `gym` across a 2.58 m declared gap.
        """

        if abs(self.rotation) < 1e-9:
            return (dx, dy)
        bearing = math.radians(self.rotation)
        cos_b, sin_b = math.cos(bearing), math.sin(bearing)
        return (dx * cos_b - dy * sin_b, dx * sin_b + dy * cos_b)

    def point(self, dx: float, dy: float) -> tuple[float, float]:
        """The world position of a frame offset, for the two verbs that place
        absolutely instead of through `box` - `taper` and `twist` hand a corner
        straight to `stack`."""

        world = self.out(dx, dy)
        return (self.cx + world[0], self.cy + world[1])

    def local(self, x: float, y: float) -> tuple[float, float]:
        """Where a world point sits in the frame's axes, from the frame centre."""

        if abs(self.rotation) < 1e-9:
            return (x - self.cx, y - self.cy)
        bearing = math.radians(-self.rotation)
        cos_b, sin_b = math.cos(bearing), math.sin(bearing)
        ox, oy = x - self.cx, y - self.cy
        return (ox * cos_b - oy * sin_b, ox * sin_b + oy * cos_b)

    def box(
        self,
        role: str,
        *,
        w: float,
        d: float,
        z: float,
        h: float,
        dx: float = 0.0,
        dy: float = 0.0,
        kind: str = "additive",
        plan: str = "",
        occupiable: bool = True,
        turn: float = 0.0,
    ) -> Placement:
        """A volume centred on the site frame, offset in the frame's own axes.

        `occupiable` is what separates a room from a piece of structure. A
        support under a lifted plate is allowed to be shorter than a storey
        because nobody stands in it; anything else is not.

        `plan` is the base shape, and defaults to whatever the sentence set for
        this composition rather than to the square. Ten of them are built
        (`profiles.plan_names`) and the grammar used one: measured across the
        forty-eight authored sentences, 302 of 302 placements were square. A
        matrix cannot turn a square into a circle, so a sentence with no way to
        name the shape has no way to say Kanazawa's 112.5 m circle or Casa da
        Música's faceted solid - and both of those came out as a `taper`, which
        is why that verb was carrying work it could never do.
        """

        least = self.storey if occupiable and kind == "additive" else 0.5
        plan = plan or self.profile
        world_dx, world_dy = self.out(dx, dy)
        return place(
            role,
            size=(max(w, 0.5), max(d, 0.5), max(h, least, 0.5)),
            at=(self.cx + world_dx - w / 2.0, self.cy + world_dy - d / 2.0, z),
            # Off the frame's bearing, not instead of it. A volume that
            # abandons the parcel's axis reads as a mistake; one sitting a few
            # degrees off it reads as having been placed.
            rotation_degrees=self.rotation + float(turn),
            kind=kind,
            plan=plan,
            occupiable=occupiable,
        )


def _direction(frame: _Frame, toward: Any) -> tuple[float, float]:
    """Which way a move is aimed, in the frame's own axes.

    Named rather than numeric, because direction is the programmatic half of a
    move - the author says "toward the open side" and means the street, not an
    angle. Anything unrecognised aims along the site's length, which is the one
    direction every parcel has.
    """

    name = str(toward or "long").lower()
    # A named regulating element wins over the three site directions: a
    # sentence that says "along the line the split cut" means that line, and
    # the fallback below is what every existing sentence already gets.
    held = frame.lines.get(str(toward or ""))
    if held is not None:
        dx, dy = held.direction
        # Back into the frame's own axes, which is what every caller expects.
        bearing = math.radians(frame.rotation)
        cos_b, sin_b = math.cos(-bearing), math.sin(-bearing)
        return (dx * cos_b - dy * sin_b, dx * sin_b + dy * cos_b)
    if name in ("cross", "short", "side"):
        return (0.0, 1.0)
    if name in ("back", "away", "off_open"):
        return (-1.0, 0.0)
    # The grammar has admitted "corner" and "diagonal" as axis words since the
    # enumeration was written, and every verb but `grade` quietly aimed them
    # along the length instead - a word accepted, validated, and doing
    # something else, which no gate can catch because the sentence does change
    # the form. `grade` carried its own diagonal branch; the meaning belongs
    # here, where every verb reads it.
    if name in ("corner", "diagonal"):
        return (_SQRT_HALF, _SQRT_HALF)
    # The frame is posed on the open side (`seed_rectangle`: "the bearing is
    # the open side - the street"), so +x IS toward the open ground. These
    # three words were grammar-legal and rode the fallback by luck; a word
    # whose meaning is an accident of the default is one default-change away
    # from aiming somewhere else, so they are said explicitly.
    if name in ("open", "to_open", "front"):
        return (1.0, 0.0)
    return (1.0, 0.0)


def _scope(frame: _Frame, op: Operation) -> tuple[list[Placement], list[Placement]]:
    """Split what is standing into what this operation acts on, and the rest.

    Without this every verb reached everything, and a grammar whose verbs all
    have the same scope is barely a grammar - stack then shear then carve gives
    one family however the words are ordered, because each word sees the whole
    building. The combinations collapse into their union.

    `on` is matched as a prefix of the volume's role, so `on: "west"` catches
    `west`, `west_tier_0` and anything split out of them. Naming a part that is
    not there does nothing rather than falling back to everything: an operation
    aimed at a wing the scheme never grew should be silent, not global.
    """

    prefix = str(op.params.get("on") or "").strip()
    if not prefix:
        return list(frame.placements), []
    picked = [item for item in frame.placements if item.role.startswith(prefix)]
    rest = [item for item in frame.placements if not item.role.startswith(prefix)]
    return picked, rest


def _bounds_of(
    items: list[Placement], frame: "_Frame"
) -> tuple[float, float, float, float]:
    """Centre and span in plan of a set of volumes, in the frame's own axes.

    The spans have to be measured on the axes the boxes are built on. Every
    volume here is posed at the parcel's bearing, and this used to take the
    axis-aligned bounding box of the posed corners - which on a skewed parcel is
    larger than the box it encloses, by the cosine of the bearing on each side.
    So every verb that rebuilds a volume from these numbers rebuilt it bigger
    than the volume it replaced, on every site whose seed rectangle is not
    square to north.

    Measured on Mountain Dwellings: the `split` leaves `slope` 49.2 m long and
    the `grade` after it rebuilds its first step at 57.8 m, eating the 3.8 m
    gap the split had opened and closing what the sentence was about. The same
    inflation is why `lift` closed Villa dall'Ava's.

    The centre comes back in the frame's axes too, as an offset from the frame
    centre, which is the form every caller passes straight to `box`. It used to
    be returned in world coordinates and the callers subtracted `frame.cx`
    themselves, which left a world quantity being added to a frame one in the
    same expression - see `_Frame.out`.
    """

    corners = [corner for item in items for corner in item.corners()]
    xs = [x for x, _y, _z in corners]
    ys = [y for _x, y, _z in corners]
    centre_x = (min(xs) + max(xs)) / 2.0
    centre_y = (min(ys) + max(ys)) / 2.0
    offset = frame.local(centre_x, centre_y)
    if abs(frame.rotation) < 1e-9:
        return (offset[0], offset[1], max(xs) - min(xs), max(ys) - min(ys))
    bearing = math.radians(-frame.rotation)
    cos_b, sin_b = math.cos(bearing), math.sin(bearing)
    turned = [
        ((x - centre_x) * cos_b - (y - centre_y) * sin_b,
         (x - centre_x) * sin_b + (y - centre_y) * cos_b)
        for x, y, _z in corners
    ]
    us = [u for u, _v in turned]
    vs = [v for _u, v in turned]
    return (offset[0], offset[1], max(us) - min(us), max(vs) - min(vs))


def _turned(x: float, y: float, degrees: float) -> tuple[float, float]:
    """An offset in a volume's own axes, read in the frame's."""

    radians = math.radians(degrees)
    cos_t, sin_t = math.cos(radians), math.sin(radians)
    return (x * cos_t - y * sin_t, x * sin_t + y * cos_t)


def _own_plan(item: Placement, frame: "_Frame") -> tuple[float, float, float]:
    """A volume's plan span on its OWN axes, and how far it is turned off the frame's.

    `_bounds_of` measures on the frame's axes, which is right for a volume posed
    at the parcel's bearing and wrong for one a `turn` or a `rotate` has moved
    off it. The frame-aligned box around a turned rectangle is larger than the
    rectangle, so a verb rebuilding from those numbers inflates the volume - and
    rebuilding through `box` without the turn also stands it square again.

    Measured on `big_lego_house_interlocking_bricks_over_a_square`: `aggregate`
    turns its five objects to -171.5, -163.9, -162.7, -161.5 and -176.3 degrees,
    `stack` keeps them, and `lift` rewrote every one of them to the parcel's own
    -168.3. The 8-degree turn the sentence declares was not in the drawing.
    """

    matrix = item.matrix
    bearing = math.degrees(math.atan2(matrix[1][0], matrix[0][0]))
    radians = math.radians(bearing)
    along = (math.cos(radians), math.sin(radians))
    across = (-along[1], along[0])
    corners = item.corners()

    def span(unit: tuple[float, float]) -> float:
        return max(
            abs((one[0] - two[0]) * unit[0] + (one[1] - two[1]) * unit[1])
            for one in corners for two in corners
        )

    return span(along), span(across), bearing - frame.rotation


def _plan_shrink(item: Placement, span_x: float, span_y: float) -> float:
    """How much a rebuilt box must shrink to hold no more plan than it had.

    Every verb that rebuilds a volume rebuilds it as a rectangle spanning the
    volume's bounding box, and every sentence starts from a parcel-shaped seed,
    so the rebuilt piece is larger than the piece it replaced. `_split` grew a
    building by 74% that way. The same arithmetic is here because `_grade` and
    `_lift` rebuild too, and measured on the corpus it is why their gaps close:
    Mountain Dwellings' `split` opens 3.8 m and its `grade` closes it to nothing,
    Villa dall'Ava's `split` opens 3.05 m and its `lift` closes it to nothing.
    The rebuilt piece grows sideways into the space the earlier word made.

    Returns 1.0 for a rectangle, so nothing that was already honest moves.
    """

    box = span_x * span_y
    if box <= 1e-9:
        return 1.0
    area = float(_plan(item).area)
    if area <= 1e-9 or area >= box:
        return 1.0
    return (area / box) ** 0.5


def _split(frame: _Frame, op: Operation) -> None:
    """Divide what it is aimed at into two named parts.

    This is the verb that makes the rest of the grammar productive. Once a mass
    has a `west` and an `east`, every other verb can be aimed at one of them,
    and the same four words describe a different building depending on where
    they land. It is also how the corpus works: OMA's patents transform a known
    type, and half of them begin by cutting it in two.

    The parts are unequal by default, because two equal masses do not occur in
    built work - and unequal in height as well as in plan. Cutting a box into
    a 62/38 pair of the same height and standing them flush produces a drawing
    identical to the box: the division is in the data and not in the building,
    and every later verb aimed at one half then acts on something nobody can
    see. `stack` has refused equal tiers since it was written, quoting the same
    corpus reading; the rule belongs to both verbs or to neither.
    """

    picked, rest = _scope(frame, op)
    if not picked:
        return
    ratio = _clamp(float(op.params.get("ratio", 0.62)), 0.3, 0.75)
    ux, uy = _direction(frame, op.params.get("along"))
    names = (str(op.params.get("first") or "part_a"), str(op.params.get("second") or "part_b"))
    gap = float(op.params.get("gap", 0.0)) * JOINT_CLEARANCE_M
    # The lesser part is the lower one. Held at the tier contrast, so the two
    # halves read as two volumes from any side rather than only in plan.
    contrast = max(MIN_TIER_CONTRAST, float(op.params.get("contrast", MIN_TIER_CONTRAST)))

    made: list[Placement] = []
    for item in picked:
        pending: list[dict] = []
        low, high = item.z_span()
        cx, cy, _frame_x, _frame_y = _bounds_of([item], frame)
        # On the volume's own axes, and the pieces go back at its own bearing.
        # Cutting a turned volume on the frame's axes measures it across its
        # diagonal and stands both halves square: measured on
        # `sejima_inujima_art_houses`, `aggregate` puts its seven houses at seven
        # bearings and the `split` after it returned twelve pieces at one. The
        # sentences this happens to are the fields - Inujima, Towada,
        # Nishinoyama, Sydney Modern - whose whole subject is that the pieces sit
        # at different angles.
        span_x, span_y, turn = _own_plan(item, frame)
        along = span_x if abs(ux) >= abs(uy) else span_y
        # Cutting cannot make the building bigger. The pieces are rectangles
        # spanning the bounding box, so a plan that is not a rectangle - the
        # parcel-shaped volume every sentence starts from - grew every time it
        # was cut: Central Beheer's three splits took 3,342 m² to 5,815 m², a
        # 74% rise that put it over 건폐율 at 1.17 of the cap while the sentence
        # believed it was dividing a settlement. So the cross dimension is
        # whatever holds the plan area it was cut from, not the bounding box.
        # For a rectangle the two are the same and nothing changes.
        # The piece is as wide as the parent's bounding span, because its own
        # outline now carries the shape. This used to be capped at
        # `plan_area / along` - the area the parent actually held, spread over
        # the cut length - because a rectangle standing in for a non-rectangular
        # plan is bigger than the plan it replaced, and Central Beheer's three
        # splits took 3,342 m2 to 5,815 that way. With `cut_plan` the piece is
        # the clipped ring and holds the right area by construction, so keeping
        # the cap charged for the same inflation twice: measured over the corpus
        # it took eighteen sentences down by a median 9.8% and one by 47.8%.
        # For a square parent the two readings are identical, which is why the
        # cap could be dropped rather than made conditional.
        across = span_y if abs(ux) >= abs(uy) else span_x
        # The gap moves the halves, it does not eat them. Requicha (1980):
        # a plane cuts a solid into its intersections with the two closed
        # half-spaces, and those two together ARE the solid - so the material
        # is conserved and what opens between them is a displacement. Taking
        # `gap / 2` off each piece instead deleted the space it opened, which
        # is why the BOOK reads this word as Displace (p.16) and massv2
        # measured it removing 154 m3 of a 1,920 m3 body.
        first = along * ratio
        second = along * (1.0 - ratio)
        # Where each piece sits on the cut axis, in the parent's own unit terms,
        # so it can carry the parent's outline between those stations rather
        # than a rectangle standing in for it.
        stations = (
            (0.0, max(0.0, min(1.0, first / max(along, 1e-9)))),
            (max(0.0, min(1.0, 1.0 - second / max(along, 1e-9))), 1.0),
        )
        for (name, size, side), window in zip(
            ((names[0], first, -1.0), (names[1], second, 1.0)), stations
        ):
            # A piece narrower than a room is not a piece of a building. The
            # floor used to be half a metre, which is a wall, and on a 264 m²
            # parcel in Gangnam `kr_hoeryong_nursery_three_low_wings` came out
            # as a 3.7 m body, a 2.1 m one and a 1.5 x 4.0 m needle standing
            # 7.6 m tall beside them. The plausibility gate passed it because it
            # weighs the whole mass and the needle is 18% of it - which is the
            # right question for that gate and the wrong place to catch this.
            #
            # Refusing the piece means a mass too small to cut comes through
            # uncut, and the silence gate then reports the `split` as a word
            # that did nothing. That is the honest outcome: on a plot this size
            # the sentence cannot be said, and it should say so rather than
            # deliver splinters.
            if size <= DEFAULT_MINIMUM_CLEAR_DEPTH_M or across <= DEFAULT_MINIMUM_CLEAR_DEPTH_M:
                continue
            # Each half steps out by half the gap, so the cut line stays where
            # the sentence put it and the pair straddles it symmetrically.
            shift = side * ((along - size) / 2.0 + gap / 2.0)
            # The two halves step apart along the volume's own axis, which is
            # the frame's turned by `turn`. Offsetting on the frame's axes
            # instead slid them off the cut line by the sine of that angle.
            radians = math.radians(turn)
            if abs(ux) >= abs(uy):
                unit = (math.copysign(1.0, ux or 1.0), 0.0)
            else:
                unit = (0.0, math.copysign(1.0, uy or 1.0))
            off_x = (unit[0] * math.cos(radians) - unit[1] * math.sin(radians)) * shift
            off_y = (unit[0] * math.sin(radians) + unit[1] * math.cos(radians)) * shift
            tall = (high - low) if size >= along / 2.0 else (high - low) / contrast
            # The piece's own outline, and the width that makes it hold the
            # area the cut actually took. `_normalized` stretches a clipped ring
            # back out to fill [0, 1]^2 - that is what lets one scale mean the
            # same thing for every profile - so the stretch has to be undone
            # here or a half-oval is rebuilt at the size of a whole one.
            # Measured both ways before this: keeping the old cap took eighteen
            # sentences down a median 9.8%, dropping it took twenty up a median
            # 2.9% and one 39.4%. Solving for the area is neither.
            piece_plan = cut_plan(
                item.plan, along_x=abs(ux) >= abs(uy),
                low=window[0], high=window[1],
            )
            piece_width = across
            taken = cut_area(piece_plan)
            if taken is not None and size > 1e-9:
                wanted = taken * along * across
                piece_width = _clamp(
                    wanted / (size * plan_fill(piece_plan)), 0.0, across
                )
            if piece_width <= DEFAULT_MINIMUM_CLEAR_DEPTH_M:
                continue
            pending.append(
                dict(
                    role=name,
                    w=size if abs(ux) >= abs(uy) else piece_width,
                    d=piece_width if abs(ux) >= abs(uy) else size,
                    z=low, h=tall,
                    dx=cx + off_x,
                    dy=cy + off_y,
                    turn=turn,
                    kind=item.kind,
                    # A piece cut from a plan is not a copy of that plan - halve
                    # a circular museum and you get two half-circles - and it is
                    # not a rectangle either. Copying the parent's name was the
                    # first attempt and measured worse than the rectangle: a
                    # profile is normalized into the unit square and then scaled
                    # by each volume's own width and depth, so the same trapezoid
                    # came out at a different splay in every part - Lab City's
                    # three volumes measured 2.07, 1.64 and 2.33 to one, three
                    # unrelated wedges where the building is one block with a
                    # diagonal street cut through it.
                    #
                    # The piece's own outline is neither. `cut_plan` clips the
                    # parent's ring at this piece's stations and registers the
                    # result under a name derived from the cut, so a half is a
                    # half and the vocabulary grows by a name rather than by a
                    # primitive. A square cut in two is a square, and that case
                    # returns the parent unchanged.
                    plan=piece_plan,
                    occupiable=item.occupiable,
                )
            )
        # What the lesser piece gives up in height, the greater one takes.
        #
        # The contrast above is an architectural rule with its reason written
        # beside it - two halves of one height standing flush are a drawing of
        # the box they came from - but it was paid for by deleting the material
        # it shortened, which is why the BOOK reads Displace on p.16 and massv2
        # measured 8.00% removed. A displacement moves material; it does not
        # spend it. So the pair still holds what the parent held, at the
        # parent's own footprint: the low half is low, the tall half is taller
        # for it, and nothing has to grow sideways into the 건폐율.
        if len(pending) > 1:
            full = high - low
            areas = [piece["w"] * piece["d"] * max(plan_fill(piece["plan"]), 1e-9)
                     for piece in pending]
            owed = sum(area * (full - piece["h"])
                       for area, piece in zip(areas, pending))
            if owed > 1e-9:
                index = max(range(len(pending)), key=lambda i: pending[i]["h"])
                pending[index]["h"] += owed / areas[index]
        made.extend(frame.box(piece.pop("role"), **piece) for piece in pending)
        # The cut is an alignment line the rest of the sentence can hold onto.
        # It is the composition's own axis rather than the site's, and it is
        # exactly what an architect draws first and keeps.
        # Stored in world terms, because that is where a line lives and what
        # `_direction` turns back into the frame's axes when a later word names
        # it. The point and the direction are both frame quantities here.
        cut = (-uy, ux) if abs(ux) >= abs(uy) else (uy, -ux)
        frame.regulates(
            f"{names[0]}|{names[1]}",
            Line(
                (frame.cx + frame.out(cx, cy)[0], frame.cy + frame.out(cx, cy)[1]),
                frame.out(*cut),
                "split",
            ),
        )
    frame.placements = rest + made


def _extrude(frame: _Frame, op: Operation) -> None:
    share = _clamp(float(op.params.get("height", 1.0)), 0.1, 1.0)
    frame.placements.append(
        frame.box("body", w=frame.width, d=frame.depth, z=0.0, h=frame.height * share)
    )


def _stack(frame: _Frame, op: Operation) -> None:
    """Tiers with the author's relative dimensions, including equal bodies.

    Subsequent targeted transforms may rotate or displace each named tier.
    Geometric support and site eligibility remain downstream checks.
    """

    count = int(_clamp(float(op.params.get("n", 3)), 2, 6))
    # VIA 57 West holds three corners near 40 m and draws the fourth to 142 m -
    # a contrast of 3.5 inside one figure. A ceiling of 2.0 made that sentence
    # unwritable, so the cap is the built work's rather than a guess, and the
    # storey and structure gates decide whether the result stands.
    contrast = _clamp(float(op.params.get("contrast", DEFAULT_STACK_CONTRAST)), *STACK_CONTRAST_RANGE)
    # Which way unequal tiers change size: Vancouver House grows floor by
    # floor once it clears the bridge, and Korean briefs put the assembly hall
    # on the top storey - 만수6동's says so in as many words - where a long-span
    # roof costs least because nothing has to be carried over it.
    #
    # Shrinking upward was hard-coded, so the largest volume was always the
    # bottom one and "hall on top" was unbuildable. The strategy axis reported
    # zero `crown` schemes out of 888 candidates for that reason alone.
    growing = bool(op.params.get("grow"))
    if growing:
        contrast = 1.0 / contrast
    share = _clamp(float(op.params.get("height", 1.0)), 0.1, 1.0)
    tier_h = frame.height * share / count
    # Which face stays flush as the tiers shrink. Centred is a wedding cake -
    # every tier steps back on all four sides at once, which is what a setback
    # regulation produces and not what an architect draws. Holding one face
    # gives the mass a front: the corpus's volumes share faces and edges, they
    # do not float concentrically inside one another.
    ux, uy = _direction(frame, op.params.get("align")) if op.params.get("align") else (0.0, 0.0)
    w, d = frame.width, frame.depth
    if growing:
        # The plot is the size of the largest tier, whichever end of the stack
        # that is. Shrinking, the largest is the first and the series starts at
        # the seed; growing, it is the last, and starting at the seed anyway
        # multiplied the plot by the contrast once per tier:
        #
        #     vancouver_house  n=3 contrast=3.0 grow   1,866 -> 166,049 m² in plan
        #     via57            n=2 contrast=3.5 grow   2,375 ->  45,723 m²
        #
        # The alignment offset below is `(frame.width - w) / 2`, which is a
        # displacement to the flush face while `w` fits the plot and a throw off
        # the site once it does not: those two masses were built 269 m and 81 m
        # from the parcel centre, and only the growth loop's re-centring
        # brought them back.
        span = contrast ** (count - 1)
        w, d = w * span, d * span
    z = 0.0
    for index in range(count):
        # Tiers meet on a shared face, they do not overlap. Overlapping them by
        # 2% is what you do to keep a boolean kernel out of a degenerate case,
        # and this pipeline has no kernel: `compile` cuts bands at the z values
        # the volumes declare, so a 2% overlap declared one extra band per joint
        # carrying the lower tier's plan - a 0.16 m slice of a 8 m tier. The
        # renderer drew each as a false eaves line, so every stacked scheme read
        # as a pancake, and `large_span_strategy` read those slices as candidate
        # halls until it was taught to weigh volume instead of plan.
        tier = frame.box(f"tier_{index}", w=w, d=d, z=z, h=tier_h,
                         dx=ux * (frame.width - w) / 2.0,
                         dy=uy * (frame.depth - d) / 2.0)
        frame.placements.append(tier)
        # Advance by what the tier actually came out at, not by what was asked
        # for. `box` holds an occupiable volume to a storey, so a stack of five
        # on a twelve-metre frame asks for 2.40 m tiers and gets 3.00 m ones -
        # and stepping by 2.40 buried each tier 0.60 m in the one below. The
        # growth loop then widened that to 1.65 m, and the compiler cut a band
        # at every overlap: nine prisms for five platforms, drawn as horizontal
        # stripes across the whole of Seattle. Which is the failure the comment
        # above already describes, arriving by a different route.
        z = tier.z_span()[1]
        w, d = w / contrast, d / contrast


def _carve(frame: _Frame, op: Operation) -> None:
    """Take a named room out of the mass, on the side the author aimed it."""

    # Sized and placed against the site's seed rectangle, not against the mass
    # that is standing. That looks like the wrong frame of reference - it is the
    # mistake `_lift` made three times - and aiming it at the standing mass was
    # tried and is not supported by the measurement. Removal as a share of the
    # compiled solid, over the thirteen sentences that carve, notch or puncture:
    #
    #     median 14.4%, and only one case under 5%
    #     big_tirpitz_blaavand at 1.6% - already reported silent by the gate
    #
    # Aiming at the mass moved two schemes up by about two points, two down by
    # about one, and left the rest flat; Tirpitz itself got worse, 2.3% to 1.6%.
    # So the compositions here stay close enough to the seed that the two frames
    # agree, and Tirpitz's weak carve has some other cause. Reverted rather than
    # kept on principle.
    share = _clamp(float(op.params.get("size", 0.35)), 0.15, 0.6)
    ux, uy = _direction(frame, op.params.get("at"))
    w, d = frame.width * share, frame.depth * share
    reach = (frame.width - w) / 2.0 * float(op.params.get("reach", 0.55))
    # How far up the void reaches. Every subtractive volume in this grammar was
    # written to go clean through - `z=-height, h=3*height` in carve, notch and
    # puncture alike - so there was no way to take out the lower part of a mass
    # and leave the upper part standing. That is an arch, and it is also CCTV:
    # "고리가 수평이 아니라 수직으로 서서, 두 다리와 공중의 귀환부가 하나의
    # 회로를 이룬다". Written with `loop`, which rings a court in plan, the mass
    # came out as a flat donut - the opposite of its own sentence, and the
    # critics tagged it `sentence-contradicted` in three rounds running.
    #
    # The compiler subtracts per band, so a cutter with a bounded z-range cuts
    # only the bands it spans. The machinery was there; the word was not.
    # 1.0 is through, which is what every existing sentence gets.
    up_to = _clamp(float(op.params.get("up_to", 1.0)), 0.2, 1.0)
    # And whether it goes all the way across. A court is inboard on both axes
    # and leaves building on every side of it; an arch is open at both ends, and
    # what is left either side of it are two legs. Without this the void stays
    # square in plan however large it is, so `up_to` alone made a low recess in
    # a face rather than a hole you can see the sky through - measured on CCTV,
    # whose whole sentence is the two legs.
    through = bool(op.params.get("through", False))
    # Measured against what is standing, not against the frame. `frame.height`
    # is what the parcel affords, and a sentence that extrudes to a third of it
    # has a mass a third as tall - so `up_to` read off the frame put the top of
    # the cutter above the building and cut clean through. Milstein extrudes to
    # 4.2 m and its 0.55 asked for 6.6, which drew a doughnut where the sentence
    # says the ground passes under a plate.
    standing = max(
        (item.z_span()[1] for item in frame.placements if item.kind == "additive"),
        default=frame.height,
    )
    # What was taken out is a place, and the rest of the sentence may want to
    # be about it - a court that later moves alone is a hole; a court the
    # building turns around is a courtyard.
    frame.regulates(
        "court",
        Centre(
            (
                frame.cx + frame.out(ux * reach, uy * reach)[0],
                frame.cy + frame.out(ux * reach, uy * reach)[1],
            ),
            "carve",
        ),
    )
    # And its two long sides as lines, so the rest of the sentence can stand
    # *against* the court rather than only turn about it. A `Centre` has one
    # reader, `rotate about:`, and turning a volume about a courtyard is not
    # what makes a courtyard - the building coming up to its edge is. Three
    # blind judges wrote the same criticism of this corpus: no court organises
    # the site. The machinery was half there - `carve` has registered the
    # centre since courts were first cut, and `align` can now bring a face onto
    # a named line - so this is the missing half of the pair rather than a new
    # mechanism.
    court_x = frame.cx + frame.out(ux * reach, uy * reach)[0]
    court_y = frame.cy + frame.out(ux * reach, uy * reach)[1]
    along = frame.out(1.0, 0.0)
    across = frame.out(0.0, 1.0)
    for name, sign in (("court_side", 1.0), ("court_side_far", -1.0)):
        frame.regulates(
            name,
            Line(
                (court_x + across[0] * sign * d / 2.0,
                 court_y + across[1] * sign * d / 2.0),
                along,
                "carve",
            ),
        )
    frame.placements.append(
        frame.box(
            "court",
            w=w if abs(ux) >= abs(uy) or not through else frame.width * 1.2,
            d=frame.depth * 1.2 if through and abs(ux) >= abs(uy) else d,
            z=-frame.height,
            # Up from below the ground to wherever the sentence says it stops.
            h=frame.height + standing * up_to,
            dx=ux * reach, dy=uy * reach,
            kind="subtractive",
        )
    )


def _notch(frame: _Frame, op: Operation) -> None:
    """Take a bite out of a corner.

    `carve` aims at a side and reaches in; a notch belongs to a corner, and the
    book keeps them apart because they read differently - a court is a room the
    building holds, a notch is the building declining to occupy a corner. Two of
    the twenty combinations the book records are notches (Notch + Notch, Shift +
    Notch), and neither is expressible as a carve.
    """

    share = _clamp(float(op.params.get("size", 0.3)), 0.15, 0.5)
    ux, uy = _direction(frame, op.params.get("at"))
    # A corner, so both axes are committed. The named direction picks the long
    # side and the cross sign follows it rather than being a second parameter.
    sy = 1.0 if ux >= 0.0 else -1.0
    w, d = frame.width * share, frame.depth * share
    frame.placements.append(
        frame.box(
            "notch",
            w=w, d=d, z=-frame.height, h=frame.height * 3.0,
            dx=(ux if abs(ux) >= abs(uy) else sy) * (frame.width - w) / 2.0,
            dy=(uy if abs(uy) > abs(ux) else sy) * (frame.depth - d) / 2.0,
            kind="subtractive",
        )
    )


# How much of the span between the outer walls the wells may spread across.
# Kept off the edges, because a puncture that reaches one is a recess.
_PUNCTURE_INBOARD = 0.8


def _plan_of(item: Placement) -> Polygon:
    """The placement's own outline in world XY."""

    corners = item.corners()
    return Polygon([(c[0], c[1]) for c in corners[:4]]).convex_hull


def _puncture(frame: _Frame, op: Operation) -> None:
    """Drive a hole clean through, top to bottom.

    A court is open to the sky and stops at the ground; a puncture goes through
    the whole mass and is a route, a light well or a passage. `carve` already
    cuts a full-height void, so the difference the book draws is where it sits:
    a puncture is inboard, away from every edge, which is what makes it read as
    a hole rather than as a recess.
    """

    share = _clamp(float(op.params.get("size", 0.22)), 0.1, 0.45)
    count = int(_clamp(float(op.params.get("n", 1)), 1, 3))
    w, d = frame.width * share, frame.depth * share
    # Two wells with no floor between them are one well, and `n` was quietly
    # ignored for most of its range: the centres sit 0.8*(width - w)/(count + 1)
    # apart, which for any size at or above 0.21 is less than the hole's own
    # width. Measured over the corpus, six of the eight sentences that ask for
    # two or three wells deliver one - `sangok_three_light_gardens` declares
    # three light gardens and hands the jury a single slot - and the default
    # size, 0.22, is on the wrong side of the line.
    #
    # So the size gives way and the count does not: the count is what the
    # sentence is about, the size is a dimension the growth loop rescales
    # anyway. Solved rather than iterated - with centres (width - w)/k apart
    # over the inboard span, a plate that holds a storey survives between
    # neighbours when w <= (span * width - k * plate) / (span + k). A frame too
    # small even for that keeps one honest hole rather than delivering a merged
    # one under the name of three.
    placed: list = []
    if count > 1:
        k = count + 1
        widest = ((frame.width * _PUNCTURE_INBOARD - k * MINIMUM_STOREY_WIDTH_M)
                  / (_PUNCTURE_INBOARD + k))
        if widest < MINIMUM_STOREY_WIDTH_M:
            count = 1
        else:
            w = min(w, widest)
            d = min(d, widest)
    for index in range(count):
        # Spaced along the length rather than stacked on one spot, and kept off
        # the edges so each one is surrounded by building.
        along = (index + 1) / (count + 1) - 0.5
        cut = frame.box(
            f"puncture_{index}",
            w=w, d=d, z=-frame.height, h=frame.height * 3.0,
            dx=along * (frame.width - w) * _PUNCTURE_INBOARD,
            dy=0.0,
            kind="subtractive",
        )
        # And the arithmetic is checked against the delivered plan, because the
        # frame's own axes are not the world's and a formula that reads right
        # can still hand back two wells that touch. Only this word's own wells
        # are tested: a puncture that coincides with a court an earlier word
        # cut is that sentence's composition to answer for, and dropping it
        # here deleted both wells of `concave_plinth_folded_crown` and left a
        # solid block - worse than the merge this is meant to fix.
        plan = _plan_of(cut)
        if any(plan.intersects(_plan_of(other)) for other in placed):
            continue
        placed.append(cut)
        frame.placements.append(cut)




def _align(frame: _Frame, op: Operation) -> None:
    """Put a face of what this picks onto a line the composition already holds.

    Akin & Moustapha watched six architects mass a building and found the one
    mechanism structuring all of it: regulating elements - axes, centres,
    alignment lines - which let masses be added and removed while the structure
    underneath survives. This language had half of that. `_Frame.regulates`
    stores the lines, the site gives `spine`, `cross` and `street`, a `split`
    registers its own cut and a `carve` its court - and the only reader used a
    named element as the **pivot of one operation**. A shared pivot is not a
    shared alignment, and measured over the corpus it showed: 118 masses of two
    or more bodies, median 1.00 bodies per line, not one reaching three. Every
    part sat on its own line, which is the definition of a pile.

    This is the missing half. It slides, it does not turn: a volume with a face
    running within `_ALIGN_PARALLEL_DEG` of the line is brought until that face
    lies on it, and one standing askew to the line is left exactly where it
    stood. Turning it would be a different word - the sentence can say `rotate
    about:` for that - and a verb that quietly reorients what it was asked to
    align is the class of surprise this package keeps removing.

    The test is the bearing modulo ninety degrees, not modulo one-eighty, and
    that is deliberate: a volume square-on to the line has faces parallel to it
    at both ends, so a bar lying across a street still has a street-facing end
    to bring up to the kerb. What it excludes is the volume at forty-five
    degrees, which has no face to offer and would have to be turned.

    A volume that cannot be aligned is left alone rather than approximated, so
    the silence gate is what reports it. Same rule `cantilever` follows when a
    body is too short to fly.
    """

    picked, rest = _scope(frame, op)
    named = str(op.params.get("to") or op.params.get("about") or "").strip()
    line = frame.lines.get(named)
    if not picked or line is None:
        return
    # Which face: the near one by default, the far one when the sentence wants
    # the body to sit across the line rather than up against it.
    far = str(op.params.get("face") or "near").strip().lower() == "far"
    moved = _slide_onto(line, picked, frame.placements, far=far)
    if moved is None:
        return
    frame.placements = rest + moved
    # Kept so delivery can put them back. The roles rather than the placements,
    # because by the time the mass is delivered the growth loop has replaced
    # every one of these objects with a larger copy of itself.
    frame.alignments.append({
        "origin": tuple(line.origin),
        "direction": tuple(line.direction),
        "far": far,
        "roles": tuple(item.role for item in moved),
    })


def _slide_onto(line, picked, standing_all, *, far: bool):
    """Move each picked volume until a face of it lies on the line.

    Shared by the verb and by the delivery pass, so what a sentence says at
    execute and what the mass does at the end are the same rule rather than two
    that drift.
    """

    dx, dy = line.direction
    length = (dx * dx + dy * dy) ** 0.5
    if length < 1e-9:
        return None
    ux, uy = dx / length, dy / length
    # The line's own normal, which is the only direction a face can travel to
    # arrive on it without changing what the volume is.
    nx, ny = -uy, ux
    ox, oy = line.origin

    # Every other standing volume, so a slide can be checked against what it
    # would run into. Sliding is only alignment while the parts stay parts:
    # sent to a line that crosses their row rather than runs along it, three
    # towers pile into one lump and the gaps the sentence declared are gone.
    # Measured, the first version without this guard: `gap_closed` refusals 7
    # to 12, and `isbjerget` and `lab_city_saclay` refused outright, having
    # earned their higher regulating score by closing themselves up. The gate
    # caught what the measure rewarded, which is the gate working - but a verb
    # should not need to be caught, so it declines the move itself.
    others = [
        _plan(other) for other in standing_all
        if other is not None and other.kind == "additive"
    ]

    moved: list[Placement] = []
    for item in picked:
        plan = _plan(item)
        if item.kind != "additive" or plan.is_empty:
            moved.append(item)
            continue
        standing = [
            shape for shape in others
            if not shape.is_empty and not shape.equals(plan)
        ]
        clear_now = min(
            (plan.distance(shape) for shape in standing), default=float("inf"))
        # Off-axis volumes are not this word's business.
        minx, miny, maxx, maxy = plan.bounds
        reachable = max(maxx - minx, maxy - miny)
        bearing = math.degrees(math.atan2(item.matrix[1][0], item.matrix[0][0]))
        offset = abs((bearing - math.degrees(math.atan2(uy, ux))) % 90.0)
        if min(offset, 90.0 - offset) > _ALIGN_PARALLEL_DEG:
            moved.append(item)
            continue
        reach = [
            (x - ox) * nx + (y - oy) * ny
            for x, y in plan.exterior.coords
        ]
        if not reach:
            moved.append(item)
            continue
        # Slide by the signed distance of the chosen face, so that face lands
        # on the line and the volume keeps its size, its bearing and its height.
        travel = -(max(reach, key=abs) if far else min(reach, key=abs))
        if abs(travel) < 1e-9 or abs(travel) > reachable * 4.0:
            # Already there, or so far off that sliding would be a different
            # composition rather than an alignment.
            moved.append(item)
            continue
        slid = affinity.translate(plan, nx * travel, ny * travel)
        clear_after = min(
            (slid.distance(shape) for shape in standing), default=float("inf"))
        if clear_after < min(clear_now, JOINT_CLEARANCE_M) - 1e-6:
            # The slide would take this volume into a neighbour, or into the
            # gap it was keeping from one. That is a different composition, not
            # an alignment, and the sentence has other words for it.
            moved.append(item)
            continue
        moved.append(replace(item, matrix=validate_matrix4(compose_matrix4(
            item.matrix, translation_matrix4((nx * travel, ny * travel, 0.0)),
        ))))
    return moved


def delivered(form: MatrixForm, *, axis: tuple[float, float] | None = None,
              storey_m: float = 0.0) -> MatrixForm:
    """The mass about to ship: the sentence's lines, then the composition's.

    Every place that compiles a delivered mass goes through here - the run,
    the sequence sheet, the board's rebuild - so a seat is drawn as it was
    judged. `realign` puts back the lines the sentence named; `regulated`
    then snaps the near-alignments nobody named, which is what separates a
    composition from parts that happen to be close.
    """

    from backend.app.modules.design.generation.maas.massv2.regulate import regulated
    return regulated(realign(form), axis=axis, storey_m=storey_m)


def realign(form: MatrixForm) -> MatrixForm:
    """Put the sentence's alignments back on the mass that is about to ship.

    A sentence that says `align` is obeyed at execute and then disobeyed by
    everything after it: the growth loop widens each volume from its own
    centre, the coverage and siting variants move the composition, and the
    legal clip takes bites out of whatever crosses a setback. Measured, one
    sentence: 4.00 parts per line when the words finished, 2.00 by delivery,
    1.00 once the `dispersed` variant had it. The corpus median did not move at
    all when six sentences were authored with the verb.

    So the line survives as an intent rather than as a position. The same slide
    runs again here, on the grown and fitted volumes, under the same guard - a
    volume that would now have to shove a neighbour to reach the line stays
    where the growth left it, because by then the reason it cannot reach is
    that the building got bigger, and that is the law's answer, not a failure
    of the sentence.
    """

    alignments = (form.extra or {}).get("alignments") or ()
    if not alignments:
        return form
    placements = list(form.placements)
    for record in alignments:
        wanted = set(record.get("roles") or ())
        picked = [item for item in placements if item.role in wanted]
        if not picked:
            continue
        rest = [item for item in placements if item.role not in wanted]
        moved = _slide_onto(
            Line(tuple(record["origin"]), tuple(record["direction"]), "site"),
            picked, placements, far=bool(record.get("far")),
        )
        if moved is None:
            continue
        placements = rest + moved
    return replace(form, placements=tuple(placements))


def _approach(frame: _Frame, op: Operation) -> None:
    """Set the street face back so the ground floor has somewhere to be entered from.

    Three rounds of blind judging, six judges, and every one of them wrote the
    same sentence about this corpus: the masses are objects rather than sites,
    and the way in is not in the drawing. *"주출입·전면 마당·민원 동선이 매스에서
    전혀 읽히지 않는다"*, *"진입·전면 마당·민원실의 지상 접근이 어느 타일에도
    그려져 있지 않다"*, *"주소·마당·현관 같은 대지와의 접점이 캡션으로만 존재한다."*
    Nothing in this language could say it.

    `carve` cuts a court, which is inboard and held by the building on every
    side. `notch` declines a corner. Neither is an approach. What a 주민센터 owes
    is a piece of ground at the street that the building steps back from and
    then addresses - a forecourt, open on the street face, deep enough to stand
    in, and low, because it belongs to the ground floor and the storeys above it
    carry on over.

    So the cut is at the open side rather than aimed by name: `siting` already
    computes which edge of this parcel faces the lane, and the entrance is not a
    thing an author chooses independently of that. It runs the full depth of the
    volume it bites into so the recess opens to the street rather than being a
    pocket, and it stops after `storeys` floors - one by default - so what
    stands over the forecourt is building rather than sky.

    The face left behind is registered as `entry`, which makes it something the
    rest of the sentence can work with: `align to: entry` brings the other
    volumes onto the line the approach cut, which is how a forecourt becomes the
    thing the composition is arranged around rather than a bite out of one side.
    """

    picked, rest = _scope(frame, op)
    standing = [item for item in (picked or frame.placements) if item.kind == "additive"]
    if not standing:
        return
    # How much of the street face steps back, and how far in.
    width = _clamp(float(op.params.get("width", 0.4)), 0.2, 0.7)
    depth = _clamp(float(op.params.get("depth", 0.3)), 0.15, 0.5)
    # A forecourt is a ground-floor room without a ceiling of its own. One
    # storey by default: cut higher and the building loses its front instead of
    # opening it.
    storeys = _clamp(float(op.params.get("storeys", 1.0)), 1.0, 3.0)
    high = min(frame.storey * storeys, frame.height)

    # The street, as the site already knows it - but said in the frame's own
    # axes. `frame.axis` is a world vector and `box` offsets in frame terms, and
    # adding one to the other is the fault this package has written down twice:
    # the forecourt came out as a hole in the middle of the roof because the
    # offset was measured on the wrong pair of axes.
    radians = math.radians(frame.rotation)
    along = (math.cos(radians), math.sin(radians))
    across_world = (-along[1], along[0])
    world_x, world_y = frame.axis
    length = (world_x * world_x + world_y * world_y) ** 0.5 or 1.0
    world_x, world_y = world_x / length, world_y / length
    # The street direction, in frame coordinates.
    fx = world_x * along[0] + world_y * along[1]
    fy = world_x * across_world[0] + world_y * across_world[1]
    on_long = abs(fx) >= abs(fy)
    cut_w = frame.width * (depth if on_long else width)
    cut_d = frame.depth * (width if on_long else depth)
    # Metres, not a fraction. `box` offsets in the frame's axes but in real
    # dimensions - `carve` computes `(frame.width - w) / 2 * reach` for exactly
    # this - and passing a 0..1 share moved the recess by a third of a metre, so
    # the forecourt came out as a skylight in the middle of the roof twice.
    span = (frame.width - cut_w) if on_long else (frame.depth - cut_d)
    step = (1.0 if (fx if on_long else fy) >= 0.0 else -1.0) * span / 2.0

    frame.placements.append(
        frame.box(
            "approach",
            # Deep along the street's own direction, wide across it.
            w=cut_w,
            d=cut_d,
            z=-frame.storey,
            # Up from below the ground so the cut reaches it, and no further
            # than the storeys the sentence gave it.
            h=frame.storey + high,
            dx=step if on_long else 0.0,
            dy=0.0 if on_long else step,
            kind="subtractive",
            occupiable=False,
        )
    )
    # The inner face of the recess, so the composition can be arranged on it.
    inner = step - (cut_w * 0.5 if on_long else cut_d * 0.5) * (1.0 if step >= 0 else -1.0)
    origin = frame.out(inner if on_long else 0.0, 0.0 if on_long else inner)
    frame.regulates(
        "entry",
        Line(
            (frame.cx + origin[0], frame.cy + origin[1]),
            frame.out(0.0, 1.0) if on_long else frame.out(1.0, 0.0),
            "approach",
        ),
    )


def _lift(frame: _Frame, op: Operation) -> None:
    """Raise what is standing and put a smaller thing under it.

    Clearance is the one magnitude in this grammar that is not scale-free.
    Everything else is a ratio because everything else is set by the building's
    own proportions - but what makes a lift a lift is that a person passes
    underneath, and a person is the same height on every site. Kaktus, Grove
    and Grace Farms all lift by 0.15 of their height, which is ten metres or
    more on the buildings they were measured from; the same ratio on a 12.6 m
    parcel is 1.89 m, a crawl space. All three came back silent on every one of
    their variants, and they were right to: nothing was standing up.

    So the ratio sets the intent and the floor-viability minimum sets the
    dimension. A building too short to give that clearance and still be a
    building simply does not get lifted.

    The same argument bounds it from above, and only the floor was there. On a
    commercial parcel `frame.height` is 65 m, so the same 0.22 asks for a 14 m
    undercroft standing on 4 m sticks - and the plausibility gate let it pass,
    because a support is exempt from being as wide as a storey and nothing
    asked how tall an exempt thing may be. Rolex and Milstein went out as four
    towers with a block on top. A person passes under a lifted building, and
    the height a person passes under is a storey or two whatever the building
    is; past that the legs are the building and the room above is its hat.
    """

    picked, rest = _scope(frame, op)
    if not picked:
        return
    asked = _clamp(float(op.params.get("clearance", 0.22)), 0.1, 0.4) * frame.height
    room = max(frame.storey, DEFAULT_MINIMUM_CLEAR_DEPTH_M)
    clearance = _clamp(asked, DEFAULT_MINIMUM_CLEAR_DEPTH_M, room * MAX_UNDERCROFT_STOREYS)
    raised: list[Placement] = []
    for item in picked:
        # Lift is a world-space translation of the complete authored body.
        # Rebuilding from a plan box changes shear, custom boundaries and holes;
        # applying the old area compensation before retaining a custom boundary
        # also spends its void twice. Keep the local frame and all roof fields.
        matrix = compose_matrix4(item.matrix, translation_matrix4((0.0, 0.0, clearance)))
        raised.append(replace(item, matrix=validate_matrix4(matrix)))

    # Four supports, a third of the plan each, so what is raised spans between
    # neighbours rather than corner to corner. Two of them left a slab spanning
    # 632 times its own depth, which the span rule refused and was right to.
    # Slim enough to read as legs. At a third of the plate each, four of them
    # cover about 40% of what they carry and the drawing shows four blocks under
    # a slab rather than a slab held in the air - both judges of the fixed
    # benchmark said "nothing floats" of Maison Bordeaux while its geometry had
    # a 3.4 m gap in it. The old value was set against the span rule with *two*
    # supports; with four the span is halved and the plate still stands.
    leg = 0.24
    # Where the lifted volume was before it went up - reading the solids only.
    # A subtractive cutter is in scope like anything else, and a carve's cutter
    # is placed to reach in from outside the mass, so `min` over everything
    # picked took its depth instead: `b_heori_du_madang` (carve, pinch, lift)
    # stood its four legs at z -12.0 to -9.6, twelve metres underground, while
    # the body it was meant to hold floated at 2.4. The mass then had nothing
    # under it and the structure gate refused every variant of the sentence.
    standing = [item for item in picked if item.kind == "additive"] or picked
    stood_at = min((item.z_span()[0] for item in standing), default=0.0)
    # Size the supports from the translated solids, never from a cutter that
    # extends outside them. The authored body itself keeps its complete plan.
    solids = [item for item in raised if item.kind == "additive"] or raised
    base_x, base_y, base_w, base_d = _bounds_of(solids, frame)
    base_turn = 0.0
    # Sized and turned to the plate when there is one plate. `_bounds_of`
    # measures on the frame's axes, so once `lift` began keeping a volume's own
    # bearing the legs were handed a box bigger than the plate they hold:
    # measured on `oma_qatar_national_library`, the four supports grew from
    # 128.5 m2 to 172.5 and 6.1 m2 of them stood outside it. Several volumes
    # raised together have no single bearing, and those keep the frame's.
    if len(solids) == 1:
        base_w, base_d, base_turn = _own_plan(solids[0], frame)
    # The legs belong to whatever this lift was aimed at. Named plain
    # "support" they answered to no later word: Villa dall'Ava's shift moved
    # the raised apartment and left its four legs standing where the building
    # used to be. A verb's derived bodies carry the scope's role as a prefix -
    # the same ownership rule the relational verbs are written under - so the
    # word that moves the plate moves what holds it up.
    owner = str(op.params.get("on") or "").strip()
    leg_role = f"{owner}_support" if owner else "support"
    # The legs are structure, not floor area.
    #
    # A lift is a translation in z and a translation has a determinant of 1 -
    # the BOOK reads the word as Displace on p.20, the architectural
    # literature reads pilotis the same way (the mass is moved upward, the
    # ground is freed, the enclosed volume above is unchanged), and the tests
    # beside this one pin the body as a rigid translation: same plan, same
    # crown section, top and bottom both risen by exactly the clearance. That
    # contract IS the BOOK's reading and it is already kept.
    #
    # What made the word measure as an addition was the four legs, and the
    # answer is not to shave the body to pay for them - tried, and it breaks
    # the rigid translation the BOOK asks for. The legs are already marked
    # `occupiable=False` because that is what they are: columns are built and
    # they are not 연면적. A ruler that counts them counts the scaffolding as
    # the building.
    # Slender circular pilotis (원형 기둥)
    # Architectural proportion: slender cylinders (지름 0.55m ~ 0.85m), not massive boxes.
    col_dia = max(0.55, min(0.85, min(base_w, base_d) * 0.07))
    inset_x = max(col_dia * 1.5, base_w * 0.08)
    inset_y = max(col_dia * 1.5, base_d * 0.08)
    pos_x = base_w * 0.5 - inset_x
    pos_y = base_d * 0.5 - inset_y

    col_offsets = [
        (sx * pos_x, sy * pos_y)
        for sx, sy in ((-1, -1), (1, 1), (1, -1), (-1, 1))
    ]
    if base_w > 16.0:
        col_offsets.extend([(0.0, -pos_y), (0.0, pos_y)])
    if base_d > 16.0:
        col_offsets.extend([(-pos_x, 0.0), (pos_x, 0.0)])

    frame.placements = rest + raised + [
        frame.box(leg_role, w=col_dia, d=col_dia,
                  occupiable=False,
                  z=stood_at, h=clearance, turn=base_turn,
                  dx=base_x + _turned(ox, oy, base_turn)[0],
                  dy=base_y + _turned(ox, oy, base_turn)[1],
                  plan="circle")
        for ox, oy in col_offsets
    ]



def _loop(frame: _Frame, op: Operation) -> None:
    """Four bars round a court, held apart at the corners.

    A ring rather than a block with a hole: the bars are separate volumes that
    meet, which is how CCTV returns its thrust and how Louvre-Lens's volumes
    touch. The corner clearance is the joint every one of them holds.
    """

    depth = _clamp(float(op.params.get("bar", 0.26)), 0.15, 0.4)
    # A ring's bars are bars. `bar` is a share of the frame, so on a 60 m field
    # the 0.4 ceiling builds four volumes 24 m deep, which is twice as deep as
    # daylight reaches from both sides - a block, not a bar - and the four of
    # them close the court to 4% of the plan. CCTV came out a solid box with a
    # light shaft in it. The ceiling is the depth the corpus already builds
    # every daylit bar to, stated one file over: twice the daylit reach.
    lit = DAYLIT_DEPTH_PER_STOREY * (frame.storey or 3.0)
    bar_w = min(frame.width * depth, 2.0 * lit)
    bar_d = min(frame.depth * depth, 2.0 * lit)
    share = _clamp(float(op.params.get("height", 1.0)), 0.1, 1.0)
    h = frame.height * share
    # The bars run the full width and meet at the corners. A ring is one
    # structure - CCTV returns its thrust through the opposite leg, which is
    # why its overhang is not a cantilever - and the corner clearance belongs
    # between separate enclosures, not inside a single closed figure. Held
    # apart it reported itself as two buildings, correctly.
    # The four bars are the same height unless the sentence says otherwise.
    # They used to be h, 0.72h, 0.86h and 0.58h, hardcoded - so every ring in
    # the corpus arrived already broken into four heights, and a sentence whose
    # one decisive move was "draw one corner up" had nothing to draw it up
    # against. Looked at full size, CCTV came out as a jumble of bars rather
    # than a ring, and the reason was in the verb, not in the sentence.
    #
    # A ring that wants a step says it: `stack` or `shift` or `lift` aimed at
    # one bar, which is what the corpus does and what `on` is for.
    step = _clamp(float(op.params.get("step", 1.0)), 0.4, 1.0)
    # A ring has a middle, and it is the thing the ring is about.
    frame.regulates("court", Centre((frame.cx, frame.cy), "loop"))
    frame.placements.extend([
        frame.box("bar_n", w=frame.width, d=bar_d, z=0.0, h=h,
                  dy=(frame.depth - bar_d) / 2.0),
        frame.box("bar_s", w=frame.width, d=bar_d, z=0.0, h=h * step,
                  dy=-(frame.depth - bar_d) / 2.0),
        frame.box("bar_e", w=bar_w, d=frame.depth, z=0.0, h=h,
                  dx=(frame.width - bar_w) / 2.0),
        frame.box("bar_w", w=bar_w, d=frame.depth, z=0.0, h=h * step,
                  dx=-(frame.width - bar_w) / 2.0),
    ])


def _aggregate(frame: _Frame, op: Operation) -> None:
    """Objects inside a boundary, no two the same.

    SANAA's second mode: a pure figure holding N inscribed things. The sizes
    fan out rather than repeating - the corpus spreads them ten to twenty times
    in plan - because identical objects are the barracks again, and because a
    field with no largest object has nothing to read first.
    """

    count = int(_clamp(float(op.params.get("n", 4)), 2, MAX_FIELD_OBJECTS))
    spread = max(MIN_FIELD_SPREAD, float(op.params.get("spread", 1.6)))
    share = _clamp(float(op.params.get("height", 0.8)), 0.1, 1.0)
    # The boundary that makes a field one building. Kanazawa's boxes sit under
    # a single roof and Zollverein's rooms inside one cube; without it the
    # objects are what the gate said they were, five buildings on one parcel.
    tie = _clamp(float(op.params.get("tie", 0.18)), 0.0, 0.4)
    if tie > 0.0:
        # Where the tie sits is the whole reading. It is Kanazawa's roof and
        # Grace Farms' ribbon - the comment said so and the code put it on the
        # ground at z=0, which is a plinth. A plinth fills the lanes: judging
        # the delivered field, four independent readers wrote "the continuous
        # plinth binds them and no street reads through", "they sit on one
        # continuous podium, so the leftover space is slab, not garden" and
        # "the podium slightly blunts their separateness" - for
        # `nishizawa_towada`, `sejima_inujima_art_houses` and
        # `kr_gusandong_library_of_five_houses`, whose sentences are all about
        # what runs between the volumes.
        #
        # Lifted to the top of the shortest object it is a canopy: every object
        # reaches it, the ground between them stays open, and the sentence
        # `big_bay_view_canopy` writes - three separate low buildings held
        # together not by touching but by one thin roof plane lifted clear above
        # all of them - becomes sayable rather than approximated.
        shortest = frame.height * share * (0.55 + 0.45 / spread)
        frame.placements.append(
            # A boundary, not a room, so it is exempt from the one-storey floor
            # for the same reason a support is. Held to a storey it grew as
            # thick as the objects it binds and swallowed them, and a `taper`
            # aimed at one of them then changed the compiled mass by nothing.
            frame.box("field_plate", w=frame.width, d=frame.depth,
                      z=max(0.0, shortest - frame.height * tie * 0.5),
                      h=frame.height * tie, occupiable=False)
        )
    # A field may have no boundary at all, and then the objects are separate
    # buildings sharing a plot - which is what Moriyama and the Inujima Art
    # Houses are: ten volumes that never touch, with the village lanes between
    # them doing the circulating. The floor of 0.08 was there because a field
    # with no tie once read as five buildings on one parcel, but that reading
    # is not wrong for these, and holding every field together is what kept
    # grade articulation pinned at one however many objects were placed.

    # How the units gather is the book's own axis, separate from what a unit
    # is: the aggregation layer (BOOK 091-095) names Reflect, Pack, Stack,
    # Array and Join. The grid settlement below is Pack; everything this verb
    # had ever built was Pack, which is why a sentence saying "엇놓아 쌓고"
    # compiled as a village at grade - the pile it wrote was unsayable. `stack`
    # is 적층 (BOOK 093): units bearing on units, each level drifted and turned
    # past its carrier, and it takes any unit the later words shape - gabled,
    # bent, tapered - because the method never asks what it is stacking.
    # Reflect, Array and Join stay unimplemented until a sentence speaks them.
    method = str(op.params.get("method", "pack")).strip().lower()
    if method == "stack":
        # A stacked unit is a building riding on a building, so its height is
        # said in storeys - the same argument `lift` makes for clearance: the
        # storey is the human constant on every site. Divided from the
        # authored height budget instead, five units on a 12 m budget came out
        # 2.3 m each and the pile drew as planks; whether the whole pile is
        # too tall is the legal clip's question, not this word's.
        per = _clamp(float(op.params.get("storeys", 2)), 1.0, 5.0)
        level = per * frame.storey if frame.storey else frame.height * share / count
        # What a unit IS is the base-volume axis (BOOK 030), separate again
        # from how the units gather. A `house` unit is the archetypal pentagon
        # section: its depth comes from its own height, never from the parcel
        # - a bar 0.62 of a forty-metre parcel wore a 0.45 pitch as a bevelled
        # slab, because a roof reads as a house only when the section is
        # house-proportioned - and its two roof planes meet the ridge at 45
        # degrees by construction (drop = half the depth).
        unit_kind = str(op.params.get("unit", "slab")).strip().lower()
        # A pile has a wider foot than its crown. One unit per level made the
        # pile a tower of bars - slenderness 6.7 against a 4.2 ceiling, a fifth
        # of the mass off the ground, every upper bar a backspan violation -
        # and VitraHaus itself is twelve houses on five levels, not five on
        # five. Units spread over levels, the spare ones landing low.
        levels = int(_clamp(float(op.params.get("levels", (count + 1) // 2)), 1, count))
        # How far a unit slides along its own long axis, as a share of its
        # length, alternating ends level by level - the flying bar ends that
        # make VitraHaus VitraHaus. Zero by default: the pile's conservative
        # habit (centres over centres) stays unless the sentence asks its ends
        # to fly, and whether a flight stands is the cantilever gate's
        # question - the gate was recalibrated on this very building (1.45 of
        # backspan) and no word could ask for what it allows.
        reach = _clamp(float(op.params.get("reach", 0.0)), 0.0, 0.6)
        base_n, extra = divmod(count, levels)
        counts = [base_n + (1 if lvl < extra else 0) for lvl in range(levels)]
        z = 0.0
        index = 0
        for lvl, in_level in enumerate(counts):
            turn = float(op.params.get("turn", 0.0)) * (1 if lvl % 2 else -1)
            rise = lvl / max(levels - 1, 1)
            h = max(level, frame.storey)
            # Neighbours in a level stand side by side across the pile's
            # cross axis; the level itself drifts as it rises, gently
            # enough that its centre stays over the level below.
            # Room for the unit as TURNED, not as drawn: a bar of length
            # w rotated th needs w*|sin th| of cross-axis air, and spacing
            # computed on the untumed depth alone is why the jackstraw
            # piles crossed. The pack branch already spaces on clearance;
            # the stack branch now owes the same debt. And the debt is paid
            # cumulatively: the size fan shrinks each unit, so slot-index
            # times own-extent left uneven gaps and units 3+ interpenetrated.
            rad_level = math.radians(turn)
            dims: list[tuple[float, float, float]] = []
            for j in range(in_level):
                scale = 1.0 / (spread ** ((index + j) / max(count - 1, 1)))
                w = frame.width * 0.62 * scale
                d = frame.depth * 0.62 * scale
                if unit_kind == "house":
                    d = min(d, HOUSE_ASPECT * h)
                cross_extent = (
                    d * abs(math.cos(rad_level)) + w * abs(math.sin(rad_level))
                )
                dims.append((w, d, cross_extent))
            rows: list[float] = [0.0]
            for j in range(1, in_level):
                rows.append(
                    rows[-1]
                    + (dims[j - 1][2] + dims[j][2]) / 2.0
                    + JOINT_CLEARANCE_M
                )
            middle = (
                (rows[0] - dims[0][2] / 2.0 + rows[-1] + dims[-1][2] / 2.0)
                / 2.0
            )
            for j in range(in_level):
                w, d, _cross = dims[j]
                row = rows[j] - middle
                drift_x = 0.10 * frame.width * rise * (1 if lvl % 2 else -1)
                drift_y = row + 0.06 * frame.depth * rise * (1 if (lvl // 2) % 2 else -1)
                # The slide is along the unit's own turned axis, ground level
                # held still - a flight needs something under its heel.
                if reach > 0.0 and lvl > 0:
                    slide = reach * w * (1 if index % 2 else -1)
                    rad = math.radians(turn)
                    drift_x += slide * math.cos(rad)
                    drift_y += slide * math.sin(rad)
                box = frame.box(
                    f"object_{index}",
                    w=w, d=d, z=z, h=h,
                    dx=drift_x, dy=drift_y, turn=turn,
                )
                if unit_kind == "house":
                    pitch = _clamp((d / 2.0) / h, 0.15, 0.9)
                    frame.placements.extend(gabled_halves(frame, box, pitch))
                else:
                    frame.placements.append(box)
                index += 1
            z += h
        return

    # Objects sit in the cells of a loose grid rather than in a table of corner
    # slots. The table held six, and six was the ceiling on how many bodies this
    # whole grammar could stand at grade - `split` divides a field, it does not
    # multiply one, so no combination of words could get past it. Moriyama is
    # ten volumes, Nishinoyama ten dwellings, Towada one per artwork; a field
    # that cannot count past six cannot say any of them.
    #
    # A grid also guarantees what the corner table only got away with at small
    # counts: every object has its own cell, so none of them overlap however
    # many there are.
    columns = max(1, int(ceil(sqrt(count))))
    rows = max(1, int(ceil(count / columns)))
    cell_w = frame.width / columns
    cell_d = frame.depth / rows
    # Where the units stand relative to one another. A grid is one answer and
    # was the only one: every figure that turns about a point - pinwheel, fan,
    # Y, splayed wings around a court - needs the field itself to rotate, and
    # no parameter said so. `turn` above turns each unit in place, which is a
    # different claim (a settlement askew of itself, Moriyama) and stays.
    arrangement = str(op.params.get("arrangement", "pack")).strip().lower()
    if arrangement not in ("pack", "radial", "pinwheel"):
        arrangement = "pack"
    # The ring the units stand on, and how big each may be on it: the chord
    # between neighbours, so they sit close without overlapping however many
    # there are.
    ring = 0.32 * min(frame.width, frame.depth)
    chord = 2.0 * ring * sin(pi / max(count, 2)) if count > 1 else ring
    for index in range(count):
        column, row = index % columns, index // columns
        # Size fans out across the whole field, and the smallest object is held
        # to a storey: the old height divisor of 1/(1+0.3i) put the ninth object
        # at a quarter of the first, which the storey gate refuses and rightly.
        scale = 1.0 / (spread ** (index / max(count - 1, 1)))
        w = (cell_w - JOINT_CLEARANCE_M) * 0.86 * scale
        d = (cell_d - JOINT_CLEARANCE_M) * 0.86 * scale
        # Cells alternate their offset so the result reads as a settlement
        # rather than as a barracks - the thing the size fan exists to avoid,
        # asked of position as well as of size.
        drift = 0.14 * (1 if (column + row) % 2 else -1)
        # And a bearing, which is the third property an object has and the only
        # one this verb left uniform. The argument in the docstring above - that
        # identical objects are the barracks again - was being applied to size
        # and to position and not to which way a thing faces. Measured over the
        # delivered sixteen, fifteen carried exactly one bearing in the entire
        # mass, which is what reads as a stack of bricks.
        #
        # Silent unless the sentence asks: a loose settlement is a claim about
        # this building, not a property of every field. Moriyama and the Inujima
        # houses sit askew of one another; Kanazawa's boxes do not.
        #
        # It is a parameter and not a verb on purpose. A turn written as its own
        # word costs the sentence a word, and `spoken_force` is the mean redraw
        # per word - measured, adding a `rotate` to ACC Gwangju drops it from
        # 0.303 to 0.283 even at 45 degrees, so the selector would refuse every
        # sentence that tried to stop looking like a brick.
        turn = float(op.params.get("turn", 0.0))
        turn *= (1 if (column * 2 + row) % 3 else -1)
        turn *= 0.4 + 0.6 * (index / max(count - 1, 1))
        if arrangement in ("radial", "pinwheel"):
            # On the ring, facing the centre. The unit is a bar pointing at the
            # middle - which is what makes a fan read as a fan rather than as
            # boxes on a circle - and the pinwheel turns each one a quarter
            # further so the whole field spins.
            angle = 2.0 * pi * index / max(count, 1)
            bearing = degrees(angle)
            turn = bearing + (90.0 if arrangement == "pinwheel" else 0.0)
            # The radial reach first, then the tangential width measured at
            # the unit's INNER end where the arc is narrowest. The chord at the
            # ring is the spacing of the CENTRES, and sizing by it overlapped
            # every neighbour from six units up - a twelve-unit pinwheel
            # arrived as one fused body, the opposite of the verb. A joint
            # clearance comes off, as the grid branch takes one off its cells.
            reach = max(ring * 0.7 * scale, frame.storey)
            inner = max(ring - reach / 2.0, 0.25 * ring)
            span = 2.0 * inner * sin(pi / max(count, 2)) - JOINT_CLEARANCE_M
            span = max(span * scale, frame.storey * 0.9)
            # `turn` rotates the box, so a pinwheel's local w axis runs along
            # the arc while d points at the centre: the two swap.
            w, d = (span, reach) if arrangement == "pinwheel" else (reach, span)
            radial_dx = ring * cos(angle)
            radial_dy = ring * sin(angle)
        frame.placements.append(
            frame.box(
                f"object_{index}",
                w=w, d=d, z=0.0,
                # A storey is the floor, not a fraction of the tallest. The
                # comment above records why a floor exists at all - an old
                # divisor put the ninth object at a quarter of the first and
                # the storey gate refused it - but `0.55 + 0.45 * scale` caps
                # the height spread at 1/0.55 = 1.82 however far the sentence
                # fans the field, and delivered a median of 1.12 across the
                # corpus. Across thirty-two works by BIG, OMA and SANAA the
                # repeated volumes of a field spread 2 to 4 in height, and
                # Nishizawa refused identical units at Moriyama in as many
                # words: they "looked like a barracks". So the size fan runs
                # all the way and the storey rule stops it, which is the same
                # discipline `_storeys` holds one file over.
                h=max(frame.height * share * scale, frame.storey),
                dx=(radial_dx if arrangement in ("radial", "pinwheel")
                    else (column + 0.5 + drift) * cell_w - frame.width / 2.0),
                dy=(radial_dy if arrangement in ("radial", "pinwheel")
                    else (row + 0.5 - drift) * cell_d - frame.depth / 2.0),
                turn=turn,
            )
        )


_VERBS = {
    "split": _split,
    "extrude": _extrude,
    "stack": _stack,
    
    
    "carve": _carve,
    "approach": _approach,
    "lift": _lift,
    "align": _align,
    "loop": _loop,
    "aggregate": _aggregate,
    # The book's own operation list runs to thirty and this grammar spoke nine
    # of them. These five ask nothing new of the machinery - the rotation and
    # lean terms have been in `place` since it was written, `form.stack` has
    # carried `twist_degrees` since it was written, and both were dead. What
    # was missing was a word.
    "notch": _notch,
    "puncture": _puncture,
    
    # Grade is the book's stepped profile, and the only way this grammar can
    # say a terraced section. `skew` leans a prism and `taper` narrows on every
    # side; neither is a slope you can stand on.
    
    # Verbs that are one matrix on volumes already standing live in `ops.affine`
    # and are written as (which volumes, which operator, about what pivot). The
    # ones above bring volumes into being or cut them, which is a different kind
    # of statement and stays here until it has a module of its own.
    **AFFINE_VERBS,
    **SWEPT_VERBS,
    **PIERCING_VERBS,
    **GRAFTING_VERBS,
    # What one body does to another - the book's last seven words
    # (Merge, Nest, Interlock, Lodge, Overlap, Extract, Inscribe).
    **RELATIONAL_VERBS,
    # The BOOK's aggregation layer, pages 50 to 58: `array`, `reflect`, `pack`
    # and `join`. Thirty-one of its thirty-five words had a massv2
    # implementation and these four had none - not because they cannot be
    # said, but because nobody wrote them.
    **AGGREGATION_VERBS,
}


class MissingOperationDependency(ValueError):
    """A valid operation has no selected body because its creator is absent."""


def _shape(frame: _Frame, op: Operation) -> None:
    """Apply an authored local region and bounded surfaces to selected bodies.

    Data uses Placement.from_record's public schema, so parser, production and
    sequence execution all deliver the same material. Existing legal, room and
    structural gates continue to read the compiled result.
    """
    fields = {"plan_region": op.params.get("plan_region"),
              "top_surface": op.params.get("top_surface"),
              "bottom_surface": op.params.get("bottom_surface")}
    fields = {key:value for key,value in fields.items() if value is not None}
    if not fields:
        raise ValueError("shape requires plan_region, top_surface or bottom_surface")
    picked, rest = _scope(frame, op)
    rest += [item for item in picked if item.kind != "additive"]
    picked = [item for item in picked if item.kind == "additive"]
    if not picked:
        raise MissingOperationDependency("shape requires an existing selected body")
    shaped = []
    for item in picked:
        record = {**item.to_record(), **fields}
        if "top_surface" in fields:
            # A declared surface takes full ownership of its top. Old roof
            # tags must not make the new underside follow an unrelated warp.
            record.update(top_drop=0.0, drop_toward=None, ridge_along=None,
                          top_profile=None, profile_across=None, warp=None)
        shaped.append(Placement.from_record(record))
    frame.placements = rest + shaped


_VERBS["shape"] = _shape


CROWN_FORMS = ("dome", "dish", "saddle")


def crown_terms(form: str, sag: float, *, along_x: bool = True) -> tuple[tuple[int, int, float], ...]:
    """Polynomial terms of a named top in the unit plan. Pure; the tests read it."""

    s = float(sag)
    if form == "dome":
        # 1 - 2s((x-.5)^2 + (y-.5)^2)
        return ((0, 0, 1.0 - s), (1, 0, 2 * s), (2, 0, -2 * s), (0, 1, 2 * s), (0, 2, -2 * s))
    if form == "dish":
        # 1 - s + 2s((x-.5)^2 + (y-.5)^2)
        return ((0, 0, 1.0), (1, 0, -2 * s), (2, 0, 2 * s), (0, 1, -2 * s), (0, 2, 2 * s))
    if form == "saddle":
        # 1 - s/2 + 2s((x-.5)^2 - (y-.5)^2); `along` swaps which axis rises
        a, b = ((1, 0), (0, 1)) if along_x else ((0, 1), (1, 0))
        return ((0, 0, 1.0 - s / 2), (a[0] * 2, a[1] * 2, 2 * s), (a[0], a[1], -2 * s),
                (b[0] * 2, b[1] * 2, -2 * s), (b[0], b[1], 2 * s))
    raise ValueError(f"crown form must be one of {CROWN_FORMS}, not {form!r}")


def _crown(frame: _Frame, op: Operation) -> None:
    """Give the selected bodies a two-variable top named by a word.

    `roof` lays a separate warped sheet over a body; this shapes the body's
    own top, so the rooms under a dome are under a dome. The surface is a
    polynomial in the body's unit plan and rides the same typed path as
    `shape`: it compiles, slices, gates and renders without a new branch.
    `sag` is the share of the body's band the top moves through (0.1-0.6).
    """

    form = str(op.params.get("form") or "dome")
    sag = float(op.params.get("sag") if op.params.get("sag") is not None else 0.35)
    if not 0.05 <= sag <= 0.6:
        raise ValueError(f"crown sag must be within 0.05..0.6, not {sag}")
    along = str(op.params.get("along") or "long")
    terms = crown_terms(form, sag, along_x=(along != "cross"))
    surface = {"type": "polynomial", "terms": [list(t) for t in terms]}
    picked, rest = _scope(frame, op)
    rest += [item for item in picked if item.kind != "additive"]
    picked = [item for item in picked if item.kind == "additive"]
    if not picked:
        raise MissingOperationDependency("crown requires an existing selected body")
    crowned = []
    for item in picked:
        record = {**item.to_record(), "top_surface": surface}
        # The named top owns the top: earlier roof tags must not warp it.
        record.update(top_drop=0.0, drop_toward=None, ridge_along=None,
                      top_profile=None, profile_across=None, warp=None)
        crowned.append(Placement.from_record(record))
    frame.placements = rest + crowned


_VERBS["crown"] = _crown


def execute(
    parti: Parti,
    *,
    buildable: Polygon,
    axis: tuple[float, float],
    height_m: float,
    storey_height_m: float = 0.0,
) -> MatrixForm | None:
    """Turn a sentence into placed volumes on this parcel.

    The last frame of `execute_steps`, rather than a second copy of the same
    loop. There were two, and keeping them in step was left to whoever edited
    one: adding the base-shape parameter to the stepped loop alone meant the
    whole pipeline still built squares while the check that reads the steps
    reported the shapes correctly. One loop is the only version of this that
    cannot drift.
    """

    steps = execute_steps(
        parti, buildable=buildable, axis=axis, height_m=height_m,
        storey_height_m=storey_height_m,
    )
    return steps[-1][1] if steps else None


def execute_steps(
    parti: Parti,
    *,
    buildable: Polygon,
    axis: tuple[float, float],
    height_m: float,
    storey_height_m: float = 0.0,
) -> list[tuple[Operation, MatrixForm]]:
    """The same sentence, stopped after each word.

    A parti is published as an ordered list of moves with one caption each -
    79&Park is EXTRUSION, POROSITY, DAYLIGHT, LANDMARK, one drawing per line -
    and that sequence is what makes the offices' massing read as an argument
    rather than a shape. We were compiling the whole sentence and drawing only
    its last word, which throws away the reasoning the author already wrote:
    every operation carries its own `why`.

    Nothing new is generated here. Running the same handlers over the same
    frame and taking a copy after each one costs one extra compile per word.
    """

    frame = _Frame(buildable, axis, height_m, storey_m=storey_height_m,
                   base_volume=parti.base_volume,
                   base_orientation=parti.base_orientation)
    if frame.base_volume_too_short:
        # The sentence asked for a base volume shorter than a storey. Delivering
        # the next one up would hand back a different building under the same
        # words, which is the fault this grammar spends most of its gates
        # catching elsewhere.
        return []
    steps: list[tuple[Operation, MatrixForm]] = []
    for op in parti.ops:
        handler = _VERBS.get(op.verb)
        if handler is None:
            continue
        # A base shape belongs to the composition, so naming one anywhere in
        # the sentence sets it for everything the sentence goes on to build.
        named = str(op.params.get("profile") or "").strip().lower()
        if named in plan_names():
            frame.profile = named
        handler(frame, op)
        form = _form_from(frame, parti)
        if form is not None:
            steps.append((op, form))
    return steps


def _form_from(frame: _Frame, parti: Parti) -> MatrixForm | None:
    if not [item for item in frame.placements if item.kind == "additive"]:
        return None
    return MatrixForm(
        name=parti.name,
        placements=tuple(frame.placements),
        primary_language=parti.primary_language,
        secondary_language=parti.secondary_language,
        formal_principle=parti.formal_principle,
        dominant_gesture=parti.dominant_gesture,
        reference_basis=parti.reference_basis,
        floor_height_m=parti.floor_height_m,
        extra={
            "parti": parti.evidence(),
            "plot_mode": parti.plot_mode(),
            # A field spreads; it does not stack. Kanazawa is one storey, and
            # the objects in a field are small - let the growth loop buy floor
            # area with height and they come back as a bundle of sticks on a
            # plinth, which is what they did. If a field cannot fill its 용적률
            # lying down, the honest answer is that it does not fill it.
            "growth": parti.growth if parti.growth is not None else ("plan"
            if any(
                op.verb == "aggregate"
                and str(op.params.get("method") or "pack") != "stack"
                for op in parti.ops
            )
            else "both"),
            # A stacked aggregation grows by rising - that is what stacking
            # IS - and labelling every aggregate "plan" locked the vitrahaus
            # pile out of height growth while the coverage lift crushed it:
            # eleven delivered variants at zero storeys. pack stays plan-
            # bound for the reason above; stack earns "both".
            # Which volumes were sent to which line. `realign` reads it just
            # before the mass is compiled, so what the sentence said survives
            # the growth loop, the variants and the clip.
            "alignments": tuple(frame.alignments),
        },
    )


__all__ = ["execute", "execute_steps"]
