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
class PlannerProvenance:
    planner_mode: str
    provider: str
    model: str | None
    response_id: str | None
    validated_assignments: tuple[FloorAssignment, ...]


@dataclass(frozen=True)
class BuildingGenerationResult:
    mass: MassAnalysis
    floor_assignments: tuple[FloorAssignment, ...]
    floor_results: tuple[GenerationResult, ...]
    total_area: float
    use_type_areas: dict[str, float]
    assignment_source: str
    vertical_core_aligned: bool
    vertical_basic_design_aligned: bool
    vertical_structure_aligned: bool
    planner_provenance: PlannerProvenance

    @property
    def accepted(self) -> bool:
        return (
            self.vertical_core_aligned
            and self.vertical_basic_design_aligned
            and self.vertical_structure_aligned
            and all(floor.validation.accepted for floor in self.floor_results)
        )


@dataclass(frozen=True)
class BuildingAlternativeResult:
    alternative_id: str
    strategy: str
    building: BuildingGenerationResult
    score: float
    rank: int
    fingerprints: tuple[str, ...]
    core_centroid: tuple[float, float]
    circulation_orientation: str
    circulation_bounds: tuple[float, float, float, float]
    circulation_graph_signature: tuple[str, ...]
    tenant_assignment_signature: tuple[str, ...]
    tenant_count: int
    tenant_entrance_assignments: tuple[str, ...]
    core_public_entrance: bool
    design_family_signature: str

    @property
    def floor_results(self) -> tuple[GenerationResult, ...]:
        return self.building.floor_results

    @property
    def accepted(self) -> bool:
        return self.building.accepted


@dataclass(frozen=True)
class BuildingAlternativesResult:
    mass: MassAnalysis
    alternatives: tuple[BuildingAlternativeResult, ...]
    comparisons: tuple["AlternativeGeometryComparison", ...]

    @property
    def accepted_count(self) -> int:
        return sum(alternative.accepted for alternative in self.alternatives)


@dataclass(frozen=True)
class AlternativeGeometryComparison:
    first_alternative_id: str
    second_alternative_id: str
    normalized_core_centroid_distance: float
    circulation_graph_different: bool
    tenant_assignment_different: bool
    semantic_distinct: bool
