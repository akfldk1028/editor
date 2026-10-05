"""Fit a form to the parcel by moving its volumes, not by carving the result.

The existing path searches for one global 4x4 pose for the whole rigid body, and
when it cannot find one it says `whole_solid_affine_fit_infeasible`, falls back
to clipping the solid against the legal prism with CSG, and then demotes what
comes out to `legal_analysis_proxy_only` - a mass that can no longer be rendered
or scored. Authored intent is spent to buy legality.

Here every volume carries its own matrix, so an offending volume can be reduced
or moved on its own and the rest of the composition survives untouched. Two laws
are enforced, in the order they bind:

  건축면적 - 건축법 시행령 제119조 제1항 제2호. The horizontal projection of the
  whole building, unioned over every height, against the parcel's BCR ceiling.
  Because it is a projection, only plan dimensions can pay for it.

  정북일조 - the legal plan shrinks as height rises. A volume is checked at the
  top of its own span, which is where it is tightest, and pulled in there.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from shapely.geometry import Polygon
from shapely.ops import unary_union

from math import atan2, degrees

from backend.app.modules.design.generation.maas.geometry_language.affine_matrix import compose_matrix4, rotation_matrix4, scale_matrix4, translation_matrix4, validate_matrix4

from backend.app.modules.design.generation.maas.massv2.compile import _plan, compile_matrix_form
from backend.app.modules.design.generation.maas.massv2.form import MatrixForm, Placement, section_held_through_height_scale
from backend.app.modules.design.generation.maas.massv2.legal import LegalSite
from backend.app.modules.design.generation.maas.massv2.measure import gross_floor_area_m2, storeys_in


# Below this the shrink is not worth another pass; further passes chase float
# noise rather than area.
_CONVERGED = 0.995
_MAX_PASSES = 6
# Plan-scale passes against a clipped measure. Clipping makes the measured area
# approach the ceiling from above rather than scale with the factor, so six
# passes stopped 0.03% over and reported fourteen schemes unlawful for 0.4 m2 on
# 1498. More passes, and aimed just inside the line rather than at it, because a
# limit converged onto from above is a limit crossed.
_CEILING_PASSES = 24
_CEILING_AIM = 0.999
# How close a volume's base has to be to another's top to count as resting on
# it, and how much plan they have to share. Both are the float-noise thresholds
# the structure module already uses for the same question.
_SETTLE_TOLERANCE_M = 0.05
_MEANINGFUL_CONTACT_M2 = 1.0

# Floor area is trimmed one storey at a time, so the bound is a storey count
# rather than a ratio. A building with more storeys than this over its capacity
# was authored for a different parcel.
_STOREY_TRIMS = 40
# Halvings used to find the height at which the sunlight envelope runs out. Ten
# brings a sixty-metre span inside six centimetres, which is finer than any
# dimension this language works in.
_BISECTIONS = 10


@dataclass(frozen=True)
class LegalFitResult:
    form: MatrixForm
    ground_area_m2: float
    ground_capacity_m2: float
    gross_floor_area_m2: float
    far_capacity_m2: float
    passes: int
    plan_scale_applied: float
    volumes_pulled_in: int
    satisfied: bool
    storey_limit: dict | None = None
    area_limits: dict | None = None

    def evidence(self) -> dict[str, Any]:
        return {
            "schema_version": "arr.maas.massv2_legal_fit.v1",
            "ground_area_m2": round(self.ground_area_m2, 3),
            "ground_capacity_m2": round(self.ground_capacity_m2, 3),
            "ground_take": round(
                self.ground_area_m2 / max(self.ground_capacity_m2, 1e-9), 4
            ),
            "gross_floor_area_m2": round(self.gross_floor_area_m2, 3),
            "far_capacity_m2": round(self.far_capacity_m2, 3),
            "far_utilization": round(
                self.gross_floor_area_m2 / max(self.far_capacity_m2, 1e-9), 4
            ),
            "passes": self.passes,
            "plan_scale_applied": round(self.plan_scale_applied, 5),
            "volumes_pulled_in": self.volumes_pulled_in,
            "satisfied": self.satisfied,
            'storey_limit': self.storey_limit,
            'area_limits': self.area_limits,
            "method": "per_volume_affine_no_csg",
        }


def projected_ground_area(form: MatrixForm, *, allowed_at=None) -> float:
    """건축면적: the plan union over every height, not the ground floor.

    A mass whose ground floor is modest while its upper floors overhang to the
    cap still covers that much ground, and measuring the lowest band would file
    it as dispersed.

    With `allowed_at` the union is taken over the compiled bands, which are cut
    to the legal plan - the same thing the report will see. Measuring the raw
    placements while the compiler clips them is how the fit and the report came
    to disagree before.
    """

    if allowed_at is not None:
        source = compile_matrix_form(form, allowed_at=allowed_at)
        if source is None:
            return 0.0
        # A basement larger than the building above it is not 건축면적:
        # the projection is of what stands above the parcel's ground.
        height = float(source.metadata.get("authored_height_m") or 0.0)
        datum = float(source.metadata.get("datum_m") or 0.0)
        plans = [volume.footprint for volume in source.volumes
                 if float(volume.top_fraction) * height > datum + 1e-6]
    else:
        plans = [_plan(item) for item in form.additive() if item.z_span()[1] > 1e-6]
    plans = [item for item in plans if not item.is_empty and item.area > 0.0]
    if not plans:
        return 0.0
    return float(unary_union(plans).area)


def _gross_floor_area(form: MatrixForm, *, floor_height_m: float, allowed_at=None) -> float:
    """연면적 of a form, measured exactly the way it will be reported.

    Sharing the storey rule was not enough. The fit measured each placement over
    its own full height while the report measured the compiled bands, and a
    volume ten metres tall counts as three storeys whole but four once it is cut
    at five - so four schemes the fit had made lawful came back over the ceiling.

    Compiling here is affordable precisely because this language has no 3D CSG:
    a compile is band cuts and 2D shapely, not booleans and mesh traversals. One
    measure, one answer.

    "One measure" includes the storey height, which this dropped. A leaning
    volume is cut at storeys and an upright one is not, so compiling without it
    collapsed a raking bar into a single band - and the fit then certified a
    용적률 the report measured 26% higher. `opening_terraced_ell` was passed as
    lawful at 2268 m2 against a 2499.7 m2 ceiling while actually standing at
    3149.4. Same form, same rule, two answers, and the gate believed the
    forgiving one.
    """

    source = compile_matrix_form(
        form, storey_height_m=floor_height_m, allowed_at=allowed_at
    )
    if source is None:
        return 0.0
    return gross_floor_area_m2(source, floor_height_m=floor_height_m)


def _scaled_in_plan(
    placement: Placement, factor: float, anchor: tuple[float, float],
    *, carrying: bool = False,
) -> Placement:
    """Shrink a volume in plan about a shared anchor, leaving its height alone.

    건축면적 is a projection, so height cannot pay for it. Scaling about a shared
    anchor rather than each volume's own centre keeps the composition's
    relationships - a shifted stack stays shifted instead of collapsing into a
    concentric wedding cake.

    A volume with a ridge keeps its section: the across-ridge share of the
    scale is undone about the volume's own centre, so a gabled bar pays for
    coverage with length, never with its pentagon. This lives here and not in
    any caller because every scaler goes through this function - the coverage
    retarget held the section and the growth loop then squashed it anyway,
    which is what an invariant enforced at one call site out of five does.
    """

    matrix = compose_matrix4(
        placement.matrix,
        translation_matrix4((-anchor[0], -anchor[1], 0.0)),
        scale_matrix4((factor, factor, 1.0)),
        translation_matrix4((anchor[0], anchor[1], 0.0)),
    )
    scaled = replace(placement, matrix=validate_matrix4(matrix))
    ridge = getattr(placement, "ridge_along", None)
    if ridge is None:
        # A profiled top holds its section the same way a ridge does: the
        # preserved axis is the fold line, perpendicular to the profile's run.
        across = getattr(placement, "profile_across", None)
        profile = getattr(placement, "top_profile", None)
        # A profile of two stations is a PLANE (grade smooth), and a plane
        # has no proportion to hold: undoing the across-scale about the
        # volume's own centre kept each of two graded bars at full width
        # while the composition shrank between them, and the 6 m valley the
        # sentence was about closed to 0.0 in every coverage band. Only a
        # folded or curved section (three stations or more) keeps its metres.
        if across is not None and profile is not None and len(profile) > 2:
            ridge = (-across[1], across[0])
    if ridge is None or abs(factor - 1.0) < 1e-6 or factor <= 1e-9:
        return scaled
    # A pitch is a rise over a run, so the section survives a plan scale if the
    # rise takes the same scale as the run. The first version kept it by
    # undoing the across-ridge scale about the volume's own centre - the bar
    # kept its width while the composition shrank around it, and a bar that
    # keeps its width inside a shrinking ring grows inward. Measured: of the
    # thirty-four sentences in this corpus that ring, cut or bore a void,
    # fourteen delivered under half of it, and `d_bakgong_madang` lost its
    # court here, 0.63 to 0.31, in this one line - the courtyard paid for the
    # roof's proportion. Scaling the rise instead costs height, which is free
    # of 건축면적 and is what a smaller house does anyway.
    if carrying:
        # Height is only spendable by a volume with nothing standing on it.
        # Shrinking a house that carries another house shortens the bearing
        # its neighbour lands on, and the four sentences that stack a gable on
        # a gable came back at 1.65 to 1.98 of backspan against a limit of
        # 1.60. A carrier keeps its height and holds its section the older
        # way; it is not part of a ring, so there is no court to spend.
        corners = scaled.corners()
        cx = sum(x for x, _y, _z in corners) / len(corners)
        cy = sum(y for _x, y, _z in corners) / len(corners)
        angle = degrees(atan2(ridge[1], ridge[0]))
        held = compose_matrix4(
            scaled.matrix,
            translation_matrix4((-cx, -cy, 0.0)),
            rotation_matrix4((0.0, 0.0, -angle)),
            scale_matrix4((1.0, 1.0 / factor, 1.0)),
            rotation_matrix4((0.0, 0.0, angle)),
            translation_matrix4((cx, cy, 0.0)),
        )
        return replace(scaled, matrix=validate_matrix4(held))
    low, _high = scaled.z_span()
    kept = compose_matrix4(
        scaled.matrix,
        translation_matrix4((0.0, 0.0, -low)),
        scale_matrix4((1.0, 1.0, factor)),
        translation_matrix4((0.0, 0.0, low)),
    )
    # No section_held here, alone of the z-scales: this branch scales the rise
    # BECAUSE the run scaled, so the share must ride along - that is the pitch
    # surviving. Dividing the share back holds the roof's metres while the
    # walls shrink, and at factor 0.7 a 1.2-pitch gable delivers 1.7.
    return replace(scaled, matrix=validate_matrix4(kept))


def _shortened(placement: Placement, factor: float) -> Placement:
    """Lower the top, keeping the base where the author put it."""

    low, _high = placement.z_span()
    matrix = compose_matrix4(
        placement.matrix,
        translation_matrix4((0.0, 0.0, -low)),
        scale_matrix4((1.0, 1.0, max(1e-3, factor))),
        translation_matrix4((0.0, 0.0, low)),
    )
    return section_held_through_height_scale(
        replace(placement, matrix=validate_matrix4(matrix)), max(1e-3, factor))


def _dropped(placement: Placement, distance: float) -> Placement:
    """Move a volume straight down, keeping its size."""

    return replace(placement, matrix=validate_matrix4(compose_matrix4(
        placement.matrix, translation_matrix4((0.0, 0.0, -distance))
    )))


def _settled_onto(placements, trimmed_index: int, drop: float):
    """Bring down whatever was resting on a volume that just got shorter.

    Taking a storey off a lower tier and leaving the tiers above it in the air
    opens a gap the width of the storey, and the mass then reports itself as
    `only_63%_of_the_mass_reaches_the_ground` - which is true, and is the
    trim's doing rather than the author's. A building settles when you remove a
    floor from underneath it.

    What is resting on it is what overlaps it in plan and starts at its old top.
    Anything standing beside it, or bridging over it from its own supports,
    stays where it is.
    """

    trimmed = placements[trimmed_index]
    old_top = trimmed.z_span()[1] + drop
    footprint = Polygon([(x, y) for x, y, _z in trimmed.corners()]).convex_hull
    out = list(placements)
    for index, item in enumerate(placements):
        if index == trimmed_index or item.kind != "additive":
            continue
        low = item.z_span()[0]
        if abs(low - old_top) > _SETTLE_TOLERANCE_M:
            continue
        plan = Polygon([(x, y) for x, y, _z in item.corners()]).convex_hull
        if plan.is_empty or footprint.is_empty:
            continue
        if float(plan.intersection(footprint).area) <= _MEANINGFUL_CONTACT_M2:
            continue
        out[index] = _dropped(item, drop)
    return out


def _lowered_under_envelope(placement: Placement, allowed_at) -> Placement | None:
    """Bring a volume down to the tallest height that still has an envelope.

    Bisection rather than fixed steps: the height where the envelope runs out is
    a property of the parcel, not a number to guess at, and halving finds it to
    within a few centimetres in the same handful of evaluations a coarse ladder
    would spend missing it.
    """

    low, high = placement.z_span()
    span = high - low
    if span <= 1e-6:
        return None
    lower, upper = 0.0, 1.0
    best: Placement | None = None
    for _step in range(_BISECTIONS):
        middle = (lower + upper) / 2.0
        candidate = _shortened(placement, middle)
        _clow, chigh = candidate.z_span()
        ceiling = allowed_at(chigh)
        if ceiling is not None and not ceiling.is_empty:
            best = candidate
            lower = middle
        else:
            upper = middle
    return best


def _pulled_inside(
    placement: Placement, allowed_at, *, minimum_plan_share: float = 0.45
) -> Placement | None:
    """Bring one volume inside the sunlight envelope, in plan or in height.

    정북일조 says step back as you rise, and a building may answer that two ways:
    move away from the boundary, or stop short of the height where the envelope
    bites. Paying only in plan - which is what this did first - pinches a tall
    volume into a sliver or drops it, when lowering its top would have kept the
    author's proportions intact. So plan is tried first, and if it would cost
    more than `minimum_plan_share` of the volume's footprint, height pays
    instead.

    Only this volume moves. The alternative in the existing pipeline is to clip
    the whole solid, which changes a mass the author did not design and forfeits
    its right to be rendered or scored.
    """

    low, high = placement.z_span()
    plan = _plan(placement)
    if plan.is_empty:
        return None

    allowed = allowed_at(high)
    if allowed is None or allowed.is_empty:
        # Nothing at all is buildable at this height - measured on the live
        # parcel, `plan_at` returns None from about 80 m up. Reading that as
        # "no envelope to check" and waving the volume through is a fail-open on
        # a legal check, and heights of 64 m were already being produced. The
        # volume has to come down to a height that does have an envelope.
        return _lowered_under_envelope(placement, allowed_at)

    if allowed.contains(plan):
        return placement

    inside = plan.intersection(allowed)
    share = float(inside.area) / float(plan.area) if float(plan.area) > 0.0 else 0.0
    if share >= minimum_plan_share:
        centre = plan.centroid
        factor = share ** 0.5
        for _attempt in range(_MAX_PASSES):
            candidate = _scaled_in_plan(placement, factor, (float(centre.x), float(centre.y)))
            if allowed.contains(_plan(candidate)):
                return candidate
            factor *= 0.94

    # Plan alone is too expensive here. Find the highest level whose envelope
    # still holds this footprint, and stop the volume there.
    span = high - low
    if span <= 1e-6:
        return None
    for step in range(1, _MAX_PASSES + 1):
        factor = 1.0 - step / (_MAX_PASSES + 1.0)
        candidate = _shortened(placement, factor)
        _clow, chigh = candidate.z_span()
        ceiling = allowed_at(chigh)
        if ceiling is not None and not ceiling.is_empty and ceiling.contains(_plan(candidate)):
            return candidate
    return None


# The space two bodies need between them to read as two bodies: the room
# width the plausibility gate erodes by, and the same number `composition`
# separates parts with. Anything narrower is a joint, not a court.
_BODY_SEPARATION_M = 1.5


def _scaled_composition(form: MatrixForm, factor: float,
                        anchor: tuple[float, float]) -> MatrixForm:
    """Scale a composition in plan with the carrying invariant enforced.

    The invariant - a section-holding volume pays the plan scale in height,
    and whatever rested on it settles back down against the ORIGINAL
    supports - lived inside `_scaled_about_own_centre` alone, while four
    other callers scaled placements one at a time and got neither rule.
    That is what an invariant enforced at one call site out of five does:
    growth buried a stacked house 5.8 m inside its carriers, and a shrink
    opened the same gap into floating ends. One owner now; every plan scale
    of a whole composition comes through here.
    """

    if abs(factor - 1.0) < 1e-9:
        return form
    enclosure = unary_union([_plan(item) for item in form.additive()])
    has_court = any(
        len(getattr(part, "interiors", ())) > 0
        for part in getattr(enclosure, "geoms", [enclosure])
    )
    carries = set()
    for index, item in enumerate(form.placements):
        if item.kind != "additive":
            continue
        top = item.z_span()[1]
        plan = _plan(item)
        holds_something = any(
            other.kind == "additive"
            and abs(other.z_span()[0] - top) <= 1e-3
            and _plan(other).intersects(plan)
            for other in form.placements
        )
        if holds_something or not has_court:
            carries.add(index)
    scaled = [
        _scaled_in_plan(item, factor, anchor, carrying=(index in carries))
        for index, item in enumerate(form.placements)
    ]
    # The section-holding exemption undoes the across-ridge scale about each
    # volume's own centre, so a gabled bar pays for coverage with length
    # rather than with its pentagon. On ONE body that is right. On a field it
    # is paid for by the space between the units: every unit keeps its width
    # while the anchor pulls their centres together, and a court of 9.4 m
    # closed to 0.35 m in a single fit - which is how "two bars flanking a
    # court" arrived as one block and why half of one round lost its parti at
    # delivery. Space between bodies is architecture too. If the exemption
    # closed it below what a person can walk through, the composition scales
    # plainly instead, where every distance moves with the factor and the
    # relationships survive.
    if factor < 1.0 - 1e-9:
        def _gaps(items) -> dict:
            """Every pair's separation, by pair, with zero included.

            The minimum positive gap answered the wrong question twice: one
            0.3 m construction joint anywhere made the whole composition look
            already closed, and a court that closed to exactly zero was
            excluded from the reading that exists to catch it. Pairs are
            compared with themselves instead.
            """

            plans = [(index, _plan(item)) for index, item in enumerate(items)
                     if item.kind == "additive" and item.occupiable]
            out = {}
            for a in range(len(plans)):
                for b in range(a + 1, len(plans)):
                    out[(plans[a][0], plans[b][0])] = plans[a][1].distance(plans[b][1])
            return out

        before = _gaps(form.placements)
        after = _gaps(scaled)
        # A declared lane already has a clearance policy. Section restoration
        # must not close it merely because the generic body split remains >1.5m.
        # Local import avoids ablation -> fill -> legal_fit initialization cycle.
        from backend.app.modules.design.generation.maas.massv2.ablation import declared_gap_m, gap_satisfied
        declared_gap = declared_gap_m(form.extra)
        if any((gap > _BODY_SEPARATION_M
                and after.get(pair, gap) < _BODY_SEPARATION_M)
               or (declared_gap > 0 and gap_satisfied(declared_gap, gap)
                   and not gap_satisfied(declared_gap, after.get(pair, gap)))
               for pair, gap in before.items()):
            # Only the no-court exemption is dropped, not the carrier rule.
            # `carries` holds volumes for two reasons, and a genuine carrier
            # paying the plan scale in height is the stacked-gable regression
            # this branch exists to prevent: 1.65 to 1.98 of backspan against
            # a limit of 1.60.
            holds = set()
            for index, item in enumerate(form.placements):
                if item.kind != "additive":
                    continue
                top = item.z_span()[1]
                plan = _plan(item)
                if any(other.kind == "additive"
                       and abs(other.z_span()[0] - top) <= 1e-3
                       and _plan(other).intersects(plan)
                       for other in form.placements):
                    holds.add(index)
            scaled = [
                _scaled_in_plan(item, factor, anchor, carrying=(index in holds))
                for index, item in enumerate(form.placements)
            ]
    order = sorted(
        (index for index, item in enumerate(form.placements) if item.kind == "additive"),
        key=lambda index: form.placements[index].z_span()[0],
    )
    for index in order:
        base = form.placements[index].z_span()[0]
        plan = _plan(form.placements[index])
        carriers = [
            other for other in order
            if other != index
            and abs(form.placements[other].z_span()[1] - base) <= 1e-3
            and _plan(form.placements[other]).intersects(plan)
        ]
        if not carriers:
            continue
        landing = max(scaled[other].z_span()[1] for other in carriers)
        drop = scaled[index].z_span()[0] - landing
        if abs(drop) > 1e-6:
            scaled[index] = replace(
                scaled[index],
                matrix=validate_matrix4(compose_matrix4(
                    scaled[index].matrix, translation_matrix4((0.0, 0.0, -drop)),
                )),
            )
    return replace(form, placements=tuple(scaled))


def _scaled_about_own_centre(form: MatrixForm, factor: float) -> MatrixForm:
    """Scale the whole composition in plan about its own centre.

    One anchor for every volume, so the relationships survive: a shifted stack
    stays shifted rather than collapsing into a concentric wedding cake.
    """

    additive = form.additive()
    if not additive or abs(factor - 1.0) < 1e-9:
        return form
    # ⚠️ An axis-aligned box around volumes posed at the parcel's bearing, so
    # this anchor is not the composition's own centre - measured over the
    # corpus on 의정부 it sits a median 0.82 m off the centroid and 45 m off on
    # `vancouver_house_grows_as_it_rises`. Scaling about the wrong point
    # translates the result by (1 - factor) times that offset.
    #
    # Left alone deliberately: 2 of 1,074 delivered records reach this path at
    # all, at factors of 0.982 and 0.999, so the worst case in practice is a
    # 0.8 m slide before a clip that re-cuts the mass anyway. Changing it would
    # move every result for no measured gain.
    bounds = unary_union([_plan(item) for item in additive]).bounds
    anchor = ((bounds[0] + bounds[2]) / 2.0, (bounds[1] + bounds[3]) / 2.0)
    # A section-holding volume pays the plan scale in height, so whatever was
    # resting on it has to come down with it - the same rule the 용적률 trim
    # already follows. Without this the plan scale left upper volumes standing
    # where the roof used to be, and the structure gate read the gap correctly
    # as an unsupported cantilever: refusals went 15 to 20 over this corpus,
    # every one of the extra six that kind.
    # Height is only spendable by a volume with nothing standing on it, and
    # only in a composition that has a court to protect. Both conditions were
    # measured: paying with every volume cost four sentences their bearing,
    # and deciding it per volume by "does this bar wall a court" measured
    # worse on the very rings it was for (0.31 to 0.21 on `d_bakgong_madang`),
    # because a gabled ring bar reads as carrying its own roof band. The
    # composition either encloses a void or it does not.
    return _scaled_composition(form, factor, anchor)


# How much of an imposing scheme has to be legal before the clip is a trim
# rather than a redesign. Left at the corpus's own coverage for this mode -
# carve, loop and aggregate schemes sit at 30-56% of the plot - so a figure
# that cannot reach it here is simply too big for this parcel.
_IMPOSED_RETENTION = 0.92
_IMPOSE_STEPS = 14


def _drawn_inside(form: MatrixForm, allowed_at) -> MatrixForm:
    """Shrink an imposing figure until the legal line only trims it.

    Scanned rather than bisected. The share of a figure that lands inside a
    polygon is not monotone in its scale - grow a courtyard scheme and the void
    covers the parcel while the built parts leave it, which sent an earlier
    bisection to a factor of 4 returning nothing inside at all.
    """

    best = form
    for step in range(_IMPOSE_STEPS):
        factor = 1.0 - step * 0.06
        candidate = _scaled_about_own_centre(form, factor) if step else form
        raw = compile_matrix_form(candidate)
        cut = compile_matrix_form(candidate, allowed_at=allowed_at)
        if raw is None or cut is None:
            continue
        whole = sum(float(v.footprint.area) for v in raw.volumes)
        kept = sum(float(v.footprint.area) for v in cut.volumes)
        if whole <= 1e-9:
            continue
        best = candidate
        if kept / whole >= _IMPOSED_RETENTION:
            break
    return best


def _seated_under_envelope(placement: Placement, allowed_at):
    """Keep a volume that has any legal plan at its own height; lower it if not.

    This is what is left of `_pulled_inside` once the compiler clips. That
    function shrank a volume about its own centre until the buildable polygon
    *contained* it, which made the ceiling on 건폐율 the largest rectangle
    inscribed in the parcel rather than the parcel - and every scheme on a
    skewed site paid for the shape of the boundary twice, once by being cut and
    once by being shrunk.
    """

    _low, high = placement.z_span()
    allowed = allowed_at(high)
    if allowed is None or allowed.is_empty:
        return _lowered_under_envelope(placement, allowed_at)
    if _plan(placement).intersection(allowed).is_empty:
        return None
    return placement


def seat_on_site(form: MatrixForm, site: LegalSite) -> MatrixForm:
    """Move the whole form onto the buildable area before anything is checked.

    Families are authored in their own frame with a corner at the origin, which
    keeps the vocabulary readable and parcel-independent. The buildable area is
    inset from the parcel by setbacks, so a form left at the origin sits in the
    corner mostly outside it - and the per-volume check then legitimately drops
    every volume. Seating is a rigid move: it changes where the building is, not
    what it is.
    """

    plans = [_plan(item) for item in form.additive()]
    plans = [item for item in plans if not item.is_empty]
    if not plans:
        return form

    # Seat by the plan at the mass's own top, not at the ground. The sunlight
    # envelope is what binds, and it binds hardest up there: measured on this
    # parcel the buildable plan loses 450 m2 between the ground and 30 m, and
    # its centre moves 3.6 m southwest, because the envelope eats the northern
    # and eastern sides. Centring on the ground plan puts every mass in the
    # middle of the plot with an even margin all round - which is why they read
    # as objects set down on a site rather than buildings on a parcel - and
    # spends the one corner where height is actually available.
    top = max(item.z_span()[1] for item in form.additive())
    allowed = site.plan_at(top)
    if allowed is None or allowed.is_empty:
        allowed = site.plan_at(0.0)
    if allowed is None or allowed.is_empty:
        return form

    here = unary_union(plans).centroid
    there = allowed.centroid
    shift = translation_matrix4((float(there.x - here.x), float(there.y - here.y), 0.0))
    return replace(
        form,
        placements=tuple(
            replace(item, matrix=validate_matrix4(compose_matrix4(item.matrix, shift)))
            for item in form.placements
        ),
    )


def fit_to_site(form: MatrixForm, site: LegalSite) -> LegalFitResult:
    """Bring a form inside the parcel's limits by adjusting its volumes."""

    capacity = site.ground_capacity_m2
    allowed_at = site.plan_at
    # A scheme that imposes its own shape is fitted *into* the parcel rather
    # than cut *by* it. Clipping is right for a mass that takes the plot's
    # outline - a stack, a shear - and wrong for one whose figure is the point:
    # Kanazawa is a pure 112.5 m circle on an irregular park, and cutting it to
    # the park would leave a faceted cast of the park. So an imposing scheme is
    # brought down until almost all of it is legal, and the clip then removes
    # a trim rather than the design. Doing this to everything is not the
    # answer either - before the clip existed, ground take sat at 0.38.
    if str(form.extra.get("plot_mode") or "") == "impose":
        form = _drawn_inside(form, allowed_at)
    # A scheme that was given a position on the parcel keeps it. Seating
    # centres on the buildable centroid, which is the right default and the
    # wrong answer for a copy whose whole point is standing somewhere else.
    current = form if form.extra.get("siting") else seat_on_site(form, site)
    total_scale = 1.0
    passes = 0

    # 건축면적 first: it is a whole-building projection, so fixing it volume by
    # volume would just move the overshoot around.
    #
    # Since the compiler clips to the legal plan, shrinking no longer reduces the
    # projection in proportion - a scheme hanging over the boundary loses the
    # overhang to the clip, not to the scale, so a 1% correction can move the
    # measured area by nothing at all. Stopping when the correction got small
    # therefore stopped while still over the ceiling, and 23 schemes came back
    # unlawful. Stop when the *area* stops moving instead, which is the thing
    # actually being converged.
    for _pass in range(_CEILING_PASSES):
        area = projected_ground_area(current, allowed_at=allowed_at)
        if capacity <= 0.0 or area <= capacity:
            break
        passes += 1
        factor = (capacity * _CEILING_AIM / area) ** 0.5
        current = _scaled_about_own_centre(current, factor)
        total_scale *= factor
        if projected_ground_area(current, allowed_at=allowed_at) >= area - 1e-6:
            break

    # 정북일조 next. The compiler now cuts each band to the legal plan, so a
    # volume that leans out is trimmed rather than shrunk, and the only thing
    # left to decide per volume is whether any of it is legal at its own height
    # at all. One that is entirely above the envelope still has to come down -
    # `plan_at` returns None from about 80 m, and a volume up there is not
    # clipped to anything, it is simply not there.
    pulled = 0
    kept: list[Placement] = []
    for placement in current.placements:
        if placement.kind == "subtractive":
            kept.append(placement)
            continue
        adjusted = _seated_under_envelope(placement, allowed_at)
        if adjusted is None:
            # Nothing of this volume is legal at its own height. Dropping it is
            # honest; keeping a sliver would report a form the author never made.
            pulled += 1
            continue
        if adjusted is not placement:
            pulled += 1
        kept.append(adjusted)

    fitted = replace(current, placements=tuple(kept))

    # 용적률 last, and paid in height. Floor area is plan times storeys, and plan
    # has already been spent on 건축면적; taking it again would drive the ground
    # take away from the position the scheme was authored at. Height is the free
    # term here, and lowering a volume is the move an architect would make.
    far_capacity = site.far_capacity_m2
    floor_height = float(fitted.floor_height_m or site.floor_height_m)
    if far_capacity > 0.0 and floor_height > 1e-6:
        # Floor area moves in whole storeys, because storeys are counted with
        # `round`. Scaling height by a continuous ratio can shave 1% off a
        # volume without removing a floor, so the loop converges on nothing and
        # leaves the scheme over the ceiling - which is what left two schemes
        # unlawful. Take a storey off the tallest volume instead, and take it
        # from the tallest because that is the one the envelope is tightest on.
        for _pass in range(_STOREY_TRIMS):
            gfa = _gross_floor_area(
                fitted, floor_height_m=floor_height, allowed_at=allowed_at
            )
            if gfa <= far_capacity:
                break
            passes += 1
            # Only volumes with a storey to spare are candidates. Picking the
            # tallest outright and stopping when *it* ran out left every other
            # volume untouched, which made this worse rather than better.
            trimmable = [
                item
                for item in fitted.placements
                if item.kind == "additive"
                # A storey can only be taken from something that has two. The
                # rule is the same `storeys_in` the area is measured with, so
                # the loop cannot trim a volume the measure calls one floor.
                and storeys_in(
                    item.z_span()[1] - item.z_span()[0], floor_height_m=floor_height
                ) >= 2
            ]
            if not trimmable:
                break
            # Everything standing at that height, not one of them. A ring is
            # four bars of one height, and taking the storey off whichever bar
            # sorted first left a court open on one side: measured over this
            # corpus, fourteen of the thirty-four sentences that ring, cut or
            # bore a void delivered less than half of it, and this pass was
            # where it went - `d_bakgong_madang` 0.85 to 0.31 in one trim. The
            # figure is what the sentence is about; a ring is trimmed as a
            # ring. A stack, whose tiers are deliberately unequal, has one
            # tallest and is unaffected.
            spans = {item: item.z_span()[1] - item.z_span()[0] for item in trimmable}
            tallest_span = max(spans.values())
            peers = [
                item for item in trimmable
                if tallest_span - spans[item] <= floor_height * 0.5
            ]
            settled = list(fitted.placements)
            # By index: settling replaces entries in place, so a peer taken
            # from the pre-trim list is no longer findable by identity once
            # its neighbour has been brought down.
            targets = [
                (position, spans[item])
                for position, item in enumerate(settled)
                if item in peers
            ]
            for index, span in targets:
                settled[index] = _shortened(settled[index], (span - floor_height) / span)
                settled = _settled_onto(settled, index, floor_height)
            fitted = replace(fitted, placements=tuple(settled))

    # Height is exhausted when every volume is down to one storey, and a scheme
    # can still be over 용적률 there - clipped to a wide parcel, plan alone can
    # carry more floor area than the ceiling allows. Plan buys both, so it pays
    # last, and each round is re-checked against both ceilings.
    for _pass in range(_CEILING_PASSES):
        gfa = _gross_floor_area(
            fitted, floor_height_m=floor_height, allowed_at=allowed_at
        )
        area = projected_ground_area(fitted, allowed_at=allowed_at)
        over_far = far_capacity > 0.0 and gfa > far_capacity
        over_ground = capacity > 0.0 and area > capacity
        if not over_far and not over_ground:
            break
        passes += 1
        wanted = min(
            (far_capacity * _CEILING_AIM / gfa) if over_far and gfa > 0.0 else 1.0,
            (capacity * _CEILING_AIM / area) if over_ground and area > 0.0 else 1.0,
        )
        shrunk = _scaled_about_own_centre(fitted, max(0.5, wanted ** 0.5))
        if projected_ground_area(shrunk, allowed_at=allowed_at) >= area - 1e-6:
            break
        fitted = shrunk
        total_scale *= max(0.5, wanted ** 0.5)

    final_area = projected_ground_area(fitted, allowed_at=allowed_at)
    final_gfa = _gross_floor_area(
        fitted, floor_height_m=floor_height, allowed_at=allowed_at
    )
    from backend.app.modules.design.generation.maas.massv2.parcel_policy import storey_limit_evidence, area_limit_evidence
    final_source = compile_matrix_form(fitted, storey_height_m=floor_height, allowed_at=allowed_at)
    storey_gate = storey_limit_evidence(final_source, site, storey_m=floor_height) if final_source else {'satisfied': False}
    area_gate = area_limit_evidence(final_source, site, final_gfa) if final_source else {'satisfied': False}
    return LegalFitResult(
        form=fitted,
        ground_area_m2=final_area,
        ground_capacity_m2=capacity,
        gross_floor_area_m2=final_gfa,
        far_capacity_m2=far_capacity,
        passes=passes,
        plan_scale_applied=total_scale,
        volumes_pulled_in=pulled,
        storey_limit=storey_gate,
        area_limits=area_gate,
        satisfied=(
            bool(fitted.additive())
            and storey_gate['satisfied']
            and area_gate['satisfied']
            and (capacity <= 0.0 or final_area <= capacity + 1e-6)
            and (far_capacity <= 0.0 or final_gfa <= far_capacity + 1e-6)
        ),
    )
