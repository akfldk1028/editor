"""Selection package for MAAS review candidate curation."""

from backend.app.modules.design.generation.maas.selection.constraints import final_mass_stage_parking_pass, final_shape, layout_status, review_set_constraints_ok, review_set_geometry_ok, source_reviewable, unresolved_llm_authoring, visible_tier_count
from backend.app.modules.design.generation.maas.selection.final_metrics import final_hard_quotas_ok_after, final_metric_snapshot, final_metrics_ok_after, final_structural_quotas_ok_after, unique_family_count_after
from backend.app.modules.design.generation.maas.selection.final_balanced import BalancedSelectionDeps, final_design_balanced_selection
from backend.app.modules.design.generation.maas.selection.formal_refinement import enforce_formal_diversity_replacements
from backend.app.modules.design.generation.maas.selection.island_refinement import enforce_island_quota_replacements
from backend.app.modules.design.generation.maas.selection.preference_guards import PreferenceGuardCallbacks, enforce_final_direct_llm_minimum, enforce_final_vlm_preference_minimum, recover_final_vlm_review_metrics
from backend.app.modules.design.generation.maas.selection.quota import duplicate_role_pattern_counts, formal_candidate_key, formal_counts, island_candidate_key, island_counts, strategy_counts
from backend.app.modules.design.generation.maas.selection.refinement import final_local_role_pattern, refine_final_review_set
from backend.app.modules.design.generation.maas.selection.recovery_refinement import build_review_replacement_pool, enforce_initial_recovery_replacements, height_bucket
from backend.app.modules.design.generation.maas.selection.state import SelectionState
from backend.app.modules.design.generation.maas.selection.types import Feature, FeatureBool, FeatureKey, FeatureText, FinalMetricCallbacks, FinalReviewRefinementCallbacks, FinalReviewRefinementPolicy, FormalDiversityCallbacks, IslandQuotaCallbacks, RecoveryRefinementCallbacks, ReviewSetConstraintCallbacks


__all__ = [
    "Feature",
    "FeatureBool",
    "FeatureKey",
    "FeatureText",
    "BalancedSelectionDeps",
    "FinalMetricCallbacks",
    "FinalReviewRefinementCallbacks",
    "FinalReviewRefinementPolicy",
    "FormalDiversityCallbacks",
    "IslandQuotaCallbacks",
    "RecoveryRefinementCallbacks",
    "ReviewSetConstraintCallbacks",
    "SelectionState",
    "PreferenceGuardCallbacks",
    "build_review_replacement_pool",
    "duplicate_role_pattern_counts",
    "enforce_formal_diversity_replacements",
    "enforce_final_direct_llm_minimum",
    "enforce_final_vlm_preference_minimum",
    "enforce_island_quota_replacements",
    "enforce_initial_recovery_replacements",
    "formal_candidate_key",
    "formal_counts",
    "height_bucket",
    "final_local_role_pattern",
    "final_hard_quotas_ok_after",
    "final_design_balanced_selection",
    "final_metric_snapshot",
    "final_metrics_ok_after",
    "final_mass_stage_parking_pass",
    "final_shape",
    "final_structural_quotas_ok_after",
    "island_candidate_key",
    "island_counts",
    "layout_status",
    "refine_final_review_set",
    "recover_final_vlm_review_metrics",
    "review_set_constraints_ok",
    "review_set_geometry_ok",
    "source_reviewable",
    "strategy_counts",
    "unresolved_llm_authoring",
    "unique_family_count_after",
    "visible_tier_count",
]
