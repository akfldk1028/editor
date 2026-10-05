"""Shared contracts for MAAS design agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class ExecutionIdentity:
    """Immutable identity of the exact compiled MASS reviewed by every agent."""

    execution_id: str
    program_hash: str
    geometry_hash: str
    floor_capacity_plan_hash: str
    pnu: str

    def __post_init__(self) -> None:
        missing = [
            key
            for key, value in (
                ("execution_id", self.execution_id),
                ("program_hash", self.program_hash),
                ("geometry_hash", self.geometry_hash),
                ("floor_capacity_plan_hash", self.floor_capacity_plan_hash),
                ("pnu", self.pnu),
            )
            if not str(value).strip()
        ]
        if missing:
            raise ValueError(f"execution identity requires: {', '.join(missing)}")

    def to_dict(self) -> dict[str, str]:
        return {
            "execution_id": self.execution_id,
            "program_hash": self.program_hash,
            "geometry_hash": self.geometry_hash,
            "floor_capacity_plan_hash": self.floor_capacity_plan_hash,
            "pnu": self.pnu,
        }


@dataclass(frozen=True)
class AgentEvidence:
    evidence_id: str
    agent: str
    status: str
    summary: str
    identity: ExecutionIdentity
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "agent": self.agent,
            "status": self.status,
            "summary": self.summary,
            "identity": self.identity.to_dict(),
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True)
class AgentHandoff:
    handoff_id: str
    source_agent: str
    target_agent: str
    identity: ExecutionIdentity
    input_evidence_ids: tuple[str, ...] = ()
    output_evidence_ids: tuple[str, ...] = ()
    status: str = "completed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "handoff_id": self.handoff_id,
            "source_agent": self.source_agent,
            "target_agent": self.target_agent,
            "identity": self.identity.to_dict(),
            "input_evidence_ids": list(self.input_evidence_ids),
            "output_evidence_ids": list(self.output_evidence_ids),
            "status": self.status,
        }


@dataclass(frozen=True)
class AgentContext:
    operation_type: str
    feature: dict[str, Any]
    constraints: dict[str, Any]
    rejected: list[dict[str, Any]] = field(default_factory=list)
    geometry_notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AgentResult:
    agent: str
    status: str
    summary: str
    metrics: dict[str, Any] | None = None
    role: str | None = None
    next_agent: str | None = None

    def to_review(self) -> dict[str, Any]:
        review: dict[str, Any] = {
            "agent": self.agent,
            "status": self.status,
            "summary": self.summary,
        }
        if self.metrics is not None:
            review["metrics"] = self.metrics
        if self.role:
            review["role"] = self.role
        if self.next_agent:
            review["next_agent"] = self.next_agent
        return review


@dataclass(frozen=True)
class AgentCard:
    name: str
    display_name: str
    description: str
    skills: list[str]
    endpoint: str
    input_schema: str = "arr.maas.agent_context.v0"
    output_schema: str = "arr.maas.agent_review.v0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "capabilities": {
                "streaming": False,
                "deterministic": True,
            },
            "skills": [
                {"id": skill, "name": skill.replace("_", " ").title()}
                for skill in self.skills
            ],
            "endpoint": self.endpoint,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
        }


class MaasAgent(Protocol):
    agent_id: str
    display_name: str
    role: str

    def run(self, context: AgentContext) -> AgentResult:
        ...

    def build_card(self) -> dict[str, Any]:
        ...


def metric(props: dict[str, Any], key: str) -> float | None:
    value = props.get(key)
    return float(value) if isinstance(value, (int, float)) else None


__all__ = [
    "AgentCard",
    "AgentContext",
    "AgentEvidence",
    "AgentHandoff",
    "AgentResult",
    "ExecutionIdentity",
    "MaasAgent",
    "metric",
]
