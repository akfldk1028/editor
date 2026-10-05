"""Immutable budgets for progressive lawful MASS portfolio runs."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil


MAX_REPLENISHMENT_CYCLES = 8


@dataclass(frozen=True)
class MassRunBudget:
    target_count: int
    raw_target: int
    compile_limit: int
    timeout_seconds: int
    configured_base_top_k: int = 8
    exact_acceptance_multiplier: int = 3
    portfolio_board_reserve: int = 1
    reference_audit_allowance: int = 0
    retry_allowance: int = 0
    replenishment_author_reserve: int | None = None
    base_diversity_reserve: int = 0
    replenishment_compile_reserve: int = 0

    @property
    def cluster_maximum(self) -> int:
        """Uniform cap for any certified-mesh cluster, regardless of label."""

        return max(1, ceil(self.target_count * 0.25))

    @property
    def author_batch_count(self) -> int:
        return ceil(self.raw_target / 24)

    @property
    def initial_author_request_limit(self) -> int:
        return self.author_batch_count

    @property
    def initial_compile_limit(self) -> int:
        """Bound initial search while reserving exact work for feedback."""

        return max(
            0,
            self.compile_limit
            - max(0, self.replenishment_compile_reserve),
        )

    @property
    def replenishment_author_request_limit(self) -> int:
        requested = (
            self.target_count
            if self.replenishment_author_reserve is None
            else int(self.replenishment_author_reserve)
        )
        return min(
            MAX_REPLENISHMENT_CYCLES,
            max(0, int(self.target_count)),
            max(0, requested),
        )

    @property
    def base_parent_review_budget(self) -> int:
        """Paid parent audits, bounded by the configured base shortlist."""

        return min(
            self.target_count + max(0, self.base_diversity_reserve),
            max(0, self.configured_base_top_k),
        )

    @property
    def exact_acceptance_opportunities(self) -> int:
        """Exact candidate audits available across acceptance stages."""

        return self.target_count * self.exact_acceptance_multiplier

    @property
    def provider_request_quotas(self) -> dict[str, int]:
        return {
            "author_initial": self.initial_author_request_limit,
            "author_replenishment": self.replenishment_author_request_limit,
            "base_candidate": self.base_parent_review_budget,
            "exact_candidate": self.exact_acceptance_opportunities,
            "portfolio_board": self.portfolio_board_reserve,
            "reference_audit": self.reference_audit_allowance,
            "retry": self.retry_allowance,
        }

    @property
    def total_provider_request_limit(self) -> int:
        return sum(self.provider_request_quotas.values())

    @property
    def live_vlm_request_limit(self) -> int:
        """VLM-only transport ceiling; author requests use their own quota."""

        return sum(
            value
            for name, value in self.provider_request_quotas.items()
            if name not in {"author_initial", "author_replenishment"}
        )


_PROGRESSIVE_BUDGETS = {
    3: MassRunBudget(3, 36, 24, 45 * 60),
    # Target 5 interpolates the target-3 and target-10 search envelopes at
    # 2/7, rounding raw/compile capacity upward and runtime to the next
    # practical 15-minute boundary. This preserves monotonic bounded scaling
    # while funding three initial author batches plus replenishment.
    5: MassRunBudget(
        5,
        52,
        60,
        60 * 60,
        base_diversity_reserve=2,
        replenishment_compile_reserve=12,
    ),
    10: MassRunBudget(10, 90, 70, 90 * 60),
    20: MassRunBudget(20, 160, 120, 180 * 60),
}


def progressive_mass_run_budget(target_count: int) -> MassRunBudget:
    try:
        return _PROGRESSIVE_BUDGETS[int(target_count)]
    except (KeyError, TypeError, ValueError):
        raise ValueError(
            "progressive MASS target must be one of 3, 5, 10, or 20"
        ) from None


def replenishment_allowed_by_deadline(
    *,
    started_at: float,
    timeout_seconds: int,
    now: float,
) -> bool:
    """Start another expensive cycle only with 60 percent time in reserve."""

    elapsed = max(0.0, float(now) - float(started_at))
    remaining = max(0.0, float(timeout_seconds) - elapsed)
    return remaining + 1e-9 >= float(timeout_seconds) * 0.60


__all__ = [
    "MAX_REPLENISHMENT_CYCLES",
    "MassRunBudget",
    "progressive_mass_run_budget",
    "replenishment_allowed_by_deadline",
]
