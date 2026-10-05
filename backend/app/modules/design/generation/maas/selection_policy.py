"""Compatibility exports for MAAS selection policy.

New code should import from ``design.maas.selection``. This module remains so
older callers do not break while the optimizer is split into role packages.
"""

from __future__ import annotations

from backend.app.modules.design.generation.maas.selection import FinalReviewRefinementCallbacks, FinalReviewRefinementPolicy, FinalMetricCallbacks, FormalDiversityCallbacks, IslandQuotaCallbacks, RecoveryRefinementCallbacks, ReviewSetConstraintCallbacks, SelectionState, build_review_replacement_pool, duplicate_role_pattern_counts, enforce_formal_diversity_replacements, enforce_island_quota_replacements, enforce_initial_recovery_replacements, final_hard_quotas_ok_after, final_local_role_pattern, final_metric_snapshot, final_metrics_ok_after, final_mass_stage_parking_pass, final_shape, final_structural_quotas_ok_after, formal_candidate_key, formal_counts, height_bucket, island_candidate_key, island_counts, layout_status, refine_final_review_set, review_set_constraints_ok, review_set_geometry_ok, source_reviewable, strategy_counts, unresolved_llm_authoring, unique_family_count_after, visible_tier_count


__all__ = [
    "FinalReviewRefinementCallbacks",
    "FinalReviewRefinementPolicy",
    "FinalMetricCallbacks",
    "FormalDiversityCallbacks",
    "IslandQuotaCallbacks",
    "RecoveryRefinementCallbacks",
    "ReviewSetConstraintCallbacks",
    "SelectionState",
    "build_review_replacement_pool",
    "duplicate_role_pattern_counts",
    "enforce_formal_diversity_replacements",
    "enforce_island_quota_replacements",
    "enforce_initial_recovery_replacements",
    "final_hard_quotas_ok_after",
    "formal_candidate_key",
    "formal_counts",
    "height_bucket",
    "final_local_role_pattern",
    "final_metric_snapshot",
    "final_metrics_ok_after",
    "final_mass_stage_parking_pass",
    "final_shape",
    "final_structural_quotas_ok_after",
    "island_candidate_key",
    "island_counts",
    "layout_status",
    "refine_final_review_set",
    "review_set_constraints_ok",
    "review_set_geometry_ok",
    "source_reviewable",
    "strategy_counts",
    "unresolved_llm_authoring",
    "unique_family_count_after",
    "visible_tier_count",
]
