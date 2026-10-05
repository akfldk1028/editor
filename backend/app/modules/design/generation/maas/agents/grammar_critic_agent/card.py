from backend.app.modules.design.generation.maas.agents.grammar_critic_agent.agent import GrammarCriticAgent


def build_card():
    return GrammarCriticAgent().build_card()


__all__ = ["build_card"]
