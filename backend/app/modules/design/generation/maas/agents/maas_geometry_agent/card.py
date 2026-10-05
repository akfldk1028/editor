from backend.app.modules.design.generation.maas.agents.maas_geometry_agent.agent import MaasGeometryAgent


def build_card():
    return MaasGeometryAgent().build_card()


__all__ = ["build_card"]
