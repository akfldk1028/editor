"""Second-stage preference distillation agent for MAAS."""

from __future__ import annotations

from typing import Any

from backend.app.modules.design.generation.maas.agents.shared.types import AgentCard, AgentContext, AgentResult
from backend.app.modules.design.generation.maas.preference import build_preference_distillation


class PreferenceDistillerAgent:
    agent_id = "preference_distiller_agent"
    display_name = "Preference Distiller Agent"
    role = "Score legal MAAS PNG candidates for architectural preference without overriding law or parking gates."

    def run(self, context: AgentContext) -> AgentResult:
        evidence = build_preference_distillation(context.feature)
        props = context.feature.setdefault("properties", {})
        props.setdefault("preference_distillation", evidence)
        model = props.get("maas_model")
        if isinstance(model, dict):
            model.setdefault("preference_distillation", evidence)
        return AgentResult(
            agent=self.agent_id,
            status="done",
            summary=(
                f"second-stage preference evidence mode={evidence['mode']} "
                f"score={evidence['distilled_preference_score']}"
            ),
            metrics={
                "schema_version": evidence["schema_version"],
                "mode": evidence["mode"],
                "distilled_preference_score": evidence["distilled_preference_score"],
                "vlm_model": evidence["vlm_model"],
                "human_pairwise_wins": evidence["human_pairwise_wins"],
                "hard_gates": evidence["hard_gates"],
            },
            role=self.role,
            next_agent="review_agent",
        )

    def build_card(self) -> dict[str, Any]:
        return AgentCard(
            name=self.agent_id,
            display_name=self.display_name,
            description=self.role,
            skills=["vlm_concept_scoring", "pairwise_preference_reranking", "legal_gate_preservation"],
            endpoint="/design/maas/agents/preference_distiller_agent",
        ).to_dict()


__all__ = ["PreferenceDistillerAgent"]
