"""Fail-closed completeness rules for an alternative-design MASS portfolio."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


MINIMUM_PORTFOLIO_ALTERNATIVES = 10
FULL_PORTFOLIO_TARGET = 20


@dataclass(frozen=True)
class PortfolioRequirement:
    """Separate publishable design scope from cost/search controls."""

    minimum_count: int
    selection_target: int
    required_scope_count: int
    smoke_mode: bool

    def to_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": "arr.maas.portfolio_requirement.v1",
            **asdict(self),
            "smoke_controls_cost_only": True,
        }


def resolve_portfolio_requirement(
    *,
    smoke_mode: bool,
    base_volume_scope_count: int,
) -> PortfolioRequirement:
    """Return the immutable alternative-design requirement for this run.

    A smoke run searches for the minimum publishable portfolio. A full run
    retains the historic 20-member target. Neither mode may call one selected
    MASS an alternative-design portfolio.
    """

    return PortfolioRequirement(
        minimum_count=MINIMUM_PORTFOLIO_ALTERNATIVES,
        selection_target=(
            MINIMUM_PORTFOLIO_ALTERNATIVES
            if smoke_mode
            else FULL_PORTFOLIO_TARGET
        ),
        required_scope_count=max(0, int(base_volume_scope_count)),
        smoke_mode=bool(smoke_mode),
    )


def resolve_progressive_portfolio_requirement(
    *,
    target_count: int,
    base_volume_scope_count: int,
) -> PortfolioRequirement:
    """Return a complete reduced 3/5/10/20 promotion requirement."""

    target = int(target_count)
    if target not in (3, 5, 10, 20):
        raise ValueError(
            "progressive MASS target must be one of 3, 5, 10, or 20"
        )
    return PortfolioRequirement(
        minimum_count=target,
        selection_target=target,
        required_scope_count=min(
            target,
            max(0, int(base_volume_scope_count)),
        ),
        smoke_mode=False,
    )


def evaluate_portfolio_completion(
    requirement: PortfolioRequirement,
    *,
    selected_count: int,
    selected_scope_count: int,
    runtime_live_vlm: bool,
    exact_vlm_hard_pass_count: int,
    require_llm_authored_ast: bool,
    llm_authored_selected_count: int,
    portfolio_vlm_audit: dict[str, Any] | None,
) -> dict[str, Any]:
    """Evaluate only evidence that cannot be inferred from a skipped stage."""

    selected_count = max(0, int(selected_count))
    selected_scope_count = max(0, int(selected_scope_count))
    exact_vlm_hard_pass_count = max(0, int(exact_vlm_hard_pass_count))
    llm_authored_selected_count = max(0, int(llm_authored_selected_count))
    audit = dict(portfolio_vlm_audit or {})
    failures: list[str] = []

    if selected_count < requirement.minimum_count:
        failures.append(
            f"selected_count_below_minimum_{requirement.minimum_count}"
        )
    if selected_scope_count < requirement.required_scope_count:
        failures.append(
            f"base_volume_scope_count_below_{requirement.required_scope_count}"
        )
    if runtime_live_vlm:
        if exact_vlm_hard_pass_count < selected_count:
            failures.append(
                "exact_post_book_vlm_hard_pass_count_below_selected_count"
            )
        if audit.get("evaluated") is not True:
            failures.append("portfolio_vlm_audit_not_evaluated")
        elif audit.get("hard_pass") is not True:
            failures.append("portfolio_vlm_visual_diversity_hard_gate_failed")
    if require_llm_authored_ast and llm_authored_selected_count < 1:
        failures.append("selected_llm_authored_ast_missing")
    if (
        require_llm_authored_ast
        and llm_authored_selected_count < selected_count
    ):
        failures.append(
            "selected_llm_authored_ast_count_below_selected_count"
        )

    return {
        "schema_version": "arr.maas.portfolio_completion.v1",
        "hard_pass": not failures,
        "failures": failures,
        "requirement": requirement.to_evidence(),
        "selected_count": selected_count,
        "selected_scope_count": selected_scope_count,
        "runtime_live_vlm": bool(runtime_live_vlm),
        "exact_vlm_hard_pass_count": exact_vlm_hard_pass_count,
        "require_llm_authored_ast": bool(require_llm_authored_ast),
        "llm_authored_selected_count": llm_authored_selected_count,
        "portfolio_vlm_audit_status": str(audit.get("status") or ""),
        "portfolio_vlm_audit_evaluated": audit.get("evaluated") is True,
    }


__all__ = [
    "FULL_PORTFOLIO_TARGET",
    "MINIMUM_PORTFOLIO_ALTERNATIVES",
    "PortfolioRequirement",
    "evaluate_portfolio_completion",
    "resolve_portfolio_requirement",
    "resolve_progressive_portfolio_requirement",
]
