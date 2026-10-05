"""Event builders for MAAS agent-to-agent flow traces."""

from __future__ import annotations

from typing import Any


def build_flow_event(
    *,
    source: str,
    target: str,
    message: str,
    index: int,
    run_id: str | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "source": "arr_maas_design_orchestrator",
        "step": index,
    }
    if run_id:
        metadata["run_id"] = run_id
    return {
        "from_agent": source,
        "to_agent": target,
        "message": message,
        "metadata": metadata,
    }


__all__ = ["build_flow_event"]
