"""Final 20-card review refinement for MAAS candidates."""

from __future__ import annotations

from collections import Counter
from typing import Any, Callable

from backend.app.modules.design.generation.maas.selection.constraints import final_mass_stage_parking_pass, final_shape
from backend.app.modules.design.generation.maas.selection.types import Feature, FinalReviewRefinementCallbacks, FinalReviewRefinementPolicy


def final_local_role_pattern(feature: Feature, *, source_signature: Callable[[Feature], dict[str, Any]]) -> str:
    signature = source_signature(feature)
    pattern = signature.get("role_pattern")
    if pattern:
        return str(pattern)
    volumes = (feature.get("properties") or {}).get("mass_volumes")
    if isinstance(volumes, list):
        roles = [
            str(volume.get("role") or "")
            for volume in volumes
            if isinstance(volume, dict) and volume.get("role")
        ]
        return "|".join(roles)
    return ""


def refine_final_review_set(
    selected: list[Feature],
    *,
    legal_candidate_pool: list[Feature],
    final_limit: int,
    preferred_operator: str | None,
    callbacks: FinalReviewRefinementCallbacks,
    policy: FinalReviewRefinementPolicy = FinalReviewRefinementPolicy(),
) -> list[Feature]:
    """Apply final review-set diversity guards without changing legal truth."""
    if preferred_operator or final_limit < 20:
        return selected
    if not selected:
        return selected

    selected_shapes = {final_shape(feature) for feature in selected}
    replacement_pool = [
        feature for feature in legal_candidate_pool
        if final_shape(feature) not in selected_shapes
        and callbacks.is_direct_openai_llm_candidate(feature)
        and callbacks.has_review_source_geometry(feature)
        and callbacks.is_reviewable_architectural_mass(feature)
        and final_mass_stage_parking_pass(feature)
        and not callbacks.is_plain_capacity_anchor(feature)
    ]
    replacement_pool.sort(
        key=lambda feature: (
            1.0 if callbacks.research_mass_language(feature) not in {callbacks.research_mass_language(item) for item in selected} else 0.0,
            1.0 if callbacks.source_family(feature) not in {callbacks.source_family(item) for item in selected} else 0.0,
            1.0 if callbacks.source_signature(feature).get("parameter_default_ratio", 1.0) <= policy.max_parameter_default_ratio else 0.0,
            *callbacks.design_review_quality_key(feature),
        ),
        reverse=True,
    )
    while (
        sum(1 for feature in selected if callbacks.is_direct_openai_llm_candidate(feature)) < policy.min_direct_llm_candidates
        and replacement_pool
    ):
        replace_indexes = [
            index for index, feature in enumerate(selected)
            if not callbacks.is_direct_openai_llm_candidate(feature)
            and not callbacks.is_llm_authored_candidate(feature)
        ]
        if not replace_indexes:
            replace_indexes = [
                index for index, feature in enumerate(selected)
                if not callbacks.is_direct_openai_llm_candidate(feature)
                and final_shape(feature) != "legal_layered_max"
            ]
        if not replace_indexes:
            replace_indexes = [
                index for index, feature in enumerate(selected)
                if not callbacks.is_direct_openai_llm_candidate(feature)
            ]
        if not replace_indexes:
            break
        candidate = replacement_pool.pop(0)
        replace_index = min(
            replace_indexes,
            key=lambda index: (
                1 if callbacks.is_agent_authored_candidate(selected[index]) else 0,
                1 if final_shape(selected[index]) == "legal_layered_max" else 0,
                callbacks.design_review_quality_key(selected[index]),
            ),
        )
        selected[replace_index] = candidate

    height_guard = 0
    while height_guard < final_limit:
        height_guard += 1
        height_counts = Counter(
            round(float((feature.get("properties") or {}).get("height") or 0.0), 2)
            for feature in selected
        )
        dominant_height, dominant_count = max(height_counts.items(), key=lambda item: item[1])
        if dominant_count <= policy.max_dominant_height_count:
            break
        selected_shapes = {final_shape(feature) for feature in selected}
        height_replacement_pool = [
            feature for feature in legal_candidate_pool
            if final_shape(feature) not in selected_shapes
            and callbacks.is_direct_openai_llm_candidate(feature)
            and callbacks.has_review_source_geometry(feature)
            and callbacks.is_reviewable_architectural_mass(feature)
            and final_mass_stage_parking_pass(feature)
            and round(float((feature.get("properties") or {}).get("height") or 0.0), 2) != dominant_height
        ]
        height_replacement_pool.sort(
            key=lambda feature: (
                1.0 if callbacks.research_mass_language(feature) not in {callbacks.research_mass_language(item) for item in selected} else 0.0,
                1.0 if callbacks.source_family(feature) not in {callbacks.source_family(item) for item in selected} else 0.0,
                *callbacks.design_review_quality_key(feature),
            ),
            reverse=True,
        )
        if not height_replacement_pool:
            break
        replace_indexes = [
            index for index, feature in enumerate(selected)
            if round(float((feature.get("properties") or {}).get("height") or 0.0), 2) == dominant_height
            and not callbacks.is_clean_layered_anchor(feature)
            and (
                sum(1 for item in selected if callbacks.is_direct_openai_llm_candidate(item)) > policy.min_direct_llm_candidates
                or callbacks.is_direct_openai_llm_candidate(feature)
            )
        ]
        if not replace_indexes:
            break
        replace_index = min(
            replace_indexes,
            key=lambda index: (
                1 if callbacks.is_direct_openai_llm_candidate(selected[index]) else 0,
                callbacks.design_review_quality_key(selected[index]),
            ),
        )
        selected[replace_index] = height_replacement_pool[0]

    pattern_guard = 0
    while pattern_guard < final_limit:
        pattern_guard += 1
        pattern_counts = Counter(
            final_local_role_pattern(feature, source_signature=callbacks.source_signature)
            for feature in selected
            if final_local_role_pattern(feature, source_signature=callbacks.source_signature)
        )
        repeated_patterns = {
            pattern for pattern, count in pattern_counts.items()
            if pattern and count > policy.max_role_pattern_repeat
        }
        if not repeated_patterns:
            break
        selected_shapes = {final_shape(feature) for feature in selected}
        replacement_pool = [
            feature for feature in legal_candidate_pool
            if final_shape(feature) not in selected_shapes
            and callbacks.is_direct_openai_llm_candidate(feature)
            and callbacks.has_review_source_geometry(feature)
            and callbacks.is_reviewable_architectural_mass(feature)
            and final_mass_stage_parking_pass(feature)
            and final_local_role_pattern(feature, source_signature=callbacks.source_signature) not in repeated_patterns
        ]
        replacement_pool.sort(
            key=lambda feature: (
                1.0 if callbacks.research_mass_language(feature) not in {callbacks.research_mass_language(item) for item in selected} else 0.0,
                1.0 if callbacks.source_family(feature) not in {callbacks.source_family(item) for item in selected} else 0.0,
                *callbacks.design_review_quality_key(feature),
            ),
            reverse=True,
        )
        if not replacement_pool:
            break
        replace_indexes = [
            index for index, feature in enumerate(selected)
            if final_local_role_pattern(feature, source_signature=callbacks.source_signature) in repeated_patterns
            and not callbacks.is_clean_layered_anchor(feature)
        ]
        if not replace_indexes:
            break
        replace_index = min(
            replace_indexes,
            key=lambda index: (
                0 if callbacks.is_direct_openai_llm_candidate(selected[index]) else 1,
                callbacks.design_review_quality_key(selected[index]),
            ),
        )
        selected[replace_index] = replacement_pool[0]

    language_guard = 0
    while language_guard < final_limit * 2:
        language_guard += 1
        language_counts = Counter(callbacks.research_mass_language(feature) for feature in selected if callbacks.research_mass_language(feature))
        family_counts = Counter(callbacks.source_family(feature) for feature in selected if callbacks.source_family(feature))
        crowded_languages = {
            language for language, count in language_counts.items()
            if language and count > policy.max_language_repeat
        }
        enough_diversity = (
            len(language_counts) >= policy.min_research_language_diversity
            and len(family_counts) >= policy.min_source_family_diversity
            and not crowded_languages
        )
        if enough_diversity:
            break
        selected_shapes = {final_shape(feature) for feature in selected}
        missing_language_bonus = {
            callbacks.research_mass_language(feature)
            for feature in legal_candidate_pool
            if callbacks.research_mass_language(feature)
        } - set(language_counts)
        missing_family_bonus = {
            callbacks.source_family(feature)
            for feature in legal_candidate_pool
            if callbacks.source_family(feature)
        } - set(family_counts)
        diversity_pool = [
            feature for feature in legal_candidate_pool
            if final_shape(feature) not in selected_shapes
            and callbacks.is_direct_openai_llm_candidate(feature)
            and callbacks.has_review_source_geometry(feature)
            and callbacks.is_reviewable_architectural_mass(feature)
            and final_mass_stage_parking_pass(feature)
            and (
                callbacks.research_mass_language(feature) in missing_language_bonus
                or callbacks.source_family(feature) in missing_family_bonus
                or language_counts.get(callbacks.research_mass_language(feature), 0) < policy.max_language_repeat
            )
        ]
        diversity_pool.sort(
            key=lambda feature: (
                1.0 if callbacks.research_mass_language(feature) in missing_language_bonus else 0.0,
                1.0 if callbacks.source_family(feature) in missing_family_bonus else 0.0,
                -language_counts.get(callbacks.research_mass_language(feature), 0),
                -family_counts.get(callbacks.source_family(feature), 0),
                *callbacks.design_review_quality_key(feature),
            ),
            reverse=True,
        )
        if not diversity_pool:
            break
        replace_indexes = [
            index for index, feature in enumerate(selected)
            if not callbacks.is_clean_layered_anchor(feature)
            and (
                callbacks.research_mass_language(feature) in crowded_languages
                or language_counts.get(callbacks.research_mass_language(feature), 0) > 1
                or family_counts.get(callbacks.source_family(feature), 0) > 1
                or not callbacks.is_direct_openai_llm_candidate(feature)
            )
        ]
        if not replace_indexes:
            break
        candidate = diversity_pool[0]
        replace_index = min(
            replace_indexes,
            key=lambda index: (
                0 if callbacks.research_mass_language(selected[index]) in crowded_languages else 1,
                0 if not callbacks.is_direct_openai_llm_candidate(selected[index]) else 1,
                callbacks.design_review_quality_key(selected[index]),
            ),
        )
        selected[replace_index] = candidate

    return selected
