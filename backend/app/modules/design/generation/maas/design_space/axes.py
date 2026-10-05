"""How much ground a proposal takes, as a choice rather than a consequence.

건폐율 is a legal ceiling, not a target. A building may take all the ground the
law allows, or hold most of it as court and approach and take a fraction. Those
are different architectural propositions, and an architect picks between them -
so the pipeline has to be able to produce both.

It currently produces only the first. `build_capacity_alternative` derives plan
area from floor area:

    target_plan_area = ground_capacity * legal_field_yield_ratio

so a demanding floor-area target drives the yield ratio toward one and the plan
to the legal ceiling. The four capacity alternatives vary floor area, and plan
area follows them; it is a consequence, never a choice. Measured on PNU
4115011300106840001: 86 of 128 delivered masses within one percent of the cap.

The bands here make it a choice. They are fractions of the same 건폐율 capacity,
so they are legal by construction and say nothing about which is better.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class CoverageBand:
    """One position on the ground-take axis."""

    band_id: str
    label: str
    intent: str
    plan_fraction: float

    def evidence(self) -> dict[str, object]:
        return {
            "band_id": self.band_id,
            "label": self.label,
            "intent": self.intent,
            "plan_fraction": self.plan_fraction,
        }


# Four positions, matching the four capacity alternatives already in the
# pipeline so the two axes can be crossed without inventing a second cadence.
# The fractions are deliberately wide apart: neighbouring proposals that differ
# by a few percent of ground are the same proposal to an architect.
COVERAGE_BANDS: tuple[CoverageBand, ...] = (
    CoverageBand(
        "dispersed_ground",
        "Dispersed ground",
        "hold most of the parcel as court and approach; the building goes up "
        "or spreads thin rather than out",
        0.45,
    ),
    CoverageBand(
        "held_ground",
        "Held ground",
        "take a clear footprint and leave a usable remainder around it",
        0.65,
    ),
    CoverageBand(
        "worked_ground",
        "Worked ground",
        "take most of the ground, keeping the remainder for access and light",
        0.85,
    ),
    CoverageBand(
        "full_ground",
        "Full ground",
        "take the whole 건폐율 the law allows",
        1.00,
    ),
)

_BAND_BY_ID = {band.band_id: band for band in COVERAGE_BANDS}


def coverage_band_ids() -> tuple[str, ...]:
    return tuple(band.band_id for band in COVERAGE_BANDS)


def coverage_band(band_id: str) -> CoverageBand:
    band = _BAND_BY_ID.get(str(band_id))
    if band is None:
        raise KeyError(f"unknown coverage band: {band_id}")
    return band


def plan_area_for_band(
    ground_capacity_m2: float,
    band: CoverageBand | str,
) -> float:
    """Return the ground plate this band asks for, in square metres.

    `ground_capacity_m2` is the 건폐율 capacity the legal field already
    certifies, so every band is legal and the ceiling is never invented here.
    """

    resolved = band if isinstance(band, CoverageBand) else coverage_band(band)
    try:
        capacity = float(ground_capacity_m2)
    except (TypeError, ValueError):
        return 0.0
    if not isfinite(capacity) or capacity <= 0.0:
        return 0.0
    return capacity * resolved.plan_fraction


def delivered_ground_take_band(ratio: float) -> CoverageBand:
    """Which position on the axis a *delivered* mass actually holds.

    The band a candidate asked for is a label; this reads the measured ground
    take back onto the same axis, so a portfolio quota counts what was built
    rather than what was requested. A mass that asked to disperse and came out
    filling the ground counts as full ground, because that is what it is.

    A ratio lands in the lowest band that can contain it, so the band names the
    ground the building takes up to.
    """

    try:
        measured = float(ratio)
    except (TypeError, ValueError):
        measured = 0.0
    if not isfinite(measured):
        measured = 0.0
    ordered = sorted(COVERAGE_BANDS, key=lambda band: band.plan_fraction)
    for band in ordered:
        if measured <= band.plan_fraction + 1e-9:
            return band
    return ordered[-1]


def capacities_under_band(
    floor_capacities: Sequence[float],
    *,
    ground_capacity_m2: float,
    band: CoverageBand | str,
) -> list[float]:
    """Bound every floor's plate by the ground this band takes.

    건축면적 is the horizontal projection of the whole building, so a band that
    holds the ground holds every plate, not only the lowest one. Bounding the
    whole vector is also what lets the stack answer: the floor-prefix selection
    downstream picks the shortest prefix carrying the target, so a smaller plate
    simply asks for more floors.
    """

    ceiling = plan_area_for_band(ground_capacity_m2, band)
    bounded: list[float] = []
    for value in floor_capacities:
        try:
            capacity = float(value)
        except (TypeError, ValueError):
            capacity = 0.0
        if not isfinite(capacity) or capacity <= 0.0:
            bounded.append(0.0)
            continue
        bounded.append(min(capacity, ceiling) if ceiling > 0.0 else capacity)
    return bounded


@dataclass(frozen=True)
class VoidBand:
    """One position on the solid/void axis."""

    band_id: str
    label: str
    intent: str
    void_ceiling: float

    def evidence(self) -> dict[str, object]:
        return {
            "band_id": self.band_id,
            "label": self.label,
            "intent": self.intent,
            "void_ceiling": self.void_ceiling,
        }


# Solid or void is the architect's other primary axis: what separates a block
# from a courtyard scheme at the same 건폐율. Voids used to be pure loss here -
# they cost floor area and nothing scored them, so a scheme with a court always
# lost to the same scheme without one. A position cannot lose to another
# position.
#
# The edges are named after the figures that produce them, computed rather than
# picked, and every one is rotation-invariant (identical at 0 and 37 degrees):
#
#     plain block                          0.000
#     court 30% of the side                0.090   <- solid_body ceiling
#     notched block                        0.120
#     court 40% / U slot                   0.160 / 0.167
#     two bars with a gap                  0.200   <- carved_body ceiling
#     L with a quarter out / court 50%     0.250
#     H with two slots                     0.333   <- open_figure ceiling
#     cross                                0.375
#
# Fitting these to one run's distribution was the alternative and is worse: the
# same building would change position depending on what else was generated
# beside it, and an axis an architect chooses along has to mean the same thing
# every time.
VOID_BANDS: tuple[VoidBand, ...] = (
    VoidBand(
        "solid_body",
        "Solid body",
        "one closed figure; the room is inside, not cut out of it",
        0.09,
    ),
    VoidBand(
        "carved_body",
        "Carved body",
        "a body still read as one mass, with a court or notch taken out",
        0.20,
    ),
    VoidBand(
        "open_figure",
        "Open figure",
        "arms and courts as much as mass; the plan reads as a figure, not a block",
        0.333,
    ),
    VoidBand(
        "porous_field",
        "Porous field",
        "more open than built than its own figure holds; a field of parts",
        1.00,
    ),
)

_VOID_BAND_BY_ID = {band.band_id: band for band in VOID_BANDS}


def void_band_ids() -> tuple[str, ...]:
    return tuple(band.band_id for band in VOID_BANDS)


def void_band(band_id: str) -> VoidBand:
    band = _VOID_BAND_BY_ID.get(str(band_id))
    if band is None:
        raise KeyError(f"unknown void band: {band_id}")
    return band


def delivered_void_band(ratio: float) -> VoidBand:
    """Which solid/void position a delivered mass holds.

    Read from the measured envelope void ratio, so it says what was built rather
    than what was asked for. A ratio lands in the lowest band that can contain
    it, and anything unmeasured reads as the most solid position rather than
    being credited with a void it never had.
    """

    try:
        measured = float(ratio)
    except (TypeError, ValueError):
        measured = 0.0
    if not isfinite(measured) or measured < 0.0:
        measured = 0.0
    ordered = sorted(VOID_BANDS, key=lambda band: band.void_ceiling)
    for band in ordered:
        if measured <= band.void_ceiling + 1e-9:
            return band
    return ordered[-1]


# ---------------------------------------------------------------------------
# Stature: how tall a proposal stands, as a choice rather than a leftover.
#
# The grid crossed ground-take with void and left height to fall where it
# fell, and it fell flat: measured on PNU 4115011300106840001, the finished
# sheet averaged 16 m on a parcel whose legal section allows 48, while the
# tallest variant of almost every delivered family lived in no cell at all -
# height changes the ground-take class, so the low bands collected the low
# variants and nothing ever demanded a tall one. An architect chooses a
# stature the way they choose a ground-take; the axis has to exist for the
# sheet to owe it diversity. Ground-take stays measured and reported - it
# becomes the free variable height used to be.
#
# The boundaries are storey counts, not metres fitted to a run: three
# storeys is the house and the walk-up, six is the street wall and the
# lift threshold, ten is where a body stops belonging to the street. The
# same building must land in the same band on every parcel.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StatureBand:
    """One position on the stature axis."""

    band_id: str
    label: str
    intent: str
    storey_ceiling: float

    def evidence(self) -> dict[str, object]:
        return {
            "band_id": self.band_id,
            "label": self.label,
            "intent": self.intent,
            "storey_ceiling": self.storey_ceiling,
        }


STATURE_BANDS: tuple[StatureBand, ...] = (
    StatureBand(
        "seated_figure",
        "Seated figure",
        "house-scaled; the roofline keeps the street's low datum",
        3.0,
    ),
    StatureBand(
        "standing_body",
        "Standing body",
        "a street wall; rooms stack but the building still faces, not looms",
        6.0,
    ),
    StatureBand(
        "risen_body",
        "Risen body",
        "clear of its neighbours; the upper floors read the skyline, not the street",
        10.0,
    ),
    StatureBand(
        "towering_figure",
        "Towering figure",
        "a vertical figure; the parcel is a base and the section is the argument",
        float("inf"),
    ),
)

_STATURE_BAND_BY_ID = {band.band_id: band for band in STATURE_BANDS}


def stature_band_ids() -> tuple[str, ...]:
    return tuple(band.band_id for band in STATURE_BANDS)


def delivered_stature_band(height_m: float, *, storey_height_m: float) -> StatureBand:
    """Which stature a *delivered* mass actually holds.

    Read from the measured height in the mass's own storey module, so it says
    what was built. A count lands in the lowest band that can contain it.
    """

    try:
        storeys = float(height_m) / max(float(storey_height_m), 1e-6)
    except (TypeError, ValueError):
        storeys = 0.0
    if not isfinite(storeys) or storeys < 0.0:
        storeys = 0.0
    for band in STATURE_BANDS:
        if storeys <= band.storey_ceiling + 1e-9:
            return band
    return STATURE_BANDS[-1]
