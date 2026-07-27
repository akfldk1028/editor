from __future__ import annotations

from backend.app.modules.validator.service import validate_layout
from backend.app.schemas.layout import LayoutCandidate
from backend.app.schemas.metrics import ValidationReport
from backend.app.schemas.program import ProgramGraph


def validate_layout_route(
    layout: LayoutCandidate,
    program: ProgramGraph,
    boundary: list[tuple[float, float]],
) -> ValidationReport:
    return validate_layout(layout, program, boundary)
