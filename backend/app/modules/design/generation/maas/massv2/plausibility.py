"""Is this a building, or is it lawful geometry that nobody could occupy.

Both ceilings can be satisfied by a chimney. Measured on the live Uijeongbu
parcel, carrying a four-block composition down to a 45% ground take produced a
21 m2 footprint under 48 m of height - a slenderness of 10.4, entirely lawful
and not a 근린생활시설 anyone would propose. Eleven of eighty-eight schemes came
out past a slenderness of 4.

Nothing here invents a threshold. Floor viability comes from the project's own
shared rule in `design/maas/floor_viability.py`, which derives a minimum
occupied area from the parcel and holds a room to a 2.4 m clear depth, and the
slenderness bound comes from the parcel too - see `slenderness_limit`, which
reuses the 용적률-over-건폐율 storey count that already stops growth in `fill`.
Using the rules the project already lives by is the point: a second set of
numbers would be a second opinion about the same question.

Standing up is asked here too, by `structure`. It belongs at this gate rather
than in the fitness score for the reason the score itself demonstrated: the
scheme the critic called a collapsed deck of cards came *first* on every number
the sheet carries. A mass that cannot be held up is not a low-scoring option,
it is not an option, and a gate is the only place that distinction exists.
"""

from __future__ import annotations

from math import hypot

from dataclasses import dataclass
from typing import Any

from backend.app.modules.design.generation.maas.floor_viability import DEFAULT_MINIMUM_CLEAR_DEPTH_M, evaluate_floor_section_viability, minimum_usable_floor_area_m2
from backend.app.modules.design.generation.maas.source_geometry.ir import SourceMass

from backend.app.modules.design.generation.maas.massv2.structure import BAND_FRACTION_STEP, Standing, assess_standing, bodies_of


AUTHORED_MINIMUM_PLAN_DIMENSION_M = 1.5

# The erosion radius under which a plate stops being a storey somebody
# occupies: half the narrowest habitable plate, which is one room's clear
# depth plus its two walls.
#
# The first value here was the room depth spent whole - erode by 2.4, so the
# plate had to be 4.8 m wide, "a room with the way to it beside it". That is a
# corridor typology, not physics, and the built canon refutes it the same way
# it refuted the four-body count: Moriyama House's freestanding units are about
# three metres wide and each IS one room - the way up is inside the room or
# outside the building. Measured on the Uijeongbu sheet the 4.8 m reading
# killed not the authored SANAA sentences (they pass, 0.67-1.00) but their
# low-coverage retargets - inujima lost 15 of 22 variants and every occupiable
# one - for bars a real Moriyama unit would clear.
#
# So the floor is the pinned 2.4 m clear room depth ([[splinters]] - do not
# touch that number) plus 0.6 m of wall, halved for the erosion: a 3.0 m plate
# holds a room and stands in the canon; below it is a wall, not a building.
# Metres rather than a ratio because a person sets this and a person is the
# same size on every site. The 4.2 m Gangnam sticks this constant was first
# aimed at now pass the width test - whether a stick belongs on a sheet is the
# selector's judgement, not a physics gate's, the same boundary the body-count
# recalibration drew.
MINIMUM_STOREY_WIDTH_M = (DEFAULT_MINIMUM_CLEAR_DEPTH_M + 0.6) / 2.0

# The cleanliness law (canon §11), finally as a gate: a delivered OCCUPIABLE
# body smaller than this share of the building's occupiable mass is a crumb -
# a fragment no architect drew on purpose, the thing that makes a tile read
# as rubble. Pure structure (legs, canopies - bands the compiler marks
# structural) is exempt: a column is small because it is a column.
CRUMB_MASS_SHARE = 0.04

# How far daylight reaches into a storey, as a multiple of its own height.
# Reinhart's rule of thumb puts the daylit zone at two to two and a half times
# the window head; in a storey of this height the head lands just under the
# ceiling, so the storey height is the dimension to scale from and the lower
# end of the range is the one to take. At 3 m that is 6 m from a façade, and a
# plate lit from both sides may be twelve across - which is the depth every
# daylit bar in the corpus is built to.
DAYLIT_DEPTH_PER_STOREY = 2.0

# How much of a plate may sit past daylight before it stops being a storey
# somebody occupies. A core, its stairs and back-of-house belong in the dark
# and run to about a fifth of a plate this size, so a quarter is the share
# above which the dark is no longer the servant space.
#
# Measured rather than guessed at: for a square plate the unlit share is
# ((s-12)/s)², so a half would only have refused something past 41 m across -
# on this parcel, nothing. A quarter refuses anything past 24 m square, and
# passes a 14 m bar of any length (0.11) and a courtyard block of the same
# outline as the slab it refuses (0.00), which is the distinction the rule
# exists to make.
MAX_UNLIT_SHARE = 0.25

# Which uses Korean law actually asks a daylight question about.
#
# 건축법 시행령 제51조(거실의 채광 등): "단독주택 및 공동주택의 거실, 교육연구시설 중
# 학교의 교실, 의료시설의 병실 및 숙박시설의 객실". That list is the whole of it -
# 근린생활시설, 업무시설 and 판매시설 are not in it, and this tool was rejecting a
# 제1종근린생활시설 on a rule written for a dwelling. 297 of 533 refusals on the
# Uijeongbu parcel were that rule alone, more than half of everything refused.
#
# Two further things the statute says, which is why even the covered uses are not
# gated on plate depth here. The duty is a per-거실 window area - 피난·방화규칙
# 제17조①, "그 거실의 바닥면적의 10분의 1 이상" - not a distance from a façade, and
# it binds rooms rather than plates, so a deep plate whose core is 복도·창고·설비
# (not 거실, 건축법 제2조제1항제6호) is untouched by it. And it is defeasible: the
# same article exempts a 거실 lit to 별표 1의3 by lamps.
#
# No Korean provision anywhere limits how far a floor may extend from a window.
# The only statutory plan-depth number is egress - 시행령 제34조①, 보행거리 30 m,
# 50 m for 내화구조·불연재료 - and that one is use-blind. If this package ever wants
# one depth gate for every use, that is the number, and 6 m is not it.
#
# 정북일조 is the other half of the same question and is not affected: 법 제61조①
# triggers on 용도지역 (전용주거·일반주거) and says nothing about the building's use,
# so a 근린생활시설 there obeys it like anything else. It is enforced in `legal_fit`
# through the envelope, not here.
DAYLIGHT_IS_A_DUTY_FOR = (
    "단독주택", "공동주택", "학교", "병원", "의료시설", "숙박시설",
)


def daylight_is_required_for(building_type: str) -> bool:
    """Does 영 제51조 ask this use for daylight at all."""

    name = str(building_type or "")
    return any(token in name for token in DAYLIGHT_IS_A_DUTY_FOR)


def daylit_depth_m(floor_height_m: float) -> float:
    """How far in from a façade or a court a storey of this height is lit."""

    return DAYLIT_DEPTH_PER_STOREY * max(float(floor_height_m), 0.0)


def unlit_share(polygon, *, floor_height_m: float) -> float:
    """The part of a plate no window reaches, as a share of its own area.

    Eroding the plan by the daylit depth leaves exactly the points that are
    further than that from any edge - the same morphological test the void axis
    uses to ask whether a gap could be a room, asked here in the other
    direction. Courts count as edges because they are: `footprint` carries its
    interiors, so a courtyard block reads as lit and a solid one of the same
    outline does not, which is the whole reason a courtyard block exists.
    """

    area = float(polygon.area)
    if area <= 1e-9:
        return 0.0
    depth = daylit_depth_m(floor_height_m)
    if depth <= 0.0:
        return 0.0
    try:
        core = polygon.buffer(-depth)
    except Exception:  # pragma: no cover - GEOS refusing a degenerate erosion
        return 0.0
    return float(core.area) / area if not core.is_empty else 0.0


def holds_a_storey(polygon) -> bool:
    """Could a room and the way to it stand side by side across this plate.

    Eroding by the minimum room depth leaves the points that have that much
    clearance on every side, so anything surviving has room for a second thing
    beside the first. It is the same morphological test `unlit_share` uses,
    asked in the other direction: that one finds the part of a plate no window
    reaches, this one finds whether the plate is a plate at all.
    """

    if polygon is None or polygon.is_empty:
        return False
    try:
        return not polygon.buffer(-MINIMUM_STOREY_WIDTH_M, join_style=2).is_empty
    except Exception:  # pragma: no cover - GEOS refusing a degenerate erosion
        return False


def slenderness_limit(*, far_capacity_m2: float, ground_capacity_m2: float) -> float:
    """How slender this parcel's own two limits say a building may be.

    The number used to be 12, quoted from `_is_reviewable_architectural_mass`
    in the other pipeline. Quoting was the right instinct and the wrong source:
    that gate judges authored masses on any site, and here it let through the
    exact case this module was written to refuse - the docstring above names a
    chimney at 10.4 as "not a 근린생활시설 anyone would propose" and then passed
    it. A limit that admits its own counterexample is not a limit.

    So it comes from the parcel, and from the number that already governs the
    other half of the same question: 용적률 divided by 건폐율 is how many storeys
    the parcel affords over the ground it allows, and `fill` already stops
    growth there. A building slenderer than the storeys its own site affords
    has stopped taking less ground and started going up instead.

    It travels correctly, which the constant did not. Uijeongbu at 20% and 100%
    affords 5, so a stick is refused. A commercial parcel at 60% and 800%
    affords 13.3, and there a slender tower is what the zoning is for. The same
    sentence gives the right answer on both because it is the site talking.
    """

    return max(1.0, float(far_capacity_m2) / max(float(ground_capacity_m2), 1e-9))


@dataclass(frozen=True)
class Plausibility:
    slenderness: float
    minimum_plan_dimension_m: float
    viable_band_share: float
    occupiable: bool
    reasons: tuple[str, ...]
    occupiable_mass_share: float = 1.0
    standing: Standing | None = None
    max_slenderness: float = 0.0

    def evidence(self) -> dict[str, Any]:
        return {
            "schema_version": "arr.maas.massv2_plausibility.v1",
            "slenderness": round(self.slenderness, 3),
            "minimum_plan_dimension_m": round(self.minimum_plan_dimension_m, 3),
            "viable_band_share": round(self.viable_band_share, 3),
            "occupiable_mass_share": round(self.occupiable_mass_share, 3),
            "occupiable": self.occupiable,
            "reasons": list(self.reasons),
            "structure": self.standing.evidence() if self.standing is not None else None,
            "max_slenderness": round(self.max_slenderness, 2),
            "basis": "design.maas.floor_viability + parcel slenderness + structure",
        }


def _min_dimension(polygon) -> float:
    """How narrow this plan is across its own narrowest direction.

    On its own axes, not the world's. Every volume here is posed at the parcel's
    bearing and an axis-aligned box around a turned shape is wider than the
    shape - a 3 x 40 m bar reads 13.3 m across at 15 degrees, 30.4 m at 45. The
    three live parcels sit at -168.3, 35.5 and 165.0 degrees, so against a
    1.5 m floor this test could not fire on any of them.
    """

    if polygon is None or polygon.is_empty:
        return 0.0
    ring = list(polygon.minimum_rotated_rectangle.exterior.coords)[:4]
    if len(ring) < 3:
        min_x, min_y, max_x, max_y = polygon.bounds
        return float(min(max_x - min_x, max_y - min_y))
    # Adjacent edges. Sorting three of them takes the long one twice whenever
    # the ring starts on a short side - the fault `seed_rectangle` and
    # `principal_axes` both carried.
    sides = [
        hypot(ring[i + 1][0] - ring[i][0], ring[i + 1][1] - ring[i][1])
        for i in range(2)
    ]
    return float(min(sides))


def assess(
    source: SourceMass,
    *,
    parcel_area_m2: float,
    max_slenderness: float,
    floor_height_m: float = 0.0,
    building_type: str = "",
) -> Plausibility:
    """Judge a compiled mass as a building rather than as a solid.

    `max_slenderness` is the parcel's own, from `slenderness_limit`. It has no
    default on purpose: the version with one was a constant that travelled to
    every site unchanged and let a chimney through on this one.
    """

    bands = tuple(source.volumes)
    if not bands:
        return Plausibility(0.0, 0.0, 0.0, False, ("no_bands",))

    height = float(source.metadata.get("authored_height_m") or 0.0)
    # Slenderness is a property of a body. Measured against `source.footprint`
    # it was the whole building's height over the widest single grounded body's
    # narrowest dimension - the same field that once reported a brick pile at
    # four percent coverage, because it keeps only the largest piece. A village
    # of five houses and a plate on four legs both read as sticks that way:
    # measured over this corpus, sixty-seven candidates were refused on
    # slenderness alone and five of six of them are not slender at all.
    #
    # Taking the union of everything grounded instead would answer the opposite
    # question wrongly - two three-metre towers standing forty metres apart
    # would measure as one fat body. So each connected body is asked about its
    # own height over its own width, and the worst of them stands for the
    # building. That refuses the chimney this gate was written for, refuses the
    # pair of sticks, and lets the village and the lifted plate through.
    ground = source.footprint
    min_dimension = _min_dimension(ground)
    bodies = bodies_of(source)
    # A fragment is not a body. Boolean cuts leave slivers a few centimetres
    # across, and "the worst body" hands the whole building's verdict to one of
    # them - `i_naseon_tap` reported a slenderness of 5,774 on a spiral that is
    # plainly a tower. A piece has to be at least room-sized before it is asked
    # to stand on its own.
    floor = max(10.0, 0.01 * sum(float(plan.area) for _l, _h, plan in bodies))
    bodies = [item for item in bodies if float(item[2].area) >= floor]
    if bodies:
        slenderness = 0.0
        for low, high, plan in bodies:
            span = max(0.0, (high - low)) * height
            width = _min_dimension(plan)
            slenderness = max(
                slenderness,
                span / width if width > 1e-6 else float("inf"),
            )
    else:
        slenderness = height / min_dimension if min_dimension > 1e-6 else float("inf")

    structural = set(source.metadata.get("structural_bands") or ())

    # Crumb gate: per connected body, sum its occupiable mass (bands not
    # marked structural whose plan meets the body's). A body with occupiable
    # mass but under CRUMB_MASS_SHARE of the whole is delivered debris.
    crumb_reason: str | None = None
    # Shard check first, at the VOLUME level: bodies_of floors out fragments
    # before physics, but the renderer draws every volume - so the debris the
    # eye complains about lives below that floor. An additive occupiable
    # volume too small or too thin to ever hold a room is delivered rubble.
    shards = 0
    for index, volume in enumerate(bands):
        if index in structural:
            continue
        span = max(0.0, float(volume.top_fraction) - float(volume.bottom_fraction))
        if span <= 1e-6:
            continue
        area = float(volume.footprint.area)
        # Width is asked the way the canon states it - can a room stand here -
        # which is the erosion `holds_a_storey` makes (3.0 m across), not the
        # 1.5 m erosion RADIUS compared against a width directly: that let a
        # 2.84 m needle through. And a volume can be room-wide at the base and
        # still be a chimney: an occupiable piece taller than a storey is held
        # to the parcel's own slenderness on its own, since the body-level
        # slenderness above sees a stack as one fat body and never asks the
        # spire on top (sweepx_0242: 9.8 m2 / 2.84 m wide, 8.3 m tall, passed).
        span_m = span * height
        width = _min_dimension(volume.footprint)
        storey = float(floor_height_m) if floor_height_m > 0.0 else 3.0
        chimney = (span_m > storey and width > 1e-6
                   and span_m / width > max_slenderness)
        if area < 9.0 or not holds_a_storey(volume.footprint) or chimney:
            shards += 1
    if shards:
        crumb_reason = f"crumb_{shards}_shard_volume{'s' if shards > 1 else ''}"
    if bodies and bands:
        body_mass = [0.0] * len(bodies)
        total_occ = 0.0
        for index, volume in enumerate(bands):
            if index in structural:
                continue
            span = max(0.0, float(volume.top_fraction) - float(volume.bottom_fraction))
            mass = float(volume.footprint.area) * span
            total_occ += mass
            for b, (_low, _high, plan) in enumerate(bodies):
                try:
                    hit = volume.footprint.intersection(plan).area
                except Exception:
                    hit = 0.0
                if hit > 1e-6:
                    body_mass[b] += mass * (hit / max(float(volume.footprint.area), 1e-9))
        if total_occ > 1e-6:
            for b, mass in enumerate(body_mass):
                share = mass / total_occ
                if crumb_reason is None and 1e-9 < share < CRUMB_MASS_SHARE:
                    crumb_reason = (
                        f"crumb_body_{share * 100:.0f}%_of_occupiable_mass")
                    break

    viable = 0.0
    counted = 0.0
    room = 0.0
    occupied = 0.0
    holding = 0.0
    for index, volume in enumerate(bands):
        # A support is not asked to be a floor. The exemption is already granted
        # two rules below - a column is small next to what it holds up, and that
        # is what makes it a column - and it was missing here, so the thinner the
        # legs the worse the building scored. Counted rather than weighed, too:
        # four slim legs are four bands against one plate, so `lift` could only
        # ever stand a slab on stumps thick enough to read as blocks under it.
        # Both judges of the fixed benchmark said the same thing about Maison
        # Bordeaux - "nothing floats", "it plainly rests on the tier below" -
        # and the geometry had a 3.4 m gap in it the whole time.
        #
        # Same correction the storey rule already carries: weigh by how much
        # building each band is.
        if index in structural:
            continue
        verdict = evaluate_floor_section_viability(
            volume.footprint, parcel_area_m2=parcel_area_m2
        )
        weight = float(volume.footprint.area) * max(
            0.0, volume.top_fraction - volume.bottom_fraction
        )
        counted += weight
        if verdict.get("hard_pass"):
            viable += weight
        # Weighed by how much building each band is, not counted. Counting made
        # one thin terrace among Mountain Dwellings' thirteen bands worth as
        # much as the forty-metre plates beside it, and refused the scheme.
        bulk = float(volume.footprint.area) * max(
            0.0, volume.top_fraction - volume.bottom_fraction
        )
        if index in structural:
            holding += bulk
            continue
        occupied += bulk
        if holds_a_storey(volume.footprint):
            room += bulk
    share = (viable / counted) if counted > 1e-9 else 1.0
    storey_share = (room / occupied) if occupied > 1e-9 else 1.0
    held_share = holding / max(holding + occupied, 1e-9)

    reasons: list[str] = []
    if crumb_reason:
        reasons.append(crumb_reason)
    if slenderness > max_slenderness:
        reasons.append(f"slenderness_{slenderness:.1f}_over_{max_slenderness:.1f}")
    if min_dimension < AUTHORED_MINIMUM_PLAN_DIMENSION_M:
        reasons.append(f"plan_dimension_{min_dimension:.1f}m_under_minimum")
    if float(ground.area) < minimum_usable_floor_area_m2(parcel_area_m2):
        reasons.append("ground_floor_below_minimum_usable_area")
    if share <= 0.5:
        reasons.append(f"only_{share:.0%}_of_bands_occupiable")
    # Every plate, not the ground alone. A mass may sit on a generous footprint
    # and taper into sticks above it, and `min_dimension` reads the ground only
    # - and reads a bounding box at that, so it cannot see a stick beside a
    # wide plate in the same band.
    if storey_share <= 0.5:
        reasons.append(f"only_{storey_share:.0%}_of_the_mass_is_wide_enough_to_occupy")
    # A column is exempt from being as wide as a storey because it is a column,
    # and what makes it one is that it is small next to what it holds up. The
    # exemption is granted by the verb - `lift` marks its supports - and nothing
    # re-examined it afterwards, so on 강남 the growth loop drew those supports
    # to 65 m and they carried the exemption all the way out: Rolex reported
    # every occupiable band wide enough because the four sticks it stands on had
    # stopped counting. Past half the mass it is not what holds the building up,
    # it is the building.
    if held_share > 0.5:
        reasons.append(f"{held_share:.0%}_of_the_mass_is_structure_rather_than_room")

    # A mass is a building only if it delivers at least the one plate this
    # gate already demands at grade. Nothing here measured how much building
    # arrived: eleven audited variants stood six to nine metres tall with a
    # gross floor area of exactly zero - crushed to sub-storey bands - and
    # every plan test passed, because every test was a plan test. Same
    # threshold as the ground rule, one storey up the same derivation.
    if floor_height_m > 0.0:
        from backend.app.modules.design.generation.maas.massv2.measure import gross_floor_area_m2

        gross = gross_floor_area_m2(source, floor_height_m=floor_height_m)
        if gross < minimum_usable_floor_area_m2(parcel_area_m2):
            reasons.append(
                f"delivers_{gross:.0f}m2_below_the_minimum_usable_plate"
            )

    # A body that claims to be rooms and arrives as a blade. The bulk-weighted
    # shares above deliberately let one thin terrace ride among wide plates,
    # which also lets a paper fin taller than two storeys ride among them -
    # three percent of the mass cannot move a fifty percent threshold. So the
    # question is asked of each body alone: nothing occupiable may stand
    # taller than two storeys while narrower everywhere than a storey's own
    # width. Declared thinness is exempt the way it always was - a body made
    # of structural bands (a lift's legs, a canopy's plate) is judged by the
    # structure gate, not by this.
    if floor_height_m > 0.0:
        structural_extents = [
            (bands[i].footprint, bands[i].bottom_fraction, bands[i].top_fraction)
            for i in structural
            if i < len(bands)
        ]
        # `bodies` is the floor-filtered list from the slenderness pass above:
        # a boolean-cut sliver is not a body there and is not one here either.
        for low, high, plan in bodies:
            span_m = max(0.0, high - low) * height
            if span_m <= 2.0 * floor_height_m:
                continue
            if _min_dimension(plan) >= MINIMUM_STOREY_WIDTH_M:
                continue
            # Declared thinness may arrive as several stacked structural bands
            # (band edges cut wherever any placement starts or stops), and the
            # body's own fractions arrive rounded - so the exemption asks
            # whether structural extents over this plan jointly cover the
            # body's run, with the rounding step as slack.
            covering = sorted(
                (b0, b1)
                for fp, b0, b1 in structural_extents
                if fp.intersection(plan).area >= 0.8 * plan.area
            )
            cursor = low
            for b0, b1 in covering:
                if b0 > cursor + BAND_FRACTION_STEP:
                    break
                cursor = max(cursor, b1)
            if cursor >= high - BAND_FRACTION_STEP:
                continue
            reasons.append(
                f"thin_element_{span_m:.1f}m_tall_under_"
                f"{MINIMUM_STOREY_WIDTH_M:.1f}m_wide"
            )
            break

    # A plate can satisfy both ceilings and still have a middle no window
    # reaches. Nothing else in this gate was asking how deep a storey is, so a
    # forty-metre-across slab passed as readily as a bar - and on a wide parcel
    # the growth loop makes exactly that, because filling 용적률 by spreading
    # is cheaper than by rising. This is the reason a courtyard block, a bar
    # and a comb exist at all, and it belongs at the gate rather than in the
    # score for the same reason standing up does.
    if floor_height_m > 0.0 and daylight_is_required_for(building_type):
        dark = max(
            (unlit_share(volume.footprint, floor_height_m=floor_height_m)
             for volume in bands),
            default=0.0,
        )
        if dark > MAX_UNLIT_SHARE:
            reasons.append(f"{dark:.0%}_of_a_plate_is_past_daylight")

    standing = assess_standing(source, height_m=height)
    reasons.extend(standing.reasons)

    return Plausibility(
        slenderness=slenderness,
        minimum_plan_dimension_m=min_dimension,
        viable_band_share=share,
        occupiable_mass_share=storey_share,
        occupiable=not reasons,
        reasons=tuple(reasons),
        standing=standing,
        max_slenderness=max_slenderness,
    )
