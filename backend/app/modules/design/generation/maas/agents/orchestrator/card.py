"""Design orchestrator card export."""

from __future__ import annotations

from backend.app.modules.design.generation.maas.agents.orchestrator.agent import DesignOrchestratorAgent


def build_card() -> dict[str, object]:
    return DesignOrchestratorAgent().build_card()


__all__ = ["build_card"]
