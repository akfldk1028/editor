"""Design orchestrator contract."""

from __future__ import annotations

from typing import Final


AGENT_CONTRACT: Final[dict[str, object]] = {
    "agent_id": "design_orchestrator",
    "owns": [
        "flow_start",
        "operation_routing",
        "canonical_handoff_sequence",
    ],
    "does_not_own": [
        "legal_pass_finality",
        "parking_pass_finality",
        "massdsl_compilation",
        "geometry_repair",
    ],
    "next_agent": "law_graph_agent",
}


__all__ = ["AGENT_CONTRACT"]
