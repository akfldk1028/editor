"""MASS v2 - masses authored as placed volumes carried by 4x4 affines.

The existing language is face operations on a single solid, and measurement put
its ceiling at roughly 0.29 departure from the mass's own convex hull. This
package authors the other thing the repo already knew it wanted: several clean
volumes, stacked and shifted.

Public surface is deliberately small.

    place / Placement / MatrixForm   author a mass
    compile_matrix_form              -> SourceMass, no 3D CSG
    measure_form                     convexity, grid cell, band profile

Nothing here writes a geometry identity hash, and nothing sets
`geometry_authority` to one of the authored values that arm the certification
layer. That is deliberate: it keeps this package outside the identity contract
while the form language is being proven.
"""

from backend.app.modules.design.generation.maas.massv2.compile import compile_matrix_form
from backend.app.modules.design.generation.maas.massv2.form import MatrixForm, Placement, PlacementKind, UNIT_BOX_CORNERS, place, stack
from backend.app.modules.design.generation.maas.massv2.measure import FormMeasurement, measure_form
from backend.app.modules.design.generation.maas.massv2.profiles import UNIT_PLANS, plan_names, unit_plan

__all__ = [
    "FormMeasurement",
    "MatrixForm",
    "Placement",
    "PlacementKind",
    "UNIT_BOX_CORNERS",
    "compile_matrix_form",
    "measure_form",
    "place",
    "stack",
    "UNIT_PLANS",
    "plan_names",
    "unit_plan",
]
