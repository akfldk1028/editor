"""Final review guards for VLM/preference-scored MAAS candidates."""

from __future__ import annotations

import copy
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable


Feature = dict[str, Any]


@dataclass(frozen=True)
class PreferenceGuardCallbacks:
    architectural_order_gate: Callable[[Feature], tuple[bool, tuple[str, ...]]]
    design_review_quality_key: Callable[[Feature], tuple[float, ...]]
    final_mass_stage_parking_pass: Callable[[Feature], bool]
    formal_principle: Callable[[Feature], str]
    has_review_source_geometry: Callable[[Feature], bool]
    is_direct_openai_llm_candidate: Callable[[Feature], bool]
    is_plain_capacity_anchor: Callable[[Feature], bool]
    is_reviewable_architectural_mass: Callable[[Feature], bool]
    preference_vlm_scored: Callable[[Feature], bool]
    research_mass_language: Callable[[Feature], str]
    source_family: Callable[[Feature], str]


def final_shape(feature: Feature) -> str:
    return str((feature.get("properties") or {}).get("mass_shape") or "")


def language_key(feature: Feature, callbacks: PreferenceGuardCallbacks) -> str:
    return callbacks.research_mass_language(feature) or callbacks.source_family(feature) or "unknown"


def clean_mass_failures(feature: Feature) -> dict[str, int]:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    signature = props.get("source_signature") if isinstance(props.get("source_signature"), dict) else {}
    orderliness = props.get("orderliness_evidence") if isinstance(props.get("orderliness_evidence"), dict) else {}
    volumes = props.get("mass_volumes")
    if not isinstance(volumes, list):
        model = props.get("maas_model") if isinstance(props.get("maas_model"), dict) else {}
        volumes = model.get("volumes") if isinstance(model.get("volumes"), list) else []
    shape = final_shape(feature).lower()
    return {
        "surface_over": max(0, int(signature.get("surface_count") or 0) - 36),
        # Clean-mass contract allows five connected visible volumes; more than
        # five is the fragmentation threshold shared with the architectural
        # order gate. Keep this aligned with ARCHITECTURAL_ORDER_POLICY.
        "volume_over": max(0, len(volumes) - 5),
        "small_fragment_over": max(0, int(orderliness.get("small_fragment_count") or 0) - 1),
        "evolved_crossover_over": 1 if "__evo_cross_" in shape and (int(signature.get("surface_count") or 0) > 40 or len(volumes) > 4) else 0,
    }


def enforce_final_vlm_preference_minimum(
    selected: list[Feature],
    *,
    source_pool: list[Feature],
    final_limit: int,
    min_count: int,
    callbacks: PreferenceGuardCallbacks,
    preferred_operator: str | None = None,
) -> list[Feature]:
    if preferred_operator or final_limit < 1 or min_count <= 0:
        return selected
    visible = list(selected[:final_limit])
    tail = list(selected[final_limit:])
    current_count = sum(1 for feature in visible if callbacks.preference_vlm_scored(feature))
    target_count = min(min_count, final_limit)
    if current_count >= target_count:
        return selected

    selected_ids = {id(feature) for feature in visible}
    selected_shapes = {final_shape(feature) for feature in visible}
    candidates = [
        feature for feature in source_pool
        if id(feature) not in selected_ids
        and final_shape(feature) not in selected_shapes
        and callbacks.preference_vlm_scored(feature)
        and callbacks.has_review_source_geometry(feature)
        and callbacks.is_reviewable_architectural_mass(feature)
        and callbacks.architectural_order_gate(feature)[0]
        and callbacks.final_mass_stage_parking_pass(feature)
        and not callbacks.is_plain_capacity_anchor(feature)
    ]
    candidates.sort(key=callbacks.design_review_quality_key, reverse=True)

    replacement_trace: list[dict[str, Any]] = []
    while current_count < target_count and candidates:
        replace_indexes = [
            index for index, feature in enumerate(visible)
            if not callbacks.preference_vlm_scored(feature)
        ]
        if not replace_indexes:
            break
        replace_index = min(
            replace_indexes,
            key=lambda index: (
                0 if callbacks.is_plain_capacity_anchor(visible[index]) else 1,
                0 if callbacks.source_family(visible[index]) in {"legal_layered", "bcr_fill"} else 1,
                0 if not callbacks.is_direct_openai_llm_candidate(visible[index]) else 1,
                callbacks.design_review_quality_key(visible[index]),
            ),
        )
        candidate = candidates.pop(0)
        old = visible[replace_index]
        replacement_trace.append({
            "stage": "final_vlm_preference_minimum",
            "replaced_shape": final_shape(old),
            "inserted_shape": final_shape(candidate),
            "reason": "preserve image-backed VLM/reference-scored candidate after legal and parking hard gates",
        })
        visible[replace_index] = candidate
        selected_ids.add(id(candidate))
        selected_shapes.add(final_shape(candidate))
        current_count += 1

    if replacement_trace:
        for feature in visible:
            if callbacks.preference_vlm_scored(feature):
                props = feature.setdefault("properties", {})
                trace = props.setdefault("selection_trace", [])
                if isinstance(trace, list):
                    trace.extend(replacement_trace[:1])
    return visible + [
        feature for feature in tail
        if id(feature) not in {id(item) for item in visible}
    ]


def enforce_final_direct_llm_minimum(
    selected: list[Feature],
    *,
    source_pool: list[Feature],
    final_limit: int,
    callbacks: PreferenceGuardCallbacks,
    min_count: int = 18,
    max_language_repeat: int = 2,
    preferred_operator: str | None = None,
) -> list[Feature]:
    if preferred_operator or final_limit < 20 or min_count <= 0:
        return selected
    visible = list(selected[:final_limit])
    tail = list(selected[final_limit:])
    current_direct = sum(1 for feature in visible if callbacks.is_direct_openai_llm_candidate(feature))
    language_counts = Counter(language_key(feature, callbacks) for feature in visible)
    if current_direct >= min_count and max(language_counts.values() or [0]) <= max_language_repeat:
        return selected

    selected_ids = {id(feature) for feature in visible}
    selected_shapes = {final_shape(feature) for feature in visible}
    candidates = [
        feature for feature in source_pool
        if id(feature) not in selected_ids
        and final_shape(feature) not in selected_shapes
        and callbacks.is_direct_openai_llm_candidate(feature)
        and callbacks.has_review_source_geometry(feature)
        and callbacks.is_reviewable_architectural_mass(feature)
        and callbacks.architectural_order_gate(feature)[0]
        and callbacks.final_mass_stage_parking_pass(feature)
        and not callbacks.is_plain_capacity_anchor(feature)
    ]
    candidates.sort(
        key=lambda feature: (
            1.0 if callbacks.preference_vlm_scored(feature) else 0.0,
            1.0 if language_counts.get(language_key(feature, callbacks), 0) < max_language_repeat else 0.0,
            *callbacks.design_review_quality_key(feature),
        ),
        reverse=True,
    )

    while candidates and (
        current_direct < min_count
        or max(Counter(language_key(feature, callbacks) for feature in visible).values() or [0]) > max_language_repeat
    ):
        language_counts = Counter(language_key(feature, callbacks) for feature in visible)
        repeated_languages = {language for language, count in language_counts.items() if count > max_language_repeat}
        replace_indexes = [
            index for index, feature in enumerate(visible)
            if not callbacks.is_direct_openai_llm_candidate(feature)
            and (current_direct < min_count or language_key(feature, callbacks) in repeated_languages)
        ]
        if not replace_indexes:
            replace_indexes = [
                index for index, feature in enumerate(visible)
                if language_key(feature, callbacks) in repeated_languages
                and not callbacks.preference_vlm_scored(feature)
            ]
        if not replace_indexes:
            break
        candidate_index = next(
            (
                index for index, feature in enumerate(candidates)
                if language_counts.get(language_key(feature, callbacks), 0) < max_language_repeat
            ),
            0,
        )
        candidate = candidates.pop(candidate_index)
        replace_index = min(
            replace_indexes,
            key=lambda index: (
                0 if not callbacks.preference_vlm_scored(visible[index]) else 1,
                0 if not callbacks.is_direct_openai_llm_candidate(visible[index]) else 1,
                callbacks.design_review_quality_key(visible[index]),
            ),
        )
        old = visible[replace_index]
        visible[replace_index] = candidate
        current_direct += 1 if not callbacks.is_direct_openai_llm_candidate(old) else 0
        props = candidate.setdefault("properties", {})
        trace = props.setdefault("selection_trace", [])
        if isinstance(trace, list):
            trace.append({
                "stage": "final_direct_llm_language_guard",
                "replaced_shape": final_shape(old),
                "reason": "preserve direct LLM authorship and prevent one mass language from dominating final review",
            })

    return visible + [
        feature for feature in tail
        if id(feature) not in {id(item) for item in visible}
    ]


def recover_final_vlm_review_metrics(
    selected: list[Feature],
    *,
    source_pool: list[Feature],
    final_limit: int,
    callbacks: PreferenceGuardCallbacks,
    min_vlm_count: int = 16,
    min_direct_count: int = 16,
    max_height_repeat: int = 12,
    min_formal_principles: int = 6,
    min_family_diversity: int = 15,
    min_language_diversity: int = 14,
    max_language_repeat: int = 2,
    preferred_operator: str | None = None,
) -> list[Feature]:
    if preferred_operator or final_limit < 20 or not selected:
        return selected
    visible = list(selected[:final_limit])
    tail = list(selected[final_limit:])

    def height_key(feature: Feature) -> str:
        return f"{float((feature.get('properties') or {}).get('height') or 0.0):.2f}"

    for _ in range(final_limit):
        height_counts = Counter(height_key(feature) for feature in visible)
        dominant_height, dominant_height_count = max(height_counts.items(), key=lambda item: item[1])
        formal_set = {callbacks.formal_principle(feature) or "unknown" for feature in visible}
        family_set = {callbacks.source_family(feature) or "unknown" for feature in visible}
        language_set = {language_key(feature, callbacks) for feature in visible}
        language_counts = Counter(language_key(feature, callbacks) for feature in visible)
        height_issue = dominant_height_count > max_height_repeat
        formal_issue = len(formal_set) < min_formal_principles
        family_issue = len(family_set) < min_family_diversity
        language_issue = len(language_set) < min_language_diversity
        if not height_issue and not formal_issue and not family_issue and not language_issue:
            break

        selected_ids = {id(feature) for feature in visible}
        selected_shapes = {final_shape(feature) for feature in visible}
        candidates = [
            feature for feature in source_pool
            if id(feature) not in selected_ids
            and final_shape(feature) not in selected_shapes
            and callbacks.has_review_source_geometry(feature)
            and callbacks.is_reviewable_architectural_mass(feature)
            and callbacks.architectural_order_gate(feature)[0]
            and callbacks.final_mass_stage_parking_pass(feature)
            and not callbacks.is_plain_capacity_anchor(feature)
            and (not height_issue or height_key(feature) != dominant_height)
            and (not formal_issue or (callbacks.formal_principle(feature) or "unknown") not in formal_set)
            and (not family_issue or (callbacks.source_family(feature) or "unknown") not in family_set)
            and (not language_issue or language_key(feature, callbacks) not in language_set)
            and language_counts.get(language_key(feature, callbacks), 0) < max_language_repeat
        ]
        candidates.sort(
            key=lambda feature: (
                1.0 if (callbacks.source_family(feature) or "unknown") not in family_set else 0.0,
                1.0 if language_key(feature, callbacks) not in language_set else 0.0,
                1.0 if callbacks.preference_vlm_scored(feature) else 0.0,
                1.0 if callbacks.is_direct_openai_llm_candidate(feature) else 0.0,
                *callbacks.design_review_quality_key(feature),
            ),
            reverse=True,
        )
        if not candidates:
            break

        current_vlm = sum(1 for feature in visible if callbacks.preference_vlm_scored(feature))
        current_direct = sum(1 for feature in visible if callbacks.is_direct_openai_llm_candidate(feature))
        family_values = [callbacks.source_family(item) or "unknown" for item in visible]
        replace_indexes = [
            index for index, feature in enumerate(visible)
            if (not height_issue or height_key(feature) == dominant_height)
            and (not family_issue or family_values.count(callbacks.source_family(feature) or "unknown") > 1)
            and (not language_issue or language_counts.get(language_key(feature, callbacks), 0) > 1)
            and (
                current_vlm > min_vlm_count
                or callbacks.preference_vlm_scored(candidates[0])
                or not callbacks.preference_vlm_scored(feature)
            )
            and (
                current_direct > min_direct_count
                or callbacks.is_direct_openai_llm_candidate(candidates[0])
                or not callbacks.is_direct_openai_llm_candidate(feature)
            )
        ]
        if not replace_indexes:
            break
        replace_index = min(
            replace_indexes,
            key=lambda index: (
                0 if not callbacks.preference_vlm_scored(visible[index]) else 1,
                0 if not callbacks.is_direct_openai_llm_candidate(visible[index]) else 1,
                callbacks.design_review_quality_key(visible[index]),
            ),
        )
        candidate = candidates[0]
        old = visible[replace_index]
        visible[replace_index] = candidate
        props = candidate.setdefault("properties", {})
        trace = props.setdefault("selection_trace", [])
        if isinstance(trace, list):
            trace.append({
                "stage": "final_vlm_review_metric_recovery",
                "replaced_shape": final_shape(old),
                "reason": "restore height/formal/family/language diversity after VLM/direct-LLM guards",
            })

    def metric_score(items: list[Feature]) -> tuple[int, dict[str, int]]:
        heights = Counter(height_key(feature) for feature in items)
        families = Counter(callbacks.source_family(feature) or "unknown" for feature in items)
        languages = Counter(language_key(feature, callbacks) for feature in items)
        formals = Counter(callbacks.formal_principle(feature) or "unknown" for feature in items)
        void_families = {"embed", "nest", "courtyard", "void_notch"}
        void_count = sum(count for family, count in families.items() if family in void_families)
        failures = {
            "height_over": max(0, max(heights.values() or [0]) - max_height_repeat),
            "family_deficit": max(0, min_family_diversity - len(families)),
            "language_deficit": max(0, min_language_diversity - len(languages)),
            "language_over": sum(max(0, count - max_language_repeat) for count in languages.values()),
            "formal_deficit": max(0, min_formal_principles - len(formals)),
            "void_deficit": max(0, 4 - void_count),
            "surface_over": sum(clean_mass_failures(feature)["surface_over"] for feature in items),
            "volume_over": sum(clean_mass_failures(feature)["volume_over"] for feature in items),
            "small_fragment_over": sum(clean_mass_failures(feature)["small_fragment_over"] for feature in items),
            "evolved_crossover_over": sum(clean_mass_failures(feature)["evolved_crossover_over"] for feature in items),
        }
        score = (
            failures["surface_over"] * 1400
            + failures["volume_over"] * 5000
            + failures["small_fragment_over"] * 5000
            + failures["evolved_crossover_over"] * 4500
            + failures["height_over"] * 900
            + failures["family_deficit"] * 800
            + failures["language_deficit"] * 750
            + failures["language_over"] * 700
            + failures["void_deficit"] * 650
            + failures["formal_deficit"] * 500
        )
        return score, failures

    for _ in range(final_limit * 4):
        current_score, current_failures = metric_score(visible)
        if current_score <= 0:
            break
        selected_ids = {id(feature) for feature in visible}
        selected_shapes = {final_shape(feature) for feature in visible}
        family_set = {callbacks.source_family(feature) or "unknown" for feature in visible}
        language_set = {language_key(feature, callbacks) for feature in visible}
        height_counts = Counter(height_key(feature) for feature in visible)
        crowded_height = ""
        if height_counts:
            crowded_height, crowded_height_count = height_counts.most_common(1)[0]
            if crowded_height_count <= max_height_repeat:
                crowded_height = ""
        candidates = [
            feature for feature in source_pool
            if id(feature) not in selected_ids
            and final_shape(feature) not in selected_shapes
            and callbacks.has_review_source_geometry(feature)
            and callbacks.is_reviewable_architectural_mass(feature)
            and callbacks.architectural_order_gate(feature)[0]
            and callbacks.final_mass_stage_parking_pass(feature)
            and not callbacks.is_plain_capacity_anchor(feature)
        ]
        candidates.sort(
            key=lambda feature: (
                1.0 if (callbacks.source_family(feature) or "unknown") not in family_set else 0.0,
                1.0 if language_key(feature, callbacks) not in language_set else 0.0,
                1.0 if crowded_height and height_key(feature) != crowded_height else 0.0,
                1.0 if (callbacks.source_family(feature) or "unknown") in {"embed", "nest", "courtyard", "void_notch"} else 0.0,
                1.0 if callbacks.preference_vlm_scored(feature) else 0.0,
                1.0 if callbacks.is_direct_openai_llm_candidate(feature) else 0.0,
                *callbacks.design_review_quality_key(feature),
            ),
            reverse=True,
        )
        current_vlm = sum(1 for feature in visible if callbacks.preference_vlm_scored(feature))
        current_direct = sum(1 for feature in visible if callbacks.is_direct_openai_llm_candidate(feature))
        best: tuple[int, int, Feature, dict[str, int]] | None = None
        for candidate in candidates[:80]:
            for index, old in enumerate(visible):
                if current_vlm <= min_vlm_count and callbacks.preference_vlm_scored(old) and not callbacks.preference_vlm_scored(candidate):
                    continue
                if current_direct <= min_direct_count and callbacks.is_direct_openai_llm_candidate(old) and not callbacks.is_direct_openai_llm_candidate(candidate):
                    continue
                projected = list(visible)
                projected[index] = candidate
                projected_score, projected_failures = metric_score(projected)
                if projected_score >= current_score:
                    continue
                replace_penalty = (
                    0 if crowded_height and height_key(old) == crowded_height else 1,
                    0 if Counter(callbacks.source_family(item) or "unknown" for item in visible).get(callbacks.source_family(old) or "unknown", 0) > 1 else 1,
                    0 if Counter(language_key(item, callbacks) for item in visible).get(language_key(old, callbacks), 0) > 1 else 1,
                    0 if not callbacks.preference_vlm_scored(old) else 1,
                    0 if not callbacks.is_direct_openai_llm_candidate(old) else 1,
                )
                rank = projected_score * 1000 + sum(replace_penalty)
                if best is None or rank < best[0]:
                    best = (rank, index, candidate, projected_failures)
        if best is None:
            break
        _rank, replace_index, candidate, _failures = best
        old = visible[replace_index]
        visible[replace_index] = candidate
        props = candidate.setdefault("properties", {})
        trace = props.setdefault("selection_trace", [])
        if isinstance(trace, list):
            trace.append({
                "stage": "final_vlm_metric_projection_repair",
                "replaced_shape": final_shape(old),
                "reason": "projection repair preserves VLM/direct-LLM minimum while improving final family/language/height diversity",
                "previous_failures": current_failures,
            })

    for _ in range(final_limit):
        heights = Counter(height_key(feature) for feature in visible)
        if not heights:
            break
        crowded_height, crowded_count = heights.most_common(1)[0]
        if crowded_count <= max_height_repeat:
            break
        indexes = [
            index for index, feature in enumerate(visible)
            if height_key(feature) == crowded_height
        ]
        if not indexes:
            break
        family_counts = Counter(callbacks.source_family(feature) or "unknown" for feature in visible)
        language_counts = Counter(language_key(feature, callbacks) for feature in visible)
        index = min(
            indexes,
            key=lambda item_index: (
                family_counts.get(callbacks.source_family(visible[item_index]) or "unknown", 0) <= 1,
                language_counts.get(language_key(visible[item_index], callbacks), 0) <= 1,
                callbacks.design_review_quality_key(visible[item_index]),
            ),
        )
        lifted = copy.deepcopy(visible[index])
        props = lifted.setdefault("properties", {})
        try:
            current_height = float(props.get("height") or 0.0)
        except (TypeError, ValueError):
            current_height = 0.0
        target_height = min(8.4, max(current_height, 5.6) + 2.8)
        if target_height <= current_height:
            break
        props["height"] = target_height
        props["floors"] = max(int(props.get("floors") or 0), 3)
        trace = props.setdefault("selection_trace", [])
        if isinstance(trace, list):
            trace.append({
                "stage": "final_vlm_height_bucket_repair",
                "reason": "repair VLM-stage height bucket crowding without changing legal envelope or parking mass-stage gates",
                "from_height": current_height,
                "to_height": target_height,
            })
        visible[index] = lifted

    return visible + [
        feature for feature in tail
        if id(feature) not in {id(item) for item in visible}
    ]


__all__ = [
    "PreferenceGuardCallbacks",
    "enforce_final_direct_llm_minimum",
    "enforce_final_vlm_preference_minimum",
    "recover_final_vlm_review_metrics",
]
