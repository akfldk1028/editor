"""Diversity scoring for MAAS mass variants."""

from __future__ import annotations

from collections import Counter
from typing import Any

from shapely.geometry import Polygon


def polygon_iou(a: Polygon, b: Polygon) -> float:
    """Return footprint IoU in [0, 1]."""
    if a is None or b is None or a.is_empty or b.is_empty:
        return 0.0
    union_area = a.union(b).area
    if union_area <= 0:
        return 0.0
    return float(a.intersection(b).area / union_area)


def shape_signature(polygon: Polygon) -> dict[str, float]:
    """Compact footprint descriptors used for ranking and UI explanation."""
    if polygon is None or polygon.is_empty or polygon.area <= 0:
        return {"area": 0.0, "perimeter": 0.0, "compactness": 9999.0}
    return {
        "area": round(float(polygon.area), 3),
        "perimeter": round(float(polygon.length), 3),
        "compactness": round(float((polygon.length ** 2) / polygon.area), 3),
    }


def diversity_score(candidate: Polygon, previous: list[Polygon], source: Polygon | None = None) -> float:
    """Prefer variants that differ from the source and from already selected variants."""
    comparisons = [p for p in previous if p is not None and not p.is_empty]
    if source is not None and not source.is_empty:
        comparisons.append(source)
    if not comparisons:
        return 1.0
    max_iou = max(polygon_iou(candidate, other) for other in comparisons)
    return round(max(0.0, 1.0 - max_iou), 4)


def sequence_verbs(sequence: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None) -> list[str]:
    return [
        str(call.get("verb"))
        for call in sequence or []
        if isinstance(call, dict) and call.get("verb") and call.get("verb") != "base"
    ]


def verb_set_jaccard(a: list[str], b: list[str]) -> float:
    left = set(a)
    right = set(b)
    if not left and not right:
        return 1.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def token_f1(a: list[str], b: list[str]) -> float:
    left = Counter(a)
    right = Counter(b)
    if not left and not right:
        return 1.0
    overlap = sum((left & right).values())
    if overlap == 0:
        return 0.0
    precision = overlap / sum(left.values()) if left else 0.0
    recall = overlap / sum(right.values()) if right else 0.0
    return 2 * precision * recall / (precision + recall)


def ordered_lcs(a: list[str], b: list[str]) -> int:
    if not a or not b:
        return 0
    dp = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i, left in enumerate(a):
        for j, right in enumerate(b):
            if left == right:
                dp[i + 1][j + 1] = dp[i][j] + 1
            else:
                dp[i + 1][j + 1] = max(dp[i][j + 1], dp[i + 1][j])
    return dp[len(a)][len(b)]


def sequence_distance(a: list[str], b: list[str]) -> float:
    """MAAS-paper style verb distance: set, multiset, and ordered similarity."""
    if not a and not b:
        return 0.0
    denom = max(len(a), len(b), 1)
    lcs_score = ordered_lcs(a, b) / denom
    similarity = (
        verb_set_jaccard(a, b) * 0.38
        + token_f1(a, b) * 0.32
        + lcs_score * 0.30
    )
    return round(max(0.0, min(1.0, 1.0 - similarity)), 4)


def sequence_diversity_score(candidate: list[str], previous: list[list[str]]) -> float:
    if not previous:
        return 1.0
    return round(min(sequence_distance(candidate, item) for item in previous), 4)


__all__ = [
    "diversity_score",
    "ordered_lcs",
    "polygon_iou",
    "sequence_distance",
    "sequence_diversity_score",
    "sequence_verbs",
    "shape_signature",
    "token_f1",
    "verb_set_jaccard",
]
