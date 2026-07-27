from __future__ import annotations

from dataclasses import dataclass

from backend.app.schemas.layout import LayoutCandidate
from backend.app.schemas.mass import MassAnalysis
from backend.app.schemas.metrics import ValidationReport
from backend.app.schemas.program import ProgramGraph


@dataclass(frozen=True)
class GenerationResult:
    mass: MassAnalysis
    program: ProgramGraph
    layout: LayoutCandidate
    validation: ValidationReport
