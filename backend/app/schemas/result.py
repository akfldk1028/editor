from __future__ import annotations

import math
from dataclasses import dataclass

from backend.app.schemas.area import BuildingAreaLedger, FloorAreaLedger
from backend.app.schemas.egress import FloorEgressGraphResult
from backend.app.schemas.layout import LayoutCandidate
from backend.app.schemas.llm import FloorAssignment
from backend.app.schemas.mass import MassAnalysis, Point
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
    floor_boundary: tuple[Point, ...] | None = None
    floor_boundary_source: str | None = None

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
                raise TypeError("egress_graph must be FloorEgressGraphResult or None")
            evidence_indexes.append(self.egress_graph.floor_index)
        screening = self.validation.regulatory_screening
        if screening is not None and screening.floor_index is not None:
            if screening.floor_index not in evidence_indexes:
                raise ValueError(
                    "validation screening floor index must match generation result"
                )
            evidence_indexes.append(screening.floor_index)
        if self.floor_boundary is not None:
            if len(self.floor_boundary) < 3:
                raise ValueError(
                    "generation result floor boundary needs at least 3 points"
                )
            if self.floor_boundary_source not in {
                "legacy_broadcast",
                "explicit_floor_footprint",
            }:
                raise ValueError("generation result floor boundary source is invalid")
        if (
            self.area_ledger is not None
            or self.egress_graph is not None
            or (screening is not None and screening.floor_index is not None)
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
            raise ValueError("building mass floor count must match floor results")
        expected_indexes = tuple(range(1, self.mass.floors + 1))
        assignment_indexes = tuple(
            assignment.floor_index for assignment in self.floor_assignments
        )
        if assignment_indexes != expected_indexes:
            raise ValueError("building floor assignments must match mass floors")
        floor_indexes = tuple(floor.program.floor_index for floor in self.floor_results)
        if floor_indexes != expected_indexes:
            raise ValueError("building floor result indexes must match mass floors")
        if any(
            floor.area_ledger is None or floor.egress_graph is None
            for floor in self.floor_results
        ):
            raise ValueError("building every floor requires area and egress evidence")
        floor_ledgers = tuple(floor.area_ledger for floor in self.floor_results)
        ledger_indexes = tuple(floor.floor_index for floor in self.area_ledger.floors)
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
class CoreSearchAttempt:
    minimum_width_m: float
    minimum_depth_m: float
    widen: bool
    candidate_count: int

    def __post_init__(self) -> None:
        if any(
            type(value) not in (int, float) or not math.isfinite(value) or value <= 0
            for value in (self.minimum_width_m, self.minimum_depth_m)
        ):
            raise ValueError("core search dimensions must be finite and positive")
        if (
            type(self.widen) is not bool
            or type(self.candidate_count) is not int
            or self.candidate_count < 0
        ):
            raise ValueError("core search count and widening evidence are invalid")


@dataclass(frozen=True)
class NoCoreCandidatesDiagnostic:
    code: str
    message: str
    shared_intersection_area_m2: float
    shared_intersection_bounds_m: tuple[float, float, float, float] | None
    requested_core_area_m2: float
    attempts: tuple[CoreSearchAttempt, ...]

    def __post_init__(self) -> None:
        if (
            self.code != "no_core_candidates"
            or not isinstance(self.message, str)
            or not self.message.strip()
        ):
            raise ValueError("empty core search diagnostic requires its code and message")
        if any(
            type(value) not in (int, float) or not math.isfinite(value)
            for value in (self.shared_intersection_area_m2, self.requested_core_area_m2)
        ):
            raise ValueError("core search areas must be finite")
        if self.shared_intersection_area_m2 < 0 or self.requested_core_area_m2 <= 0:
            raise ValueError("core search areas are invalid")
        bounds = self.shared_intersection_bounds_m
        if bounds is not None and (
            not isinstance(bounds, tuple)
            or len(bounds) != 4
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in bounds)
            or bounds[0] > bounds[2]
            or bounds[1] > bounds[3]
        ):
            raise ValueError("core search intersection bounds are invalid")
        if bounds is None and self.shared_intersection_area_m2 > 0:
            raise ValueError("positive intersection requires bounds")
        if (
            not isinstance(self.attempts, tuple)
            or not self.attempts
            or any(
                not isinstance(attempt, CoreSearchAttempt) or attempt.candidate_count != 0
                for attempt in self.attempts
            )
        ):
            raise ValueError("empty core search requires zero-count attempt evidence")


@dataclass(frozen=True)
class RejectedAlternativeFamilyResult:
    family: str
    reasons: tuple[str, ...]
    diagnostics: tuple[NoCoreCandidatesDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.diagnostics, tuple) or any(
            not isinstance(diagnostic, NoCoreCandidatesDiagnostic)
            for diagnostic in self.diagnostics
        ):
            raise TypeError("family diagnostics must be immutable evidence records")
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
