"""Law graph review agent for MAAS legal design."""

from __future__ import annotations

from typing import Any

from backend.app.modules.design.generation.maas.agents.shared.types import AgentCard, AgentContext, AgentResult, metric


class LawGraphAgent:
    agent_id = "law_graph_agent"
    display_name = "Law Graph Agent"
    role = "Verify FAR/BCR/height legal metrics and cite structured constraints."

    def run(self, context: AgentContext) -> AgentResult:
        props = context.feature.get("properties") or {}
        far = metric(props, "far")
        bcr = metric(props, "bcr")
        height = metric(props, "height")
        far_limit = metric(context.constraints, "far_limit")
        bcr_limit = metric(context.constraints, "bcr_limit")
        height_limit = metric(context.constraints, "height_limit")

        legal_pass = True
        if far is not None and far_limit is not None and far > far_limit + 0.1:
            legal_pass = False
        if bcr is not None and bcr_limit is not None and bcr > bcr_limit + 0.1:
            legal_pass = False
        if height is not None and height_limit is not None and height > height_limit + 0.1:
            legal_pass = False

        return AgentResult(
            agent=self.agent_id,
            status="pass" if legal_pass else "fail",
            summary="FAR/BCR/height metrics are within returned legal limits"
            if legal_pass
            else "Returned mass exceeds at least one legal metric",
            metrics={
                "far": far,
                "bcr": bcr,
                "height": height,
                "far_limit": far_limit,
                "bcr_limit": bcr_limit,
                "height_limit": height_limit,
            },
            role=self.role,
            next_agent="master_plan_agent",
        )

    def build_card(self) -> dict[str, Any]:
        return AgentCard(
            name=self.agent_id,
            display_name=self.display_name,
            description=self.role,
            skills=["legal_metric_review", "graph_rule_evidence"],
            endpoint="/design/maas/agents/law_graph_agent",
        ).to_dict()


__all__ = ["LawGraphAgent"]
