"""A2UI surfaces for MAAS agent review results.

The official A2UI repository is kept at ``clone/A2UI`` as an integration
reference. This module emits a small v0.9-style message stream using an
ARR-specific catalog so the frontend can render trusted review components.
"""

from __future__ import annotations

from typing import Any

from backend.app.modules.design.generation.maas.agents.orchestrator.flow import build_flow_edges


ARR_MAAS_CATALOG_ID = "arr.maas.agent_review.v0"


def build_agent_review_a2ui_messages(
    *,
    surface_id: str,
    operation_type: str,
    feature: dict[str, Any],
    agent_reviews: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    props = feature.get("properties") or {}
    metrics = {
        "far": props.get("far"),
        "bcr": props.get("bcr"),
        "height": props.get("height"),
        "maas_score": props.get("maas_score"),
    }
    massdsl = props.get("massdsl_proposal")
    grammar_review = props.get("grammar_review")
    review_ids = [f"review-{i}" for i in range(len(agent_reviews))]
    components: list[dict[str, Any]] = [
        {"id": "root", "component": "Column", "children": ["title", "metrics", *review_ids]},
        {"id": "title", "component": "Text", "text": {"path": "/title"}, "tone": "strong"},
        {"id": "metrics", "component": "MetricStrip", "metrics": {"path": "/metrics"}},
    ]
    for i, _review in enumerate(agent_reviews):
        components.append({
            "id": f"review-{i}",
            "component": "AgentReviewCard",
            "review": {"path": f"/agent_reviews/{i}"},
        })

    return [
        {
            "version": "v0.9",
            "createSurface": {
                "surfaceId": surface_id,
                "catalogId": ARR_MAAS_CATALOG_ID,
            },
        },
        {
            "version": "v0.9",
            "updateComponents": {
                "surfaceId": surface_id,
                "components": components,
            },
        },
        {
            "version": "v0.9",
            "updateDataModel": {
                "surfaceId": surface_id,
                "path": "/",
                "value": {
                    "title": f"MAAS agent review · {operation_type}",
                    "metrics": metrics,
                    "flow_edges": build_flow_edges(),
                    "massdsl_proposal": massdsl if isinstance(massdsl, dict) else None,
                    "grammar_review": grammar_review if isinstance(grammar_review, dict) else None,
                    "agent_reviews": agent_reviews,
                },
            },
        },
    ]


__all__ = ["ARR_MAAS_CATALOG_ID", "build_agent_review_a2ui_messages"]
