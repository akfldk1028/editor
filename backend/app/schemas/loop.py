from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.app.schemas.layout import LayoutCandidate
from backend.app.schemas.mass import MassAnalysis
from backend.app.schemas.metrics import ValidationReport
from backend.app.schemas.program import ProgramGraph


@dataclass(frozen=True)
class LoopConfig:
    max_iterations: int = 5
    evaluation_budget: int = 32
    beam_width: int = 4
    stagnation_iterations: int = 2
    seed: int = 0

    def __post_init__(self) -> None:
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be at least 1")
        if self.evaluation_budget < 1:
            raise ValueError("evaluation_budget must be at least 1")
        if self.beam_width < 1:
            raise ValueError("beam_width must be at least 1")
        if self.stagnation_iterations < 1:
            raise ValueError("stagnation_iterations must be at least 1")


@dataclass(frozen=True)
class CandidateProposal:
    layout: LayoutCandidate
    parent_id: str | None
    operator: str
    operator_params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateRecord:
    iteration: int
    layout: LayoutCandidate
    validation: ValidationReport
    fingerprint: str
    parent_id: str | None
    operator: str
    operator_params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IterationRecord:
    iteration: int
    candidates: list[CandidateRecord]
    best: CandidateRecord
    best_so_far: CandidateRecord


@dataclass(frozen=True)
class LoopResult:
    mass: MassAnalysis
    program: ProgramGraph
    best: CandidateRecord | None
    iterations: list[IterationRecord]
    history: list[CandidateRecord]
    termination_reason: str
    evaluation_count: int
    error: str | None = None

    @property
    def accepted(self) -> bool:
        return self.best is not None and self.best.validation.accepted
