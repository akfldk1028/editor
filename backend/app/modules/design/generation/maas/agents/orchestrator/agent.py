"""Top-level MAAS design orchestrator."""

from __future__ import annotations

from backend.app.modules.design.generation.maas.agents.shared.types import AgentCard, AgentContext, AgentResult


class DesignOrchestratorAgent:
    agent_id = "design_orchestrator"
    display_name = "Design Orchestrator"
    role = "Route PNU/design candidates through law, parking, MassDSL, MAAS geometry, grammar critique, and final review agents."

    def run(self, context: AgentContext) -> AgentResult:
        return AgentResult(
            agent=self.agent_id,
            status="routed",
            summary=f"operation {context.operation_type} routed to law_graph_agent",
            role=self.role,
            next_agent="law_graph_agent",
        )

    def build_card(self) -> dict[str, object]:
        return AgentCard(
            name=self.agent_id,
            display_name=self.display_name,
            description=self.role,
            skills=["agent_routing", "design_flow_coordination"],
            endpoint="/design/maas/agents/design_orchestrator",
        ).to_dict()


__all__ = ["DesignOrchestratorAgent"]
