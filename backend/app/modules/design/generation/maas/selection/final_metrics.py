"""Final review-set metric checks for MAAS candidate selection."""

from __future__ import annotations

from collections import Counter
from typing import Any

from backend.app.modules.design.generation.maas.selection.types import Feature, FinalMetricCallbacks


def final_metric_snapshot(items: list[Feature], *, callbacks: FinalMetricCallbacks) -> dict[str, Any]:
    languages = [callbacks.final_language(item) for item in items if callbacks.final_language(item)]
    groups = Counter(callbacks.research_quota_group(item) for item in items)
    defaults = [callbacks.final_parameter_default_ratio(item) for item in items]
    role_patterns = [callbacks.final_role_pattern(item) for item in items if callbacks.final_role_pattern(item)]
    return {
        "agent_count": sum(1 for item in items if callbacks.is_agent_authored_candidate(item)),
        "llm_count": sum(1 for item in items if callbacks.is_llm_authored_candidate(item)),
        "unique_families": len({callbacks.final_family(item) for item in items if callbacks.final_family(item)}),
        "unique_languages": len(set(languages)),
        "max_language": max(Counter(languages).values() or [0]),
        "max_role_pattern": max(Counter(role_patterns).values() or [0]),
        "three_volume": sum(1 for item in items if callbacks.final_volume_count(item) == 3),
        "max_height": max(Counter(callbacks.height_bucket(item) for item in items).values() or [0]),
        "high_default": sum(1 for item in items if callbacks.final_parameter_default_ratio(item) > 0.45),
        "max_default": max(defaults or [0.0]),
        "severe_repair": sum(1 for item in items if callbacks.repair_retention(item) < 0.65),
        "additive": groups.get("additive", 0),
        "subtractive": groups.get("subtractive", 0),
        "hybrid": groups.get("hybrid", 0),
        "sectional": groups.get("sectional", 0),
    }


def unique_family_count_after(
    items: list[Feature],
    index: int,
    candidate: Feature,
    *,
    callbacks: FinalMetricCallbacks,
) -> int:
    families = [
        callbacks.final_family(item)
        for item_index, item in enumerate(items)
        if item_index != index and callbacks.final_family(item)
    ]
    candidate_family = callbacks.final_family(candidate)
    if candidate_family:
        families.append(candidate_family)
    return len(set(families))


def final_metrics_ok_after(
    items: list[Feature],
    index: int,
    candidate: Feature,
    *,
    min_reviewable_llm: int,
    callbacks: FinalMetricCallbacks,
) -> bool:
    revised = list(items)
    revised[index] = candidate
    metrics = final_metric_snapshot(revised, callbacks=callbacks)
    return (
        metrics["unique_families"] >= 15
        and metrics["unique_languages"] >= 14
        and metrics["max_language"] <= 2
        and metrics["llm_count"] >= min_reviewable_llm
        and metrics["max_role_pattern"] <= 2
        and metrics["three_volume"] <= 10
        and metrics["max_height"] <= 12
        and metrics["high_default"] <= 2
        and metrics["max_default"] <= 0.50
        and metrics["severe_repair"] <= 2
        and metrics["additive"] >= 4
        and metrics["subtractive"] >= 4
        and metrics["hybrid"] >= 4
        and metrics["sectional"] >= 4
    )


def final_hard_quotas_ok_after(
    items: list[Feature],
    index: int,
    candidate: Feature,
    *,
    min_reviewable_llm: int,
    callbacks: FinalMetricCallbacks,
) -> bool:
    revised = list(items)
    revised[index] = candidate
    metrics = final_metric_snapshot(revised, callbacks=callbacks)
    return (
        metrics["unique_families"] >= 15
        and metrics["unique_languages"] >= 14
        and metrics["max_language"] <= 2
        and metrics["llm_count"] >= min_reviewable_llm
        and metrics["max_height"] <= 12
        and metrics["high_default"] <= 2
        and metrics["max_default"] <= 0.50
        and metrics["severe_repair"] <= 2
        and metrics["additive"] >= 4
        and metrics["subtractive"] >= 4
        and metrics["hybrid"] >= 4
        and metrics["sectional"] >= 4
    )


def final_structural_quotas_ok_after(
    items: list[Feature],
    index: int,
    candidate: Feature,
    *,
    callbacks: FinalMetricCallbacks,
) -> bool:
    revised = list(items)
    revised[index] = candidate
    metrics = final_metric_snapshot(revised, callbacks=callbacks)
    return (
        metrics["unique_families"] >= 15
        and metrics["unique_languages"] >= 14
        and metrics["max_language"] <= 2
        and metrics["three_volume"] <= 10
        and metrics["max_height"] <= 12
        and metrics["high_default"] <= 2
        and metrics["max_default"] <= 0.50
        and metrics["severe_repair"] <= 2
        and metrics["additive"] >= 4
        and metrics["subtractive"] >= 4
        and metrics["hybrid"] >= 4
        and metrics["sectional"] >= 4
    )
