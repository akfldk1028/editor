"""Final review agent for MAAS legal design."""

from __future__ import annotations

from typing import Any

from backend.app.modules.design.generation.maas.agents.shared.types import AgentCard, AgentContext, AgentResult


class ReviewAgent:
    agent_id = "review_agent"
    display_name = "Review Agent"
    role = "Summarize final audit state and remaining rejected candidate evidence."

    def run(self, context: AgentContext) -> AgentResult:
        props = context.feature.get("properties") or {}
        return AgentResult(
            agent=self.agent_id,
            status="done",
            summary=f"{len(context.rejected)} rejected candidates kept for audit; selected mass_shape={props.get('mass_shape')}",
            metrics={
                "rejected_count": len(context.rejected),
                "selected_mass_shape": props.get("mass_shape"),
            },
            role=self.role,
        )

    def build_card(self) -> dict[str, Any]:
        return AgentCard(
            name=self.agent_id,
            display_name=self.display_name,
            description=self.role,
            skills=["final_structured_review", "candidate_lineage_summary"],
            endpoint="/design/maas/agents/review_agent",
        ).to_dict()


__all__ = ["ReviewAgent"]
