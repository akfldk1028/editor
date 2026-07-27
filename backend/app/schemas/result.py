from __future__ import annotations

from dataclasses import dataclass

from backend.app.schemas.layout import LayoutCandidate
from backend.app.schemas.llm import FloorAssignment
from backend.app.schemas.mass import MassAnalysis
from backend.app.schemas.metrics import ValidationReport
from backend.app.schemas.program import ProgramGraph


@dataclass(frozen=True)
class GenerationResult:
    mass: MassAnalysis
    program: ProgramGraph
    layout: LayoutCandidate
    validation: ValidationReport


@dataclass(frozen=True)
class BuildingGenerationResult:
    mass: MassAnalysis
    floor_assignments: tuple[FloorAssignment, ...]
    floor_results: tuple[GenerationResult, ...]
    total_area: float
    use_type_areas: dict[str, float]
    assignment_source: str
    vertical_core_aligned: bool

    @property
    def accepted(self) -> bool:
        return self.vertical_core_aligned and all(
            floor.validation.accepted for floor in self.floor_results
        )
