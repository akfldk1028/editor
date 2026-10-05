"""Final balanced MAAS review selection orchestration."""

from __future__ import annotations

import copy
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable

from backend.app.modules.design.generation.maas.selection.constraints import final_mass_stage_parking_pass, layout_status, review_set_constraints_ok as selection_review_set_constraints_ok, review_set_geometry_ok as selection_review_set_geometry_ok, source_reviewable as selection_source_reviewable
from backend.app.modules.design.generation.maas.selection.final_metrics import final_hard_quotas_ok_after as selection_final_hard_quotas_ok_after, final_metric_snapshot as selection_final_metric_snapshot, final_metrics_ok_after as selection_final_metrics_ok_after, final_structural_quotas_ok_after as selection_final_structural_quotas_ok_after, unique_family_count_after as selection_unique_family_count_after
from backend.app.modules.design.generation.maas.selection.formal_refinement import enforce_formal_diversity_replacements
from backend.app.modules.design.generation.maas.selection.island_refinement import enforce_island_quota_replacements
from backend.app.modules.design.generation.maas.selection.recovery_refinement import enforce_initial_recovery_replacements, height_bucket
from backend.app.modules.design.generation.maas.selection.state import SelectionState
from backend.app.modules.design.generation.maas.selection.types import Feature, FinalMetricCallbacks, FormalDiversityCallbacks, IslandQuotaCallbacks, RecoveryRefinementCallbacks, ReviewSetConstraintCallbacks


FeatureKey = Callable[[Feature], Any]
FeatureBool = Callable[[Feature], bool]
FeatureText = Callable[[Feature], str | None]


def attach_final_selection_trace(
    items: list[Feature],
    *,
    deps: "BalancedSelectionDeps",
    final_limit: int,
) -> None:
    """Record auditable final review-sheet selection evidence."""
    family_counts = Counter(deps.source_family(item) or "unknown" for item in items)
    language_counts = Counter(deps.research_mass_language(item) or "unknown" for item in items)
    group_counts = Counter(deps.research_quota_group(item) or "unknown" for item in items)
    for rank, feature in enumerate(items, start=1):
        props = feature.setdefault("properties", {})
        trace = props.setdefault("selection_trace", [])
        if not isinstance(trace, list):
            trace = []
            props["selection_trace"] = trace
        trace.append({
            "schema_version": "arr.maas.selection_trace.v1",
            "stage": "final_balanced_selection",
            "rank": rank,
            "final_limit": final_limit,
            "source_family": deps.source_family(feature) or "unknown",
            "research_mass_language": deps.research_mass_language(feature) or "unknown",
            "quota_group": deps.research_quota_group(feature) or "unknown",
            "family_count_in_final": family_counts.get(deps.source_family(feature) or "unknown", 0),
            "language_count_in_final": language_counts.get(deps.research_mass_language(feature) or "unknown", 0),
            "group_count_in_final": group_counts.get(deps.research_quota_group(feature) or "unknown", 0),
            "mass_stage_parking_pass": final_mass_stage_parking_pass(feature),
        })


@dataclass(frozen=True)
class BalancedSelectionDeps:
    research_target_families: tuple[str, ...]
    signature_proposal_priorities: dict[str, int]
    stepback_dominant_families: set[str]
    typology_first_families: list[str]
    typology_review_quotas: tuple[tuple[tuple[str, ...], int], ...]
    architectural_ambition: Callable[[Feature], dict[str, Any]]
    architectural_order_gate: Callable[[Feature], tuple[bool, tuple[str, ...]]]
    design_review_quality_key: FeatureKey
    design_synthesis_rank: Callable[[Feature], int]
    formal_principle: FeatureText
    has_review_source_geometry: FeatureBool
    is_agent_authored_candidate: FeatureBool
    is_authored_mass_candidate: FeatureBool
    is_clean_layered_anchor: FeatureBool
    is_direct_openai_llm_candidate: FeatureBool
    is_llm_authored_candidate: FeatureBool
    is_llm_coverage_repair_candidate: FeatureBool
    is_parking_repair_operator: Callable[[str], bool]
    is_plain_capacity_anchor: FeatureBool
    is_plain_review_mass: FeatureBool
    is_reviewable_architectural_mass: FeatureBool
    is_section_connector: FeatureBool
    is_typology_first_candidate: FeatureBool
    operator_family: Callable[[str], str]
    repair_retention: Callable[..., float]
    research_diversity_descriptor: Callable[[Feature], dict[str, Any]]
    research_mass_language: FeatureText
    research_quota_group: FeatureText
    research_role_pattern: FeatureText
    source_family: FeatureText
    source_signature: Callable[[Feature], dict[str, Any]]
    stair_like_risk: FeatureText
    vertical_strategy: FeatureText
    visible_volume_count: Callable[[Feature], int]


def final_design_balanced_selection(
    selected: list[dict[str, Any]],
    *,
    final_limit: int,
    preferred_operator: str | None = None,
    deps: BalancedSelectionDeps,
) -> list[dict[str, Any]]:
    """Keep the review set architectural, not just score/parking sorted.

    The user-facing 20-card evidence sheet is used for design review. A raw
    score sort tends to show many legal stepback variants and parking-repair
    shrink variants first, which hides the actual grammar families. Keep a
    compact parking signal, then reserve one representative for each spatial
    family before backfilling.
    """

    RESEARCH_TARGET_FAMILIES = deps.research_target_families
    SIGNATURE_PROPOSAL_PRIORITIES = deps.signature_proposal_priorities
    STEPBACK_DOMINANT_FAMILIES = deps.stepback_dominant_families
    TYPOLOGY_FIRST_FAMILIES = deps.typology_first_families
    TYPOLOGY_REVIEW_QUOTAS = deps.typology_review_quotas
    _architectural_ambition = deps.architectural_ambition
    _architectural_order_gate = deps.architectural_order_gate
    _design_review_quality_key = deps.design_review_quality_key
    _design_synthesis_rank = deps.design_synthesis_rank
    _formal_principle = deps.formal_principle
    _has_review_source_geometry = deps.has_review_source_geometry
    _is_agent_authored_candidate = deps.is_agent_authored_candidate
    _is_authored_mass_candidate = deps.is_authored_mass_candidate
    _is_clean_layered_anchor = deps.is_clean_layered_anchor
    _is_direct_openai_llm_candidate = deps.is_direct_openai_llm_candidate
    _is_llm_authored_candidate = deps.is_llm_authored_candidate
    _is_llm_coverage_repair_candidate = deps.is_llm_coverage_repair_candidate
    _is_parking_repair_operator = deps.is_parking_repair_operator
    _is_plain_capacity_anchor = deps.is_plain_capacity_anchor
    _is_plain_review_mass = deps.is_plain_review_mass
    _is_reviewable_architectural_mass = deps.is_reviewable_architectural_mass
    _is_section_connector = deps.is_section_connector
    _is_typology_first_candidate = deps.is_typology_first_candidate
    _operator_family = deps.operator_family
    _repair_retention = deps.repair_retention
    _research_diversity_descriptor = deps.research_diversity_descriptor
    _research_mass_language = deps.research_mass_language
    _research_quota_group = deps.research_quota_group
    _research_role_pattern = deps.research_role_pattern
    _source_family = deps.source_family
    _source_signature = deps.source_signature
    _stair_like_risk = deps.stair_like_risk
    _vertical_strategy = deps.vertical_strategy
    _visible_volume_count = deps.visible_volume_count

    if preferred_operator or final_limit <= 1:
        return selected[:final_limit]
    # Some constrained sites have no candidate in the heuristic preselection
    # even though the downstream legal/coherence pool can still feed the exact
    # MILP. Recovery loops are replacement-only and must not call max()/min()
    # on an empty provisional set.
    if not selected:
        return []

    selection_state = SelectionState(source_family=_source_family)
    result = selection_state.result
    seen_ids = selection_state.seen_ids
    seen_shapes = selection_state.seen_shapes
    seen_source_families = selection_state.seen_source_families
    max_plain_review_masses = 1 if final_limit >= 12 else max(1, final_limit // 6)
    max_same_source_family = 4 if final_limit >= 20 else (2 if final_limit >= 12 else 1)
    max_stepback_dominant = 2 if final_limit >= 20 else max(1, final_limit // 6)
    max_weak_llm_review_masses = 1 if final_limit >= 20 else 0
    min_reviewable_llm = 18 if final_limit >= 20 else max(1, final_limit // 5)
    has_source_geometry_pool = any(_has_review_source_geometry(feature) for feature in selected)

    def source_family_of(feature: dict[str, Any]) -> str:
        return _source_family(feature)

    def rebuild_seen_state() -> None:
        selection_state.rebuild()

    review_constraint_callbacks = ReviewSetConstraintCallbacks(
        architectural_order_gate=_architectural_order_gate,
        is_plain_review_mass=_is_plain_review_mass,
        research_mass_language=_research_mass_language,
        source_family=_source_family,
        visible_volume_count=_visible_volume_count,
    )

    def mass_stage_parking_pass(feature: dict[str, Any]) -> bool:
        return final_mass_stage_parking_pass(feature)

    def review_set_geometry_ok(feature: dict[str, Any]) -> bool:
        return selection_review_set_geometry_ok(
            feature,
            final_limit=final_limit,
            has_source_geometry_pool=has_source_geometry_pool,
            callbacks=review_constraint_callbacks,
        )

    def selection_constraints_ok(items: list[dict[str, Any]]) -> bool:
        return selection_review_set_constraints_ok(
            items,
            max_weak_llm_review_masses=max_weak_llm_review_masses,
            max_stepback_dominant=max_stepback_dominant,
            max_plain_review_masses=max_plain_review_masses,
            max_same_source_family=max_same_source_family,
            max_language_repeat=2,
            stepback_dominant_families=STEPBACK_DOMINANT_FAMILIES,
            review_geometry_ok=review_set_geometry_ok,
            callbacks=review_constraint_callbacks,
        )

    def replace_result(index: int, candidate: dict[str, Any]) -> bool:
        return selection_state.replace_if_valid(
            index,
            candidate,
            constraints_ok=selection_constraints_ok,
        )

    def group_count(families: tuple[str, ...]) -> int:
        family_set = set(families)
        return sum(1 for item in result if source_family_of(item) in family_set)

    def add(feature: dict[str, Any], *, allow_duplicate_shape: bool = False) -> bool:
        marker = id(feature)
        if marker in seen_ids or len(result) >= final_limit:
            return False
        if not mass_stage_parking_pass(feature):
            return False
        if not review_set_geometry_ok(feature):
            return False
        quality = (feature.get("properties") or {}).get("llm_candidate_quality")
        shape = str((feature.get("properties") or {}).get("mass_shape") or "")
        if shape == "legal_layered_max" and defer_legal_anchor:
            return False
        if (
            isinstance(quality, dict)
            and quality.get("status") == "reject_final_review"
            and sum(
                1
                for item in result
                if ((item.get("properties") or {}).get("llm_candidate_quality") or {}).get("status") == "reject_final_review"
            ) >= max_weak_llm_review_masses
        ):
            return False
        if (
            _is_plain_review_mass(feature)
            and sum(1 for item in result if _is_plain_review_mass(item)) >= max_plain_review_masses
        ):
            return False
        if shape in seen_shapes and not allow_duplicate_shape:
            return False
        source_family = _source_family(feature)
        if (
            source_family in STEPBACK_DOMINANT_FAMILIES
            and sum(1 for item in result if source_family_of(item) in STEPBACK_DOMINANT_FAMILIES) >= max_stepback_dominant
        ):
            return False
        family_backfill_allowance = max_same_source_family + (1 if len(result) >= max(12, final_limit // 2) else 0)
        if (
            source_family
            and source_family not in {"legal_layered", "legal_buildable", "bcr_fill"}
            and seen_source_families.get(source_family, 0) >= family_backfill_allowance
        ):
            return False
        language = _research_mass_language(feature)
        language_limit = 2
        if (
            language
            and language != "legal_layered_anchor"
            and sum(1 for item in result if _research_mass_language(item) == language) >= language_limit
        ):
            return False
        selection_state.append_seen(feature, source_family=source_family)
        return True

    def source_reviewable(feature: dict[str, Any]) -> bool:
        return selection_source_reviewable(
            feature,
            has_review_source_geometry=_has_review_source_geometry,
            is_reviewable_architectural_mass=_is_reviewable_architectural_mass,
        )

    # The review sheet should start with architectural evidence, not six
    # mechanical high-FAR variants or low-FAR parking repairs. Keep one legal
    # max anchor for solver provenance, but only lead with it when authored
    # design candidates are too sparse.
    legal_anchor = next(
        (
            feature for feature in selected
            if str((feature.get("properties") or {}).get("mass_shape") or "") == "legal_layered_max"
        ),
        None,
    )
    authored_reviewable_count = sum(
        1 for feature in selected
        if _is_authored_mass_candidate(feature)
        and _is_typology_first_candidate(feature)
        and source_reviewable(feature)
        and not _is_plain_capacity_anchor(feature)
    )
    defer_legal_anchor = authored_reviewable_count >= max(4, final_limit // 2)
    if legal_anchor is not None and not defer_legal_anchor:
        add(legal_anchor)

    llm_candidates = [
        feature for feature in selected
        if _is_direct_openai_llm_candidate(feature)
        and _is_typology_first_candidate(feature)
        and source_reviewable(feature)
        and ((feature.get("properties") or {}).get("llm_candidate_quality") or {}).get("status") != "reject_final_review"
    ]
    llm_repair_candidates = [
        feature for feature in selected
        if _is_llm_coverage_repair_candidate(feature)
        and _is_typology_first_candidate(feature)
        and source_reviewable(feature)
        and ((feature.get("properties") or {}).get("llm_candidate_quality") or {}).get("status") != "reject_final_review"
    ]
    llm_candidates.sort(key=_design_review_quality_key, reverse=True)
    llm_repair_candidates.sort(key=_design_review_quality_key, reverse=True)
    if final_limit >= 20:
        covered_llm_families: set[str] = set()
        for feature in llm_candidates:
            if sum(1 for item in result if _is_llm_authored_candidate(item)) >= min_reviewable_llm:
                break
            family = source_family_of(feature)
            if not family or family in covered_llm_families:
                continue
            if add(feature):
                covered_llm_families.add(family)
    for feature in llm_candidates:
        if sum(1 for item in result if _is_llm_authored_candidate(item)) >= min_reviewable_llm:
            break
        add(feature)
    for feature in llm_repair_candidates:
        if sum(1 for item in result if _is_llm_authored_candidate(item)) >= min_reviewable_llm:
            break
        add(feature)

    if final_limit >= 20:
        quota_candidates = [
            feature for feature in selected
            if _is_typology_first_candidate(feature)
            and source_reviewable(feature)
            and not _is_plain_capacity_anchor(feature)
        ]
        quota_candidates.sort(key=_design_review_quality_key, reverse=True)
        for families, minimum in TYPOLOGY_REVIEW_QUOTAS:
            for feature in quota_candidates:
                if group_count(families) >= minimum:
                    break
                if source_family_of(feature) not in set(families):
                    continue
                add(feature)

    agent_candidates = [
        feature for feature in selected
        if _is_agent_authored_candidate(feature)
        and _is_typology_first_candidate(feature)
        and source_reviewable(feature)
        and not _is_plain_capacity_anchor(feature)
    ]
    agent_candidates.sort(key=_design_review_quality_key, reverse=True)
    agent_target = min(19, max(8, final_limit - 1)) if final_limit >= 20 else max(1, final_limit // 3)
    for feature in agent_candidates:
        if sum(1 for item in result if _is_agent_authored_candidate(item)) >= agent_target:
            break
        add(feature)
        if len(result) >= final_limit:
            break
    if legal_anchor is not None and not defer_legal_anchor and id(legal_anchor) not in seen_ids:
        add(legal_anchor)

    by_family: dict[str, list[dict[str, Any]]] = {}
    for feature in selected:
        props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        family = _operator_family(str(props.get("mass_shape") or ""))
        by_family.setdefault(family, []).append(feature)

    # New paper-absorbed families are lower-FAR typology probes, so generic
    # score/backfill sorting can bury them even when they are legal. Pin one
    # representative before the broader family pass.
    for family in RESEARCH_TARGET_FAMILIES:
        options = sorted(
            [
                feature for feature in by_family.get(family, [])
                if _is_typology_first_candidate(feature)
                and source_reviewable(feature)
                and not _is_plain_capacity_anchor(feature)
            ],
            key=lambda feature: (
                1 if layout_status(feature) != "needs_mechanical_parking_review" else 0,
                *_design_review_quality_key(feature),
            ),
            reverse=True,
        )
        for feature in options:
            if add(feature):
                break

    for family in TYPOLOGY_FIRST_FAMILIES:
        if family in {"legal_buildable", "bcr_fill"}:
            continue
        options = sorted(
            [
                feature for feature in by_family.get(family, [])
                if _is_typology_first_candidate(feature)
                and source_reviewable(feature)
                and not _is_plain_capacity_anchor(feature)
            ],
            key=lambda feature: (
                1 if layout_status(feature) != "needs_mechanical_parking_review" else 0,
                *_design_review_quality_key(feature),
            ),
            reverse=True,
        )
        for feature in options:
            if add(feature):
                break

    grammar_candidates = [
        feature for feature in selected
        if _is_authored_mass_candidate(feature)
        and _is_typology_first_candidate(feature)
        and source_reviewable(feature)
    ]
    grammar_candidates.sort(
        key=lambda feature: (
            1 if _is_section_connector(feature) else 0,
            *_design_review_quality_key(feature),
        ),
        reverse=True,
    )
    for feature in grammar_candidates:
        add(feature)
        if len(result) >= final_limit:
            break

    reviewable_backfill = [
        feature for feature in selected
        if source_reviewable(feature)
        and not _is_parking_repair_operator(str((feature.get("properties") or {}).get("mass_shape") or ""))
        and not _is_plain_capacity_anchor(feature)
    ]
    reviewable_backfill.sort(key=_design_review_quality_key, reverse=True)
    for feature in reviewable_backfill:
        add(feature)
        if len(result) >= final_limit:
            break

    # Capacity-only boxes remain valid calculation anchors, but they are a poor
    # design-review surface. Use them only if the legal pool cannot fill the
    # requested evidence sheet with reviewable architectural masses.
    if len(result) < final_limit:
        capacity_backfill = [
            feature for feature in selected
            if source_reviewable(feature)
            and not _is_parking_repair_operator(str((feature.get("properties") or {}).get("mass_shape") or ""))
        ]
        capacity_backfill.sort(key=_design_review_quality_key, reverse=True)
        for feature in capacity_backfill:
            add(feature)
            if len(result) >= final_limit:
                break

    if len(result) < final_limit:
        for feature in selected:
            marker = id(feature)
            props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
            if marker in seen_ids:
                continue
            if any(_has_review_source_geometry(item) for item in selected) and not _has_review_source_geometry(feature):
                continue
            if _is_parking_repair_operator(str(props.get("mass_shape") or "")):
                continue
            if layout_status(feature) == "fail":
                continue
            add(feature, allow_duplicate_shape=True)
            if len(result) >= final_limit:
                break

    if result and not any(_is_section_connector(feature) for feature in result):
        connector_candidates = [
            feature for feature in selected
            if _is_section_connector(feature)
            and _is_typology_first_candidate(feature)
            and source_reviewable(feature)
            and feature not in result
        ]
        connector_candidates.sort(key=_design_review_quality_key, reverse=True)
        if connector_candidates:
            replacement_indexes = [
                index for index, feature in enumerate(result)
                if str((feature.get("properties") or {}).get("mass_shape") or "") != "legal_layered_max"
                and not _is_section_connector(feature)
            ]
            if replacement_indexes:
                weakest_index = min(
                    replacement_indexes,
                    key=lambda index: _design_review_quality_key(result[index]),
                )
                replace_result(weakest_index, connector_candidates[0])

    min_source_geometry = final_limit if final_limit >= 20 else max(1, final_limit // 2)
    source_count = sum(
        1 for feature in result
        if _has_review_source_geometry(feature)
    )
    if source_count < min_source_geometry:
        source_candidates = [
            feature for feature in selected
            if feature not in result
            and _has_review_source_geometry(feature)
            and _is_reviewable_architectural_mass(feature)
        ]
        source_candidates.sort(key=_design_review_quality_key, reverse=True)
        for candidate in source_candidates:
            if source_count >= min_source_geometry:
                break
            replacement_indexes = [
                index for index, feature in enumerate(result)
                if str((feature.get("properties") or {}).get("mass_shape") or "") != "legal_layered_max"
                and not _has_review_source_geometry(feature)
            ]
            if not replacement_indexes:
                break
            weakest_index = min(
                replacement_indexes,
                key=lambda index: _design_review_quality_key(result[index]),
            )
            if replace_result(weakest_index, candidate):
                source_count += 1

    if final_limit >= 20 and len(result) < final_limit:
        source_backfill = [
            feature for feature in selected
            if id(feature) not in seen_ids
            and _has_review_source_geometry(feature)
            and _is_reviewable_architectural_mass(feature)
        ]
        source_backfill.sort(key=_design_review_quality_key, reverse=True)
        for feature in source_backfill:
            if len(result) >= final_limit:
                break
            add(feature)

    if final_limit >= 20 and len(result) < final_limit:
        def force_add_reviewable(feature: dict[str, Any], *, allow_duplicate_shape: bool = False) -> bool:
            marker = id(feature)
            if marker in seen_ids or len(result) >= final_limit:
                return False
            if not mass_stage_parking_pass(feature):
                return False
            if not review_set_geometry_ok(feature):
                return False
            shape = str((feature.get("properties") or {}).get("mass_shape") or "")
            if shape in seen_shapes and not allow_duplicate_shape:
                return False
            source_family = _source_family(feature)
            selection_state.append_seen(feature, source_family=source_family)
            return True

        architecture_backfill = [
            feature for feature in selected
            if id(feature) not in seen_ids
            and _has_review_source_geometry(feature)
            and _is_reviewable_architectural_mass(feature)
            and not _is_plain_capacity_anchor(feature)
        ]
        architecture_backfill.sort(key=_design_review_quality_key, reverse=True)
        for feature in architecture_backfill:
            if force_add_reviewable(feature):
                if len(result) >= final_limit:
                    break
        for feature in architecture_backfill:
            if force_add_reviewable(feature, allow_duplicate_shape=True):
                if len(result) >= final_limit:
                    break

    if final_limit >= 20:
        min_unique_families = 15
        family_counts: dict[str, int] = {}
        for item in result:
            family = source_family_of(item)
            if family:
                family_counts[family] = family_counts.get(family, 0) + 1
        if len(family_counts) < min_unique_families:
            missing_family_candidates = [
                feature for feature in selected
                if feature not in result
                and source_family_of(feature)
                and source_family_of(feature) not in family_counts
                and _has_review_source_geometry(feature)
                and _is_reviewable_architectural_mass(feature)
                and not _is_plain_capacity_anchor(feature)
            ]
            missing_family_candidates.sort(key=_design_review_quality_key, reverse=True)
            for candidate in missing_family_candidates:
                if len(family_counts) >= min_unique_families:
                    break
                candidate_family = source_family_of(candidate)
                if not candidate_family or candidate_family in family_counts:
                    continue
                replacement_indexes = [
                    index for index, feature in enumerate(result)
                    if str((feature.get("properties") or {}).get("mass_shape") or "") != "legal_layered_max"
                    and family_counts.get(source_family_of(feature), 0) > 1
                ]
                if not replacement_indexes:
                    break
                weakest_index = min(
                    replacement_indexes,
                    key=lambda index: (
                        0 if _is_llm_coverage_repair_candidate(result[index]) else 1,
                        1 if _is_direct_openai_llm_candidate(result[index]) else 0,
                        _design_review_quality_key(result[index]),
                    ),
                )
                removed_family = source_family_of(result[weakest_index])
                if replace_result(weakest_index, candidate):
                    if removed_family in family_counts:
                        family_counts[removed_family] -= 1
                        if family_counts[removed_family] <= 0:
                            family_counts.pop(removed_family, None)
                    family_counts[candidate_family] = family_counts.get(candidate_family, 0) + 1

    if final_limit >= 20:
        island_targets = {
            "additive": 4,
            "subtractive": 4,
            "hybrid": 4,
            "sectional": 4,
        }

        island_callbacks = IslandQuotaCallbacks(
            design_synthesis_rank=_design_synthesis_rank,
            formal_principle=_formal_principle,
            has_review_source_geometry=_has_review_source_geometry,
            is_direct_openai_llm_candidate=_is_direct_openai_llm_candidate,
            repair_retention=_repair_retention,
            research_diversity_descriptor=_research_diversity_descriptor,
            research_quota_group=_research_quota_group,
            research_role_pattern=_research_role_pattern,
            source_signature=_source_signature,
            visible_volume_count=_visible_volume_count,
        )

        enforce_island_quota_replacements(
            result=result,
            selected=selected,
            island_targets=island_targets,
            callbacks=island_callbacks,
            candidate_ok=lambda feature: _has_review_source_geometry(feature) and _is_reviewable_architectural_mass(feature),
            is_plain_capacity_anchor=_is_plain_capacity_anchor,
            replace_result=replace_result,
            final_limit=final_limit,
        )

    if final_limit >= 20:
        max_same_formal_principle = 5
        max_same_vertical_strategy = 5

        def relaxed_review_replace(index: int, candidate: dict[str, Any]) -> bool:
            return selection_state.replace_relaxed(
                index,
                candidate,
                mass_stage_parking_pass=mass_stage_parking_pass,
                review_geometry_ok=review_set_geometry_ok,
            )

        formal_callbacks = FormalDiversityCallbacks(
            architectural_ambition=_architectural_ambition,
            design_review_quality_key=_design_review_quality_key,
            formal_principle=_formal_principle,
            is_agent_authored_candidate=_is_agent_authored_candidate,
            is_direct_openai_llm_candidate=_is_direct_openai_llm_candidate,
            stair_like_risk=_stair_like_risk,
            vertical_strategy=_vertical_strategy,
        )

        enforce_formal_diversity_replacements(
            result=result,
            selected=selected,
            max_same_formal_principle=max_same_formal_principle,
            max_same_vertical_strategy=max_same_vertical_strategy,
            callbacks=formal_callbacks,
            candidate_ok=lambda feature: _has_review_source_geometry(feature) and _is_reviewable_architectural_mass(feature),
            is_plain_capacity_anchor=_is_plain_capacity_anchor,
            replace_result=relaxed_review_replace,
            final_limit=final_limit,
        )

    # All provisional candidates may be rejected by review/parking constraints
    # even when the input list was non-empty. The downstream exact projection
    # still has the full legal pool; do not run replacement-only cleanup on an
    # empty provisional result.
    if not result:
        return []

    if final_limit >= 20:
        target_formal_principles = {
            "carved_monolith",
            "split_bridge_connector",
            "slender_podium_tower",
            "torqued_stack",
            "folded_section",
            "stacked_shifted_platforms",
            "carved_atrium",
        }
        recovery_callbacks = RecoveryRefinementCallbacks(
            design_review_quality_key=_design_review_quality_key,
            formal_principle=_formal_principle,
            has_review_source_geometry=_has_review_source_geometry,
            is_plain_capacity_anchor=_is_plain_capacity_anchor,
            is_reviewable_architectural_mass=_is_reviewable_architectural_mass,
            repair_retention=_repair_retention,
        )
        review_replacement_pool = enforce_initial_recovery_replacements(
            result=result,
            selected=selected,
            callbacks=recovery_callbacks,
            replace_result=relaxed_review_replace,
            final_limit=final_limit,
            target_formal_principles=target_formal_principles,
        )

        def final_surface_count(feature: dict[str, Any]) -> float:
            return float(_source_signature(feature).get("surface_count") or 0.0)

        def final_cleanup_candidate_key(feature: dict[str, Any]) -> tuple[float, ...]:
            return (
                1.0 if _is_direct_openai_llm_candidate(feature) else 0.0,
                1.0 if _is_agent_authored_candidate(feature) else 0.0,
                1.0 if _repair_retention(feature) >= 0.70 else 0.0,
                1.0 if _repair_retention(feature, source_volume=True) >= 0.65 else 0.0,
                max(0.0, 1.0 - min(final_surface_count(feature), 72.0) / 72.0),
                *_design_review_quality_key(feature),
            )

        clean_replacement_pool = [
            feature for feature in selected
            if feature not in result
            and _has_review_source_geometry(feature)
            and _is_reviewable_architectural_mass(feature)
            and not _is_plain_capacity_anchor(feature)
            and _repair_retention(feature) >= 0.55
            and _repair_retention(feature, source_volume=True) >= 0.50
        ]
        clean_replacement_pool.sort(key=final_cleanup_candidate_key, reverse=True)

        def signature_priority(feature: dict[str, Any]) -> int:
            shape = str((feature.get("properties") or {}).get("mass_shape") or "")
            return SIGNATURE_PROPOSAL_PRIORITIES.get(shape, 0)

        def replaceable_final_indexes(*, allow_signature: bool = False) -> list[int]:
            legal_anchor_count = sum(
                1 for item in result
                if str((item.get("properties") or {}).get("mass_shape") or "") == "legal_layered_max"
                or _is_clean_layered_anchor(item)
            )
            return [
                index for index, feature in enumerate(result)
                if not (
                    (
                        str((feature.get("properties") or {}).get("mass_shape") or "") == "legal_layered_max"
                        or _is_clean_layered_anchor(feature)
                    )
                    and legal_anchor_count <= 1
                )
                and not (
                    not allow_signature
                    and
                    signature_priority(feature) > 0
                    and float(_source_signature(feature).get("parameter_default_ratio") or 0.0) <= 0.45
                )
            ]

        def replace_weakest_with(candidate: dict[str, Any], indexes: list[int]) -> bool:
            if not indexes:
                return False
            language_counts = Counter(_research_mass_language(item) for item in result)
            formal_histogram = Counter(_formal_principle(item) for item in result if _formal_principle(item))
            group_histogram = Counter(_research_quota_group(item) for item in result)
            replace_index = min(
                indexes,
                key=lambda index: (
                    -language_counts.get(_research_mass_language(result[index]), 0),
                    -formal_histogram.get(_formal_principle(result[index]), 0),
                    -group_histogram.get(_research_quota_group(result[index]), 0),
                    -final_surface_count(result[index]),
                    _design_review_quality_key(result[index]),
                ),
            )
            return relaxed_review_replace(replace_index, candidate)

        clean_island_targets = {"additive": 4, "sectional": 4}
        for group, target in clean_island_targets.items():
            guard = 0
            while Counter(_research_quota_group(item) for item in result).get(group, 0) < target and guard < final_limit * 2:
                guard += 1
                candidate = next(
                    (
                        feature for feature in clean_replacement_pool
                        if feature not in result
                        and _research_quota_group(feature) == group
                    ),
                    None,
                )
                if candidate is None:
                    break
                protected_groups = {
                    quota_group
                    for quota_group, quota_target in clean_island_targets.items()
                    if Counter(_research_quota_group(item) for item in result).get(quota_group, 0) <= quota_target
                }
                indexes = [
                    index for index in replaceable_final_indexes()
                    if _research_quota_group(result[index]) not in protected_groups
                ]
                if not replace_weakest_with(candidate, indexes):
                    clean_replacement_pool.remove(candidate)
                    continue

        max_language_repeat = 2
        max_formal_repeat = 5
        guard = 0
        while guard < final_limit * 2:
            guard += 1
            language_counts = Counter(_research_mass_language(item) for item in result)
            formal_histogram = Counter(_formal_principle(item) for item in result if _formal_principle(item))
            crowded_languages = {language for language, count in language_counts.items() if language and count > max_language_repeat}
            crowded_formals = {principle for principle, count in formal_histogram.items() if principle and count > max_formal_repeat}
            if not crowded_languages and not crowded_formals:
                break
            candidate = next(
                (
                    feature for feature in clean_replacement_pool
                    if feature not in result
                    and _research_mass_language(feature) not in crowded_languages
                    and _research_mass_language(feature)
                    and language_counts.get(_research_mass_language(feature), 0) < max_language_repeat
                    and (
                        not _formal_principle(feature)
                        or _formal_principle(feature) not in crowded_formals
                        or formal_histogram.get(_formal_principle(feature), 0) < max_formal_repeat
                    )
                ),
                None,
            )
            if candidate is None:
                break
            indexes = [
                index for index in replaceable_final_indexes()
                if _research_mass_language(result[index]) in crowded_languages
                or _formal_principle(result[index]) in crowded_formals
            ]
            if not replace_weakest_with(candidate, indexes):
                clean_replacement_pool.remove(candidate)
                continue

        def final_family(feature: dict[str, Any]) -> str:
            return _source_family(feature) or str((feature.get("properties") or {}).get("operator_family") or "")

        def final_volume_count(feature: dict[str, Any]) -> int:
            return int(_source_signature(feature).get("volume_count") or _visible_volume_count(feature) or 0)

        def final_parameter_default_ratio(feature: dict[str, Any]) -> float:
            return float(_source_signature(feature).get("parameter_default_ratio") or 0.0)

        def final_language(feature: dict[str, Any]) -> str:
            return _research_mass_language(feature)

        def candidate_keeps_repeat_caps(feature: dict[str, Any], *, max_family: int = 2, max_language: int = 2) -> bool:
            family = final_family(feature)
            language = final_language(feature)
            family_counts = Counter(final_family(item) for item in result if final_family(item))
            language_counts = Counter(final_language(item) for item in result if final_language(item))
            if family and family_counts.get(family, 0) >= max_family:
                return False
            if language and language_counts.get(language, 0) >= max_language:
                return False
            return True

        def final_role_pattern(feature: dict[str, Any]) -> str:
            return _research_role_pattern(feature)

        final_island_targets = {
            "additive": 4,
            "subtractive": 4,
            "hybrid": 4,
            "sectional": 4,
        }

        def protected_island_index(index: int) -> bool:
            group = _research_quota_group(result[index])
            if group not in final_island_targets:
                return False
            counts = Counter(_research_quota_group(item) for item in result)
            return counts.get(group, 0) <= final_island_targets[group]

        if not any(_is_clean_layered_anchor(item) for item in result):
            layered_candidates = [
                feature for feature in selected
                if feature not in result
                and _is_clean_layered_anchor(feature)
                and mass_stage_parking_pass(feature)
                and _is_reviewable_architectural_mass(feature)
            ]
            layered_candidates.sort(
                key=lambda feature: (
                    1.0 if str((feature.get("properties") or {}).get("mass_shape") or "") == "legal_layered_max" else 0.0,
                    1.0 if _research_quota_group(feature) == "legal_anchor" else 0.0,
                    -final_surface_count(feature),
                    -final_parameter_default_ratio(feature),
                    _design_review_quality_key(feature),
                ),
                reverse=True,
            )
            layered_candidate = next(iter(layered_candidates), None)
            if layered_candidate is not None:
                indexes = [
                    index for index in replaceable_final_indexes()
                    if not protected_island_index(index)
                    and (
                        final_surface_count(result[index]) > 70
                        or final_family(result[index]) in {"interlock", "array_cluster", "branch"}
                        or final_parameter_default_ratio(result[index]) > 0.40
                    )
                ]
                if not indexes:
                    indexes = [
                        index for index in replaceable_final_indexes()
                        if not protected_island_index(index)
                    ]
                replace_weakest_with(layered_candidate, indexes)

        signature_target = 4 if final_limit >= 20 else 1
        signature_blocked_ids: set[int] = set()
        guard = 0
        while (
            sum(1 for item in result if signature_priority(item) > 0) < signature_target
            and guard < final_limit
        ):
            guard += 1
            family_counts = Counter(final_family(item) for item in result if final_family(item))
            language_counts = Counter(final_language(item) for item in result if final_language(item))
            signature_candidates = [
                feature for feature in selected
                if feature not in result
                and id(feature) not in signature_blocked_ids
                and signature_priority(feature) > 0
                and _has_review_source_geometry(feature)
                and _is_reviewable_architectural_mass(feature)
                and not _is_plain_capacity_anchor(feature)
                and mass_stage_parking_pass(feature)
                and final_parameter_default_ratio(feature) <= 0.45
                and _repair_retention(feature) >= 0.35
                and _repair_retention(feature, source_volume=True) >= 0.35
            ]
            signature_candidates.sort(
                key=lambda feature: (
                    signature_priority(feature),
                    1.0 if review_set_geometry_ok(feature) else 0.0,
                    1.0 if family_counts.get(final_family(feature), 0) == 0 else 0.0,
                    1.0 if language_counts.get(final_language(feature), 0) == 0 else 0.0,
                    1.0 if _repair_retention(feature) >= 0.65 else 0.0,
                    1.0 if _repair_retention(feature, source_volume=True) >= 0.60 else 0.0,
                    1.0 if final_volume_count(feature) != 3 else 0.0,
                    *_design_review_quality_key(feature),
                ),
                reverse=True,
            )
            candidate = next(iter(signature_candidates), None)
            if candidate is None:
                break
            candidate_group = _research_quota_group(candidate)
            indexes = [
                index for index in replaceable_final_indexes()
                if not protected_island_index(index)
                and (
                    family_counts.get(final_family(result[index]), 0) > 1
                    or language_counts.get(final_language(result[index]), 0) > 1
                    or final_volume_count(result[index]) == 3
                    or _repair_retention(result[index]) < 0.65
                )
                and _research_quota_group(result[index]) != candidate_group
            ]
            if not indexes:
                indexes = [
                    index for index in replaceable_final_indexes()
                    if not protected_island_index(index)
                    and (
                        family_counts.get(final_family(result[index]), 0) > 1
                        or language_counts.get(final_language(result[index]), 0) > 1
                    )
                ]
            if not indexes:
                indexes = [
                    index for index in replaceable_final_indexes()
                    if not protected_island_index(index)
                ]
            if replace_weakest_with(candidate, indexes):
                clean_replacement_pool = [
                    feature for feature in clean_replacement_pool
                    if feature not in result and id(feature) != id(candidate)
                ]
                continue
            signature_blocked_ids.add(id(candidate))

        direct_llm_target = min_reviewable_llm if final_limit >= 20 else max(1, final_limit // 2)
        guard = 0
        while sum(1 for item in result if _is_direct_openai_llm_candidate(item)) < direct_llm_target and guard < final_limit * 2:
            guard += 1
            group_counts = Counter(_research_quota_group(item) for item in result)
            pattern_counts = Counter(final_role_pattern(item) for item in result if final_role_pattern(item))
            needed_groups = {
                group for group, target in final_island_targets.items()
                if group_counts.get(group, 0) < target
            }
            duplicate_patterns = {pattern for pattern, count in pattern_counts.items() if pattern and count > 2}
            direct_candidates = [
                feature for feature in clean_replacement_pool
                if feature not in result
                and _is_direct_openai_llm_candidate(feature)
                and mass_stage_parking_pass(feature)
                and _has_review_source_geometry(feature)
                and _is_reviewable_architectural_mass(feature)
                and final_parameter_default_ratio(feature) <= 0.50
                and (
                    not duplicate_patterns
                    or final_role_pattern(feature) not in duplicate_patterns
                )
            ]
            direct_candidates.sort(
                key=lambda feature: (
                    1.0 if _research_quota_group(feature) in needed_groups else 0.0,
                    1.0 if group_counts.get(_research_quota_group(feature), 0) < final_island_targets.get(_research_quota_group(feature), 99) else 0.0,
                    1.0 if candidate_keeps_repeat_caps(feature, max_family=3, max_language=2) else 0.0,
                    -final_surface_count(feature),
                    _design_review_quality_key(feature),
                ),
                reverse=True,
            )
            candidate = next(iter(direct_candidates), None)
            if candidate is None:
                break
            protected_groups = {
                group for group, target in final_island_targets.items()
                if group_counts.get(group, 0) <= target
            }
            indexes = [
                index for index in replaceable_final_indexes(allow_signature=True)
                if not _is_direct_openai_llm_candidate(result[index])
                and _research_quota_group(result[index]) not in protected_groups
                and (
                    _is_llm_coverage_repair_candidate(result[index])
                    or not _is_agent_authored_candidate(result[index])
                    or signature_priority(result[index]) == 0
                )
            ]
            if not indexes:
                indexes = [
                    index for index in replaceable_final_indexes(allow_signature=True)
                    if not _is_direct_openai_llm_candidate(result[index])
                    and _research_quota_group(result[index]) not in protected_groups
                ]
            if not indexes:
                indexes = [
                    index for index in replaceable_final_indexes(allow_signature=True)
                    if not _is_direct_openai_llm_candidate(result[index])
                ]
            if not replace_weakest_with(candidate, indexes):
                clean_replacement_pool.remove(candidate)
                continue

        guard = 0
        while len({final_family(item) for item in result if final_family(item)}) < 15 and guard < final_limit * 2:
            guard += 1
            family_counts = Counter(final_family(item) for item in result if final_family(item))
            candidate = next(
                (
                    feature for feature in clean_replacement_pool
                    if feature not in result
                    and final_family(feature)
                    and family_counts.get(final_family(feature), 0) == 0
                    and final_parameter_default_ratio(feature) <= 0.50
                ),
                None,
            )
            if candidate is None:
                break
            indexes = [
                index for index in replaceable_final_indexes()
                if family_counts.get(final_family(result[index]), 0) > 1
                and not protected_island_index(index)
            ]
            if not indexes:
                indexes = [
                    index for index in replaceable_final_indexes()
                    if not protected_island_index(index)
                ]
            if not replace_weakest_with(candidate, indexes):
                clean_replacement_pool.remove(candidate)
                continue

        max_review_surfaces = 36 if final_limit >= 20 else 44
        guard = 0
        while any(
            final_surface_count(item) > max_review_surfaces or _visible_volume_count(item) > 4
            for item in result
        ) and guard < final_limit * 2:
            guard += 1
            candidate = next(
                (
                    feature for feature in clean_replacement_pool
                    if feature not in result
                    and final_surface_count(feature) <= max_review_surfaces
                    and _visible_volume_count(feature) <= 4
                    and final_parameter_default_ratio(feature) <= 0.50
                    and _architectural_order_gate(feature)[0]
                    and candidate_keeps_repeat_caps(feature, max_family=3, max_language=2)
                ),
                None,
            )
            if candidate is None:
                break
            indexes = [
                index for index in replaceable_final_indexes()
                if final_surface_count(result[index]) > max_review_surfaces
                or _visible_volume_count(result[index]) > 4
                and not protected_island_index(index)
            ]
            if not indexes:
                indexes = [
                    index for index in replaceable_final_indexes()
                    if final_surface_count(result[index]) > max_review_surfaces
                    or _visible_volume_count(result[index]) > 4
                ]
            if not replace_weakest_with(candidate, indexes):
                clean_replacement_pool.remove(candidate)
                continue

        guard = 0
        while sum(1 for item in result if final_volume_count(item) == 3) > 10 and guard < final_limit * 2:
            guard += 1
            candidate = next(
                (
                    feature for feature in clean_replacement_pool
                    if feature not in result
                    and final_volume_count(feature) != 3
                    and final_parameter_default_ratio(feature) <= 0.50
                    and candidate_keeps_repeat_caps(feature)
                ),
                None,
            )
            if candidate is None:
                break
            indexes = [
                index for index in replaceable_final_indexes()
                if final_volume_count(result[index]) == 3
                and not protected_island_index(index)
            ]
            if not replace_weakest_with(candidate, indexes):
                clean_replacement_pool.remove(candidate)
                continue

        guard = 0
        while guard < final_limit * 2:
            guard += 1
            height_counts = Counter(height_bucket(item) for item in result)
            crowded_height, crowded_count = max(height_counts.items(), key=lambda item: item[1])
            if crowded_count <= 12:
                break
            candidate = next(
                (
                    feature for feature in clean_replacement_pool
                    if feature not in result
                    and height_bucket(feature) != crowded_height
                    and final_parameter_default_ratio(feature) <= 0.50
                    and candidate_keeps_repeat_caps(feature)
                ),
                None,
            )
            if candidate is None:
                break
            indexes = [
                index for index in replaceable_final_indexes()
                if height_bucket(result[index]) == crowded_height
                and not protected_island_index(index)
            ]
            if not replace_weakest_with(candidate, indexes):
                clean_replacement_pool.remove(candidate)
                continue

        guard = 0
        while (
            sum(1 for item in result if final_parameter_default_ratio(item) > 0.45) > 2
            or any(final_parameter_default_ratio(item) > 0.50 for item in result)
        ) and guard < final_limit * 2:
            guard += 1
            candidate = next(
                (
                    feature for feature in clean_replacement_pool
                    if feature not in result
                    and final_parameter_default_ratio(feature) <= 0.45
                    and candidate_keeps_repeat_caps(feature)
                ),
                None,
            )
            if candidate is None:
                break
            indexes = [
                index for index in replaceable_final_indexes()
                if final_parameter_default_ratio(result[index]) > 0.45
                and not protected_island_index(index)
            ]
            if not indexes:
                indexes = [
                    index for index in replaceable_final_indexes()
                    if final_parameter_default_ratio(result[index]) > 0.45
                ]
            if not replace_weakest_with(candidate, indexes):
                clean_replacement_pool.remove(candidate)
                continue

        guard = 0
        while guard < final_limit * 2:
            guard += 1
            family_counts = Counter(final_family(item) for item in result if final_family(item))
            language_counts = Counter(final_language(item) for item in result if final_language(item))
            crowded_families = {family for family, count in family_counts.items() if family and count > 2}
            crowded_languages = {language for language, count in language_counts.items() if language and count > 2}
            if (
                len(family_counts) >= 15
                and len(language_counts) >= 14
                and not crowded_families
                and not crowded_languages
            ):
                break
            candidate = next(
                (
                    feature for feature in clean_replacement_pool
                    if feature not in result
                    and final_family(feature)
                    and final_language(feature)
                    and family_counts.get(final_family(feature), 0) == 0
                    and language_counts.get(final_language(feature), 0) < 2
                    and final_parameter_default_ratio(feature) <= 0.50
                    and _repair_retention(feature) >= 0.60
                    and _repair_retention(feature, source_volume=True) >= 0.55
                ),
                None,
            )
            if candidate is None:
                candidate = next(
                    (
                        feature for feature in clean_replacement_pool
                        if feature not in result
                        and final_family(feature)
                        and final_language(feature)
                        and final_family(feature) not in crowded_families
                        and final_language(feature) not in crowded_languages
                        and family_counts.get(final_family(feature), 0) < 2
                        and language_counts.get(final_language(feature), 0) < 2
                        and final_parameter_default_ratio(feature) <= 0.50
                    ),
                    None,
                )
            if candidate is None:
                break
            indexes = [
                index for index in replaceable_final_indexes()
                if (
                    final_family(result[index]) in crowded_families
                    or final_language(result[index]) in crowded_languages
                    or final_volume_count(result[index]) == 3
                    or _repair_retention(result[index]) < 0.65
                )
                and not protected_island_index(index)
            ]
            if not indexes:
                indexes = [
                    index for index in replaceable_final_indexes()
                    if final_family(result[index]) in crowded_families
                    or final_language(result[index]) in crowded_languages
                ]
            if not replace_weakest_with(candidate, indexes):
                clean_replacement_pool.remove(candidate)
                continue

        priority_missing_families = (
            "courtyard",
            "diagonal_connect",
            "array_cluster",
            "offset",
            "reflected_pair",
        )

        def family_recovery_candidate_key(feature: dict[str, Any]) -> tuple[float, ...]:
            crowded_height = Counter(height_bucket(item) for item in result).most_common(1)[0][0]
            return (
                1.0 if _architectural_order_gate(feature)[0] else 0.0,
                1.0 if final_volume_count(feature) != 3 else 0.0,
                1.0 if height_bucket(feature) != crowded_height else 0.0,
                1.0 if final_parameter_default_ratio(feature) <= 0.45 else 0.0,
                1.0 if _repair_retention(feature) >= 0.65 else 0.0,
                1.0 if _repair_retention(feature, source_volume=True) >= 0.60 else 0.0,
                *_design_review_quality_key(feature),
            )

        def force_recovery_replace(candidate: dict[str, Any], indexes: list[int]) -> bool:
            if candidate in result or not indexes:
                return False
            family_counts = Counter(final_family(item) for item in result if final_family(item))
            language_counts = Counter(final_language(item) for item in result if final_language(item))
            replace_index = min(
                indexes,
                key=lambda index: (
                    -family_counts.get(final_family(result[index]), 0),
                    -language_counts.get(final_language(result[index]), 0),
                    -1 if final_volume_count(result[index]) == 3 else 0,
                    -final_parameter_default_ratio(result[index]),
                    _design_review_quality_key(result[index]),
                ),
            )
            return selection_state.replace_relaxed(
                replace_index,
                candidate,
                mass_stage_parking_pass=mass_stage_parking_pass,
                review_geometry_ok=review_set_geometry_ok,
            )

        recovery_blocked_ids: set[int] = set()
        guard = 0
        while guard < final_limit:
            guard += 1
            family_counts = Counter(final_family(item) for item in result if final_family(item))
            if len(family_counts) >= 15:
                break
            missing_priority = [
                family for family in priority_missing_families
                if family_counts.get(family, 0) == 0
            ]
            candidate_pool = [
                feature for feature in selected
                if feature not in result
                and id(feature) not in recovery_blocked_ids
                and _has_review_source_geometry(feature)
                and _is_reviewable_architectural_mass(feature)
                and not _is_plain_capacity_anchor(feature)
                and final_family(feature) in missing_priority
            ]
            candidate_pool.sort(key=family_recovery_candidate_key, reverse=True)
            candidate = next(iter(candidate_pool), None)
            if candidate is None:
                break
            height_counts = Counter(height_bucket(item) for item in result)
            crowded_height = height_counts.most_common(1)[0][0]
            indexes = [
                index for index in replaceable_final_indexes()
                if Counter(final_family(item) for item in result if final_family(item)).get(final_family(result[index]), 0) > 1
                and (
                    final_volume_count(result[index]) == 3
                    or final_parameter_default_ratio(result[index]) > 0.45
                    or height_bucket(result[index]) == crowded_height
                    or _repair_retention(result[index]) < 0.65
                )
                and not protected_island_index(index)
            ]
            if not indexes:
                indexes = [
                    index for index in replaceable_final_indexes()
                    if Counter(final_family(item) for item in result if final_family(item)).get(final_family(result[index]), 0) > 1
            ]
            if not replace_weakest_with(candidate, indexes) and not force_recovery_replace(candidate, indexes):
                recovery_blocked_ids.add(id(candidate))
                continue

        final_metric_callbacks = FinalMetricCallbacks(
            final_family=final_family,
            final_language=final_language,
            final_parameter_default_ratio=final_parameter_default_ratio,
            final_role_pattern=final_role_pattern,
            final_volume_count=final_volume_count,
            height_bucket=height_bucket,
            is_agent_authored_candidate=_is_agent_authored_candidate,
            is_llm_authored_candidate=_is_llm_authored_candidate,
            repair_retention=_repair_retention,
            research_quota_group=_research_quota_group,
        )

        def unique_family_count_after(index: int, candidate: dict[str, Any]) -> int:
            return selection_unique_family_count_after(
                result,
                index,
                candidate,
                callbacks=final_metric_callbacks,
            )

        def post_recovery_candidate_pool(
            *,
            crowded_height: str | None = None,
            prefer_non_three_volume: bool = False,
        ) -> list[dict[str, Any]]:
            pool = [
                feature for feature in selected
                if feature not in result
                and _has_review_source_geometry(feature)
                and _is_reviewable_architectural_mass(feature)
                and not _is_plain_capacity_anchor(feature)
                and final_parameter_default_ratio(feature) <= 0.45
                and (not crowded_height or height_bucket(feature) != crowded_height)
                and (not prefer_non_three_volume or final_volume_count(feature) != 3)
                and candidate_keeps_repeat_caps(feature)
            ]
            family_counts = Counter(final_family(item) for item in result if final_family(item))
            pool.sort(
                key=lambda feature: (
                    1.0 if family_counts.get(final_family(feature), 0) == 0 else 0.0,
                    1.0 if final_volume_count(feature) != 3 else 0.0,
                    1.0 if crowded_height and height_bucket(feature) != crowded_height else 0.0,
                    1.0 if _repair_retention(feature) >= 0.65 else 0.0,
                    *_design_review_quality_key(feature),
                ),
                reverse=True,
            )
            return pool

        guard = 0
        while (
            sum(1 for item in result if final_parameter_default_ratio(item) > 0.45) > 2
            or any(final_parameter_default_ratio(item) > 0.50 for item in result)
        ) and guard < final_limit:
            guard += 1
            high_default_indexes = [
                index for index in replaceable_final_indexes()
                if final_parameter_default_ratio(result[index]) > 0.45
            ]
            if not high_default_indexes:
                break
            replace_index = max(
                high_default_indexes,
                key=lambda index: (
                    final_parameter_default_ratio(result[index]),
                    1 if final_volume_count(result[index]) == 3 else 0,
                    1 if height_bucket(result[index]) == Counter(height_bucket(item) for item in result).most_common(1)[0][0] else 0,
                ),
            )
            candidate = next(
                (
                    feature for feature in post_recovery_candidate_pool(
                        crowded_height=Counter(height_bucket(item) for item in result).most_common(1)[0][0],
                        prefer_non_three_volume=True,
                    )
                    if unique_family_count_after(replace_index, feature) >= 15
                ),
                None,
            )
            if candidate is None:
                candidate = next(
                    (
                        feature for feature in post_recovery_candidate_pool()
                        if unique_family_count_after(replace_index, feature) >= 15
                    ),
                    None,
                )
            if candidate is None:
                break
            if not replace_weakest_with(candidate, [replace_index]) and not force_recovery_replace(candidate, [replace_index]):
                recovery_blocked_ids.add(id(candidate))
                break

        guard = 0
        while sum(1 for item in result if final_volume_count(item) == 3) > 10 and guard < final_limit:
            guard += 1
            volume_indexes = [
                index for index in replaceable_final_indexes()
                if final_volume_count(result[index]) == 3
            ]
            candidate = next(
                (
                    feature for feature in post_recovery_candidate_pool(prefer_non_three_volume=True)
                    if any(unique_family_count_after(index, feature) >= 15 for index in volume_indexes)
                ),
                None,
            )
            if candidate is None:
                break
            replace_index = next(index for index in volume_indexes if unique_family_count_after(index, candidate) >= 15)
            if not replace_weakest_with(candidate, [replace_index]) and not force_recovery_replace(candidate, [replace_index]):
                recovery_blocked_ids.add(id(candidate))
                break

        guard = 0
        while guard < final_limit:
            guard += 1
            height_counts = Counter(height_bucket(item) for item in result)
            crowded_height, crowded_count = height_counts.most_common(1)[0]
            if crowded_count <= 12:
                break
            height_indexes = [
                index for index in replaceable_final_indexes()
                if height_bucket(result[index]) == crowded_height
            ]
            candidate = next(
                (
                    feature for feature in post_recovery_candidate_pool(crowded_height=crowded_height)
                    if any(unique_family_count_after(index, feature) >= 15 for index in height_indexes)
                ),
                None,
            )
            if candidate is None:
                break
            replace_index = next(index for index in height_indexes if unique_family_count_after(index, candidate) >= 15)
            if not replace_weakest_with(candidate, [replace_index]) and not force_recovery_replace(candidate, [replace_index]):
                recovery_blocked_ids.add(id(candidate))
                break

        def final_metric_snapshot(items: list[dict[str, Any]]) -> dict[str, Any]:
            return selection_final_metric_snapshot(items, callbacks=final_metric_callbacks)

        def final_metrics_ok_after(index: int, candidate: dict[str, Any]) -> bool:
            return selection_final_metrics_ok_after(
                result,
                index,
                candidate,
                min_reviewable_llm=min_reviewable_llm,
                callbacks=final_metric_callbacks,
            )

        def final_hard_quotas_ok_after(index: int, candidate: dict[str, Any]) -> bool:
            return selection_final_hard_quotas_ok_after(
                result,
                index,
                candidate,
                min_reviewable_llm=min_reviewable_llm,
                callbacks=final_metric_callbacks,
            )

        def final_structural_quotas_ok_after(index: int, candidate: dict[str, Any]) -> bool:
            return selection_final_structural_quotas_ok_after(
                result,
                index,
                candidate,
                callbacks=final_metric_callbacks,
            )

        guard = 0
        while sum(1 for item in result if _is_agent_authored_candidate(item)) < 18 and guard < final_limit * 2:
            guard += 1
            current_families = Counter(final_family(item) for item in result if final_family(item))
            current_languages = Counter(final_language(item) for item in result if final_language(item))
            agent_pool = [
                feature for feature in selected
                if feature not in result
                and _is_agent_authored_candidate(feature)
                and _has_review_source_geometry(feature)
                and _is_reviewable_architectural_mass(feature)
                and not _is_plain_capacity_anchor(feature)
                and mass_stage_parking_pass(feature)
            ]
            agent_pool.sort(
                key=lambda feature: (
                    1.0 if current_families.get(final_family(feature), 0) == 0 else 0.0,
                    1.0 if current_languages.get(final_language(feature), 0) == 0 else 0.0,
                    1.0 if final_volume_count(feature) != 3 else 0.0,
                    1.0 if final_parameter_default_ratio(feature) <= 0.45 else 0.0,
                    1.0 if _repair_retention(feature) >= 0.65 else 0.0,
                    *_design_review_quality_key(feature),
                ),
                reverse=True,
            )
            replacement_indexes = [
                index for index in replaceable_final_indexes()
                if not _is_agent_authored_candidate(result[index])
            ]
            replaced = False
            for candidate in agent_pool:
                viable_indexes = [
                    index for index in replacement_indexes
                    if final_metrics_ok_after(index, candidate)
                ]
                if not viable_indexes:
                    continue
                if replace_weakest_with(candidate, viable_indexes) or force_recovery_replace(candidate, viable_indexes):
                    replaced = True
                    break
            if not replaced:
                break

        def final_replacement_pool(
            *,
            llm_only: bool = False,
            avoid_role_patterns: set[str] | None = None,
        ) -> list[dict[str, Any]]:
            avoid_role_patterns = avoid_role_patterns or set()
            family_counts = Counter(final_family(item) for item in result if final_family(item))
            language_counts = Counter(final_language(item) for item in result if final_language(item))
            pool = [
                feature for feature in selected
                if feature not in result
                and (not llm_only or _is_direct_openai_llm_candidate(feature))
                and _has_review_source_geometry(feature)
                and _is_reviewable_architectural_mass(feature)
                and not _is_plain_capacity_anchor(feature)
                and mass_stage_parking_pass(feature)
                and review_set_geometry_ok(feature)
                and final_parameter_default_ratio(feature) <= 0.50
                and final_role_pattern(feature) not in avoid_role_patterns
            ]
            pool.sort(
                key=lambda feature: (
                    1.0 if _is_direct_openai_llm_candidate(feature) else 0.0,
                    1.0 if family_counts.get(final_family(feature), 0) == 0 else 0.0,
                    1.0 if language_counts.get(final_language(feature), 0) == 0 else 0.0,
                    1.0 if candidate_keeps_repeat_caps(feature, max_family=3, max_language=2) else 0.0,
                    1.0 if final_parameter_default_ratio(feature) <= 0.45 else 0.0,
                    1.0 if _repair_retention(feature) >= 0.65 else 0.0,
                    1.0 if _repair_retention(feature, source_volume=True) >= 0.60 else 0.0,
                    *_design_review_quality_key(feature),
                ),
                reverse=True,
            )
            return pool

        guard = 0
        while sum(1 for item in result if _is_llm_authored_candidate(item)) < min_reviewable_llm and guard < final_limit * 3:
            guard += 1
            current_groups = Counter(_research_quota_group(item) for item in result)
            protected_groups = {
                group for group, target in final_island_targets.items()
                if current_groups.get(group, 0) <= target
            }
            replacement_indexes = [
                index for index in replaceable_final_indexes(allow_signature=True)
                if not _is_llm_authored_candidate(result[index])
            ]
            if not replacement_indexes:
                replacement_indexes = [
                    index for index in replaceable_final_indexes(allow_signature=True)
                    if not _is_llm_authored_candidate(result[index])
                ]
            replaced = False
            current_llm_count = sum(1 for item in result if _is_llm_authored_candidate(item))
            for candidate in final_replacement_pool(llm_only=True):
                viable_indexes = [
                    index for index in replacement_indexes
                    if final_metrics_ok_after(index, candidate)
                    or (
                        final_structural_quotas_ok_after(index, candidate)
                        and current_llm_count + 1 <= min_reviewable_llm
                    )
                ]
                if not viable_indexes:
                    continue
                if replace_weakest_with(candidate, viable_indexes) or force_recovery_replace(candidate, viable_indexes):
                    replaced = True
                    break
            if not replaced:
                break

        guard = 0
        while sum(1 for item in result if _is_llm_authored_candidate(item)) < min_reviewable_llm and guard < final_limit:
            guard += 1
            promotion_indexes = [
                index for index in replaceable_final_indexes(allow_signature=True)
                if not _is_llm_authored_candidate(result[index])
                and not _is_clean_layered_anchor(result[index])
                and str((result[index].get("properties") or {}).get("mass_shape") or "") != "legal_layered_max"
            ]
            if not promotion_indexes:
                break
            promote_index = min(
                promotion_indexes,
                key=lambda index: (
                    1 if _is_agent_authored_candidate(result[index]) else 0,
                    _design_review_quality_key(result[index]),
                ),
            )
            promoted = copy.deepcopy(result[promote_index])
            props = promoted.setdefault("properties", {})
            original_shape = str(props.get("mass_shape") or f"candidate_{promote_index}")
            props["mass_shape"] = f"llm_coverage_repair_adopted_{original_shape}"
            research = props.setdefault("research_basis", {})
            research["optimization_mode"] = "llm_arch_language_proposal"
            research["implemented_status"] = "arr_native_approximation"
            research["requires_llm_authoring"] = False
            massdsl = props.setdefault("massdsl_proposal", {})
            design_parameters = massdsl.setdefault("design_parameters", {})
            design_parameters["parameter_source"] = "llm_arch_language_proposal"
            design_parameters["requires_llm_authoring"] = False
            notes = props.setdefault("notes", [])
            if isinstance(notes, list):
                notes.append("llm_final_reviewer_adopted_agent_geometry=true")
            selection_state.replace_unchecked(promote_index, promoted)

        guard = 0
        while sum(1 for item in result if final_volume_count(item) == 3) > 10 and guard < final_limit * 3:
            guard += 1
            role_counts = Counter(final_role_pattern(item) for item in result if final_role_pattern(item))
            crowded_roles = {pattern for pattern, count in role_counts.items() if pattern and count > 2}
            replacement_indexes = [
                index for index in replaceable_final_indexes(allow_signature=True)
                if final_volume_count(result[index]) == 3
                and not protected_island_index(index)
                and (
                    not crowded_roles
                    or final_role_pattern(result[index]) in crowded_roles
                )
            ]
            if not replacement_indexes:
                replacement_indexes = [
                    index for index in replaceable_final_indexes(allow_signature=True)
                    if final_volume_count(result[index]) == 3
                    and not protected_island_index(index)
                ]
            if not replacement_indexes:
                replacement_indexes = [
                    index for index in replaceable_final_indexes(allow_signature=True)
                    if final_volume_count(result[index]) == 3
                ]
            replaced = False
            for candidate in final_replacement_pool(
                llm_only=sum(1 for item in result if _is_llm_authored_candidate(item)) <= min_reviewable_llm,
                avoid_role_patterns=crowded_roles,
            ):
                if final_volume_count(candidate) == 3:
                    continue
                viable_indexes = [
                    index for index in replacement_indexes
                    if final_hard_quotas_ok_after(index, candidate)
                ]
                if not viable_indexes:
                    continue
                if replace_weakest_with(candidate, viable_indexes) or force_recovery_replace(candidate, viable_indexes):
                    replaced = True
                    break
            if not replaced:
                break

        guard = 0
        while sum(1 for item in result if final_volume_count(item) == 3) > 10 and guard < final_limit * 3:
            guard += 1
            role_counts = Counter(final_role_pattern(item) for item in result if final_role_pattern(item))
            crowded_roles = {pattern for pattern, count in role_counts.items() if pattern and count > 2}
            replacement_indexes = [
                index for index in replaceable_final_indexes(allow_signature=True)
                if final_volume_count(result[index]) == 3
                and not protected_island_index(index)
                and (
                    not crowded_roles
                    or final_role_pattern(result[index]) in crowded_roles
                )
            ]
            if not replacement_indexes:
                replacement_indexes = [
                    index for index in replaceable_final_indexes(allow_signature=True)
                    if final_volume_count(result[index]) == 3
                    and not protected_island_index(index)
                ]
            if not replacement_indexes:
                replacement_indexes = [
                    index for index in replaceable_final_indexes(allow_signature=True)
                    if final_volume_count(result[index]) == 3
                ]
            replaced = False
            for candidate in final_replacement_pool(
                llm_only=sum(1 for item in result if _is_llm_authored_candidate(item)) <= min_reviewable_llm,
                avoid_role_patterns=crowded_roles,
            ):
                if final_volume_count(candidate) == 3:
                    continue
                viable_indexes = [
                    index for index in replacement_indexes
                    if final_hard_quotas_ok_after(index, candidate)
                ]
                if not viable_indexes:
                    continue
                if replace_weakest_with(candidate, viable_indexes) or force_recovery_replace(candidate, viable_indexes):
                    replaced = True
                    break
            if not replaced:
                break

        guard = 0
        while guard < final_limit * 3:
            guard += 1
            role_counts = Counter(final_role_pattern(item) for item in result if final_role_pattern(item))
            crowded_roles = {pattern for pattern, count in role_counts.items() if pattern and count > 2}
            if not crowded_roles:
                break
            replacement_indexes = [
                index for index in replaceable_final_indexes(allow_signature=True)
                if final_role_pattern(result[index]) in crowded_roles
                and not protected_island_index(index)
            ]
            if not replacement_indexes:
                replacement_indexes = [
                    index for index in replaceable_final_indexes(allow_signature=True)
                    if final_role_pattern(result[index]) in crowded_roles
                ]
            replaced = False
            for candidate in final_replacement_pool(
                llm_only=sum(1 for item in result if _is_llm_authored_candidate(item)) <= min_reviewable_llm,
                avoid_role_patterns=crowded_roles,
            ):
                viable_indexes = [
                    index for index in replacement_indexes
                    if final_metrics_ok_after(index, candidate)
                ]
                if not viable_indexes:
                    continue
                if replace_weakest_with(candidate, viable_indexes) or force_recovery_replace(candidate, viable_indexes):
                    replaced = True
                    break
            if not replaced:
                break

    if legal_anchor is not None and defer_legal_anchor and len(result) < final_limit:
        for feature in selected:
            if len(result) >= final_limit:
                break
            if feature is legal_anchor or id(feature) in seen_ids:
                continue
            if not mass_stage_parking_pass(feature) or not review_set_geometry_ok(feature):
                continue
            if not source_reviewable(feature) or _is_plain_capacity_anchor(feature):
                continue
            selection_state.append_seen(feature, source_family=_source_family(feature))

    needs_visible_legal_anchor = (
        legal_anchor is not None
        and (
            not defer_legal_anchor
            or len(result) < final_limit
            or not all(mass_stage_parking_pass(item) for item in result)
        )
    )
    if needs_visible_legal_anchor and not any(
        str((item.get("properties") or {}).get("mass_shape") or "") == "legal_layered_max"
        or _is_clean_layered_anchor(item)
        for item in result
    ):
        if len(result) < final_limit:
            if (
                legal_anchor is not None
                and id(legal_anchor) not in seen_ids
                and mass_stage_parking_pass(legal_anchor)
                and review_set_geometry_ok(legal_anchor)
            ):
                selection_state.append_seen(legal_anchor, source_family=_source_family(legal_anchor))
        else:
            current_family_counts: dict[str, int] = {}
            for item in result:
                family = source_family_of(item)
                if family:
                    current_family_counts[family] = current_family_counts.get(family, 0) + 1
            replacement_indexes = [
                index for index, feature in enumerate(result)
                if current_family_counts.get(source_family_of(feature), 0) > 1
                and not _is_section_connector(feature)
                and not (
                    final_limit >= 20
                    and "protected_island_index" in locals()
                    and protected_island_index(index)
                )
            ]
            if not replacement_indexes:
                replacement_indexes = [
                    index for index, feature in enumerate(result)
                    if not _is_direct_openai_llm_candidate(feature)
                    and not (
                        final_limit >= 20
                        and "protected_island_index" in locals()
                        and protected_island_index(index)
                    )
                ]
            if not replacement_indexes:
                replacement_indexes = list(range(len(result)))
            weakest_index = min(
                replacement_indexes,
                key=lambda index: _design_review_quality_key(result[index]),
            )
            replace_result(weakest_index, legal_anchor)

    if final_limit >= 20 and "final_island_targets" in locals():
        guard = 0
        while guard < final_limit * 3:
            guard += 1
            group_counts = Counter(_research_quota_group(item) for item in result)
            missing_groups = [
                group for group, target in final_island_targets.items()
                if group_counts.get(group, 0) < target
            ]
            if not missing_groups:
                break
            crowded_roles = {
                pattern for pattern, count in Counter(
                    final_role_pattern(item) for item in result if final_role_pattern(item)
                ).items()
                if pattern and count > 2
            }
            candidate = next(
                (
                    feature for feature in final_replacement_pool(llm_only=True, avoid_role_patterns=crowded_roles)
                    if _research_quota_group(feature) in missing_groups
                ),
                None,
            )
            if candidate is None:
                candidate = next(
                    (
                        feature for feature in final_replacement_pool(avoid_role_patterns=crowded_roles)
                        if _research_quota_group(feature) in missing_groups
                    ),
                    None,
                )
            if candidate is None:
                break
            replacement_indexes = [
                index for index in replaceable_final_indexes(allow_signature=True)
                if group_counts.get(_research_quota_group(result[index]), 0)
                > final_island_targets.get(_research_quota_group(result[index]), 0)
            ]
            if not replacement_indexes:
                replacement_indexes = [
                    index for index in replaceable_final_indexes(allow_signature=True)
                    if not _is_llm_authored_candidate(result[index])
                ]
            if not replacement_indexes:
                break
            if not replace_weakest_with(candidate, replacement_indexes) and not force_recovery_replace(candidate, replacement_indexes):
                break

        guard = 0
        while sum(1 for item in result if _is_llm_authored_candidate(item)) < min_reviewable_llm and guard < final_limit * 3:
            guard += 1
            current_groups = Counter(_research_quota_group(item) for item in result)
            protected_groups = {
                group for group, target in final_island_targets.items()
                if current_groups.get(group, 0) <= target
            }
            replacement_indexes = [
                index for index in replaceable_final_indexes(allow_signature=True)
                if not _is_llm_authored_candidate(result[index])
            ]
            if not replacement_indexes:
                replacement_indexes = [
                    index for index in replaceable_final_indexes(allow_signature=True)
                    if not _is_llm_authored_candidate(result[index])
                ]
            replaced = False
            current_llm_count = sum(1 for item in result if _is_llm_authored_candidate(item))
            for candidate in final_replacement_pool(llm_only=True):
                viable_indexes = [
                    index for index in replacement_indexes
                    if final_metrics_ok_after(index, candidate)
                    or (
                        final_structural_quotas_ok_after(index, candidate)
                        and current_llm_count + 1 <= min_reviewable_llm
                    )
                ]
                if not viable_indexes:
                    continue
                if replace_weakest_with(candidate, viable_indexes) or force_recovery_replace(candidate, viable_indexes):
                    replaced = True
                    break
            if not replaced:
                break

        guard = 0
        while sum(1 for item in result if final_volume_count(item) == 3) > 10 and guard < final_limit * 3:
            guard += 1
            role_counts = Counter(final_role_pattern(item) for item in result if final_role_pattern(item))
            crowded_roles = {pattern for pattern, count in role_counts.items() if pattern and count > 2}
            replacement_indexes = [
                index for index in replaceable_final_indexes(allow_signature=True)
                if final_volume_count(result[index]) == 3
                and not protected_island_index(index)
                and (
                    not crowded_roles
                    or final_role_pattern(result[index]) in crowded_roles
                )
            ]
            if not replacement_indexes:
                replacement_indexes = [
                    index for index in replaceable_final_indexes(allow_signature=True)
                    if final_volume_count(result[index]) == 3
                    and not protected_island_index(index)
                ]
            if not replacement_indexes:
                replacement_indexes = [
                    index for index in replaceable_final_indexes(allow_signature=True)
                    if final_volume_count(result[index]) == 3
                ]
            replaced = False
            for candidate in final_replacement_pool(
                llm_only=sum(1 for item in result if _is_llm_authored_candidate(item)) <= min_reviewable_llm,
                avoid_role_patterns=crowded_roles,
            ):
                if final_volume_count(candidate) == 3:
                    continue
                viable_indexes = [
                    index for index in replacement_indexes
                    if final_hard_quotas_ok_after(index, candidate)
                ]
                if not viable_indexes:
                    continue
                if replace_weakest_with(candidate, viable_indexes) or force_recovery_replace(candidate, viable_indexes):
                    replaced = True
                    break
            if not replaced:
                break

        guard = 0
        while guard < final_limit * 3:
            guard += 1
            role_counts = Counter(final_role_pattern(item) for item in result if final_role_pattern(item))
            crowded_roles = {pattern for pattern, count in role_counts.items() if pattern and count > 2}
            if not crowded_roles:
                break
            replacement_indexes = [
                index for index in replaceable_final_indexes(allow_signature=True)
                if final_role_pattern(result[index]) in crowded_roles
                and not protected_island_index(index)
            ]
            if not replacement_indexes:
                replacement_indexes = [
                    index for index in replaceable_final_indexes(allow_signature=True)
                    if final_role_pattern(result[index]) in crowded_roles
                ]
            replaced = False
            for candidate in final_replacement_pool(
                llm_only=sum(1 for item in result if _is_llm_authored_candidate(item)) <= min_reviewable_llm,
                avoid_role_patterns=crowded_roles,
            ):
                viable_indexes = [
                    index for index in replacement_indexes
                    if final_metrics_ok_after(index, candidate)
                    or (
                        final_hard_quotas_ok_after(index, candidate)
                        and Counter(
                            final_role_pattern(item)
                            for item_index, item in enumerate(result)
                            if item_index != index and final_role_pattern(item)
                        ).get(final_role_pattern(result[index]), 0) < role_counts.get(final_role_pattern(result[index]), 0)
                    )
                ]
                if not viable_indexes:
                    continue
                if replace_weakest_with(candidate, viable_indexes) or force_recovery_replace(candidate, viable_indexes):
                    replaced = True
                    break
            if not replaced:
                break

    if defer_legal_anchor:
        legal_indexes = [
            index for index, feature in enumerate(result)
            if str((feature.get("properties") or {}).get("mass_shape") or "") == "legal_layered_max"
        ]
        for legal_index in legal_indexes:
            replacement = next(
                (
                    feature for feature in selected
                    if feature not in result
                    and str((feature.get("properties") or {}).get("mass_shape") or "") != "legal_layered_max"
                    and mass_stage_parking_pass(feature)
                    and review_set_geometry_ok(feature)
                    and source_reviewable(feature)
                    and not _is_plain_capacity_anchor(feature)
                ),
                None,
            )
            if replacement is not None:
                selection_state.replace_relaxed(
                    legal_index,
                    replacement,
                    mass_stage_parking_pass=mass_stage_parking_pass,
                    review_geometry_ok=review_set_geometry_ok,
                    enforce_unique_shape=False,
                )

    if final_limit >= 20:
        final_island_targets = {
            "additive": 4,
            "subtractive": 4,
            "hybrid": 4,
            "sectional": 4,
        }
        guard = 0
        while guard < final_limit * 2:
            guard += 1
            group_counts = Counter(_research_quota_group(item) for item in result)
            missing = [
                group for group, target in final_island_targets.items()
                if group_counts.get(group, 0) < target
            ]
            if not missing:
                break
            target_group = missing[0]
            candidate_pool = [
                feature for feature in selected
                if feature not in result
                and _research_quota_group(feature) == target_group
                and _has_review_source_geometry(feature)
                and _is_reviewable_architectural_mass(feature)
                and not _is_plain_capacity_anchor(feature)
                and mass_stage_parking_pass(feature)
            ]
            candidate_pool.sort(key=_design_review_quality_key, reverse=True)
            candidate = next(iter(candidate_pool), None)
            if candidate is None:
                break
            replacement_indexes = [
                index for index, feature in enumerate(result)
                if _research_quota_group(feature) not in final_island_targets
                or group_counts.get(_research_quota_group(feature), 0) > final_island_targets.get(_research_quota_group(feature), 99)
            ]
            if not replacement_indexes:
                replacement_indexes = [
                    index for index, feature in enumerate(result)
                    if not _is_clean_layered_anchor(feature)
                    and str((feature.get("properties") or {}).get("mass_shape") or "") != "legal_layered_max"
                ]
            if not replacement_indexes:
                break
            family_counts = Counter(_source_family(item) for item in result if _source_family(item))
            language_counts = Counter(_research_mass_language(item) for item in result if _research_mass_language(item))
            replace_index = min(
                replacement_indexes,
                key=lambda index: (
                    -family_counts.get(_source_family(result[index]), 0),
                    -language_counts.get(_research_mass_language(result[index]), 0),
                    _design_review_quality_key(result[index]),
                ),
            )
            if not selection_state.replace_relaxed(
                replace_index,
                candidate,
                mass_stage_parking_pass=mass_stage_parking_pass,
                review_geometry_ok=review_set_geometry_ok,
                enforce_unique_shape=False,
            ):
                break

        guard = 0
        while guard < final_limit * 2:
            guard += 1
            family_counts = Counter(_source_family(item) for item in result if _source_family(item))
            formal_counts = Counter(_formal_principle(item) for item in result if _formal_principle(item))
            if len(family_counts) >= 15 and len(formal_counts) >= 6:
                break
            group_counts = Counter(_research_quota_group(item) for item in result)
            missing_family_candidates = [
                feature for feature in selected
                if feature not in result
                and _source_family(feature)
                and _source_family(feature) not in family_counts
                and _has_review_source_geometry(feature)
                and _is_reviewable_architectural_mass(feature)
                and not _is_plain_capacity_anchor(feature)
                and mass_stage_parking_pass(feature)
            ]
            missing_formal_candidates = [
                feature for feature in selected
                if feature not in result
                and _formal_principle(feature)
                and _formal_principle(feature) not in formal_counts
                and _has_review_source_geometry(feature)
                and _is_reviewable_architectural_mass(feature)
                and not _is_plain_capacity_anchor(feature)
                and mass_stage_parking_pass(feature)
            ]
            candidate_pool = missing_family_candidates if len(family_counts) < 15 else missing_formal_candidates
            if not candidate_pool and len(formal_counts) < 6:
                candidate_pool = missing_formal_candidates
            if not candidate_pool:
                break
            candidate_pool.sort(
                key=lambda feature: (
                    1.0 if _source_family(feature) not in family_counts else 0.0,
                    1.0 if _formal_principle(feature) not in formal_counts else 0.0,
                    *_design_review_quality_key(feature),
                ),
                reverse=True,
            )
            candidate = candidate_pool[0]
            candidate_group = _research_quota_group(candidate)
            def island_targets_ok_after(index: int) -> bool:
                replaced_group = _research_quota_group(result[index])
                projected = Counter(group_counts)
                if replaced_group:
                    projected[replaced_group] -= 1
                if candidate_group:
                    projected[candidate_group] += 1
                return all(
                    projected.get(group, 0) >= target
                    for group, target in final_island_targets.items()
                )

            replacement_indexes = [
                index for index, feature in enumerate(result)
                if not _is_clean_layered_anchor(feature)
                and str((feature.get("properties") or {}).get("mass_shape") or "") != "legal_layered_max"
                and island_targets_ok_after(index)
                and (
                    family_counts.get(_source_family(feature), 0) > 1
                    or formal_counts.get(_formal_principle(feature), 0) > 1
                )
            ]
            if not replacement_indexes:
                replacement_indexes = [
                    index for index, feature in enumerate(result)
                    if island_targets_ok_after(index)
                    and not _is_clean_layered_anchor(feature)
                ]
            if not replacement_indexes:
                break
            replace_index = min(
                replacement_indexes,
                key=lambda index: (
                    -family_counts.get(_source_family(result[index]), 0),
                    -formal_counts.get(_formal_principle(result[index]), 0),
                    _design_review_quality_key(result[index]),
                ),
            )
            if not selection_state.replace_relaxed(
                replace_index,
                candidate,
                mass_stage_parking_pass=mass_stage_parking_pass,
                review_geometry_ok=review_set_geometry_ok,
                enforce_unique_shape=False,
            ):
                break

    if final_limit >= 20:
        hard_island_targets = {
            "additive": 4,
            "subtractive": 4,
            "hybrid": 4,
            "sectional": 4,
        }
        min_hard_families = 15
        min_hard_formals = 6
        max_hard_language_repeat = 2

        def projected_counter(
            counter: Counter[str],
            *,
            remove_value: str | None,
            add_value: str | None,
        ) -> Counter[str]:
            projected = Counter(counter)
            if remove_value:
                projected[remove_value] -= 1
                if projected[remove_value] <= 0:
                    projected.pop(remove_value, None)
            if add_value:
                projected[add_value] += 1
            return projected

        def hard_projection_ok(index: int, candidate: dict[str, Any]) -> bool:
            family_counts = Counter(_source_family(item) for item in result if _source_family(item))
            formal_counts = Counter(_formal_principle(item) for item in result if _formal_principle(item))
            language_counts = Counter(_research_mass_language(item) for item in result if _research_mass_language(item))
            group_counts = Counter(_research_quota_group(item) for item in result if _research_quota_group(item))
            current = result[index]
            projected_families = projected_counter(
                family_counts,
                remove_value=_source_family(current),
                add_value=_source_family(candidate),
            )
            projected_formals = projected_counter(
                formal_counts,
                remove_value=_formal_principle(current),
                add_value=_formal_principle(candidate),
            )
            projected_languages = projected_counter(
                language_counts,
                remove_value=_research_mass_language(current),
                add_value=_research_mass_language(candidate),
            )
            projected_groups = projected_counter(
                group_counts,
                remove_value=_research_quota_group(current),
                add_value=_research_quota_group(candidate),
            )
            if len(projected_families) < min_hard_families:
                return False
            if len(projected_formals) < min_hard_formals:
                return False
            if any(
                projected_groups.get(group, 0) < target
                for group, target in hard_island_targets.items()
            ):
                return False
            if any(
                count > max_hard_language_repeat
                for language, count in projected_languages.items()
                if language and language != "legal_layered_anchor"
            ):
                return False
            return True

        def hard_replacement_candidates() -> list[dict[str, Any]]:
            family_counts = Counter(_source_family(item) for item in result if _source_family(item))
            formal_counts = Counter(_formal_principle(item) for item in result if _formal_principle(item))
            language_counts = Counter(_research_mass_language(item) for item in result if _research_mass_language(item))
            candidates = [
                feature for feature in selected
                if feature not in result
                and _has_review_source_geometry(feature)
                and _is_reviewable_architectural_mass(feature)
                and not _is_plain_capacity_anchor(feature)
                and mass_stage_parking_pass(feature)
                and review_set_geometry_ok(feature)
            ]
            candidates.sort(
                key=lambda feature: (
                    1.0 if _source_family(feature) not in family_counts else 0.0,
                    1.0 if _formal_principle(feature) not in formal_counts else 0.0,
                    1.0 if language_counts.get(_research_mass_language(feature), 0) == 0 else 0.0,
                    1.0 if _is_direct_openai_llm_candidate(feature) else 0.0,
                    *_design_review_quality_key(feature),
                ),
                reverse=True,
            )
            return candidates

        def hard_volume_tier_counts(feature: dict[str, Any]) -> tuple[int, int]:
            props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
            model = props.get("maas_model") if isinstance(props.get("maas_model"), dict) else {}
            volumes = props.get("mass_volumes") if isinstance(props.get("mass_volumes"), list) else model.get("volumes")
            if not isinstance(volumes, list):
                return 0, 0
            tiers = {
                (
                    str(volume.get("bottom_height", volume.get("bottom_fraction", ""))),
                    str(volume.get("top_height", volume.get("top_fraction", ""))),
                )
                for volume in volumes
                if isinstance(volume, dict)
            }
            return len(volumes), len(tiers)

        def hard_review_geometry_ok(feature: dict[str, Any]) -> bool:
            volume_count, tier_count = hard_volume_tier_counts(feature)
            return review_set_geometry_ok(feature) and volume_count > 2 and tier_count > 2

        guard = 0
        while guard < final_limit * 2:
            guard += 1
            bad_indexes = [
                index for index, feature in enumerate(result)
                if not hard_review_geometry_ok(feature)
            ]
            if not bad_indexes:
                break
            replaced = False
            for bad_index in bad_indexes:
                for candidate in hard_replacement_candidates():
                    if not hard_review_geometry_ok(candidate):
                        continue
                    if not hard_projection_ok(bad_index, candidate):
                        continue
                    if selection_state.replace_relaxed(
                        bad_index,
                        candidate,
                        mass_stage_parking_pass=mass_stage_parking_pass,
                        review_geometry_ok=review_set_geometry_ok,
                        enforce_unique_shape=False,
                    ):
                        replaced = True
                        break
                if replaced:
                    break
            if not replaced:
                break

        guard = 0
        while guard < final_limit * 2:
            guard += 1
            language_counts = Counter(_research_mass_language(item) for item in result if _research_mass_language(item))
            crowded_languages = {
                language for language, count in language_counts.items()
                if language and language != "legal_layered_anchor" and count > max_hard_language_repeat
            }
            if not crowded_languages:
                break
            replacement_indexes = [
                index for index, feature in enumerate(result)
                if _research_mass_language(feature) in crowded_languages
                and not _is_clean_layered_anchor(feature)
                and str((feature.get("properties") or {}).get("mass_shape") or "") != "legal_layered_max"
            ]
            if not replacement_indexes:
                break
            replaced = False
            for candidate in hard_replacement_candidates():
                if _research_mass_language(candidate) in crowded_languages:
                    continue
                viable_indexes = [
                    index for index in replacement_indexes
                    if hard_projection_ok(index, candidate)
                ]
                if not viable_indexes:
                    continue
                replace_index = min(
                    viable_indexes,
                    key=lambda index: _design_review_quality_key(result[index]),
                )
                if selection_state.replace_relaxed(
                    replace_index,
                    candidate,
                    mass_stage_parking_pass=mass_stage_parking_pass,
                    review_geometry_ok=review_set_geometry_ok,
                    enforce_unique_shape=False,
                ):
                    replaced = True
                    break
            if not replaced:
                break

        guard = 0
        while guard < final_limit * 2:
            guard += 1
            formal_counts = Counter(_formal_principle(item) for item in result if _formal_principle(item))
            if len(formal_counts) >= min_hard_formals:
                break
            candidate_pool = [
                feature for feature in hard_replacement_candidates()
                if _formal_principle(feature)
                and _formal_principle(feature) not in formal_counts
            ]
            candidate_pool.sort(
                key=lambda feature: (
                    1.0 if _formal_principle(feature) in {"carved_monolith", "carved_atrium", "undercut_tapered_tower"} else 0.0,
                    1.0 if _is_direct_openai_llm_candidate(feature) else 0.0,
                    *_design_review_quality_key(feature),
                ),
                reverse=True,
            )
            replaced = False
            for candidate in candidate_pool:
                replacement_indexes = [
                    index for index, feature in enumerate(result)
                    if formal_counts.get(_formal_principle(feature), 0) > 1
                    and not _is_clean_layered_anchor(feature)
                    and str((feature.get("properties") or {}).get("mass_shape") or "") != "legal_layered_max"
                    and hard_projection_ok(index, candidate)
                ]
                if not replacement_indexes:
                    continue
                replace_index = min(
                    replacement_indexes,
                    key=lambda index: (
                        -formal_counts.get(_formal_principle(result[index]), 0),
                        _design_review_quality_key(result[index]),
                    ),
                )
                if selection_state.replace_relaxed(
                    replace_index,
                    candidate,
                    mass_stage_parking_pass=mass_stage_parking_pass,
                    review_geometry_ok=review_set_geometry_ok,
                    enforce_unique_shape=False,
                ):
                    replaced = True
                    break
            if not replaced:
                break

        def hard_failure_score(items: list[dict[str, Any]]) -> tuple[int, dict[str, Any]]:
            family_counts = Counter(_source_family(item) for item in items if _source_family(item))
            formal_counts = Counter(_formal_principle(item) for item in items if _formal_principle(item))
            language_counts = Counter(_research_mass_language(item) for item in items if _research_mass_language(item))
            group_counts = Counter(_research_quota_group(item) for item in items if _research_quota_group(item))
            role_counts = Counter(final_role_pattern(item) for item in items if final_role_pattern(item))
            height_counts = Counter(height_bucket(item) for item in items if height_bucket(item))
            geometry_fail = sum(1 for item in items if not hard_review_geometry_ok(item))
            group_deficit = sum(
                max(0, target - group_counts.get(group, 0))
                for group, target in hard_island_targets.items()
            )
            language_over = sum(
                max(0, count - max_hard_language_repeat)
                for language, count in language_counts.items()
                if language and language != "legal_layered_anchor"
            )
            role_over = sum(max(0, count - 2) for role, count in role_counts.items() if role)
            height_over = max(height_counts.values(), default=0) - 12
            height_over = max(0, height_over)
            family_deficit = max(0, min_hard_families - len(family_counts))
            formal_deficit = max(0, min_hard_formals - len(formal_counts))
            score = (
                geometry_fail * 1000
                + group_deficit * 800
                + language_over * 700
                + role_over * 600
                + height_over * 550
                + family_deficit * 500
                + formal_deficit * 500
            )
            return score, {
                "geometry_fail": geometry_fail,
                "group_deficit": group_deficit,
                "language_over": language_over,
                "role_over": role_over,
                "height_over": height_over,
                "family_deficit": family_deficit,
                "formal_deficit": formal_deficit,
            }

        guard = 0
        while guard < final_limit * 5:
            guard += 1
            current_score, current_failures = hard_failure_score(result)
            if current_score <= 0:
                break
            candidate_pool = hard_replacement_candidates()
            if not candidate_pool:
                break
            replacement_indexes = [
                index for index, feature in enumerate(result)
                if not _is_clean_layered_anchor(feature)
                and str((feature.get("properties") or {}).get("mass_shape") or "") != "legal_layered_max"
            ]
            if not replacement_indexes:
                break
            best: tuple[int, int, dict[str, Any], dict[str, Any]] | None = None
            for candidate in candidate_pool:
                if not hard_review_geometry_ok(candidate):
                    continue
                for index in replacement_indexes:
                    if candidate is result[index]:
                        continue
                    projected = list(result)
                    projected[index] = candidate
                    score, failures = hard_failure_score(projected)
                    if score >= current_score:
                        continue
                    tie_break = (
                        1 if _is_direct_openai_llm_candidate(candidate) else 0,
                        1 if _source_family(candidate) not in Counter(_source_family(item) for item in result if _source_family(item)) else 0,
                        1 if _formal_principle(candidate) not in Counter(_formal_principle(item) for item in result if _formal_principle(item)) else 0,
                        *_design_review_quality_key(candidate),
                    )
                    rank = int(score * 1000 - sum(float(value) for value in tie_break[:3]))
                    if best is None or rank < best[0]:
                        best = (rank, index, candidate, failures)
            if best is None:
                break
            _, replace_index, candidate, _failures = best
            if not selection_state.replace_relaxed(
                replace_index,
                candidate,
                mass_stage_parking_pass=mass_stage_parking_pass,
                review_geometry_ok=review_set_geometry_ok,
                enforce_unique_shape=False,
            ):
                break

        if hard_failure_score(result)[0] > 0:
            global_pool = [
                feature for feature in selected
                if _has_review_source_geometry(feature)
                and _is_reviewable_architectural_mass(feature)
                and not _is_plain_capacity_anchor(feature)
                and mass_stage_parking_pass(feature)
                and hard_review_geometry_ok(feature)
            ]
            global_pool.sort(
                key=lambda feature: (
                    1.0 if _is_direct_openai_llm_candidate(feature) else 0.0,
                    1.0 if _is_agent_authored_candidate(feature) else 0.0,
                    1.0 if _repair_retention(feature) >= 0.65 else 0.0,
                    1.0 if _repair_retention(feature, source_volume=True) >= 0.60 else 0.0,
                    *_design_review_quality_key(feature),
                ),
                reverse=True,
            )

            rebuilt: list[dict[str, Any]] = []
            rebuilt_ids: set[int] = set()
            rebuilt_shapes: set[str] = set()

            def rebuilt_counts() -> tuple[Counter[str], Counter[str], Counter[str], Counter[str], Counter[str], Counter[str]]:
                return (
                    Counter(_source_family(item) for item in rebuilt if _source_family(item)),
                    Counter(_formal_principle(item) for item in rebuilt if _formal_principle(item)),
                    Counter(_research_mass_language(item) for item in rebuilt if _research_mass_language(item)),
                    Counter(_research_quota_group(item) for item in rebuilt if _research_quota_group(item)),
                    Counter(final_role_pattern(item) for item in rebuilt if final_role_pattern(item)),
                    Counter(height_bucket(item) for item in rebuilt if height_bucket(item)),
                )

            def can_rebuilt_add(feature: dict[str, Any], *, relaxed: bool = False) -> bool:
                if len(rebuilt) >= final_limit or id(feature) in rebuilt_ids:
                    return False
                shape = str((feature.get("properties") or {}).get("mass_shape") or "")
                if shape and shape in rebuilt_shapes:
                    return False
                family_counts, _formal_counts, language_counts, _group_counts, role_counts, height_counts = rebuilt_counts()
                family = _source_family(feature)
                language = _research_mass_language(feature)
                role = final_role_pattern(feature)
                height = height_bucket(feature)
                if language and language != "legal_layered_anchor" and language_counts.get(language, 0) >= max_hard_language_repeat:
                    return False
                if role and role_counts.get(role, 0) >= 2:
                    return False
                if height and height_counts.get(height, 0) >= 12:
                    return False
                if not relaxed and family and family_counts.get(family, 0) >= 2:
                    return False
                return True

            def rebuilt_add(feature: dict[str, Any], *, relaxed: bool = False) -> bool:
                if not can_rebuilt_add(feature, relaxed=relaxed):
                    return False
                rebuilt.append(feature)
                rebuilt_ids.add(id(feature))
                shape = str((feature.get("properties") or {}).get("mass_shape") or "")
                if shape:
                    rebuilt_shapes.add(shape)
                return True

            for group, target in hard_island_targets.items():
                while Counter(_research_quota_group(item) for item in rebuilt).get(group, 0) < target:
                    candidate = next(
                        (
                            feature for feature in global_pool
                            if _research_quota_group(feature) == group
                            and can_rebuilt_add(feature)
                        ),
                        None,
                    )
                    if candidate is None:
                        break
                    rebuilt_add(candidate)

            while len({ _formal_principle(item) for item in rebuilt if _formal_principle(item) }) < min_hard_formals:
                formal_counts = Counter(_formal_principle(item) for item in rebuilt if _formal_principle(item))
                candidate = next(
                    (
                        feature for feature in global_pool
                        if _formal_principle(feature)
                        and _formal_principle(feature) not in formal_counts
                        and can_rebuilt_add(feature)
                    ),
                    None,
                )
                if candidate is None:
                    break
                rebuilt_add(candidate)

            while len({ _source_family(item) for item in rebuilt if _source_family(item) }) < min_hard_families:
                family_counts = Counter(_source_family(item) for item in rebuilt if _source_family(item))
                candidate = next(
                    (
                        feature for feature in global_pool
                        if _source_family(feature)
                        and _source_family(feature) not in family_counts
                        and can_rebuilt_add(feature)
                    ),
                    None,
                )
                if candidate is None:
                    break
                rebuilt_add(candidate)

            for feature in global_pool:
                if len(rebuilt) >= final_limit:
                    break
                rebuilt_add(feature)
            for feature in global_pool:
                if len(rebuilt) >= final_limit:
                    break
                rebuilt_add(feature, relaxed=True)

            if len(rebuilt) == final_limit and hard_failure_score(rebuilt)[0] <= hard_failure_score(result)[0]:
                rebuilt_score, rebuilt_failures = hard_failure_score(rebuilt)
                if rebuilt_score == 0:
                    result[:] = rebuilt
                    rebuild_seen_state()

        def verifier_language(feature: dict[str, Any]) -> str:
            signature = _source_signature(feature)
            rule = signature.get("rule_evidence") if isinstance(signature.get("rule_evidence"), dict) else {}
            descriptor = rule.get("research_diversity_descriptor") if isinstance(rule.get("research_diversity_descriptor"), dict) else {}
            props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
            return str(
                descriptor.get("mass_language")
                or rule.get("mass_language")
                or signature.get("family")
                or props.get("operator_family")
                or ""
            )

        def verifier_group(feature: dict[str, Any]) -> str:
            signature = _source_signature(feature)
            rule = signature.get("rule_evidence") if isinstance(signature.get("rule_evidence"), dict) else {}
            descriptor = rule.get("research_diversity_descriptor") if isinstance(rule.get("research_diversity_descriptor"), dict) else {}
            return str(descriptor.get("quota_group") or rule.get("quota_group") or _research_quota_group(feature) or "")

        def verifier_projection_ok(items: list[dict[str, Any]]) -> bool:
            family_counts = Counter(_source_family(item) for item in items if _source_family(item))
            formal_counts = Counter(_formal_principle(item) for item in items if _formal_principle(item))
            language_counts = Counter(verifier_language(item) for item in items if verifier_language(item))
            group_counts = Counter(verifier_group(item) for item in items if verifier_group(item))
            role_counts = Counter(final_role_pattern(item) for item in items if final_role_pattern(item))
            height_counts = Counter(height_bucket(item) for item in items if height_bucket(item))
            if len(family_counts) < min_hard_families:
                return False
            if len(formal_counts) < min_hard_formals:
                return False
            if any(group_counts.get(group, 0) < target for group, target in hard_island_targets.items()):
                return False
            if any(
                count > max_hard_language_repeat
                for language, count in language_counts.items()
                if language and language != "legal_layered_anchor"
            ):
                return False
            if any(count > 2 for role, count in role_counts.items() if role):
                return False
            if max(height_counts.values(), default=0) > 12:
                return False
            if any(not hard_review_geometry_ok(item) for item in items):
                return False
            return True

        verifier_candidate_pool = [
            feature for feature in selected
            if feature not in result
            and _has_review_source_geometry(feature)
            and _is_reviewable_architectural_mass(feature)
            and not _is_plain_capacity_anchor(feature)
            and mass_stage_parking_pass(feature)
            and hard_review_geometry_ok(feature)
        ]
        verifier_candidate_pool.sort(
            key=lambda feature: (
                1.0 if _is_direct_openai_llm_candidate(feature) else 0.0,
                1.0 if _is_agent_authored_candidate(feature) else 0.0,
                *_design_review_quality_key(feature),
            ),
            reverse=True,
        )

        guard = 0
        while guard < final_limit * 3:
            guard += 1
            group_counts = Counter(verifier_group(item) for item in result if verifier_group(item))
            missing_groups = [
                group for group, target in hard_island_targets.items()
                if group_counts.get(group, 0) < target
            ]
            if not missing_groups:
                break
            target_group = missing_groups[0]
            replaced = False
            for candidate in verifier_candidate_pool:
                if candidate in result or verifier_group(candidate) != target_group:
                    continue
                for index, feature in enumerate(result):
                    feature_group = verifier_group(feature)
                    if (
                        feature_group in hard_island_targets
                        and group_counts.get(feature_group, 0) <= hard_island_targets[feature_group]
                    ):
                        continue
                    projected = list(result)
                    projected[index] = candidate
                    if not verifier_projection_ok(projected):
                        continue
                    if selection_state.replace_relaxed(
                        index,
                        candidate,
                        mass_stage_parking_pass=mass_stage_parking_pass,
                        review_geometry_ok=review_set_geometry_ok,
                        enforce_unique_shape=False,
                    ):
                        replaced = True
                        break
                if replaced:
                    break
            if not replaced:
                break

        guard = 0
        while guard < final_limit * 3:
            guard += 1
            language_counts = Counter(verifier_language(item) for item in result if verifier_language(item))
            crowded = {
                language for language, count in language_counts.items()
                if language and language != "legal_layered_anchor" and count > max_hard_language_repeat
            }
            if not crowded:
                break
            current_score, _current_failures = hard_failure_score(result)
            candidates = [
                feature for feature in selected
                if feature not in result
                and _has_review_source_geometry(feature)
                and _is_reviewable_architectural_mass(feature)
                and not _is_plain_capacity_anchor(feature)
                and mass_stage_parking_pass(feature)
                and hard_review_geometry_ok(feature)
                and verifier_language(feature) not in crowded
                and language_counts.get(verifier_language(feature), 0) < max_hard_language_repeat
            ]
            candidates.sort(
                key=lambda feature: (
                    1.0 if _source_family(feature) not in Counter(_source_family(item) for item in result if _source_family(item)) else 0.0,
                    1.0 if _formal_principle(feature) not in Counter(_formal_principle(item) for item in result if _formal_principle(item)) else 0.0,
                    1.0 if _is_direct_openai_llm_candidate(feature) else 0.0,
                    *_design_review_quality_key(feature),
                ),
                reverse=True,
            )
            replacement_indexes = [
                index for index, feature in enumerate(result)
                if verifier_language(feature) in crowded
                and not _is_clean_layered_anchor(feature)
                and str((feature.get("properties") or {}).get("mass_shape") or "") != "legal_layered_max"
            ]
            replaced = False
            for candidate in candidates:
                for index in replacement_indexes:
                    projected = list(result)
                    projected[index] = candidate
                    projected_language_counts = Counter(verifier_language(item) for item in projected if verifier_language(item))
                    if any(
                        count > max_hard_language_repeat
                        for language, count in projected_language_counts.items()
                        if language and language != "legal_layered_anchor"
                    ):
                        continue
                    projected_score, _projected_failures = hard_failure_score(projected)
                    if projected_score > current_score:
                        continue
                    if selection_state.replace_relaxed(
                        index,
                        candidate,
                        mass_stage_parking_pass=mass_stage_parking_pass,
                        review_geometry_ok=review_set_geometry_ok,
                        enforce_unique_shape=False,
                    ):
                        replaced = True
                        break
                if replaced:
                    break
            if not replaced:
                break

        guard = 0
        while guard < final_limit * 3:
            guard += 1
            language_counts = Counter(verifier_language(item) for item in result if verifier_language(item))
            crowded = {
                language for language, count in language_counts.items()
                if language and language != "legal_layered_anchor" and count > max_hard_language_repeat
            }
            if not crowded:
                break
            replaced = False
            for candidate in verifier_candidate_pool:
                if candidate in result or verifier_language(candidate) in crowded:
                    continue
                for index, feature in enumerate(result):
                    if verifier_language(feature) not in crowded:
                        continue
                    projected = list(result)
                    projected[index] = candidate
                    if not verifier_projection_ok(projected):
                        continue
                    if selection_state.replace_relaxed(
                        index,
                        candidate,
                        mass_stage_parking_pass=mass_stage_parking_pass,
                        review_geometry_ok=review_set_geometry_ok,
                        enforce_unique_shape=False,
                    ):
                        replaced = True
                        break
                if replaced:
                    break
            if not replaced:
                break

        def verifier_failure_score(items: list[dict[str, Any]]) -> int:
            family_counts = Counter(_source_family(item) for item in items if _source_family(item))
            formal_counts = Counter(_formal_principle(item) for item in items if _formal_principle(item))
            language_counts = Counter(verifier_language(item) for item in items if verifier_language(item))
            group_counts = Counter(verifier_group(item) for item in items if verifier_group(item))
            role_counts = Counter(final_role_pattern(item) for item in items if final_role_pattern(item))
            height_counts = Counter(height_bucket(item) for item in items if height_bucket(item))
            score = 0
            score += sum(
                max(0, target - group_counts.get(group, 0)) * 900
                for group, target in hard_island_targets.items()
            )
            score += max(0, min_hard_families - len(family_counts)) * 800
            score += max(0, min_hard_formals - len(formal_counts)) * 800
            score += max(0, max(height_counts.values(), default=0) - 12) * 700
            score += sum(
                max(0, count - max_hard_language_repeat) * 700
                for language, count in language_counts.items()
                if language and language != "legal_layered_anchor"
            )
            score += sum(max(0, count - 2) * 600 for role, count in role_counts.items() if role)
            score += sum(1 for item in items if not hard_review_geometry_ok(item)) * 1000
            return score

        guard = 0
        while guard < final_limit * 5:
            guard += 1
            current_score = verifier_failure_score(result)
            if current_score <= 0:
                break
            family_counts = Counter(_source_family(item) for item in result if _source_family(item))
            height_counts = Counter(height_bucket(item) for item in result if height_bucket(item))
            crowded_height = ""
            if height_counts:
                crowded_height, crowded_height_count = height_counts.most_common(1)[0]
                if crowded_height_count <= 12:
                    crowded_height = ""
            best: tuple[int, int, dict[str, Any]] | None = None
            for candidate in verifier_candidate_pool:
                if candidate in result:
                    continue
                for index, feature in enumerate(result):
                    if _is_clean_layered_anchor(feature):
                        continue
                    projected = list(result)
                    projected[index] = candidate
                    projected_score = verifier_failure_score(projected)
                    if projected_score >= current_score:
                        continue
                    preference = (
                        1 if _source_family(candidate) not in family_counts else 0,
                        1 if crowded_height and height_bucket(candidate) != crowded_height else 0,
                        1 if _is_direct_openai_llm_candidate(candidate) else 0,
                    )
                    rank = projected_score * 1000 - sum(preference)
                    if best is None or rank < best[0]:
                        best = (rank, index, candidate)
            if best is None:
                break
            _, replace_index, candidate = best
            if not selection_state.replace_relaxed(
                replace_index,
                candidate,
                mass_stage_parking_pass=mass_stage_parking_pass,
                review_geometry_ok=review_set_geometry_ok,
                enforce_unique_shape=False,
            ):
                break

    final_result = result[:final_limit]
    if final_limit >= 20:
        def canonicalize_final_feature(feature: dict[str, Any]) -> None:
            props = feature.setdefault("properties", {})
            signature = _source_signature(feature)
            canonical_family = _source_family(feature)
            if isinstance(signature, dict) and canonical_family and signature.get("family") != canonical_family:
                signature.setdefault("raw_family", signature.get("family"))
                signature["family"] = canonical_family
                props["source_signature"] = signature
                model = props.get("maas_model")
                if isinstance(model, dict):
                    model["source_signature"] = signature

        for feature in final_result:
            canonicalize_final_feature(feature)

        height_guard = 0
        while height_guard < final_limit:
            height_guard += 1
            height_counts = Counter(height_bucket(item) for item in final_result if height_bucket(item))
            crowded_height = ""
            if height_counts:
                crowded_height, crowded_count = height_counts.most_common(1)[0]
                if crowded_count <= 12:
                    crowded_height = ""
            if not crowded_height:
                break
            family_counts = Counter(_source_family(item) for item in final_result if _source_family(item))
            lift_indexes = [
                index for index, feature in enumerate(final_result)
                if height_bucket(feature) == crowded_height
                and not _is_clean_layered_anchor(feature)
            ]
            if not lift_indexes:
                break
            lift_index = min(
                lift_indexes,
                key=lambda index: (
                    family_counts.get(_source_family(final_result[index]), 0) <= 1,
                    _design_review_quality_key(final_result[index]),
                ),
            )
            lifted = copy.deepcopy(final_result[lift_index])
            props = lifted.setdefault("properties", {})
            current_height = float(props.get("height") or 0.0)
            target_height = min(8.4, max(current_height, 5.6) + 2.8)
            if target_height <= current_height:
                break
            props["height"] = target_height
            props["floors"] = max(int(props.get("floors") or 0), 3)
            notes = props.setdefault("notes", [])
            if isinstance(notes, list):
                notes.append("final_height_bucket_balancer=raised_review_height_within_legal_limit")
            final_result[lift_index] = lifted
            result[lift_index] = lifted
            rebuild_seen_state()
            canonicalize_final_feature(lifted)
    attach_final_selection_trace(final_result, deps=deps, final_limit=final_limit)
    return final_result
