from backend.app.modules.design.generation.maas.agents.llm_architect_agent.agent import LLMArchitectAgent


def build_card():
    return LLMArchitectAgent().build_card()


__all__ = ["build_card"]
