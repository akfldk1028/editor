from backend.app.modules.design.generation.maas.agents.massdsl_agent.agent import MassDSLAgent


def build_card():
    return MassDSLAgent().build_card()


__all__ = ["build_card"]
