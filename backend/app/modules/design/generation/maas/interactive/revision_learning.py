"""Project-scoped online calibration from persisted architect revision feedback."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from backend.app.adapters.design_storage.models import MaasRevisionEvent


LEARNING_PROFILE_SCHEMA_VERSION = "arr.maas.revision_learning_profile.v1"


def build_revision_learning_profile(project_key: str, *, limit: int = 200) -> dict[str, Any]:
    key = str(project_key or "").strip()
    if not key:
        return _empty_profile()
    events = list(
        MaasRevisionEvent.objects.filter(project_key=key)
        .exclude(user_decision="pending")
        .order_by("-created_at")[:limit]
    )
    scores: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    accepted_count = 0
    undo_count = 0
    for event in events:
        if event.user_decision == "accepted":
            accepted_count += 1
            outcome = 1.0 + max(0.0, float(event.user_rating or 3.0) - 3.0) * 0.15
        elif event.user_decision == "undo":
            undo_count += 1
            outcome = -1.5
        else:
            outcome = -1.0
        for diff in event.graph_diff if isinstance(event.graph_diff, list) else []:
            if not isinstance(diff, dict):
                continue
            signature = f"{diff.get('type')}:{diff.get('parameter') or 'node'}"
            before = diff.get("before")
            after = diff.get("after")
            if isinstance(before, int | float) and isinstance(after, int | float):
                direction = "increase" if float(after) > float(before) else "decrease"
            else:
                direction = "remove"
            key_with_direction = f"{signature}:{direction}"
            scores[key_with_direction] += outcome
            counts[key_with_direction] += 1
    ranked = sorted(scores, key=lambda item: (scores[item], counts[item]), reverse=True)
    avoided = sorted(scores, key=lambda item: (scores[item], -counts[item]))
    total = len(events)
    return {
        "schema_version": LEARNING_PROFILE_SCHEMA_VERSION,
        "project_key": key,
        "feedback_event_count": total,
        "accept_rate": round(accepted_count / total, 3) if total else None,
        "undo_rate": round(undo_count / total, 3) if total else None,
        "preferred_operation_patterns": [
            {"pattern": item, "score": round(scores[item], 3), "count": counts[item]}
            for item in ranked if scores[item] > 0
        ][:8],
        "avoided_operation_patterns": [
            {"pattern": item, "score": round(scores[item], 3), "count": counts[item]}
            for item in avoided if scores[item] < 0
        ][:8],
    }


def _empty_profile() -> dict[str, Any]:
    return {
        "schema_version": LEARNING_PROFILE_SCHEMA_VERSION,
        "project_key": "",
        "feedback_event_count": 0,
        "accept_rate": None,
        "undo_rate": None,
        "preferred_operation_patterns": [],
        "avoided_operation_patterns": [],
    }


__all__ = ["LEARNING_PROFILE_SCHEMA_VERSION", "build_revision_learning_profile"]
