"""Stage-specific quality contracts for BOOK image review.

The base operative is an intermediate design state.  It must be coherent and
developable, but it is not yet the final competition entry.  Keeping these
contracts separate prevents a final-board rubric from erasing useful base
languages before combinations and aggregations can develop them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class BookVlmStagePolicy:
    stage: str
    role: str
    require_program_fit: bool
    blocking_actions: frozenset[str]
    quality_floors: Mapping[str, float]
    quality_floor_label: str
    quality_floors_hard_gate: bool
    locally_derived_actions_hard_gate: bool
    require_finished_silhouette: bool
    minimum_feasible_capacity_utilization: float
    capacity_normalization: str

    def to_evidence(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "role": self.role,
            "require_program_fit": self.require_program_fit,
            "blocking_actions": sorted(self.blocking_actions),
            "quality_floors": dict(self.quality_floors),
            "quality_floor_label": self.quality_floor_label,
            "quality_floors_hard_gate": self.quality_floors_hard_gate,
            "locally_derived_actions_hard_gate": self.locally_derived_actions_hard_gate,
            "require_finished_silhouette": self.require_finished_silhouette,
            "minimum_feasible_capacity_utilization": self.minimum_feasible_capacity_utilization,
            "capacity_normalization": self.capacity_normalization,
        }


BASE_OPERATIVE_POLICY = BookVlmStagePolicy(
    stage="book_base_operative",
    role="developable_parent_before_descendant_release",
    require_program_fit=False,
    blocking_actions=frozenset({
        "too_fragmented",
        "weak_primary_mass",
        "too_many_surface_pieces",
        "overlapping_volumes",
    }),
    quality_floors={
        "gesture_clarity": 0.58,
        "hierarchy": 0.58,
        "repair_integrity": 0.60,
    },
    quality_floor_label="development_floor",
    quality_floors_hard_gate=True,
    locally_derived_actions_hard_gate=True,
    require_finished_silhouette=False,
    minimum_feasible_capacity_utilization=0.40,
    capacity_normalization="book_scope_fraction",
)


FINAL_BOOK_POLICY = BookVlmStagePolicy(
    stage="final_book",
    role="exact_post_book_competition_gate",
    require_program_fit=True,
    blocking_actions=frozenset({
        "too_fragmented",
        "weak_primary_mass",
        "needs_clean_anchor",
        "too_many_surface_pieces",
        "overlapping_volumes",
        "too_box_like",
        "weak_form_continuity",
        "wrong_program_typology",
        "missing_program_section",
    }),
    quality_floors={
        "gesture_clarity": 0.72,
        "hierarchy": 0.70,
        "repair_integrity": 0.68,
        "program_appropriateness": 0.65,
    },
    quality_floor_label="competition_floor",
    quality_floors_hard_gate=False,
    locally_derived_actions_hard_gate=False,
    require_finished_silhouette=True,
    # Capacity target remains 0.78 in the data-backed feasible-capacity
    # contract.  The image gate only rejects forms below the shared creative
    # feasibility floor; legal/FAR/parking and selection still score the exact
    # achieved capacity downstream.
    minimum_feasible_capacity_utilization=0.40,
    capacity_normalization="none",
)


def book_vlm_stage_policy(review_stage: str) -> BookVlmStagePolicy:
    if review_stage == BASE_OPERATIVE_POLICY.stage:
        return BASE_OPERATIVE_POLICY
    return FINAL_BOOK_POLICY


__all__ = [
    "BASE_OPERATIVE_POLICY",
    "BookVlmStagePolicy",
    "FINAL_BOOK_POLICY",
    "book_vlm_stage_policy",
]
