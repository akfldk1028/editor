"""Quota and diversity scoring helpers for MAAS review selection."""

from __future__ import annotations

from backend.app.modules.design.generation.maas.selection.types import Feature, FeatureText, FormalDiversityCallbacks, IslandQuotaCallbacks


def island_counts(items: list[Feature], *, research_quota_group: FeatureText) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        group = research_quota_group(item)
        counts[group] = counts.get(group, 0) + 1
    return counts


def duplicate_role_pattern_counts(items: list[Feature], *, research_role_pattern: FeatureText) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        pattern = research_role_pattern(item)
        if pattern:
            counts[pattern] = counts.get(pattern, 0) + 1
    return counts


def island_candidate_key(feature: Feature, *, callbacks: IslandQuotaCallbacks) -> tuple[float, ...]:
    descriptor = callbacks.research_diversity_descriptor(feature)
    tags = descriptor.get("topology_tags") if isinstance(descriptor.get("topology_tags"), list) else []
    signature = callbacks.source_signature(feature)
    surface_count = float(signature.get("surface_count") or 0.0)
    volume_count = float(descriptor.get("volume_count") or callbacks.visible_volume_count(feature))
    return (
        1.0 if callbacks.is_direct_openai_llm_candidate(feature) else 0.0,
        1.0 if callbacks.has_review_source_geometry(feature) else 0.0,
        1.0 if callbacks.repair_retention(feature) >= 0.70 else 0.0,
        1.0 if callbacks.repair_retention(feature, source_volume=True) >= 0.65 else 0.0,
        max(0.0, 1.0 - min(surface_count, 70.0) / 70.0),
        max(0.0, 1.0 - abs(volume_count - 4.0) / 6.0),
        min(float(len(tags)), 8.0) / 8.0,
        float(callbacks.design_synthesis_rank(feature)) / 3.0,
        float(feature.get("properties", {}).get("diversity_score") or 0.0),
        float(feature.get("properties", {}).get("maas_score") or 0.0),
    )


def formal_counts(items: list[Feature], *, formal_principle: FeatureText) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        principle = formal_principle(item)
        if principle:
            counts[principle] = counts.get(principle, 0) + 1
    return counts


def strategy_counts(items: list[Feature], *, vertical_strategy: FeatureText) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        strategy = vertical_strategy(item)
        if strategy:
            counts[strategy] = counts.get(strategy, 0) + 1
    return counts


def formal_candidate_key(feature: Feature, *, callbacks: FormalDiversityCallbacks) -> tuple[float, ...]:
    ambition = callbacks.architectural_ambition(feature)
    return (
        1.0 if callbacks.is_direct_openai_llm_candidate(feature) else 0.0,
        1.0 if callbacks.is_agent_authored_candidate(feature) else 0.0,
        float(ambition.get("silhouette_strength") or 0.0),
        float(ambition.get("sectional_diagram_clarity") or 0.0),
        *callbacks.design_review_quality_key(feature),
    )
