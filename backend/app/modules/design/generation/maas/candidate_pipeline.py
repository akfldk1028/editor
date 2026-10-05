"""Cheap-to-expensive candidate pipeline boundaries for live MAAS review."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


SelectDiverse = Callable[..., list[dict[str, Any]]]


def build_bounded_review_pool(
    features: list[dict[str, Any]],
    *,
    max_variants: int,
    preferred_operator: str | None,
    select_diverse: SelectDiverse,
) -> list[dict[str, Any]]:
    """Bound candidates before parking, VLM, critic and final projection."""
    pool_limit = min(len(features), max(24, int(max_variants) * 3))
    return select_diverse(
        list(features),
        max(1, pool_limit),
        preferred_operator=preferred_operator,
    )


__all__ = ["build_bounded_review_pool"]
