"""The vocabulary, as operators on a matrix rather than as arithmetic on boxes.

Every verb in this grammar was a function that computed a width, a depth and an
offset and asked the frame for a new box. That works, and it is why the same
few lines are copied into nine places - and it is why `shear` forgot to add the
volume's own position back and teleported everything it touched to the middle
of the parcel, while `split`, `lift` and `taper` remembered.

A volume here is already one 4x4. So an operation on a volume is another 4x4,
composed about a pivot, and the project already has the table that turns an
operator name into one: `geometry_language.affine_matrix.matrix4_for_transform`
handles translate, scale, rotate, mirror and shear, each with a pivot. Written
that way a verb is three answers - which volumes, which operator, about what
point - and the arithmetic that used to be per-verb is written once.

    affine     one matrix per volume: rotate, skew, shift, offset,
               expand, compress, inflate, reflect
    swept      a matrix per storey, because the transform varies with height
               and a single matrix is linear: taper, twist, and later bend,
               pinch, grade
    carving    subtractive volumes: carve, notch, puncture
    making     verbs that bring volumes into being rather than transform them:
               extrude, split, stack, loop, aggregate, lift

The book (`docs/260506/BOOK/BOOK_건축언어_전체목록.csv`) lists thirty operations,
five aggregations and twenty recorded combinations. This package is where the
rest of them go.
"""

from __future__ import annotations

from backend.app.modules.design.generation.maas.massv2.ops.affine import AFFINE_VERBS

__all__ = ["AFFINE_VERBS"]
