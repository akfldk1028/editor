"""Compatibility entry points for conversational MAAS agent reviews."""

from __future__ import annotations

from typing import Any

from backend.app.modules.design.generation.maas.agents.shared.registry import build_agent_cards, build_agent_registry, run_review_flow
from backend.app.modules.design.generation.maas.agents.shared.types import AgentContext


def build_agent_reviews(
    *,
    operation_type: str,
    feature: dict[str, Any],
    constraints: dict[str, Any] | None,
    rejected: list[dict[str, Any]] | None = None,
    geometry_notes: list[str] | None = None,
) -> list[dict[str, Any]]:
    return run_review_flow(
        AgentContext(
            operation_type=operation_type,
            feature=feature,
            constraints=constraints or {},
            rejected=rejected or [],
            geometry_notes=geometry_notes or [],
        )
    )


__all__ = ["build_agent_cards", "build_agent_registry", "build_agent_reviews"]
