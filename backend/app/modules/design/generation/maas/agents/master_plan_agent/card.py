from backend.app.modules.design.generation.maas.agents.master_plan_agent.agent import MasterPlanAgent


def build_card():
    return MasterPlanAgent().build_card()


__all__ = ["build_card"]
