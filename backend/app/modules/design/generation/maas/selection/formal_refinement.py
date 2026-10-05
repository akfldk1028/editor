"""Formal-language refinement for MAAS review selection."""

from __future__ import annotations

from typing import Callable

from backend.app.modules.design.generation.maas.selection.constraints import final_shape
from backend.app.modules.design.generation.maas.selection.quota import formal_candidate_key, formal_counts, strategy_counts
from backend.app.modules.design.generation.maas.selection.types import Feature, FeatureBool, FormalDiversityCallbacks


def enforce_formal_diversity_replacements(
    *,
    result: list[Feature],
    selected: list[Feature],
    max_same_formal_principle: int,
    max_same_vertical_strategy: int,
    callbacks: FormalDiversityCallbacks,
    candidate_ok: FeatureBool,
    is_plain_capacity_anchor: FeatureBool,
    replace_result: Callable[[int, Feature], bool],
    final_limit: int,
) -> None:
    """Mutate ``result`` to reduce over-repeated formal principles/strategies."""
    candidate_pool = [
        feature for feature in selected
        if feature not in result
        and candidate_ok(feature)
        and not is_plain_capacity_anchor(feature)
    ]
    candidate_pool.sort(key=lambda feature: formal_candidate_key(feature, callbacks=callbacks), reverse=True)

    guard = 0
    while guard < final_limit * 2:
        guard += 1
        current_principles = formal_counts(result, formal_principle=callbacks.formal_principle)
        current_strategies = strategy_counts(result, vertical_strategy=callbacks.vertical_strategy)
        over_principles = {
            principle for principle, count in current_principles.items()
            if count > max_same_formal_principle
        }
        over_strategies = {
            strategy for strategy, count in current_strategies.items()
            if count > max_same_vertical_strategy
        }
        if not over_principles and not over_strategies:
            break

        candidate = next(
            (
                feature for feature in candidate_pool
                if feature not in result
                and (
                    not callbacks.formal_principle(feature)
                    or current_principles.get(callbacks.formal_principle(feature), 0) < max_same_formal_principle
                )
                and (
                    not callbacks.vertical_strategy(feature)
                    or current_strategies.get(callbacks.vertical_strategy(feature), 0) < max_same_vertical_strategy
                )
            ),
            None,
        )
        if candidate is None:
            break

        replacement_indexes = [
            index for index, feature in enumerate(result)
            if final_shape(feature) != "legal_layered_max"
            and (
                callbacks.formal_principle(feature) in over_principles
                or callbacks.vertical_strategy(feature) in over_strategies
            )
        ]
        if not replacement_indexes:
            break

        weakest_index = min(
            replacement_indexes,
            key=lambda index: (
                0 if callbacks.stair_like_risk(result[index]) == "high" else 1,
                float((result[index].get("properties") or {}).get("maas_score") or 0.0),
                callbacks.design_review_quality_key(result[index]),
            ),
        )
        if not replace_result(weakest_index, candidate):
            candidate_pool.remove(candidate)
            continue
