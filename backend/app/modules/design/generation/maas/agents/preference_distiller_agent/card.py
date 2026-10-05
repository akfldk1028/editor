from backend.app.modules.design.generation.maas.agents.preference_distiller_agent.agent import PreferenceDistillerAgent


def build_card():
    return PreferenceDistillerAgent().build_card()


__all__ = ["build_card"]

