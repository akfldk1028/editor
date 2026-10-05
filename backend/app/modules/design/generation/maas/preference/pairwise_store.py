"""JSONL store for MAAS pairwise preference labels."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PAIRWISE_SCHEMA_VERSION = "arr.maas.pairwise_preference.v1"


@dataclass(frozen=True)
class PairwisePreference:
    preferred_candidate_id: str
    rejected_candidate_id: str
    reviewer_id: str = "user"
    session_id: str = "default"
    reason: str = ""
    preferred_geometry_hash: str = ""
    rejected_geometry_hash: str = ""
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PAIRWISE_SCHEMA_VERSION,
            "preferred_candidate_id": self.preferred_candidate_id,
            "rejected_candidate_id": self.rejected_candidate_id,
            "reviewer_id": self.reviewer_id,
            "session_id": self.session_id,
            "reason": self.reason,
            "preferred_geometry_hash": self.preferred_geometry_hash,
            "rejected_geometry_hash": self.rejected_geometry_hash,
            "created_at": self.created_at or time.time(),
        }

    def to_event_fields(self) -> dict[str, str]:
        return {
            "preferred_candidate_id": self.preferred_candidate_id,
            "rejected_candidate_id": self.rejected_candidate_id,
            "reviewer_id": self.reviewer_id,
            "session_id": self.session_id,
            "reason": self.reason,
            "preferred_geometry_hash": self.preferred_geometry_hash,
            "rejected_geometry_hash": self.rejected_geometry_hash,
        }


def append_pairwise_label(path: Path, label: PairwisePreference) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(label.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")


def load_pairwise_labels(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    labels: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        data = json.loads(line)
        if data.get("schema_version") == PAIRWISE_SCHEMA_VERSION:
            labels.append(data)
    return labels


def pairwise_win_counts(labels: list[dict[str, Any]], *, reviewer_id: str | None = None) -> dict[str, int]:
    counts: dict[str, int] = {}
    for label in labels:
        if reviewer_id and label.get("reviewer_id") != reviewer_id:
            continue
        preferred = str(label.get("preferred_candidate_id") or "")
        if preferred:
            counts[preferred] = counts.get(preferred, 0) + 1
    return counts


__all__ = [
    "PAIRWISE_SCHEMA_VERSION",
    "PairwisePreference",
    "append_pairwise_label",
    "load_pairwise_labels",
    "pairwise_win_counts",
]
