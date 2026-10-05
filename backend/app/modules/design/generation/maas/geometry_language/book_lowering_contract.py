"""Page-reviewed kernel lowering contract for the thirty BOOK operatives and the five aggregations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BookOperativeLowering:
    required_operators: frozenset[str]
    forbidden_operators: frozenset[str] = frozenset()


BOOK_OPERATIVE_LOWERING: dict[str, BookOperativeLowering] = {
    "expand": BookOperativeLowering(frozenset({"boundary_expand"})),
    "extrude": BookOperativeLowering(frozenset({"scale"})),
    "inflate": BookOperativeLowering(frozenset({"inflate"})),
    "branch": BookOperativeLowering(frozenset({"book_branch"})),
    "merge": BookOperativeLowering(frozenset({"merge_related"})),
    "nest": BookOperativeLowering(frozenset({"nested_related"}), frozenset({"courtyard"})),
    "offset": BookOperativeLowering(frozenset({"book_array"}), frozenset({"translate"})),
    "bend": BookOperativeLowering(frozenset({"bend"})),
    "skew": BookOperativeLowering(frozenset({"shear"})),
    "split": BookOperativeLowering(
        frozenset({"book_split"}), frozenset({"split_wing"})
    ),
    "twist": BookOperativeLowering(frozenset({"twist"})),
    "interlock": BookOperativeLowering(frozenset({"interlock_related"})),
    "intersect": BookOperativeLowering(
        frozenset({"intersect_related"}), frozenset({"intersection"})
    ),
    "lift": BookOperativeLowering(
        frozenset({"book_lift"}), frozenset({"lift"})
    ),
    "lodge": BookOperativeLowering(
        frozenset({"book_lodge"}), frozenset({"offset_related"})
    ),
    "overlap": BookOperativeLowering(frozenset({"overlap_related"})),
    "rotate": BookOperativeLowering(
        frozenset({"book_rotate"}), frozenset({"rotate"})
    ),
    "shift": BookOperativeLowering(frozenset({"shift_related"})),
    "carve": BookOperativeLowering(
        frozenset({"book_carve"}), frozenset({"notch"})
    ),
    "compress": BookOperativeLowering(frozenset({"scale"})),
    "fracture": BookOperativeLowering(
        frozenset({"book_fracture"}), frozenset({"split_wing"})
    ),
    "grade": BookOperativeLowering(
        frozenset({"book_grade"}), frozenset({"terrace", "taper"})
    ),
    "notch": BookOperativeLowering(
        frozenset({"book_notch"}), frozenset({"notch"})
    ),
    "pinch": BookOperativeLowering(frozenset({"pinch"})),
    "shear": BookOperativeLowering(frozenset({"slice"}), frozenset({"shear"})),
    "taper": BookOperativeLowering(frozenset({"taper"})),
    "embed": BookOperativeLowering(frozenset({"embed_void"})),
    "extract": BookOperativeLowering(
        frozenset({"book_extract"}), frozenset({"notch"})
    ),
    "inscribe": BookOperativeLowering(frozenset({"courtyard"})),
    "puncture": BookOperativeLowering(frozenset({"puncture"})),
    # The aggregation layer, pp.50-58. The BOOK records no transformation for
    # these five, and without a contract the author had no word for them:
    # comp18's 120 programs used 24 of the 35 and none of these. Each lowers
    # to the operator its verb file names (`executed_by`); delivery is still
    # one connected solid, so an array or a reflection must be joined.
    "array": BookOperativeLowering(frozenset({"book_array"})),
    "join": BookOperativeLowering(frozenset({"join_related"})),
    "pack": BookOperativeLowering(frozenset({"book_array"})),
    "reflect": BookOperativeLowering(frozenset({"mirror_array"})),
    "stack": BookOperativeLowering(frozenset({"book_stack"})),
}


__all__ = ["BOOK_OPERATIVE_LOWERING", "BookOperativeLowering"]
