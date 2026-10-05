"""Recovery-stage cleanup for MAAS review selection."""

from __future__ import annotations

from collections import Counter
from typing import Callable

from backend.app.modules.design.generation.maas.selection.constraints import final_shape
from backend.app.modules.design.generation.maas.selection.types import Feature, RecoveryRefinementCallbacks


def height_bucket(feature: Feature) -> str:
    try:
        return f"{float((feature.get('properties') or {}).get('height') or 0.0):.2f}"
    except (TypeError, ValueError):
        return "0.00"


def build_review_replacement_pool(
    *,
    result: list[Feature],
    selected: list[Feature],
    callbacks: RecoveryRefinementCallbacks,
) -> list[Feature]:
    pool = [
        feature for feature in selected
        if feature not in result
        and callbacks.has_review_source_geometry(feature)
        and callbacks.is_reviewable_architectural_mass(feature)
        and not callbacks.is_plain_capacity_anchor(feature)
    ]
    pool.sort(key=callbacks.design_review_quality_key, reverse=True)
    return pool


def enforce_initial_recovery_replacements(
    *,
    result: list[Feature],
    selected: list[Feature],
    callbacks: RecoveryRefinementCallbacks,
    replace_result: Callable[[int, Feature], bool],
    final_limit: int,
    target_formal_principles: set[str],
) -> list[Feature]:
    replacement_pool = build_review_replacement_pool(
        result=result,
        selected=selected,
        callbacks=callbacks,
    )

    guard = 0
    while sum(1 for item in result if callbacks.repair_retention(item) < 0.65) > 2 and guard < final_limit * 2:
        guard += 1
        candidate = next(
            (
                feature for feature in replacement_pool
                if feature not in result
                and callbacks.repair_retention(feature) >= 0.65
                and callbacks.repair_retention(feature, source_volume=True) >= 0.60
            ),
            None,
        )
        if candidate is None:
            break
        severe_indexes = [
            index for index, feature in enumerate(result)
            if final_shape(feature) != "legal_layered_max"
            and callbacks.repair_retention(feature) < 0.65
        ]
        if not severe_indexes:
            break
        replace_index = min(
            severe_indexes,
            key=lambda index: (
                callbacks.repair_retention(result[index]),
                callbacks.repair_retention(result[index], source_volume=True),
                callbacks.design_review_quality_key(result[index]),
            ),
        )
        if not replace_result(replace_index, candidate):
            replacement_pool.remove(candidate)
            continue

    guard = 0
    while guard < final_limit * 2:
        guard += 1
        height_counts = Counter(height_bucket(item) for item in result)
        if not height_counts:
            break
        crowded_height, crowded_count = max(height_counts.items(), key=lambda item: item[1])
        if crowded_count <= 12:
            break
        candidate = next(
            (
                feature for feature in replacement_pool
                if feature not in result
                and height_bucket(feature) != crowded_height
                and callbacks.repair_retention(feature) >= 0.65
            ),
            None,
        )
        if candidate is None:
            break
        replacement_indexes = [
            index for index, feature in enumerate(result)
            if height_bucket(feature) == crowded_height
            and final_shape(feature) != "legal_layered_max"
        ]
        if not replacement_indexes:
            break
        replace_index = min(
            replacement_indexes,
            key=lambda index: (
                callbacks.repair_retention(result[index]),
                callbacks.design_review_quality_key(result[index]),
            ),
        )
        if not replace_result(replace_index, candidate):
            replacement_pool.remove(candidate)
            continue

    guard = 0
    while guard < final_limit * 2:
        guard += 1
        formal_counts = Counter(callbacks.formal_principle(item) for item in result if callbacks.formal_principle(item))
        missing_formals = [
            principle for principle in target_formal_principles
            if formal_counts.get(principle, 0) == 0
        ]
        over_formals = [
            principle for principle, count in formal_counts.items()
            if count > 5
        ]
        if len(formal_counts) >= 6 and not over_formals:
            break
        candidate = next(
            (
                feature for feature in replacement_pool
                if feature not in result
                and callbacks.formal_principle(feature)
                and (
                    callbacks.formal_principle(feature) in missing_formals
                    or formal_counts.get(callbacks.formal_principle(feature), 0) < 2
                )
                and (
                    (
                        callbacks.repair_retention(feature) >= 0.60
                        and callbacks.repair_retention(feature, source_volume=True) >= 0.55
                    )
                    or (
                        callbacks.formal_principle(feature) in missing_formals
                        and sum(1 for item in result if callbacks.repair_retention(item) < 0.65) < 2
                        and callbacks.repair_retention(feature) >= 0.42
                        and callbacks.repair_retention(feature, source_volume=True) >= 0.42
                    )
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
                callbacks.formal_principle(feature) in over_formals
                or formal_counts.get(callbacks.formal_principle(feature), 0) > 2
            )
        ]
        if not replacement_indexes:
            break
        replace_index = min(
            replacement_indexes,
            key=lambda index: (
                callbacks.repair_retention(result[index]),
                callbacks.design_review_quality_key(result[index]),
            ),
        )
        if not replace_result(replace_index, candidate):
            replacement_pool.remove(candidate)
            continue

    return replacement_pool
