"""Registry for deterministic ARR MAAS design agents."""

from __future__ import annotations

from typing import Any

from backend.app.modules.design.generation.maas.agents.orchestrator.agent import DesignOrchestratorAgent
from backend.app.modules.design.generation.maas.agents.orchestrator.flow import FLOW_AGENT_SEQUENCE, REVIEW_AGENT_SEQUENCE
from backend.app.modules.design.generation.maas.agents.grammar_critic_agent.agent import GrammarCriticAgent
from backend.app.modules.design.generation.maas.agents.law_graph_agent.agent import LawGraphAgent
from backend.app.modules.design.generation.maas.agents.llm_architect_agent.agent import LLMArchitectAgent
from backend.app.modules.design.generation.maas.agents.maas_geometry_agent.agent import MaasGeometryAgent
from backend.app.modules.design.generation.maas.agents.massdsl_agent.agent import MassDSLAgent
from backend.app.modules.design.generation.maas.agents.master_plan_agent.agent import MasterPlanAgent
from backend.app.modules.design.generation.maas.agents.preference_distiller_agent.agent import PreferenceDistillerAgent
from backend.app.modules.design.generation.maas.agents.review_agent.agent import ReviewAgent
from backend.app.modules.design.generation.maas.agents.shared.types import AgentContext, MaasAgent


AGENT_SEQUENCE = REVIEW_AGENT_SEQUENCE


def build_agent_registry() -> dict[str, MaasAgent]:
    agents: list[MaasAgent] = [
        DesignOrchestratorAgent(),
        LawGraphAgent(),
        MasterPlanAgent(),
        LLMArchitectAgent(),
        MassDSLAgent(),
        MaasGeometryAgent(),
        GrammarCriticAgent(),
        PreferenceDistillerAgent(),
        ReviewAgent(),
    ]
    return {agent.agent_id: agent for agent in agents}


def build_agent_cards() -> list[dict[str, Any]]:
    registry = build_agent_registry()
    return [registry[agent_id].build_card() for agent_id in FLOW_AGENT_SEQUENCE]


def run_review_flow(context: AgentContext) -> list[dict[str, Any]]:
    registry = build_agent_registry()
    return [registry[agent_id].run(context).to_review() for agent_id in AGENT_SEQUENCE]


__all__ = ["AGENT_SEQUENCE", "build_agent_cards", "build_agent_registry", "run_review_flow"]
