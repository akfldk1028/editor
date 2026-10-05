from backend.app.modules.design.generation.maas.agents.law_graph_agent.agent import LawGraphAgent


def build_card():
    return LawGraphAgent().build_card()


__all__ = ["build_card"]
