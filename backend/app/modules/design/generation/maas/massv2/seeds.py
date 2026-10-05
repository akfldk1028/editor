"""Massing families, sized by the parcel's own limits rather than by constants.

Every dimension here is derived from two numbers the legal engine produced for
this parcel - the 건축면적 ceiling and the 용적률 capacity - so the same family
means the same thing on a 20% BCR parcel in Uijeongbu and a 60% one in Gangnam.
Nothing is tuned per site; that would make the language a set of parcel-specific
hacks rather than an architectural vocabulary.

The families are the ones an architect would actually name. They are chosen to
spread across both axes of the delivered grid - a single bar and a stacked tower
sit at opposite ends of ground take, a courtyard and a solid block at opposite
ends of void - because the goal is a grid to choose from, not one best mass.
"""

from __future__ import annotations

import math
from typing import Callable, Iterable

from backend.app.modules.design.generation.maas.massv2.form import MatrixForm, Placement, place


# Cutters are pushed this far past the face they cut so the subtraction lands
# cleanly instead of leaving a film of geometry behind a coplanar boundary.
_CUTTER_OVERSHOOT_M = 1.0
# Stacked volumes overlap by this much: a shared coplanar face is a degenerate
# boolean input and reads as two separate bands that happen to touch.
_STACK_OVERLAP_M = 0.1


class _Site:
    """The parcel facts a family needs, and the proportions derived from them."""

    def __init__(self, *, ground_capacity_m2: float, far_capacity_m2: float, floor_height_m: float):
        self.ground_capacity_m2 = max(1.0, float(ground_capacity_m2))
        self.far_capacity_m2 = max(1.0, float(far_capacity_m2))
        self.floor_height_m = max(2.4, float(floor_height_m or 3.0))

    def floors_at(self, footprint_m2: float) -> int:
        """How many storeys the 용적률 capacity affords at this footprint."""

        return max(1, int(self.far_capacity_m2 // max(1.0, footprint_m2)))

    def height_at(self, footprint_m2: float) -> float:
        return self.floors_at(footprint_m2) * self.floor_height_m

    def side(self, footprint_m2: float, *, aspect: float = 1.0) -> tuple[float, float]:
        """Plan dimensions for a target area at a given proportion."""

        area = max(1.0, float(footprint_m2))
        width = math.sqrt(area * float(aspect))
        return width, area / width


def _block(site: _Site, *, take: float) -> MatrixForm:
    area = site.ground_capacity_m2 * take
    width, depth = site.side(area, aspect=1.35)
    height = site.height_at(area)
    return MatrixForm(
        name=f"block_{int(take * 100)}",
        placements=(place("block", size=(width, depth, height)),),
        primary_language="single_block",
        formal_principle="extruded_block",
        dominant_gesture="one closed body holding the whole programme",
    )


def _stacked(site: _Site, *, take: float, steps: int = 3) -> MatrixForm:
    """A plinth stepping back to a tower - ground take falls as height rises."""

    base_area = site.ground_capacity_m2 * take
    width, depth = site.side(base_area, aspect=1.5)
    total_height = site.height_at(base_area)
    band = total_height / steps
    placements: list[Placement] = []
    for index in range(steps):
        shrink = 1.0 - 0.28 * index
        step_w, step_d = width * shrink, depth * shrink
        placements.append(
            place(
                ("plinth", "middle", "crown")[min(index, 2)],
                size=(step_w, step_d, band + _STACK_OVERLAP_M),
                # Setbacks are uneven on purpose: a concentric step is a wedding
                # cake, and reads as one figure rather than three volumes.
                at=((width - step_w) * (0.18 + 0.22 * index),
                    (depth - step_d) * (0.62 - 0.20 * index),
                    index * band - (_STACK_OVERLAP_M if index else 0.0)),
            )
        )
    return MatrixForm(
        name=f"stacked_{int(take * 100)}",
        placements=tuple(placements),
        primary_language="stacked_platform",
        secondary_language="setback_tower",
        formal_principle="shifted_stack",
        dominant_gesture="a base that steps back as it rises",
    )


def _paired_bars(site: _Site, *, take: float, splay_degrees: float = 0.0) -> MatrixForm:
    """Two bars holding a court between them, optionally splayed apart."""

    area = site.ground_capacity_m2 * take
    span, _ = site.side(area, aspect=6.0)
    bar_depth = (area / span) / 2.0
    gap = bar_depth * 1.6
    height = site.height_at(area)
    return MatrixForm(
        name=f"paired_bars_{int(take * 100)}{'_splayed' if splay_degrees else ''}",
        placements=(
            place("bar_south", size=(span, bar_depth, height)),
            place(
                "bar_north",
                size=(span, bar_depth, height),
                at=(0.0, bar_depth + gap, 0.0),
                rotation_degrees=splay_degrees,
            ),
            # The link is what keeps two bars one building rather than two.
            place("link", size=(span * 0.22, gap + 2 * _STACK_OVERLAP_M, height * 0.34),
                  at=(span * 0.39, bar_depth - _STACK_OVERLAP_M, height * 0.5)),
        ),
        primary_language="paired_bars",
        secondary_language="splayed_pair" if splay_degrees else "parallel_pair",
        formal_principle="court_between",
        dominant_gesture="two bars holding a room-sized gap between them",
    )


def _courtyard(site: _Site, *, take: float) -> MatrixForm:
    """A body with its centre taken out - the court is cut, not left over."""

    area = site.ground_capacity_m2 * take
    width, depth = site.side(area / 0.68, aspect=1.15)
    height = site.height_at(area)
    court_w, court_d = width * 0.42, depth * 0.40
    return MatrixForm(
        name=f"courtyard_{int(take * 100)}",
        placements=(
            place("perimeter", size=(width, depth, height)),
            place(
                "court",
                size=(court_w, court_d, height + 2 * _CUTTER_OVERSHOOT_M),
                at=((width - court_w) * 0.44, (depth - court_d) * 0.52, -_CUTTER_OVERSHOOT_M),
                kind="subtractive",
            ),
        ),
        primary_language="courtyard_block",
        formal_principle="subtracted_court",
        dominant_gesture="a perimeter around a cut void",
    )


def _crossed_arms(site: _Site, *, take: float) -> MatrixForm:
    """A core with arms cantilevering past it on alternating axes."""

    area = site.ground_capacity_m2 * take
    core_w, core_d = site.side(area * 0.44, aspect=1.0)
    height = site.height_at(area)
    arm_h = height / 3.0
    return MatrixForm(
        name=f"crossed_arms_{int(take * 100)}",
        placements=(
            place("core", size=(core_w, core_d, height)),
            place("arm_low", size=(core_w * 2.3, core_d * 0.58, arm_h + _STACK_OVERLAP_M),
                  at=(-core_w * 0.66, core_d * 0.2, arm_h - _STACK_OVERLAP_M)),
            place("arm_high", size=(core_w * 0.60, core_d * 2.4, arm_h + _STACK_OVERLAP_M),
                  at=(core_w * 0.22, -core_d * 0.72, 2 * arm_h - _STACK_OVERLAP_M)),
        ),
        primary_language="crossed_arms",
        secondary_language="cantilever",
        formal_principle="cantilevered_cross",
        dominant_gesture="arms reaching past the core on opposite axes",
    )


def _notched_slab(site: _Site, *, take: float) -> MatrixForm:
    """One slab with slots cut from opposite faces at different heights."""

    area = site.ground_capacity_m2 * take
    width, depth = site.side(area / 0.86, aspect=2.1)
    height = site.height_at(area)
    return MatrixForm(
        name=f"notched_slab_{int(take * 100)}",
        placements=(
            place("slab", size=(width, depth, height)),
            place("slot_low", size=(width * 0.26, depth + 2 * _CUTTER_OVERSHOOT_M, height * 0.42),
                  at=(width * 0.14, -_CUTTER_OVERSHOOT_M, -_CUTTER_OVERSHOOT_M), kind="subtractive"),
            place("slot_high", size=(width * 0.30, depth * 0.62, height * 0.5),
                  at=(width * 0.58, depth * 0.5, height * 0.58), kind="subtractive"),
        ),
        primary_language="notched_slab",
        formal_principle="slotted_body",
        dominant_gesture="slots cut from opposite faces at different levels",
    )


# Ground takes are fractions of this run's own certified 건축면적 capacity, so
# they mean the same thing on any parcel. They mirror the delivered grid's own
# coverage bands rather than inventing a second set of numbers.
_TAKES: tuple[float, ...] = (0.45, 0.65, 0.85, 1.00)

_FAMILIES: tuple[tuple[str, Callable[[_Site, float], MatrixForm]], ...] = (
    ("block", lambda site, take: _block(site, take=take)),
    ("stacked", lambda site, take: _stacked(site, take=take)),
    ("paired_bars", lambda site, take: _paired_bars(site, take=take)),
    ("splayed_bars", lambda site, take: _paired_bars(site, take=take, splay_degrees=16.0)),
    ("courtyard", lambda site, take: _courtyard(site, take=take)),
    ("crossed_arms", lambda site, take: _crossed_arms(site, take=take)),
    ("notched_slab", lambda site, take: _notched_slab(site, take=take)),
)


def seed_forms(
    *,
    ground_capacity_m2: float,
    far_capacity_m2: float,
    floor_height_m: float,
    takes: Iterable[float] = _TAKES,
) -> list[MatrixForm]:
    """One form per (family x ground take), all sized from the parcel's limits."""

    site = _Site(
        ground_capacity_m2=ground_capacity_m2,
        far_capacity_m2=far_capacity_m2,
        floor_height_m=floor_height_m,
    )
    return [build(site, float(take)) for take in takes for _name, build in _FAMILIES]


def family_names() -> tuple[str, ...]:
    return tuple(name for name, _build in _FAMILIES)
