"""Fail-closed status contract for one evaluated MASS candidate."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Mapping


EVALUATION_STAGES = (
    "geometry",
    "law",
    "capacity",
    "parking",
    "program",
    "vlm",
    "selection",
)
DETERMINISTIC_LEGAL_STAGES = EVALUATION_STAGES[:5]
EVALUATION_STATUSES = frozenset({"pass", "fail", "not_evaluated"})
OVERALL_STATUSES = frozenset({
    "selected",
    "legal_pass",
    "failed",
    "not_evaluated",
})


def _ordered_unique_reasons(values) -> tuple[str, ...]:
    reasons: list[str] = []
    for value in values or ():
        reason = str(value or "").strip()
        if reason and reason not in reasons:
            reasons.append(reason)
    return tuple(reasons)


@dataclass(frozen=True)
class StageDecision:
    stage: str
    status: str
    reasons: tuple[str, ...] = ()
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.stage not in EVALUATION_STAGES:
            raise ValueError(f"unknown evaluation stage: {self.stage}")
        if self.status not in EVALUATION_STATUSES:
            raise ValueError(f"unknown evaluation status: {self.status}")
        object.__setattr__(self, "reasons", _ordered_unique_reasons(
            self.reasons
        ))
        object.__setattr__(self, "evidence", deepcopy(dict(self.evidence)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "status": self.status,
            "reasons": list(self.reasons),
            "evidence": deepcopy(dict(self.evidence)),
        }


def classify_candidate_evaluation(
    stage_decisions: Mapping[str, StageDecision],
    *,
    selected: bool,
    integrity_failures: tuple[str, ...],
) -> str:
    """Classify without allowing missing evidence to become a PASS claim."""

    if _ordered_unique_reasons(integrity_failures):
        return "failed"
    deterministic = [
        stage_decisions.get(stage)
        for stage in DETERMINISTIC_LEGAL_STAGES
    ]
    if any(
        decision is not None and decision.status == "fail"
        for decision in deterministic
    ):
        return "failed"
    if not all(
        decision is not None and decision.status == "pass"
        for decision in deterministic
    ):
        return "not_evaluated"
    return "selected" if selected else "legal_pass"


@dataclass(frozen=True)
class CandidateEvaluation:
    candidate_id: str
    program_hash: str
    geometry_hash: str
    stages: Mapping[str, StageDecision] = field(default_factory=dict)
    selected: bool = False
    integrity_failures: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        candidate_id = str(self.candidate_id or "").strip()
        if not candidate_id:
            raise ValueError("candidate_id is required")
        normalized_stages: dict[str, StageDecision] = {}
        for stage, decision in self.stages.items():
            if stage not in EVALUATION_STAGES:
                raise ValueError(f"unknown evaluation stage: {stage}")
            if not isinstance(decision, StageDecision):
                raise TypeError("candidate stages must be StageDecision values")
            if decision.stage != stage:
                raise ValueError("stage decision key does not match its stage")
            normalized_stages[stage] = decision
        object.__setattr__(self, "candidate_id", candidate_id)
        object.__setattr__(self, "program_hash", str(
            self.program_hash or ""
        ).strip())
        object.__setattr__(self, "geometry_hash", str(
            self.geometry_hash or ""
        ).strip())
        object.__setattr__(self, "stages", normalized_stages)
        object.__setattr__(
            self,
            "integrity_failures",
            _ordered_unique_reasons(self.integrity_failures),
        )

    @property
    def overall_status(self) -> str:
        return classify_candidate_evaluation(
            self.stages,
            selected=self.selected,
            integrity_failures=self.integrity_failures,
        )

    def evidence(self) -> dict[str, Any]:
        terminal_reasons = list(self.integrity_failures)
        for stage in EVALUATION_STAGES:
            decision = self.stages.get(stage)
            if decision is None or decision.status != "fail":
                continue
            for reason in decision.reasons:
                if reason not in terminal_reasons:
                    terminal_reasons.append(reason)
        return {
            "schema_version": "arr.maas.candidate_evaluation.v1",
            "candidate_id": self.candidate_id,
            "program_hash": self.program_hash,
            "geometry_hash": self.geometry_hash,
            "overall_status": self.overall_status,
            "selected": bool(self.selected),
            "integrity_failures": list(self.integrity_failures),
            "terminal_reasons": terminal_reasons,
            "stages": {
                stage: self.stages[stage].to_dict()
                for stage in EVALUATION_STAGES
                if stage in self.stages
            },
        }


__all__ = [
    "CandidateEvaluation",
    "DETERMINISTIC_LEGAL_STAGES",
    "EVALUATION_STAGES",
    "EVALUATION_STATUSES",
    "OVERALL_STATUSES",
    "StageDecision",
    "classify_candidate_evaluation",
]
