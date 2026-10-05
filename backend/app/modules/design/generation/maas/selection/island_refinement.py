"""Island quota refinement for MAAS review selection.

This keeps the review sheet from collapsing into one morphology family. It is
still a deterministic quota/projection step, not a true EvoMass evolutionary
operator.
"""

from __future__ import annotations

from typing import Callable

from backend.app.modules.design.generation.maas.selection.constraints import final_shape
from backend.app.modules.design.generation.maas.selection.quota import duplicate_role_pattern_counts, island_candidate_key, island_counts
from backend.app.modules.design.generation.maas.selection.types import Feature, FeatureBool, IslandQuotaCallbacks


def enforce_island_quota_replacements(
    *,
    result: list[Feature],
    selected: list[Feature],
    island_targets: dict[str, int],
    callbacks: IslandQuotaCallbacks,
    candidate_ok: FeatureBool,
    is_plain_capacity_anchor: FeatureBool,
    replace_result: Callable[[int, Feature], bool],
    final_limit: int,
) -> None:
    """Mutate ``result`` through ``replace_result`` until island quotas improve."""
    candidate_pool = [
        feature for feature in selected
        if feature not in result
        and candidate_ok(feature)
        and not is_plain_capacity_anchor(feature)
    ]
    candidate_pool.sort(key=lambda feature: island_candidate_key(feature, callbacks=callbacks), reverse=True)

    def counts() -> dict[str, int]:
        return island_counts(result, research_quota_group=callbacks.research_quota_group)

    def pattern_counts(items: list[Feature]) -> dict[str, int]:
        return duplicate_role_pattern_counts(items, research_role_pattern=callbacks.research_role_pattern)

    for group, target in island_targets.items():
        guard = 0
        while counts().get(group, 0) < target and guard < final_limit * 2:
            guard += 1
            candidate = next(
                (
                    feature for feature in candidate_pool
                    if feature not in result
                    and callbacks.research_quota_group(feature) == group
                ),
                None,
            )
            if candidate is None:
                break
            current_pattern_counts = pattern_counts(result)
            protected_groups = {
                quota_group
                for quota_group, quota_target in island_targets.items()
                if counts().get(quota_group, 0) <= quota_target
            }
            replacement_indexes = [
                index for index, feature in enumerate(result)
                if final_shape(feature) != "legal_layered_max"
                and callbacks.research_quota_group(feature) not in protected_groups
            ]
            if not replacement_indexes:
                replacement_indexes = [
                    index for index, feature in enumerate(result)
                    if final_shape(feature) != "legal_layered_max"
                ]
            if not replacement_indexes:
                break
            weakest_index = min(
                replacement_indexes,
                key=lambda index: (
                    -current_pattern_counts.get(callbacks.research_role_pattern(result[index]), 0),
                    -1 if callbacks.research_quota_group(result[index]) == "generic" else 0,
                    -1 if callbacks.formal_principle(result[index]) == "torqued_stack" else 0,
                    -float((callbacks.source_signature(result[index]).get("surface_count") or 0.0)),
                    -float(result[index].get("properties", {}).get("maas_score") or 0.0),
                ),
            )
            if not replace_result(weakest_index, candidate):
                candidate_pool.remove(candidate)
                continue

    duplicated_patterns = {
        pattern for pattern, count in pattern_counts(result).items()
        if pattern and count > 2
    }
    if not duplicated_patterns:
        return

    replacement_pool = [
        feature for feature in candidate_pool
        if feature not in result
        and callbacks.research_role_pattern(feature) not in duplicated_patterns
    ]
    replacement_pool.sort(key=lambda feature: island_candidate_key(feature, callbacks=callbacks), reverse=True)
    for pattern in sorted(duplicated_patterns):
        guard = 0
        while pattern_counts(result).get(pattern, 0) > 2 and guard < final_limit * 2:
            guard += 1
            candidate = next((feature for feature in replacement_pool if feature not in result), None)
            if candidate is None:
                break
            replace_index = next(
                (
                    index for index, feature in enumerate(result)
                    if callbacks.research_role_pattern(feature) == pattern
                    and final_shape(feature) != "legal_layered_max"
                ),
                None,
            )
            if replace_index is None:
                break
            if not replace_result(replace_index, candidate):
                replacement_pool.remove(candidate)
                continue
