"""Order a form supply so an early cut of it still suits the lawful ground.

Measured on PNU 1168011800104170004: the lawful ground is proportioned 1.606:1,
while the deterministic form bank's own seeds have a median plan aspect of 1.16
and 47 of 86 are effectively square.  More than half the supply is mis-
proportioned for the parcel before a single gate runs, which is why so many
poses cannot cover the required area and end up rebuilt by floorwise repair.

Ordering by proximity alone was tried and measured: it lifted program-gate
throughput by a third but narrowed the selected portfolio's aspect spread,
because a distance sort front-loads near-identical proportions. The order here
therefore leads with the lawful proportion and then disperses.

This module only *orders* the supply.  It never edits a program, drops one, or
selects a form: the same programs come back in a different sequence, so a
caller that ignores the ranking is unaffected and every downstream hard gate is
untouched.
"""

from __future__ import annotations

from math import isfinite
from typing import Any, Sequence

from backend.app.modules.design.generation.maas.geometry_language.compiler import compile_geometry_program


def seed_plan_aspect(program: Any) -> float | None:
    """Return a compiled program's plan long/short ratio, or None.

    Proportion has to be measured on the compiled solid: a form-bank program
    routinely carries an identity Matrix4 and gets its shape from later typed
    modifiers, so the matrix alone says nothing about plan proportion.
    """

    try:
        compilation = compile_geometry_program(program)
    except Exception:  # noqa: BLE001 - a broken supply entry must not raise here
        return None
    if getattr(compilation, "status", "") != "compiled":
        return None
    vertices = getattr(compilation, "vertices", None) or ()
    if not vertices:
        return None
    try:
        xs = [float(vertex[0]) for vertex in vertices]
        ys = [float(vertex[1]) for vertex in vertices]
    except (IndexError, TypeError, ValueError):
        return None
    span_x = max(xs) - min(xs)
    span_y = max(ys) - min(ys)
    if (
        not isfinite(span_x)
        or not isfinite(span_y)
        or min(span_x, span_y) <= 1e-9
    ):
        return None
    return max(span_x, span_y) / min(span_x, span_y)


def rank_programs_by_lawful_fit(
    programs: Sequence[Any],
    conditioning: dict[str, Any] | None,
) -> tuple[Any, ...]:
    """Order a supply by plan-proportion distance from the lawful ground.

    With no conditioning the supply is returned in its original order, so this
    is inert until a caller actually has a lawful field to respect.
    """

    supply = tuple(programs)
    guidance = conditioning if isinstance(conditioning, dict) else {}
    lawful_aspect = guidance.get("plan_aspect")
    if (
        not supply
        or isinstance(lawful_aspect, bool)
        or not isinstance(lawful_aspect, (int, float))
        or not isfinite(float(lawful_aspect))
        or float(lawful_aspect) <= 0.0
    ):
        return supply
    target = float(lawful_aspect)

    # Distance in log space, so 2x too wide and 2x too narrow are equally far
    # from the lawful ground.
    measured: list[tuple[int, Any, float]] = []
    unmeasured: list[tuple[int, Any]] = []
    for index, program in enumerate(supply):
        aspect = seed_plan_aspect(program)
        if aspect is None:
            # Unmeasurable supply keeps its relative order at the back rather
            # than being scored against a proportion it does not have.
            unmeasured.append((index, program))
        else:
            measured.append((index, program, _log_ratio(aspect, target)))
    if not measured:
        return supply

    # Ordering by distance alone front-loads near-identical proportions: the
    # first block evaluated is a cluster, and the portfolio inherits its narrow
    # spread. Lead with the lawful proportion, then repeatedly take whichever
    # seed sits furthest from everything already taken, so an early cut of the
    # supply still covers the range.
    remaining = sorted(measured, key=lambda item: (abs(item[2]), item[0]))
    ordered = [remaining.pop(0)]
    while remaining:
        best_position = 0
        best_separation = -1.0
        for position, item in enumerate(remaining):
            separation = min(
                abs(item[2] - chosen[2]) for chosen in ordered
            )
            if separation > best_separation:
                best_separation = separation
                best_position = position
        ordered.append(remaining.pop(best_position))
    return tuple(
        [program for _index, program, _distance in ordered]
        + [program for _index, program in unmeasured]
    )


def _log_ratio(value: float, target: float) -> float:
    from math import log

    return log(value / target)


__all__ = [
    "rank_programs_by_lawful_fit",
    "seed_plan_aspect",
]
