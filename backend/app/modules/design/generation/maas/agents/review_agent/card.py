from backend.app.modules.design.generation.maas.agents.review_agent.agent import ReviewAgent


def build_card():
    return ReviewAgent().build_card()


__all__ = ["build_card"]
