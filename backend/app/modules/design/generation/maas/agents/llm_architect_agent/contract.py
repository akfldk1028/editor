"""LLM architect agent contract."""

from __future__ import annotations

from typing import Final

from backend.app.modules.design.generation.maas.agents.llm_architect_agent.agent import LLM_ARCHITECT_REVIEW_SCHEMA_VERSION


AGENT_CONTRACT: Final[dict[str, object]] = {
    "agent_id": "llm_architect_agent",
    "schema_version": LLM_ARCHITECT_REVIEW_SCHEMA_VERSION,
    "owns": [
        "llm_architectural_language",
        "primary_secondary_language_check",
        "llm_parameter_source_audit",
        "revision_request",
    ],
    "does_not_own": [
        "legal_pass_finality",
        "parking_pass_finality",
        "geometry_finality",
    ],
    "next_agent": "massdsl_agent",
}


__all__ = ["AGENT_CONTRACT"]
