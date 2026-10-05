"""Geometry review agent for MAAS legal design."""

from __future__ import annotations

from typing import Any

from backend.app.modules.design.generation.maas.agents.shared.types import AgentCard, AgentContext, AgentResult


class MaasGeometryAgent:
    agent_id = "maas_geometry_agent"
    display_name = "MAAS Geometry Agent"
    role = "Translate operation and parking/legal evidence into geometry repair context."

    def run(self, context: AgentContext) -> AgentResult:
        props = context.feature.get("properties") or {}
        notes = "; ".join(context.geometry_notes)
        mass_shape = props.get("mass_shape")
        summary = notes if notes else f"operation {context.operation_type} normalized into a MAAS seed"
        return AgentResult(
            agent=self.agent_id,
            status="done",
            summary=summary,
            metrics={
                "mass_shape": mass_shape,
                "maas_score": props.get("maas_score"),
                "diversity_score": props.get("diversity_score"),
            },
            role=self.role,
            next_agent="grammar_critic_agent",
        )

    def build_card(self) -> dict[str, Any]:
        return AgentCard(
            name=self.agent_id,
            display_name=self.display_name,
            description=self.role,
            skills=["mass_repair_review", "morphology_operator_review"],
            endpoint="/design/maas/agents/maas_geometry_agent",
        ).to_dict()


__all__ = ["MaasGeometryAgent"]
