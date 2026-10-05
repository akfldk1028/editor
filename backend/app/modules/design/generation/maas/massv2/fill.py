"""Grow a scheme into the parcel until a law stops it.

The legal fit only ever reduces - it answers "is this lawful", never "is this
enough". So an authored composition whose proportions came from a building on a
different site stays at whatever it happened to land on: measured across the
built-work vocabulary on the Uijeongbu parcel, 용적률 came out at a median of
0.42 and one scheme at 0.16. Lawful, and an under-built site.

This is the other half. The scheme is grown until one of its own ceilings binds,
and the two directions are kept separate because the laws are:

  Height buys floor area at constant ground take, so it is tried first - the
  scheme keeps the footprint it was composed with.

  Plan buys both, so it is tried only when height has run out, and it moves the
  scheme along the coverage axis, which is a change of position rather than a
  change of size.

Growth stops at the first ceiling. Nothing here overrides `fit_to_site`; the fit
is re-run after every step and has the last word.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from shapely import affinity
from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.massv2.compile import _plan, compile_matrix_form
from backend.app.modules.design.generation.maas.geometry_language.affine_matrix import compose_matrix4, translation_matrix4, validate_matrix4

from backend.app.modules.design.generation.maas.massv2.form import MatrixForm, Placement, section_held_through_height_scale
from backend.app.modules.design.generation.maas.massv2.legal import LegalSite
from backend.app.modules.design.generation.maas.massv2.measure import measure_form
from backend.app.modules.design.generation.maas.massv2.legal_fit import LegalFitResult, _gross_floor_area, _scaled_composition, fit_to_site
from backend.app.modules.design.generation.maas.massv2.variations import _stretched
from backend.app.modules.design.generation.maas.massv2.delivery_gate import stature_ceiling_m


# A scheme within this much of its floor-area ceiling is full; chasing the rest
# costs a storey and buys a rounding error.
_FULL_ENOUGH = 0.97
# How far past the brief a scheme may sit before it has to come down. The
# tolerance Korean 설계공모지침서 give on 연면적 is almost always ±5%, and the
# same documents make exceeding it a deduction and then a disqualification.
_OVER_ENOUGH = 1.05
_MAX_STEPS = 24
# What a scheme asks for when it says nothing. Not 1.0: a brief that wants the
# whole capacity should have to say so, because the schemes that do not want it
# are the ones with something to say about form.
_DEFAULT_TARGET = 0.85
# How little a scheme is allowed to ask for. A brief may want less than the cap
# - a gallery is not a shop block - but a 근린생활시설 that uses 41% of its
# allowed floor area has left half the parcel's value unbuilt, and on the
# Uijeongbu sheet three of sixteen sat at 0.41, 0.50 and 0.63. The form is still
# protected: `worth_taking` refuses any step that costs the composition, so a
# scheme that genuinely cannot grow without ceasing to be itself stops early and
# keeps its own number.
_TARGET_FLOOR = 0.75

# What each formal language can hold without ceasing to be itself.
#
# The docstring of `fill_to_site` already argued this and nothing acted on it:
# "a shop block fills it, a gallery does not, and a scheme of small dispersed
# rooms cannot without ceasing to be one". Measured across the corpus, not one
# authored sentence sets `far_target`, so every one of them - a bathhouse, a
# vertical city, a bridge over a river, a field of pavilions - was grown to
# between 0.75 and 0.85 of the same cap. That is the monoculture: sixteen
# buildings at one density, which is what a sheet looks like when the growth
# loop is the only thing deciding how big anything is.
#
# A field is the clearest case and it sets the low end: Moriyama, Inujima and
# Towada are ten to twenty small volumes with lanes between them, and the only
# way to add area to that is to pull it upward, which is the one thing it must
# not do. A stacked body is the opposite - De Rotterdam is called a vertical
# city - and a solid body sits between them.
#
# These are the language's own ceiling, not a target to chase: `worth_taking`
# still refuses any step that costs the composition, so a scheme stops earlier
# than this whenever growing would cost it its shape.
_LANGUAGE_TARGET: dict[str, float] = {
    "porous_field": 0.45,
    "open_figure": 0.62,
    "carved_body": 0.72,
    "solid_body": 0.85,
    "stacked_body": 0.98,
}
# How much of its authored void a scheme may lose in exchange for floor area.
# Not zero: a court may narrow as the building around it thickens, and the
# legal clip legitimately takes a slice of one. Past this it has closed, and
# the sentence that asked for it is no longer the building being delivered.
_VOID_KEPT = 0.65
# How much of its articulation a scheme may lose in exchange for floor area.
# Not zero: growth legitimately rounds a composition off a little. But a step
# that costs a fifth of the move is buying area with the design.
_ARTICULATION_KEPT = 0.80
# A volume may run a little past the parcel's own storey count - a double-height
# hall, a parapet - without becoming a stick. Past this it is not a tall room,
# it is a different decision about where the building goes.
_VOLUME_HEIGHT_SLACK = 1.25


@dataclass(frozen=True)
class FillResult:
    fit: LegalFitResult
    steps_taken: int
    grew_height: int
    grew_plan: int
    reason: str
    target_utilization: float = 1.0

    def evidence(self) -> dict[str, Any]:
        return {
            "schema_version": "arr.maas.massv2_fill.v1",
            "steps_taken": self.steps_taken,
            "grew_height": self.grew_height,
            "grew_plan": self.grew_plan,
            "stopped_because": self.reason,
            "target_utilization": round(self.target_utilization, 3),
        }


def _kept(form: MatrixForm, *, storey_height_m: float, allowed_at=None) -> tuple[float, float]:
    """What a growth step is allowed to spend: (articulation, plan void).

    Two readings of one compile, because they are two different ways for a
    step to buy floor area with the design and the second was not being
    watched. Measured over this corpus: of thirty-four sentences that cut,
    ringed or bored a void, fourteen delivered less than half the void they
    wrote - `d_bakgong_madang` 0.84 to 0.31, the courtscraper 0.21 to 0.01,
    a court that is simply not there. Articulation did not catch it; it
    counts the break-up of the whole mass, and a ring whose bars fatten
    inward until the court closes is still an articulated ring.

    A court is not currency. It is the thing the sentence is about.

    Compiled without `allowed_at` this measures a mass nobody receives. Every
    area in `legal_fit` is taken through the clip, and the sheet compiles
    through it too, so growth was the one reader left looking at the uncut
    form - and it is the reader whose whole job is to refuse a step that costs
    the composition. A widening step that pushes a court out to the boundary
    closes it, because the clip takes the wall that was holding it open; uncut,
    the court is still there and the step reads as free. That is one building
    measured two ways, for the fourth time in this package.
    """

    source = compile_matrix_form(
        form, storey_height_m=storey_height_m, allowed_at=allowed_at
    )
    if source is None:
        return (0.0, 0.0)
    measured = measure_form(source)
    return (measured.articulation(), measured.plan_void_ratio)


def _taller(form: MatrixForm, factor: float) -> MatrixForm:
    """Grow the building upward. Structure keeps the height it was given.

    `_stretched` scales a volume about its own base, so a body already sitting
    on supports stays where it is and only grows taller - which means leaving
    the supports alone keeps the composition intact and lifts nothing.

    Stretching them too was how a four-metre column became a thirty-eight metre
    tower: the growth loop asked for floor area, and area bought on a support
    is area nobody can enter. A column is sized by what walks under it and that
    does not change when the parcel allows more storeys.

    A void is not a support and was being left behind with them, because the
    test was `additive and occupiable` and a cutter is neither. So the building
    grew and its courts, tubes and arches stayed the height they were authored:
    CCTV's arch is cut to 62% of a 12 m mass, the growth loop takes that mass to
    21.9 m, and what was an opening a person walks under becomes a notch at the
    foot of a tall box. Three of four blind judges said so independently -
    "a cube on two stumps", "the six carved theses collectively produced two
    voids", "rings and fields survive the pipeline; lifts, slopes, cores and
    voids do not".

    A court that is the full height of a building is still the full height of it
    after the building grows. Subtractive volumes stretch with what they cut.
    """

    # Bottom-up, each volume rebased onto whatever it was resting on. Stretching
    # about a volume's own base is right when what is under it did not move, and
    # wrong for a stack: tiers keep their spacing while their thickness grows, so
    # they interpenetrate, and the compiler cuts a band at every overlap. Seattle
    # is five platforms 2.40 m apart that grew to 4.05 m thick - band edges at
    # 0, 2.40, 4.05, 4.80, 6.45, 7.20, 8.85, 9.60, 11.25, 13.65, which is nine
    # prisms for five platforms and reads as horizontal stripes across every one
    # of them. `form.stack` already warns about exactly this: "an overlap
    # declares one extra band per joint carrying the plan of the slab below".
    #
    # Rebasing keeps both cases right. A body on supports still lands on its
    # supports, because they do not grow and its base does not move; a tier lands
    # on the new top of the tier below.
    grown: dict[int, Placement] = {}
    order = sorted(
        range(len(form.placements)),
        key=lambda index: form.placements[index].z_span()[0],
    )
    for index in order:
        item = form.placements[index]
        low, high = item.z_span()
        if not ((item.kind == "additive" and item.occupiable)
                or item.kind == "subtractive"):
            grown[index] = item
            continue
        # What it was standing on: anything whose old top met its old base.
        carried = [
            grown[other].z_span()[1]
            for other in order
            if other in grown
            and abs(form.placements[other].z_span()[1] - low) <= 1e-6
        ]
        if item.kind == "subtractive":
            # A cutter stretches about the ground, not about its own base. It
            # overshoots downward on purpose - carve writes z at minus the
            # building's height so the cut clears the floor face - and scaling
            # that overshoot about its own base grows the cutter's top three
            # times as fast as the body it cuts. Casa da Música's bore was
            # authored to stop at 55% of the body with two storeys of building
            # bridging over it; grown 1.82x, the body topped out at 19.7 m and
            # the cutter at 20.7, and the bridge that made it one solid with a
            # void - rather than two towers - was eaten by its own overshoot.
            # About z = 0 the ratio of cut to body is what the sentence set,
            # at every size.
            raised = _stretched_about_ground(item, factor)
            grown[index] = raised
            continue
        raised = _stretched(item, factor)
        if carried:
            lift = max(carried) - raised.z_span()[0]
            if abs(lift) > 1e-9:
                raised = replace(
                    raised,
                    matrix=validate_matrix4(compose_matrix4(
                        raised.matrix, translation_matrix4((0.0, 0.0, lift))
                    )),
                )
        grown[index] = raised
    return replace(
        form,
        placements=tuple(grown[index] for index in range(len(form.placements))),
    )


def _stretched_about_ground(item: Placement, factor: float) -> Placement:
    """Scale a volume's height about z = 0 rather than its own base."""

    return section_held_through_height_scale(replace(
        item,
        matrix=validate_matrix4(compose_matrix4(
            item.matrix,
            (
                (1.0, 0.0, 0.0, 0.0),
                (0.0, 1.0, 0.0, 0.0),
                (0.0, 0.0, float(factor), 0.0),
                (0.0, 0.0, 0.0, 1.0),
            ),
        )),
    ), float(factor))


def _wider(form: MatrixForm, factor: float) -> MatrixForm:
    plans = [item for item in form.additive()]
    if not plans:
        return form
    corners = [corner for item in plans for corner in item.corners()]
    anchor = (
        (min(x for x, _y, _z in corners) + max(x for x, _y, _z in corners)) / 2.0,
        (min(y for _x, y, _z in corners) + max(y for _x, y, _z in corners)) / 2.0,
    )
    return _scaled_composition(form, factor, anchor)



def fill_to_site(
    form: MatrixForm,
    site: LegalSite,
    *,
    allow_plan_growth: bool = True,
    target_utilization: float | None = None,
) -> FillResult:
    """Grow toward the scheme's own target, refit each step, stop at a ceiling.

    `target_utilization` is a share of the 용적률 capacity, not a maximum to be
    chased. Filling the capacity is one brief among several: a shop block fills
    it, a gallery does not, and a scheme of small dispersed rooms cannot without
    ceasing to be one. Growing everything to the cap produced exactly the
    monoculture that follows from a single objective - Moriyama's scattered
    rooms came back as two sticks, because the only way to add area to a
    dispersed composition is to pull it upward.

    So the target comes from the scheme (`MatrixForm.extra["far_target"]`), then
    from the caller, and only then from a default. Growth still stops at the
    first legal ceiling; the target only says when to stop wanting more.

    Each step is proposed and then judged: the grown form goes back through
    `fit_to_site`, and a step is kept only if the fit still certifies it and the
    floor area actually rose. A step the sunlight envelope claws straight back
    is not progress, and taking it on trust is how a growth loop becomes an
    oscillation.
    """

    best = fit_to_site(form, site)
    if best.storey_limit and not best.storey_limit.get('satisfied', False):
        return FillResult(best, 0, 0, 0, 'parcel_storey_limit_refused', 0.0)
    capacity = site.far_capacity_m2
    if capacity <= 0.0:
        return FillResult(best, 0, 0, 0, "no_far_capacity", 0.0)

    # A scheme placed on the coverage axis is there on purpose. Growing its plan
    # would move it off the band it was made to occupy, so those grow upward
    # only; the position is the point of the copy.
    if form.extra.get("coverage_band"):
        allow_plan_growth = False

    authored = form.extra.get("far_target")
    spoken_for = _LANGUAGE_TARGET.get(str(form.primary_language or "").strip())
    share = float(
        authored if authored is not None
        else target_utilization if target_utilization is not None
        else spoken_for if spoken_for is not None
        else _DEFAULT_TARGET
    )
    # The floor exists for the case where nothing says how large the building
    # should be, and it is the wrong assumption the moment something does. A
    # brief does: Korean competition winners include a 청년문화센터 at 7.88%
    # 건폐율 and a 커뮤니티센터 at 6.94%, and the schedule those buildings were
    # asked for is the reason. A statutory ceiling is a ceiling, not a target -
    # and 면적표 is judged the other way, with 연면적 over the brief by more
    # than 5% costing marks and enough of it disqualifying the entry.
    briefed = form.extra.get("programme_target") is not None
    # The floor is for a scheme that says nothing about its own size. A language
    # says something, so it is not overruled by a number written for silence -
    # holding a `porous_field` to 0.75 is exactly the instruction to stop being
    # a field.
    if briefed or authored is not None or spoken_for is not None:
        share = min(1.0, share)
    else:
        share = max(_TARGET_FLOOR, min(1.0, share))
    capacity = capacity * share

    current = best.form
    storey = float(form.floor_height_m or site.floor_height_m)
    started_at, started_void = _kept(
        current, storey_height_m=storey, allowed_at=site.plan_at
    )
    floor = started_at * _ARTICULATION_KEPT
    void_floor = started_void * _VOID_KEPT
    taller = wider = 0
    reason = "reached_step_limit"

    def _settled_to_parcel_height(form: MatrixForm) -> MatrixForm:
        """No single volume taller than the storeys this parcel affords.

        The whole-building ceiling is an average - floor area over projection -
        so a scheme can sit under it while one thin piece of it shoots up, and
        that is what a bundle of sticks on a plinth is. Refusing it by verb was
        a patch: fields were stopped from growing upward, and the next sheet
        came back with sticks made by `stack` on a split instead. The rule is
        about the piece's height, not about which word produced it.

        용적률 divided by 건폐율 again - the same number that bounds slenderness
        and stops the growth loop. Uijeongbu affords 4.2 storeys, so a volume
        past 12.5 m is going up where the parcel asked it to go out.
        """

        ceiling = volume_ceiling
        tallest = _tallest_volume(form)
        if tallest <= ceiling or tallest <= 1e-6:
            return form
        return _taller(form, ceiling / tallest)

    def _tallest_volume(form: MatrixForm) -> float:
        return max(
            (item.z_span()[1] - item.z_span()[0] for item in form.additive()),
            default=0.0,
        )

    def worth_taking(candidate: LegalFitResult) -> bool:
        """Lawful, larger, and still the same building.

        Floor area is not the only thing a step can spend. Grown without this,
        CCTV's two legs and high return came back as a slab - lawful, fuller,
        and no longer the move. A step that costs a fifth of the scheme's
        articulation, or a third of its court, is buying area with the design.
        """

        if not candidate.satisfied:
            return False
        if candidate.gross_floor_area_m2 <= best.gross_floor_area_m2 + 1.0:
            return False
        articulation, void = _kept(
            candidate.form, storey_height_m=storey, allowed_at=site.plan_at
        )
        return articulation >= floor and void >= void_floor

    # How many storeys this parcel's own law implies: the floor area it allows
    # over the ground it allows. On the Uijeongbu parcel that is 2499.7 / 499.9
    # = 5. It is not a number anyone chose - it is 용적률 divided by 건폐율.
    #
    # Without it, the coverage axis manufactures towers. A scheme on the 45%
    # band that is told to fill its 용적률 needs 2499.7 / (0.45 * 499.9) = 11.1
    # storeys, so every low-coverage cell came out as a tower and no amount of
    # new vocabulary changed it. Above this line a scheme has stopped being a
    # building that takes less ground and started being a building that goes up
    # instead, which is a different decision and not the one the axis is about.
    #
    # Plan growth is not capped by it: widening buys storeys honestly, by taking
    # more ground, and that moves the scheme along the coverage axis where the
    # architect can see it.
    storeys_allowed = site.far_capacity_m2 / max(site.ground_capacity_m2, 1e-9)
    # The tallest a single volume may stand. For a sentence that declared its
    # storeys on a building-opener (extrude/loop) that is the declaration's own
    # tolerance - the same 5/3 the delivery gate retires it at - and not the
    # parcel's average: settling a declared tower to the average and then
    # growing it back to 용적률 was how 949 sweep01 variants arrived at the gate
    # "over" their own sentence. Every other scheme keeps the parcel rule.
    declared_storeys = float(form.extra.get("declared_storeys") or 0.0)
    if declared_storeys > 0.0 and form.extra.get("stature_is_building"):
        volume_ceiling = stature_ceiling_m(declared_storeys, storey)
    else:
        volume_ceiling = storeys_allowed * storey * _VOLUME_HEIGHT_SLACK
    if getattr(site, 'max_storeys', None) is not None:
        # Search budget at THIS candidate's storey, never a legal metre cap.
        volume_ceiling = min(volume_ceiling, site.max_storeys * storey)


    # Settle an over-tall scheme onto the parcel before growing it. Stopping
    # growth at the ceiling was not enough: a scheme authored tall arrives above
    # it, and nothing else pulls it down - eleven storeys on 45% of the ground
    # is entirely lawful here, so the legal fit has no reason to object. This is
    # the only place that says a tower is the wrong answer to a small footprint.
    # No single volume taller than the storeys this parcel affords. The ceiling
    # below is an average - floor area over projection - so a scheme can sit
    # under it while one thin piece shoots up, and that is what a bundle of
    # sticks on a plinth is. Refusing it by verb was a patch: fields were
    # stopped from rising and the next sheet came back with sticks made by
    # `stack` on a split instead. The rule is about a piece's height, not about
    # which word produced it. Settled once here rather than refused inside the
    # growth loop, where it made every scheme run all twenty-four steps.
    settled_height = fit_to_site(_settled_to_parcel_height(current), site)
    if settled_height.satisfied and settled_height.gross_floor_area_m2 > 0.0:
        best, current = settled_height, settled_height.form

    # Storeys standing = floor area over the ground it stands on, and both
    # numbers have to come off the same building. The fit already carries the
    # projection it certified through the clip, so taking it from there rather
    # than re-projecting the uncut form is one measurement instead of two: a
    # scheme hanging over the boundary was dividing a cut floor area by an
    # uncut footprint, reading short, and being told it had storeys to spare.
    standing = best.gross_floor_area_m2 / max(best.ground_area_m2, 1.0)
    # A sentence that says how many storeys it is has already answered this
    # question, and the pipeline honours that answer everywhere else: the
    # height budget is raised to what it asked for, and the delivery gate
    # retires it if it comes back short. Holding it to the parcel's *average*
    # storeys as well says the average is a law, which it is not - the legal
    # fit is the law and it has already passed. The rule below still governs
    # every sentence that says nothing about its own stature, which is the
    # case it was written for: those were the low-coverage cells that all came
    # back as towers when nothing else decided their height.
    # `storeys` is a count on one operation - the height of the piece that word
    # makes - not the building's total. Tried as a ceiling it capped exactly the
    # sentences the exemption was for: vitrahaus, e_dollin and pixel_peaks each
    # declare two, meaning two-storey units, and holding the whole composition
    # to two storeys took back all of +10.2 m, +9.4 m and +7.6 m. So the
    # declaration opens the ceiling; it does not become one. 용적률 and the fit
    # are what stop the growth, as they do for every other scheme.
    declared_stature = float(form.extra.get("declared_storeys") or 0.0) > 0.0
    if standing > storeys_allowed and not declared_stature:
        settled = fit_to_site(_taller(current, storeys_allowed / standing), site)
        if settled.satisfied and settled.gross_floor_area_m2 > 0.0:
            best, current = settled, settled.form

    # Too large is as wrong as too small once a brief exists. A 설계공모지침서
    # gives 연면적 with a tolerance - ±5% is close to universal - and going
    # over it costs marks before a juror has looked at the drawing, with enough
    # of it disqualifying the entry. The loop below only ever grew, so a
    # sentence that arrives at the full height the parcel affords stayed three
    # times the size it was asked for.
    #
    # Plan first, and only plan: the brief says how much floor, and the storey
    # heights belong to the rooms. `_wider` scales the whole composition about
    # one anchor, so shrinking brings the volumes toward each other in the same
    # proportion and what was touching stays touching - which is the thing two
    # hand-written attempts at this got wrong, reporting 296 of 403 schemes as
    # several separate buildings.
    #
    # ⚠️ That anchor is an axis-aligned box around volumes posed at the parcel's
    # bearing, so it is not the composition's own centre, as this comment used
    # to claim. Scaling about the wrong point translates the result by
    # (1 - factor) times the offset. Measured over the corpus on 의정부 the
    # offset is a median 0.82 m and 9.91 m at worst, so a 1.15 growth step
    # slides the mass 0.12 m typically and 1.5 m at worst on a 68 m plot.
    # Contact is preserved either way - a similarity transform cannot break it -
    # so this is left alone and measured rather than changed. Same call, same
    # reason, as `legal_fit._scaled_about_own_centre`.
    if briefed:
        for _step in range(_MAX_STEPS):
            standing = best.gross_floor_area_m2
            if standing <= capacity * _OVER_ENOUGH:
                break
            smaller = _wider(current, max(0.75, (capacity / standing) ** 0.5))
            candidate = fit_to_site(smaller, site)
            if not candidate.satisfied or candidate.gross_floor_area_m2 <= 0.0:
                reason = "brief_could_not_be_met"
                break
            if candidate.gross_floor_area_m2 >= standing - 1.0:
                reason = "brief_could_not_be_met"
                break
            best, current, wider = candidate, candidate.form, wider + 1
        else:
            reason = "brief_reached"

    for step in range(_MAX_STEPS):
        if best.gross_floor_area_m2 >= capacity * _FULL_ENOUGH:
            reason = "far_capacity_reached"
            break

        standing = best.gross_floor_area_m2 / max(best.ground_area_m2, 1.0)
        # Same exemption as the settle above, and it has to be both or neither.
        # Exempting only the settle stopped two sentences from growing into the
        # floor area they were allowed - cctv_a_loop_stood_up and
        # f_daegak_monolith came out 1.9 m and 1.6 m shorter than when they
        # were cut here and grew back - because the cut is what left them room
        # to grow. A sentence that declared its stature keeps growing until the
        # capacity check above stops it, which is 용적률, or until the fit does.
        if standing >= storeys_allowed and not declared_stature:
            if not allow_plan_growth:
                reason = "parcel_storey_ceiling_reached"
                break
            grown = _wider(current, 1.12)
            candidate = fit_to_site(grown, site)
            if worth_taking(candidate):
                best, current, wider = candidate, candidate.form, wider + 1
                continue
            reason = "parcel_storey_ceiling_reached"
            break

        # Ask for exactly the shortfall rather than a fixed increment: the step
        # size is a property of how far this scheme is from its ceiling.
        #
        # Unless the scheme is a field, which buys area by spreading and never
        # by rising. Left to grow upward, a field's small objects came back as
        # a bundle of sticks on a plinth at 용적률 0.99 - lawful, slender enough
        # to pass, and not the building that was authored.
        if (form.extra.get("growth") != "plan"
                and _tallest_volume(current) < volume_ceiling - 1e-6):
            want = capacity / max(best.gross_floor_area_m2, 1.0)
            grown = _taller(current, min(
                1.35, max(1.02, want),
                volume_ceiling / max(_tallest_volume(current), 1e-6)))
            candidate = fit_to_site(grown, site)
            if worth_taking(candidate):
                best, current, taller = candidate, candidate.form, taller + 1
                continue

        if not allow_plan_growth:
            reason = "height_exhausted"
            break

        # Headroom read on the UNCLIPPED projection: `best.ground_area_m2`
        # is taken through the legal clip, so once a widening field runs past
        # the boundary the clipped number stops rising and the loop keeps
        # widening forever - each step fusing the lanes the clip cuts back to
        # the same edge. The audit's scattered village dissolving into one
        # plate at exactly the parcel line is this loop. What the scheme
        # actually occupies, clip or no clip, is the honest brake.
        from backend.app.modules.design.generation.maas.massv2.legal_fit import projected_ground_area

        unclipped = projected_ground_area(current)
        headroom = site.ground_capacity_m2 / max(
            best.ground_area_m2, unclipped, 1.0
        )
        if headroom <= 1.01:
            reason = "both_ceilings_reached"
            break
        grown = _wider(current, min(1.20, headroom ** 0.5))
        candidate = fit_to_site(grown, site)
        if worth_taking(candidate):
            best, current, wider = candidate, candidate.form, wider + 1
            continue

        reason = "growth_would_cost_the_form"
        break

    return FillResult(best, taller + wider, taller, wider, reason, share)
