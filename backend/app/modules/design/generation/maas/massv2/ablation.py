"""Take one word out of the sentence and see whether the building notices.

`postcondition` asks whether a word changed the mass *at the moment it was
said* - it runs the sentence forward and compares consecutive frames, at the
size it was authored, before the growth loop and before the legal clip. That is
the right question for finding a word that was never doing anything, and it is
the wrong one for finding a word whose effect does not survive to the drawing.

The two come apart because everything after the sentence can undo it. `fill`
grows the composition toward the parcel's own capacity; the compiler cuts every
band to the sunlight envelope. A shear measured 0.35 unclipped and 0.04 after
the clip on the same scheme, which was recorded at the time as the gate being
right - the two masses really were nearly the same building. So a word can pass
the postcondition and still be absent from what a person is shown.

This asks the other question, the one the critics are actually answering:

    remove this word from the sentence, run the whole pipeline again, and
    compare the two delivered masses.

A word that changes nothing when removed is not in the building, whatever it
did in the middle of the sentence. Removing a word can also break the words
after it - `on: "west_islands"` names a part that a removed `split` never made,
and `_scope` then finds nothing and the operation is silent. That is not a flaw
in the measurement, it is the measurement: a word the rest of the sentence
depends on is load-bearing, and the number says so.

An operation that requires a selected body can instead report a typed missing
dependency. Only the shortened counterfactual maps that condition to no mass;
the original sentence and malformed geometry still fail normally.

Cost is one extra pipeline run per word, at sentence level rather than per
delivered variant - about three runs for a typical sentence. The coverage and
siting copies of one sentence share its words, so they share this number.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.floor_viability import DEFAULT_MINIMUM_CLEAR_DEPTH_M

from backend.app.modules.design.generation.maas.source_geometry.ir import SourceMass

from backend.app.modules.design.generation.maas.massv2.compile import compile_matrix_form
from backend.app.modules.design.generation.maas.massv2.execute import MissingOperationDependency, execute as execute_parti
from backend.app.modules.design.generation.maas.massv2.fill import fill_to_site
from backend.app.modules.design.generation.maas.massv2.grammar import JOINT_CLEARANCE_M
from backend.app.modules.design.generation.maas.massv2.postcondition import changed_share


@dataclass(frozen=True)
class Ablation:
    """What each word is worth to the mass that gets drawn."""

    declared: tuple[str, ...]
    removed_share: tuple[float, ...]

    @property
    def force(self) -> float:
        """The mean word. Not the weakest: a sentence is allowed one quiet word
        beside a loud one, and the postcondition gate already refuses a word
        that does nothing at all."""

        if not self.removed_share:
            return 0.0
        return sum(self.removed_share) / len(self.removed_share)

    @property
    def idle(self) -> tuple[str, ...]:
        """Words the delivered building does not notice the loss of."""

        return tuple(
            verb
            for verb, share in zip(self.declared, self.removed_share)
            if share < IDLE_BELOW
        )

    def evidence(self) -> dict[str, Any]:
        return {
            "schema_version": "arr.maas.massv2_ablation.v1",
            "declared": list(self.declared),
            "removed_share": [round(value, 4) for value in self.removed_share],
            "force": round(self.force, 4),
            "idle": list(self.idle),
        }


# Below this the delivered mass is the same drawing without the word. The same
# floor `postcondition` uses, for the same reason and against the same corpus
# reading - a move under a twentieth of the building is not a decision anyone
# can see. Reported, not gated: this module measures, and whether it should
# refuse anything is a question for evidence that does not exist yet.
IDLE_BELOW = 0.05


def _delivered(
    parti, *, buildable, axis, height_m, site, storey_height_m: float,
    allow_missing_dependency: bool = False,
) -> SourceMass | None:
    """The mass this sentence actually puts on the sheet, clip and growth included."""

    if not parti.ops:
        return None
    try:
        form = execute_parti(
            parti, buildable=buildable, axis=axis, height_m=height_m,
            storey_height_m=storey_height_m,
        )
    except MissingOperationDependency:
        # Only a shortened, already-valid sentence may lose its creator.
        # Invalid authored payloads and errors in the whole sentence propagate.
        if allow_missing_dependency:
            return None
        raise
    if form is None:
        return None
    filled = fill_to_site(form, site)
    return compile_matrix_form(
        filled.fit.form, storey_height_m=storey_height_m, allowed_at=site.plan_at
    )


def ablate(
    parti, *, buildable, axis, height_m, site, storey_height_m: float
) -> Ablation:
    """One run per word, each with that word taken out."""

    declared = tuple(op.verb for op in parti.ops)
    whole = _delivered(
        parti, buildable=buildable, axis=axis, height_m=height_m,
        site=site, storey_height_m=storey_height_m,
    )
    if whole is None:
        return Ablation(declared, tuple(0.0 for _ in declared))

    shares: list[float] = []
    for index in range(len(parti.ops)):
        shorter = replace(
            parti,
            ops=tuple(op for position, op in enumerate(parti.ops) if position != index),
        )
        without = _delivered(
            shorter, buildable=buildable, axis=axis, height_m=height_m,
            site=site, storey_height_m=storey_height_m, allow_missing_dependency=True,
        )
        # A sentence that will not stand without this word is entirely this
        # word's, which is the strongest thing the measure can say.
        shares.append(1.0 if without is None else changed_share(whole, without))
    return Ablation(declared, tuple(shares))


def gap_survived(
    parti, *, buildable, axis, height_m, site, storey_height_m: float
) -> tuple[float, float]:
    """A sentence that declared a gap, and the widest gap the building has.

    Returned as (declared_m, delivered_m). Both zero when the sentence never
    claimed one.

    Sixteen of the faults in the last critique round were `gaps-not-present`,
    and three of the four judges independently named the same thing: a verb ran,
    the gate said it changed the mass, and the thing the sentence was about -
    the lane, the street, the space between - is not in the drawing. The two
    lowest-scoring alternatives of sixteen both say volumes stand apart and both
    draw them fused; each lost every pair it appeared in.

    It is checked on the delivered mass because that is where it goes wrong. The
    executor sets the gap by construction, so at authoring size it is always
    there; the growth loop widens the pieces back toward each other and the
    legal clip trims what overhangs, and between them the gap closes.

    `gap` in a sentence is multiplied by JOINT_CLEARANCE_M, which is how a
    corpus came to write 0.14 and mean 11 cm while the caption said "separate
    pavilions".
    """

    # ⚠️ This is the narrowest separation anywhere in the storey, not the
    # separation the split asked for, and the difference matters on one class of
    # scheme. `sanaa_sydney_modern` splits a field its `aggregate` already made:
    # two of those objects stand 0.63 m apart, the split's own gap is fine, and
    # this refuses the sentence for a gap it never claimed.
    #
    # Measuring between the parts the split named was tried and is worse. Roles
    # do not survive the compiler - `_band_role` names each band after whichever
    # volume dominates it, so both halves of a split share one name wherever
    # they share a storey, the lookup finds nothing, and twenty-two sentences
    # came back at 0.0 m. Fixing it properly means carrying both roles through
    # the band, which is a change to the compiled representation.
    # The narrowest claim, against the narrowest delivery below. Taking the
    # widest claim compares the loudest thing the sentence says to the quietest
    # thing it builds, and on a sentence that cuts twice those are different
    # cuts: `kr_hansol_gym_is_its_own_body` declares 2.58 m and 1.82 m and
    # delivers 1.82 m exactly - its second gap, intact - and was being failed
    # against its first. What this gate exists to catch is a declared
    # separation that came out fused, and min against min catches that.
    declared = declared_gap_m(parti)
    if declared <= 0.0:
        return (0.0, 0.0)
    source = _delivered(
        parti, buildable=buildable, axis=axis, height_m=height_m,
        site=site, storey_height_m=storey_height_m,
    )
    evidence = gap_evidence(source, declaration=parti)
    return evidence['declared_m'], evidence['delivered_m']


def declared_gap_m(declaration):
    """Read either Parti or its compiler-preserved operation evidence."""
    if hasattr(declaration, 'ops'):
        operations = declaration.ops
    else:
        declaration = declaration or {}
        declaration = declaration.get('parti') or declaration
        operations = declaration.get('operations') or declaration.get('ops') or ()
    claims = []
    for operation in operations:
        params = operation.params if hasattr(operation, 'params') else operation.get('params', operation)
        value = float(params.get('gap') or 0.)
        if value > 0.:
            claims.append(value * JOINT_CLEARANCE_M)
    return min(claims) if claims else 0.


def gap_satisfied(declared_m, delivered_m):
    """The existing space-or-reveal rule, shared by fitting and delivery."""
    return not (declared_m > 0. and delivered_m < min(declared_m, GAP_IS_A_SPACE_M) - GAP_TOLERANCE_M)


def gap_evidence(source, *, declaration=None):
    """Measure the actual delivered SourceMass using the existing band-gap rule.

    This is the widest level's narrowest separation, not proof of a traversable
    path, entry location or clearance between individually named split roles.
    """
    if declaration is None:
        declaration = source.metadata if source is not None else {}
    declared = declared_gap_m(declaration)
    delivered = _source_gap_m(source) if source is not None and declared > 0. else 0.
    return {'declared_m': declared, 'delivered_m': delivered,
            'required_m': min(declared, GAP_IS_A_SPACE_M), 'tolerance_m': GAP_TOLERANCE_M,
            'satisfied': gap_satisfied(declared, delivered),
            'basis': 'widest band-level narrowest component separation; not verified circulation'}


def _source_gap_m(source):
    # A gap is the narrowest separation in the storey that has one, not the
    # distance between the two furthest pieces - the first version measured the
    # latter and reported every sentence at over 100% because the two ends of a
    # building are always far apart.
    height = float(source.metadata.get("authored_height_m") or 0.0)
    widest = 0.0
    for volume in source.volumes:
        level = (volume.bottom_fraction + volume.top_fraction) / 2.0
        parts = [
            item.footprint
            for item in source.volumes
            if item.bottom_fraction - 1e-6 <= level <= item.top_fraction + 1e-6
        ]
        if len(parts) < 2:
            continue
        merged = unary_union(parts)
        pieces = list(merged.geoms) if merged.geom_type == "MultiPolygon" else [merged]
        if len(pieces) < 2:
            # Everything at this height is one solid: nothing stands apart.
            continue
        narrowest = min(
            float(one.distance(two))
            for index, one in enumerate(pieces)
            for two in pieces[index + 1:]
        )
        widest = max(widest, narrowest)
    return widest


# How wide the surviving gap has to be to still be a gap.
#
# A share of what was declared is the wrong test, and the corpus says why: Lab
# City writes 7.6 m and delivers 2.7 m, which is 35% and is still a lane you
# walk down - it scored 83% with the critics and is one of the best things the
# grammar makes. Kimbell writes 6.1 m and delivers 0.6 m, which is 10% and is a
# construction joint. What separates them is not the ratio, it is whether the
# thing left over is a space.
#
# So the threshold is the project's own minimum room depth. A gap narrower than
# a room is not a street, a lane, a court or a valley - it is the line where two
# volumes failed to touch. Measured over the corpus: 34 sentences declare a gap,
# 15 deliver under half of it and four deliver exactly nothing.
GAP_IS_A_SPACE_M = DEFAULT_MINIMUM_CLEAR_DEPTH_M

# Below this a shortfall is construction noise, not a closed gap. `JOINT_CLEARANCE_M`
# is 0.76 m, so the smallest thing any sentence can declare is centimetres wide:
# `sanaa_bocconi_campus` writes 0.21 m and delivers 0.20 m, and failing that as a
# missing space says nothing about the building.
GAP_TOLERANCE_M = 0.05


__all__ = ["Ablation", "ablate", "gap_survived", "IDLE_BELOW", "GAP_IS_A_SPACE_M",
           "GAP_TOLERANCE_M", "gap_evidence", "declared_gap_m", "gap_satisfied"]
