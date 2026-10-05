"""A mass as an ordered list of operations on a site-derived seed.

The archive repeated itself because the vocabulary was sixty-one finished
compositions - volume coordinates, authored once - and everything downstream
only resized and repositioned them. Sixteen grid cells came back as sixteen
variants of the same catalogue rather than sixteen buildings. A catalogue can
only ever be re-sorted.

So the unit of authorship is a sentence, not a picture. BIG publish their own
partis exactly this way, one operation per diagram caption - 79&Park is
EXTRUSION -> POROSITY -> DAYLIGHT -> LANDMARK - and every one of OMA's fifteen
patents in *Content* is a transformation of a known type rather than a form
from nothing. Earlier corpus preferences for unequal bodies were encoded as
universal restrictions. They are not universal: repeated equal bodies can
organize different frontages, overlaps and courts. Authored relations must be
executed and checked rather than silently replaced with preferred proportions.

The seed comes from the parcel, so the site is present from the first move
rather than arriving at the end as a cutter. The executor owns supported
geometry and parameter semantics; site and structural screens remain separate.
What the author chooses is which
operations, in what order, and toward what on this particular site. Magnitude
is geometric; direction is programmatic - Seattle's shear is 0.26 of its plan
depth, and its engineers state the direction was picked "not on structural
balance but rather to maximize views and capture desired light and shadow".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from shapely.geometry import Polygon

from backend.app.modules.design.generation.maas.massv2.form import MatrixForm, Placement, place


# Below this an offset reads as a construction tolerance rather than a move;
# above it the volume stops reading as the same volume, displaced. Measured
# across the corpus: De Rotterdam 8.88 m on a 36 m plan depth = 0.25, Seattle
# 15.8 m on a 61 m plate = 0.26, Timmerhuis 21 m = exactly three 7.2 m modules.
MIN_OFFSET_RATIO = 0.15
# Seattle Central Library moves its platforms by half to nine tenths of their
# own plan, and the result is more legible for it, not less. The old ceiling
# said that past 0.35 "the volume stops reading as displaced", which is an
# observation this corpus contradicts: what it actually guaranteed was that
# every sentence came out moderate, and moderate composed three times is a
# composition rather than a diagram. Whether a displaced volume still stands is
# `structure`'s question and it is still asked.
MAX_OFFSET_RATIO = 0.9

# Legacy split/sampler contrast. This is not a universal architectural rule:
# equal occupied bodies can form a deliberate rotated or offset composition.
MIN_TIER_CONTRAST = 1.25

# Authored stack dimensions: unity preserves equal tiers; grow selects the
# direction of the size progression. Validation consumes this same interval.
# Keep the existing default and ceiling; remove only forced inequality.
STACK_CONTRAST_RANGE = (1.0, 3.5)
DEFAULT_STACK_CONTRAST = 1.35

# Two volumes meeting hold a joint rather than merging: Toledo keeps 760 mm
# everywhere its cells meet, two glass walls and not one, and Louvre-Lens's five
# volumes touch only at their corners. One declared union in thirty-two projects.
JOINT_CLEARANCE_M = 0.76


PlotMode = Literal["inherit", "impose"]


@dataclass(frozen=True)
class Operation:
    """One move, and what it does to the site's shape.

    `plot_mode` is the finding that matters most here. Conforming to the plot
    is a property of the operation, not a setting for the whole run: stacking
    and shearing inherit the plot outline, while carving, looping and
    aggregating impose an independent shape and sit at 30-56% coverage.
    Kanazawa is a mathematically pure 112.5 m circle dropped on an irregular
    park. Applied globally, clipping turned every mass into a faceted cast of
    the parcel; refused globally, ground take collapsed to 0.38.
    """

    verb: str
    plot_mode: PlotMode
    params: dict[str, Any] = field(default_factory=dict)
    why: str = ""

    def evidence(self) -> dict[str, Any]:
        return {"verb": self.verb, "plot_mode": self.plot_mode, "params": dict(self.params), "why": self.why}


# The operations, with the plot relationship each one carries.
PLOT_MODES: dict[str, PlotMode] = {
    "shape": "impose",
    "crown": "impose",
    "split": "inherit",
    "extrude": "inherit",
    "stack": "inherit",
    # The stepped stack that used to be called `shear`. It slides volumes
    # inside a mass that still takes the plot's outline, which is the reading
    # that put it here in the first place.
    "stagger": "inherit",
    # And `shear` is the BOOK's p.32 oblique cut now, so it imposes for the
    # same reason `carve` and `grade` do: a void is the point of the scheme and
    # a clip to the boundary erases it.
    "shear": "impose",
    # 내밈. A slide inside a mass that still takes the plot's outline.
    "cantilever": "inherit",
    "taper": "inherit",
    # The book's Bend (연결을 유지하며 방향을 꺾음) and Pinch (중앙 양측을 깎아
    # 좁힘). Both transform what is standing rather than imposing a shape, so
    # they inherit - and both were being said with stand-ins before they
    # existed: a `rotate` for VM Houses' kinked bars, a `compress` for Eight
    # House's waist. The stand-ins turn or shrink a part; neither can kink a
    # bar at a joint or close a waist while leaving both ends full.
    "bend": "inherit",
    "pinch": "inherit",
    # The book's Intersect (두 볼륨을 서로 관통시킴). The bar is aimed across
    # what is standing, so it inherits the standing frame.
    "intersect": "inherit",
    # Branch (하나의 줄기에서 여러 팔) and Embed (제2 볼륨을 제1에 삽입). Both
    # grow off what is standing, in the host's own unit space, so they inherit.
    "branch": "inherit",
    "fracture": "inherit",
    # 박공. Tried once as a staircase and reverted by measurement; with
    # `top_drop` in the IR it is two real planes meeting at a ridge. The
    # butterfly and the mansard are the same top profile with the folds
    # elsewhere - a valley, a pair of shoulders.
    "gable": "inherit",
    "butterfly": "inherit",
    "mansard": "inherit",
    # 볼트. A polyline with enough vertices is a curve, so the barrel needed
    # the word rather than a new primitive.
    "vault": "inherit",
    # 접힌 판. The same polyline with its breaks left in rather than sampled
    # away - a concertina is a vault that admits it has corners.
    "fold": "inherit",
    # A void imposes, for the reason written four lines down about `inscribe`:
    # a cut takes the plot's outline rather than the host's. `embed` used to
    # add a body and inherited with `branch`; now that it delivers the void the
    # BOOK reads on p.36 it belongs with `inscribe` and `carve`.
    "embed": "impose",
    # The book's volume-to-volume family (BOOK 045/046/052/055/056/068/069),
    # said in the host's own unit space like branch and embed, so they inherit
    # - except inscribe, which is a void, and a void imposes for the same
    # reason carve does.
    "merge": "inherit",
    "nest": "inherit",
    "interlock": "inherit",
    "lodge": "inherit",
    "overlap": "inherit",
    "extract": "inherit",
    "inscribe": "impose",
    "canopy": "inherit",
    "roof": "inherit",
    "carve": "impose",
    "lift": "impose",
    # 정렬. A slide onto a line the composition already holds, so the mass still
    # takes the plot's outline - the line is the composition's, not a new shape.
    "align": "inherit",
    "loop": "impose",
    "aggregate": "impose",
    # The ten below were added to the executor and never added here, so the
    # parser dropped them - six words across the corpus, and `skew` three times,
    # which is why Mountain Dwellings' 30-degree ramp never appeared. Worse
    # than being wrong: the postcondition check judges the ops it was *given*,
    # so a word lost at parse time is never reported silent. The sentence said
    # three things, two were built, and nothing anywhere said so.
    #
    # `_VERBS` and this table must name the same verbs; a test holds them equal.
    #
    # Which mode follows what the verb does to the figure. A void or a turn is
    # the point of the scheme and a clip to the boundary erases it, so those
    # impose; a slide or a size change is a move inside a mass that still takes
    # the plot's outline, so those inherit - the same reading that puts `shear`
    # and `taper` on one side and `carve` on the other.
    "grade": "impose",
    "notch": "impose",
    # The forecourt at the street. Judged three rounds running as the thing this
    # language could not say.
    "approach": "impose",
    "puncture": "impose",
    "twist": "impose",
    "rotate": "impose",
    "skew": "inherit",
    "shift": "inherit",
    "sink": "inherit",
    # Now that it delivers a twin rather than moving the host, it takes the
    # host's own outline like the other relational words.
    "offset": "inherit",
    "expand": "inherit",
    "compress": "inherit",
    "inflate": "inherit",
    # The BOOK's aggregation layer (pp.50-58). These four were added to
    # `_VERBS` and not to this table - the identical fault the ten above
    # record, made a second time, and the measurement said so at once: the
    # three that place a body read 0.00% change because the parser had already
    # thrown them away.
    #
    # Three impose. An array's copies and a reflection's twin stand outside the
    # host's own outline, and a pack's legibility is the gap between its
    # pieces: clipping to the boundary would eat the outer copies and leave a
    # broken run rather than a smaller one, which is the reading that put
    # `aggregate` and `loop` on this side. `join` inherits - the bridge is said
    # in the host's unit space and reaches its neighbour, like `merge`.
    "array": "impose",
    "reflect": "impose",
    "pack": "impose",
    "join": "inherit",
}


def plot_mode_of(ops: tuple[Operation, ...]) -> PlotMode:
    """One mode per composition: imposing anywhere means imposing.

    A scheme that carves a court out of a stack is not a cast of the parcel
    with a hole in it - the court is the point, and clipping it back to the
    boundary is what erases the move.
    """

    return "impose" if any(op.plot_mode == "impose" for op in ops) else "inherit"


@dataclass(frozen=True)
class Parti:
    """A named sequence of operations, with the reason each one is there."""

    name: str
    ops: tuple[Operation, ...]
    primary_language: str
    secondary_language: str = ""
    formal_principle: str = ""
    dominant_gesture: str = ""
    reference_basis: str = ""
    floor_height_m: float | None = None
    growth: str | None = None
    # The BOOK's first move, which this grammar never had. A base operative is
    # three parts - choose a relative base volume and an orientation, perform
    # one action, explore the action's bounded variations - and massv2 only
    # ever had the middle one: every sentence started from `seed_rectangle`,
    # the parcel's own extent, so every mass began as the plot. Six fractions
    # and three orientations are eighteen openings nothing here could say.
    # Silence still means 1/1 on the open side, so the corpus is unaffected.
    base_volume: str | None = None
    base_orientation: str | None = None

    def plot_mode(self) -> PlotMode:
        return plot_mode_of(self.ops)

    def evidence(self) -> dict[str, Any]:
        return {
            "schema_version": "arr.maas.massv2_parti.v1",
            "name": self.name,
            "plot_mode": self.plot_mode(),
            "operations": [op.evidence() for op in self.ops],
            **({"growth": self.growth} if self.growth is not None else {}),
            **({"base_volume": self.base_volume} if self.base_volume else {}),
            **({"base_orientation": self.base_orientation}
               if self.base_orientation else {}),
        }


# Words whose value is drawn from a fixed list. An axis slot holding
# something else is the dangerous case: `_along_is_x` reads anything that is
# not cross/short/side as "long", so a sentence that wrote a role name where
# an axis belongs - `along: "west_arm|rest"`, four times in this corpus - was
# obeyed as "long" and the silence gate passed it, because the word did do
# something. It did the wrong thing, quietly, which is worse than doing
# nothing. Unknown verbs were already refused rather than guessed at; the
# same rule belongs on their arguments.
_AXIS_WORDS = frozenset({
    "long", "cross", "short", "side", "corner", "diagonal",
    "open", "to_open", "off_open", "back", "front",
})
# The BOOK's own six fractions and three orientations, from
# `book_language.corpus_contract`. Named here rather than imported so the
# grammar stays readable on its own; the conformance test holds them equal.
BASE_VOLUME_LABELS = frozenset({"1/1", "3/8", "1/2", "1/4", "1/8", "1/16"})
BASE_ORIENTATIONS = frozenset({"long_axis", "short_axis", "vertical"})

_ENUMERATED: dict[str, frozenset[str]] = {
    "along": _AXIS_WORDS,
    "toward": _AXIS_WORDS,
    "method": frozenset({"pack", "stack"}),
    "unit": frozenset({"slab", "house"}),
}
GROWTH_POLICIES = frozenset({"plan", "both"})


def mistyped_words(record: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Arguments outside their fixed list, as (verb, parameter, value)."""

    found: list[tuple[str, str, str]] = []
    if "growth" in record:
        value = record["growth"]
        if not isinstance(value, str) or value not in GROWTH_POLICIES:
            found.append(("parti", "growth", repr(value)))
    for item in record.get("ops") or ():
        verb = str(item.get("op") or "").strip()
        for key, allowed in _ENUMERATED.items():
            value = item.get(key)
            if isinstance(value, str) and value.strip().lower() not in allowed:
                found.append((verb, key, value))
    return found


def declared_stature(record: dict[str, Any]) -> dict[str, Any]:
    """What a sentence declares about its own height, as form.extra fields.

    `declared_storeys` is the tallest `storeys` any op names; on extrude/loop
    the declaration IS the building (`stature_is_building`), on aggregate and
    stack it sizes the unit. The run stamped both and the rebuild tools
    stamped only the first, so fill settled a rebuilt tower to the parcel
    average while the run had held it to its own ceiling - rebuild != run for
    exactly the sentences the ceiling was written for. One owner, read by the
    command, finalists.rebuild and the probes alike.
    """

    ops = list(record.get("ops") or [])
    asked = max((float(op.get("storeys") or 0) for op in ops), default=0.0)
    if asked <= 0.0:
        return {}
    opener = str((ops[0].get("op") if ops else "") or "")
    return {"declared_storeys": asked,
            "stature_is_building": opener in ("extrude", "loop")}


def declared_height_m(record: dict[str, Any], storey_m: float) -> float:
    """The height budget a declaration asks for, at this storey height.

    The executor multiplies whatever budget it is handed by the sentence's
    own `height` share, so the declaration is divided by that share or
    `storeys: 2, height: 0.3` is born at one storey. The executor clamps
    height to 0.1..1.0, so the share floor is 0.1, not the 0.2 the first
    version used (a 0.15 share was still born at a third of its storeys).
    """

    ops = list(record.get("ops") or [])
    asked = max((float(op.get("storeys") or 0) for op in ops), default=0.0)
    if asked <= 0.0:
        return 0.0
    share = max((float(op.get("height") or 0.0) for op in ops), default=0.0)
    share = min(1.0, max(0.1, share)) if share > 0.0 else 1.0
    return asked * storey_m / share


def parti_from_record(record: dict[str, Any]) -> Parti | None:
    """Read an authored sentence. Unknown verbs are dropped, not guessed at."""

    if mistyped_words(record):
        # Refused rather than coerced: the delivered mass would not be the
        # sentence the caller is holding, and every gate downstream would
        # certify it as one.
        return None

    ops: list[Operation] = []
    for item in record.get("ops") or ():
        verb = str(item.get("op") or "").strip()
        mode = PLOT_MODES.get(verb)
        if mode is None:
            continue
        ops.append(Operation(
            verb=verb,
            plot_mode=mode,
            params={k: v for k, v in item.items() if k not in ("op", "why")},
            why=str(item.get("why") or ""),
        ))
    if not ops:
        return None
    # A sentence that does not open with a creator gets the implicit seed every
    # massing study starts from - the parcel volume - so its first spoken word
    # transforms something that exists. Three LLM-authored sentences opened
    # with split or compress ("조여진 씨앗에서 시작한다" is a legitimate first
    # thought) and every word of them ran on an empty frame and did nothing:
    # the silence gate reported all-silent with an empty trace.
    # stack creates too - it builds its tiers from the frame whether or not
    # anything stands. Leaving it off this list prepended a full seed in
    # front of seven stack-first sentences and the seed swallowed their
    # tiers, the exact disease vancouver_house was cured of.
    if ops[0].verb not in ("extrude", "loop", "aggregate", "stack"):
        ops.insert(0, Operation(
            verb="extrude", plot_mode=PLOT_MODES["extrude"],
            params={"height": 0.9},
            why="암묵 씨앗 - 첫 동사가 변형이라 파서가 필지 볼륨을 깔았다.",
        ))
    return Parti(
        name=str(record.get("name") or "unnamed"),
        ops=tuple(ops),
        primary_language=str(record.get("primary_language") or "matrix_form"),
        secondary_language=str(record.get("secondary_language") or ""),
        formal_principle=str(record.get("formal_principle") or ""),
        dominant_gesture=str(record.get("dominant_gesture") or ""),
        reference_basis=str(record.get("reference_basis") or ""),
        floor_height_m=record.get("floor_height_m"),
        growth=record.get("growth"),
        # Unknown labels are dropped rather than guessed at, the same rule the
        # enumerated words follow: a base volume nobody can name is silence,
        # and silence is 1/1 on the open side.
        base_volume=(str(record["base_volume"])
                     if str(record.get("base_volume") or "") in BASE_VOLUME_LABELS
                     else None),
        base_orientation=(str(record["base_orientation"])
                          if str(record.get("base_orientation") or "")
                          in BASE_ORIENTATIONS else None),
    )


def seed_rectangle(buildable: Polygon, axis: tuple[float, float]) -> tuple[float, float, float, float, float]:
    """The site's own starting box: the parcel's extent on the axis it is posed on.

    Turning the box to the site rather than to north is what lets a clean
    orthogonal composition sit in a skewed plot without meeting every boundary
    at an angle. The bearing is the open side - the street - because that is the
    direction a building is placed along, and when no side is open it falls back
    to the parcel's own longest edge.

    Measured on that same bearing, which is the part that was wrong. Two faults
    sat on top of each other here.

    The depth was read off the minimum rotated rectangle's edge list, and that
    list runs corner to corner: for a rectangle, `ring[:4]` gives three edges as
    long, short, long. Sorting them by length and taking the first two takes the
    long edge twice whenever the ring happens to start on a short side, so the
    seed came out square. Which way it fell was decided by wherever shapely
    began the ring:

        의정부  edges 57.8, 41.8, 57.8  ->  57.8 x 57.8   3,343 m² on a 1,922 m² plot
        종로    edges 231.6, 73.3, 231.6 -> 231.6 x 231.6  53,627 m² on a 1,503 m²
        강남    edges 8.0, 12.9, 8.0    ->  12.9 x 8.0    correct

    And the extent was measured on the minimum rotated rectangle's own axes
    while the frame is posed on the axis, which on 의정부 differ by 41.5 degrees
    - so even a correctly read pair of edges described a rectangle standing
    somewhere else. The same fault `_bounds_of` had, one stage earlier: measure
    on the axes the thing is built on.

    Returns (centre x, centre y, width, depth, rotation in degrees).
    """

    from math import atan2, cos, degrees, hypot, radians, sin

    if axis != (0.0, 0.0):
        rotation = degrees(atan2(axis[1], axis[0]))
    else:
        ring = list(buildable.minimum_rotated_rectangle.exterior.coords)[:4]
        adjacent = [
            (ring[i + 1][0] - ring[i][0], ring[i + 1][1] - ring[i][1]) for i in range(2)
        ]
        longest = max(adjacent, key=lambda edge: hypot(edge[0], edge[1]))
        rotation = degrees(atan2(longest[1], longest[0]))

    bearing = radians(-rotation)
    cos_b, sin_b = cos(bearing), sin(bearing)
    turned = [
        (x * cos_b - y * sin_b, x * sin_b + y * cos_b)
        for x, y in buildable.exterior.coords
    ]
    us = [u for u, _v in turned]
    vs = [v for _u, v in turned]
    width, depth = max(us) - min(us), max(vs) - min(vs)

    # The centre of that box, said in world terms again.
    mid_u, mid_v = (min(us) + max(us)) / 2.0, (min(vs) + max(vs)) / 2.0
    back = radians(rotation)
    cos_f, sin_f = cos(back), sin(back)
    centre_x = mid_u * cos_f - mid_v * sin_f
    centre_y = mid_u * sin_f + mid_v * cos_f
    return float(centre_x), float(centre_y), float(width), float(depth), float(rotation)


__all__ = [
    "JOINT_CLEARANCE_M",
    "MAX_OFFSET_RATIO",
    "MIN_OFFSET_RATIO",
    "MIN_TIER_CONTRAST",
    "STACK_CONTRAST_RANGE",
    "DEFAULT_STACK_CONTRAST",
    "Operation",
    "PLOT_MODES",
    "Parti",
    "PlotMode",
    "parti_from_record",
    "plot_mode_of",
    "seed_rectangle",
]
