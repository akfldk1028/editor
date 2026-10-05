"""Shared selection types and callback contracts for MAAS review selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


Feature = dict[str, Any]
FeatureBool = Callable[[Feature], bool]
FeatureKey = Callable[[Feature], Any]
FeatureText = Callable[[Feature], str | None]


@dataclass(frozen=True)
class FinalReviewRefinementCallbacks:
    """Optimizer-owned predicates used by final review-set refinement."""

    design_review_quality_key: FeatureKey
    has_review_source_geometry: FeatureBool
    is_agent_authored_candidate: FeatureBool
    is_clean_layered_anchor: FeatureBool
    is_direct_openai_llm_candidate: FeatureBool
    is_llm_authored_candidate: FeatureBool
    is_plain_capacity_anchor: FeatureBool
    is_reviewable_architectural_mass: FeatureBool
    research_mass_language: FeatureText
    source_family: FeatureText
    source_signature: Callable[[Feature], dict[str, Any]]


@dataclass(frozen=True)
class ReviewSetConstraintCallbacks:
    """Optimizer-owned predicates used by review-set constraint checks."""

    architectural_order_gate: Callable[[Feature], tuple[bool, tuple[str, ...]]]
    is_plain_review_mass: FeatureBool
    research_mass_language: FeatureText
    source_family: FeatureText
    visible_volume_count: Callable[[Feature], int]


@dataclass(frozen=True)
class FinalReviewRefinementPolicy:
    """Named review-set policy thresholds for the 20-card MAAS sheet."""

    min_direct_llm_candidates: int = 16
    max_dominant_height_count: int = 12
    max_role_pattern_repeat: int = 2
    max_language_repeat: int = 2
    min_research_language_diversity: int = 14
    min_source_family_diversity: int = 15
    max_parameter_default_ratio: float = 0.35


@dataclass(frozen=True)
class IslandQuotaCallbacks:
    """Optimizer-owned feature readers used by island quota selection."""

    design_synthesis_rank: Callable[[Feature], int]
    formal_principle: FeatureText
    has_review_source_geometry: FeatureBool
    is_direct_openai_llm_candidate: FeatureBool
    repair_retention: Callable[..., float]
    research_diversity_descriptor: Callable[[Feature], dict[str, Any]]
    research_quota_group: FeatureText
    research_role_pattern: FeatureText
    source_signature: Callable[[Feature], dict[str, Any]]
    visible_volume_count: Callable[[Feature], int]


@dataclass(frozen=True)
class FormalDiversityCallbacks:
    """Optimizer-owned feature readers used by formal/sectional diversity."""

    architectural_ambition: Callable[[Feature], dict[str, Any]]
    design_review_quality_key: FeatureKey
    formal_principle: FeatureText
    is_agent_authored_candidate: FeatureBool
    is_direct_openai_llm_candidate: FeatureBool
    stair_like_risk: FeatureText
    vertical_strategy: FeatureText


@dataclass(frozen=True)
class RecoveryRefinementCallbacks:
    """Optimizer-owned readers used by recovery-stage review refinement."""

    design_review_quality_key: FeatureKey
    formal_principle: FeatureText
    has_review_source_geometry: FeatureBool
    is_plain_capacity_anchor: FeatureBool
    is_reviewable_architectural_mass: FeatureBool
    repair_retention: Callable[..., float]


@dataclass(frozen=True)
class FinalMetricCallbacks:
    """Optimizer-owned readers used by final review-set metric checks."""

    final_family: FeatureText
    final_language: FeatureText
    final_parameter_default_ratio: Callable[[Feature], float]
    final_role_pattern: FeatureText
    final_volume_count: Callable[[Feature], int]
    height_bucket: FeatureText
    is_agent_authored_candidate: FeatureBool
    is_llm_authored_candidate: FeatureBool
    repair_retention: Callable[..., float]
    research_quota_group: FeatureText
