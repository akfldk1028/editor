from __future__ import annotations

from dataclasses import dataclass

from backend.app.schemas.area import BuildingAreaLedger, FloorAreaLedger
from backend.app.schemas.egress import FloorEgressGraphResult
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
    area_ledger: FloorAreaLedger | None = None
    egress_graph: FloorEgressGraphResult | None = None

    def __post_init__(self) -> None:
        evidence_indexes = [
            self.program.floor_index,
            self.layout.floor_index,
        ]
        if self.area_ledger is not None:
            if not isinstance(self.area_ledger, FloorAreaLedger):
                raise TypeError("area_ledger must be FloorAreaLedger or None")
            evidence_indexes.append(self.area_ledger.floor_index)
        if self.egress_graph is not None:
            if not isinstance(self.egress_graph, FloorEgressGraphResult):
                raise TypeError(
                    "egress_graph must be FloorEgressGraphResult or None"
                )
            evidence_indexes.append(self.egress_graph.floor_index)
        screening = self.validation.regulatory_screening
        if screening is not None and screening.floor_index is not None:
            if screening.floor_index not in evidence_indexes:
                raise ValueError(
                    "validation screening floor index must match generation result"
                )
            evidence_indexes.append(screening.floor_index)
        if (
            self.area_ledger is not None
            or self.egress_graph is not None
            or (
                screening is not None
                and screening.floor_index is not None
            )
        ) and len(set(evidence_indexes)) != 1:
            raise ValueError("generation result floor indexes must match")


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
    area_ledger: BuildingAreaLedger | None = None

    def __post_init__(self) -> None:
        if self.area_ledger is None:
            return
        if not isinstance(self.area_ledger, BuildingAreaLedger):
            raise TypeError("area_ledger must be BuildingAreaLedger or None")
        if len(self.floor_results) != self.mass.floors:
            raise ValueError(
                "building mass floor count must match floor results"
            )
        expected_indexes = tuple(range(1, self.mass.floors + 1))
        assignment_indexes = tuple(
            assignment.floor_index for assignment in self.floor_assignments
        )
        if assignment_indexes != expected_indexes:
            raise ValueError(
                "building floor assignments must match mass floors"
            )
        floor_indexes = tuple(
            floor.program.floor_index for floor in self.floor_results
        )
        if floor_indexes != expected_indexes:
            raise ValueError(
                "building floor result indexes must match mass floors"
            )
        if any(
            floor.area_ledger is None or floor.egress_graph is None
            for floor in self.floor_results
        ):
            raise ValueError(
                "building every floor requires area and egress evidence"
            )
        floor_ledgers = tuple(
            floor.area_ledger for floor in self.floor_results
        )
        ledger_indexes = tuple(
            floor.floor_index for floor in self.area_ledger.floors
        )
        if ledger_indexes != floor_indexes:
            raise ValueError(
                "building area ledger floor indexes must match floor results"
            )
        if self.area_ledger.floors != floor_ledgers:
            raise ValueError(
                "building area ledger floors must exactly match floor result ledgers"
            )

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
class RejectedAlternativeFamilyResult:
    family: str
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.family, str) or not self.family.strip():
            raise ValueError("rejected alternative family must be non-empty")
        if (
            not isinstance(self.reasons, tuple)
            or not self.reasons
            or any(
                not isinstance(reason, str) or not reason.strip()
                for reason in self.reasons
            )
        ):
            raise ValueError(
                "rejected alternative family requires exact non-empty reasons"
            )


@dataclass(frozen=True)
class BuildingAlternativesResult:
    mass: MassAnalysis
    alternatives: tuple[BuildingAlternativeResult, ...]
    comparisons: tuple["AlternativeGeometryComparison", ...]
    rejected_families: tuple[RejectedAlternativeFamilyResult, ...] = ()

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
