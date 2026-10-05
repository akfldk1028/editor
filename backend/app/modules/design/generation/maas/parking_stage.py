"""Budgets and policies for the expensive MAAS parking repair stage."""

from __future__ import annotations


def parking_repair_budget(max_variants: int) -> int:
    """Keep parking repair proportional to the requested review set."""
    return min(8, max(2, (int(max_variants) + 1) // 2))


__all__ = ["parking_repair_budget"]
