"""Hash-bound specialist collaboration for one compiled MASS.

This is deliberately separate from the conversational review registry.  It is
an acceptance protocol: every specialist reviews the same compiled geometry,
and missing specialist evidence propagates to the selector without being
silently converted into a pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from backend.app.modules.design.generation.maas.agents.shared.types import AgentEvidence, AgentHandoff, ExecutionIdentity


SPECIALIST_SEQUENCE = (
    "maas_geometry_agent",
    "law_graph_agent",
    "master_plan_agent",
    "review_agent",
)

AgentExecutor = Callable[
    [ExecutionIdentity, Sequence[AgentEvidence]],
    AgentEvidence,
]


class ExecutionCollaborationError(ValueError):
    pass


@dataclass(frozen=True)
class CollaborationTrace:
    identity: ExecutionIdentity
    evidence: tuple[AgentEvidence, ...]
    handoffs: tuple[AgentHandoff, ...]
    final_status: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "arr.maas.agent_collaboration.v1",
            "identity": self.identity.to_dict(),
            "final_status": self.final_status,
            "evidence": [row.to_dict() for row in self.evidence],
            "handoffs": [row.to_dict() for row in self.handoffs],
        }


def run_execution_collaboration(
    identity: ExecutionIdentity,
    *,
    executors: Mapping[str, AgentExecutor],
) -> CollaborationTrace:
    """Run required specialists in order and derive a fail-closed selector."""

    missing = [agent for agent in SPECIALIST_SEQUENCE if agent not in executors]
    if missing:
        raise ExecutionCollaborationError(
            f"missing specialist executors: {', '.join(missing)}"
        )

    evidence: list[AgentEvidence] = []
    handoffs: list[AgentHandoff] = []
    source = "design_orchestrator"
    for index, agent in enumerate(SPECIALIST_SEQUENCE):
        input_ids = tuple(row.evidence_id for row in evidence)
        result = executors[agent](identity, tuple(evidence))
        if result.agent != agent:
            raise ExecutionCollaborationError(
                f"agent mismatch: expected {agent}, received {result.agent}"
            )
        if result.identity != identity:
            raise ExecutionCollaborationError(f"identity mismatch at {agent}")
        evidence.append(result)
        handoffs.append(AgentHandoff(
            handoff_id=f"handoff:{index:02d}:{source}:{agent}",
            source_agent=source,
            target_agent=agent,
            identity=identity,
            input_evidence_ids=input_ids,
            output_evidence_ids=(result.evidence_id,),
            status="completed" if result.status not in {"failed", "needs_evidence"} else result.status,
        ))
        source = agent

    blocking_statuses = {row.status for row in evidence}
    if "failed" in blocking_statuses:
        final_status = "rejected"
    elif "needs_evidence" in blocking_statuses:
        final_status = "needs_evidence"
    else:
        final_status = "accepted"
    selector = AgentEvidence(
        evidence_id="evidence:selector",
        agent="selector",
        status=final_status,
        summary=f"selector decision={final_status}",
        identity=identity,
        evidence={
            "specialist_evidence_ids": [row.evidence_id for row in evidence],
            "blocking_statuses": sorted(
                status for status in blocking_statuses if status in {"failed", "needs_evidence"}
            ),
        },
    )
    handoffs.append(AgentHandoff(
        handoff_id="handoff:04:review_agent:selector",
        source_agent="review_agent",
        target_agent="selector",
        identity=identity,
        input_evidence_ids=tuple(row.evidence_id for row in evidence),
        output_evidence_ids=(selector.evidence_id,),
        status=final_status,
    ))
    evidence.append(selector)
    return CollaborationTrace(
        identity=identity,
        evidence=tuple(evidence),
        handoffs=tuple(handoffs),
        final_status=final_status,
    )


def build_default_execution_executors(
    *,
    compilation: Any,
    geometry_gate_issues: Sequence[Any],
    downstream_evidence: Mapping[str, Any],
    program_metadata: Mapping[str, Any],
) -> dict[str, AgentExecutor]:
    """Bind existing specialist logic to one already-compiled MASS."""

    from backend.app.modules.design.generation.maas.agents.law_graph_agent.evidence import collect_law_agent_evidence

    metadata = dict(program_metadata or {})
    downstream = dict(downstream_evidence or {})

    def geometry(identity: ExecutionIdentity, accumulated: Sequence[AgentEvidence]) -> AgentEvidence:
        passed = compilation.status == "compiled" and not geometry_gate_issues
        return AgentEvidence(
            evidence_id="evidence:maas_geometry_agent",
            agent="maas_geometry_agent",
            status="passed" if passed else "failed",
            summary="compiled MASS passed geometry gate" if passed else "compiled MASS failed geometry gate",
            identity=identity,
            evidence={
                "compiler_status": str(compilation.status or ""),
                "geometry_hash": str(compilation.geometry_hash or ""),
                "gate_issue_codes": [str(getattr(issue, "code", "")) for issue in geometry_gate_issues],
                "metrics": dict(compilation.metrics or {}),
            },
        )

    def law(identity: ExecutionIdentity, accumulated: Sequence[AgentEvidence]) -> AgentEvidence:
        projection = metadata.get("program_projection")
        projection = projection if isinstance(projection, Mapping) else {}
        context = {
            "law": downstream.get("law") or {},
            "building_type": (
                metadata.get("building_type")
                or metadata.get("program_id")
                or projection.get("building_type")
                or projection.get("program_id")
                or metadata.get("family")
                or "building mass"
            ),
        }
        return collect_law_agent_evidence(identity, context)

    def parking(identity: ExecutionIdentity, accumulated: Sequence[AgentEvidence]) -> AgentEvidence:
        # A MasterPlanagent layout hand-off (masterplan.layout.v1) takes the
        # master_plan_agent seat when present; it is identity-checked and
        # fails closed. Otherwise the legacy parking hard-gate evidence is read.
        from backend.app.modules.design.generation.maas.agents.master_plan_agent.handoff import evidence_from_masterplan_layout, is_masterplan_layout

        masterplan = downstream.get("masterplan")
        if is_masterplan_layout(masterplan):
            return evidence_from_masterplan_layout(identity, masterplan)
        payload = downstream.get("parking")
        payload = dict(payload) if isinstance(payload, Mapping) else {}
        failed = str(payload.get("status") or "") == "failed" or (
            payload.get("evaluated") is True and payload.get("hard_pass") is False
        )
        passed = str(payload.get("status") or "") == "passed" or payload.get("hard_pass") is True
        status = "failed" if failed else "passed" if passed else "needs_evidence"
        return AgentEvidence(
            evidence_id="evidence:master_plan_agent",
            agent="master_plan_agent",
            status=status,
            summary=f"parking specialist status={status}",
            identity=identity,
            evidence=payload,
        )

    def review(identity: ExecutionIdentity, accumulated: Sequence[AgentEvidence]) -> AgentEvidence:
        statuses = {row.status for row in accumulated}
        status = "failed" if "failed" in statuses else "needs_evidence" if "needs_evidence" in statuses else "passed"
        return AgentEvidence(
            evidence_id="evidence:review_agent",
            agent="review_agent",
            status=status,
            summary=f"specialist review status={status}",
            identity=identity,
            evidence={"specialist_statuses": {row.agent: row.status for row in accumulated}},
        )

    return {
        "maas_geometry_agent": geometry,
        "law_graph_agent": law,
        "master_plan_agent": parking,
        "review_agent": review,
    }


__all__ = [
    "CollaborationTrace",
    "AgentExecutor",
    "build_default_execution_executors",
    "ExecutionCollaborationError",
    "SPECIALIST_SEQUENCE",
    "run_execution_collaboration",
]
