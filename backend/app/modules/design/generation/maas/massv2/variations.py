"""Move a composition to a different ground take without changing what it is.

The two axes are independent in a way the old language could not exploit. Ground
take is how much of the allowed footprint the building claims, and for a set of
placed volumes that is a plan scale. Void is a property of the composition - how
the pieces sit relative to one another - and plan scaling leaves it alone,
because scaling a figure and its holes together does not change the share of the
figure that is open.

So a courtyard scheme authored at one ground take can be carried across the
whole coverage axis, and the grid fills from the compositions that already
exist rather than from hand-authoring one scheme per cell. That is the
difference between a vocabulary and a lookup table.
"""

from __future__ import annotations

from dataclasses import replace

from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.design_space import COVERAGE_BANDS, CoverageBand
from backend.app.modules.design.generation.maas.geometry_language.affine_matrix import compose_matrix4, scale_matrix4, validate_matrix4

from backend.app.modules.design.generation.maas.massv2.compile import _plan
from backend.app.modules.design.generation.maas.massv2.form import MatrixForm, section_held_through_height_scale
from backend.app.modules.design.generation.maas.massv2.legal_fit import _gross_floor_area, _scaled_composition, projected_ground_area


def retarget_ground_take(
    form: MatrixForm,
    *,
    target_area_m2: float,
    hold_programme: bool = True,
    far_capacity_m2: float = 0.0,
    floor_height_m: float = 3.0,
) -> MatrixForm | None:
    """Scale the composition in plan to claim `target_area_m2`.

    The scale is applied about the composition's own centre so relationships
    between volumes survive: a bar that overhung its plinth still overhangs it.

    `hold_programme` is what makes the copy a real alternative rather than a
    smaller picture of the same building. Taking less ground with the same height
    means building less - measured before this, a 45% copy delivered 45% of the
    floor area and read as an under-built site at 9% 용적률. An architect who
    disperses builds *taller* to hold the same programme, so height rises by the
    inverse of the plan scale. The legal fit still owns both ceilings and will
    cut the height back if 용적률 or the sunlight envelope says so.
    """

    area = projected_ground_area(form)
    if area <= 1e-9 or target_area_m2 <= 1e-9:
        return None
    factor = (target_area_m2 / area) ** 0.5
    if abs(factor - 1.0) < 1e-4:
        return form
    bounds = unary_union([_plan(item) for item in form.additive()]).bounds
    anchor = ((bounds[0] + bounds[2]) / 2.0, (bounds[1] + bounds[3]) / 2.0)
    lift = (
        _programme_lift(
            form, factor=factor, far_capacity_m2=far_capacity_m2, floor_height_m=floor_height_m
        )
        # Explicit plan-only authorship holds the authored section while the
        # footprint changes. Omitted policy retains legacy inferred field
        # behavior; its historical coverage lift is not reinterpreted here.
        if hold_programme and (form.extra.get("parti") or {}).get("growth") != "plan"
        else 1.0
    )
    scaled = _scaled_composition(form, factor, anchor)
    return replace(
        scaled,
        name=f"{form.name}@{int(round(target_area_m2))}",
        placements=tuple(
            _stretched(item, lift) for item in scaled.placements
        ),
    )


def _height_span(form: MatrixForm) -> tuple[float, float]:
    """The composition's own z-extent, off its additive corners."""

    zs = [
        corner[2]
        for item in form.additive()
        for corner in item.corners()
    ]
    if not zs:
        return (0.0, 0.0)
    return (min(zs), max(zs))


def _stretched(placement, lift: float):
    """Scale a volume's height about the ground, so compositions settle.

    This scaled about each volume's own base once - harmless while every
    base sat at grade, and wrong the day units stacked: shrinking a pile's
    heights left every upper base where it was, opened an air gap between
    levels, and the connectivity gate honestly reported two thirds of the
    building floating. Scaling z about the ground moves bases and heights
    together, so what rested on what still does, at every lift.
    """

    if abs(lift - 1.0) < 1e-6:
        return placement
    matrix = compose_matrix4(
        placement.matrix,
        scale_matrix4((1.0, 1.0, max(1e-3, lift))),
    )
    return section_held_through_height_scale(
        replace(placement, matrix=validate_matrix4(matrix)), max(1e-3, lift))


def _programme_lift(
    form: MatrixForm, *, factor: float, far_capacity_m2: float, floor_height_m: float
) -> float:
    """How much taller the copy has to be to hold the same programme.

    The inverse of the plan scale, but never past the 용적률 ceiling. Holding the
    programme unconditionally holds whatever the author wrote, and an authored
    scheme is free to be over capacity - measured here, a U covering most of the
    buildable plan carried 7,183 m2 against a 2,500 m2 ceiling. Preserving that
    at 45% ground take asked for 6.6 times the height, produced an 80 m building,
    and no amount of trimming afterwards could bring it back.

    So the programme this holds is the lawful one: whichever is smaller, what the
    author drew or what the parcel allows.
    """

    if factor <= 1e-9:
        return 1.0
    inverse = 1.0 / (factor * factor)
    if far_capacity_m2 <= 0.0:
        return inverse
    current = _gross_floor_area(form, floor_height_m=floor_height_m)
    if current <= 1e-9:
        return inverse
    # After the plan scale the copy carries `current * factor^2`; the lift
    # multiplies that again.
    scaled = current * factor * factor
    if scaled <= 1e-9:
        return inverse
    # The floor was a bare 0.05 - a composition could legally be crushed to
    # five percent of its height, which is how six-metre house piles arrived
    # at zero storeys. The floor a lift may never go under is the one the
    # executor already enforces at birth: the shortest unit still holds one
    # storey. Derived, not chosen. And it is the UNIT's span, not the whole
    # composition's - dividing by a three-house pile's total height let each
    # house crush to a third of a storey while the stack as a whole "held"
    # one, which is exactly how the Korean brief-resize flattened every
    # declared vertical event.
    # Occupiable units only: a declared-thin plate (a canopy, a brim) is not
    # a storey and must not forbid the crush the rooms could take.
    unit = min(
        (max(high - low, 0.0) for low, high in
         (item.z_span() for item in form.additive()
          if getattr(item, "occupiable", True))),
        default=0.0,
    )
    if unit <= 1e-9:
        low, high = _height_span(form)
        unit = max(high - low, 1e-9)
    floor = min(1.0, floor_height_m / unit) if floor_height_m > 0 else 0.05
    return max(floor, min(inverse, far_capacity_m2 / scaled))


def spread_across_coverage(
    form: MatrixForm,
    *,
    ground_capacity_m2: float,
    far_capacity_m2: float = 0.0,
    floor_height_m: float = 3.0,
    bands: tuple[CoverageBand, ...] = COVERAGE_BANDS,
) -> list[MatrixForm]:
    """One copy of this composition per coverage band.

    Bands are fractions of the run's own certified capacity, so this means the
    same thing on any parcel.
    """

    out: list[MatrixForm] = []
    for band in bands:
        # Sit just inside the band's ceiling rather than on it: the legal fit
        # can only ever reduce area further, and a copy authored exactly at the
        # edge lands in the band below as soon as the sunlight envelope bites.
        target = ground_capacity_m2 * band.plan_fraction * 0.97
        moved = retarget_ground_take(
            form,
            target_area_m2=target,
            far_capacity_m2=far_capacity_m2,
            floor_height_m=floor_height_m,
        )
        if moved is not None:
            out.append(replace(
                moved,
                name=f"{form.name}~{band.band_id}",
                # The copy exists to occupy this position on the coverage axis.
                # Without saying so, the growth loop widens it back off the band
                # it was made for and the grid collapses to whatever the fill
                # happens to reach - measured, 16 cells fell to 5.
                extra={**dict(moved.extra), "coverage_band": band.band_id},
            ))
    return out
