"""One exact final-solid VLM review and typed-repair cycle.

The benchmark used to carry two near-identical copies of this causal loop:
final render review -> typed AST repair -> downstream legal/parking gate ->
second final render review.  Keeping the loop here gives initial generation
and every bounded replenishment variant one implementation and one evidence
contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from backend.app.modules.design.generation.maas.book_language.candidate_analysis import _Candidate
from backend.app.modules.design.generation.maas.book_language.capacity_routing import route_capacity_target_hard_passes
from backend.app.modules.design.generation.maas.book_language.downstream_hard_gate import evaluate_accepted_sources_downstream
from backend.app.modules.design.generation.maas.book_language.portfolio_selection import _bounded_visual_selection_pool
from backend.app.modules.design.generation.maas.book_language.vlm_review import _audit_final_book_geometry_with_vlm, _repair_exact_post_book_candidates_from_vlm
from backend.app.modules.design.generation.maas.paid_provider_budget import paid_provider_budget_snapshot


@dataclass(frozen=True)
class FinalVlmCycleResult:
    selection_pool: list[_Candidate]
    initial_vlm_passes: list[_Candidate]
    initial_vlm_gate: dict[str, Any]
    repair_pool: list[_Candidate]
    repair_vlm_passes: list[_Candidate]
    repair_evidence: dict[str, Any]
    final_vlm_gate: dict[str, Any]


def _bounded_final_review_pool(pool: list[_Candidate]) -> list[_Candidate]:
    """Review every valid descendant when the live pool is five or smaller."""

    return list(pool) if len(pool) <= 5 else _bounded_visual_selection_pool(pool)


def _expected_repair_finalization_context(
    base_capacity_contract: dict[str, Any] | None,
    downstream_context: dict[str, Any],
) -> dict[str, str]:
    capacity_contract = base_capacity_contract or {}
    legal_floor_field = capacity_contract.get("legal_floor_field") or {}
    return {
        "pnu": str(downstream_context.get("pnu") or ""),
        "legal_floor_field_hash": str(
            legal_floor_field.get("legal_floor_field_hash")
            or capacity_contract.get("legal_floor_field_hash")
            or ""
        ),
        "floor_capacity_plan_hash": str(
            capacity_contract.get("floor_capacity_plan_hash") or ""
        ),
    }


def run_final_vlm_cycle(
    review_pool: list[_Candidate],
    *,
    retained_hard_passes: list[_Candidate],
    building_type: str,
    output_dir: Path,
    visual_directive: dict[str, Any],
    outcome_graph: Any,
    program_slug: str,
    generation_site: Any,
    height: float,
    floors: int,
    generation_context: Any,
    program_dimensional_context: dict[str, Any] | None,
    site_boundary_source: str,
    site_access_context: dict[str, Any] | None,
    site_access_geometry: dict[str, Any] | None,
    base_capacity_contract: dict[str, Any] | None,
    downstream_context: dict[str, Any],
    hard_gate_summary: Callable[[dict[str, Any] | None, list[_Candidate]], dict[str, Any]],
    completion_status: str,
    no_repair_status: str,
    target_count: int | None = None,
) -> FinalVlmCycleResult:
    """Run the exact causal review loop without relaxing any hard gate."""
    if target_count is None:
        configured_target = (
            paid_provider_budget_snapshot().get("run_metadata") or {}
        ).get("target_count")
        if configured_target is not None:
            target_count = max(0, int(configured_target))
    _capacity_routed_review_pool, initial_capacity_routing = (
        route_capacity_target_hard_passes(
            review_pool,
            stage="initial_final_book_paid_vlm",
        )
    )
    initial_capacity_routing = {
        **initial_capacity_routing,
        "authority": "diagnostic_only",
        "selection_effect": "none",
    }
    routed_review_pool = list(review_pool)
    bounded_review_pool = _bounded_final_review_pool(routed_review_pool)
    if not bounded_review_pool:
        initial_gate = {
            "schema_version": "arr.maas.final_book_vlm_portfolio_gate.v2",
            "required": True,
            "status": initial_capacity_routing["status"],
            "input_count": len(review_pool),
            "shortlist_count": 0,
            "scored_count": 0,
            "hard_pass_count": 0,
            "post_book_geometry_reviewed": False,
            "synthetic_fallback_used": False,
            "capacity_target_routing": initial_capacity_routing,
            "no_call_reason": (
                "routing_pool_empty"
                if not review_pool
                else "routing_pool_empty_after_diagnostic_routing"
            ),
        }
        repair_vlm_gate = {
            "schema_version": "arr.maas.final_book_vlm_portfolio_gate.v1",
            "required": True,
            "status": no_repair_status,
            "input_count": 0,
            "hard_pass_count": 0,
            "post_book_geometry_reviewed": False,
            "synthetic_fallback_used": False,
        }
        repair_evidence = {
            "repaired_candidate_count": 0,
            "preselection_hard_gate": hard_gate_summary(None, []),
            "final_book_vlm_gate": repair_vlm_gate,
            "accepted_after_second_vlm_count": 0,
            "same_run_causal_loop_closed": True,
        }
        final_gate = {
            **initial_gate,
            "status": initial_capacity_routing["status"],
            "retained_prior_vlm_hard_pass_count": len(retained_hard_passes),
            "initial_hard_pass_count": 0,
            "exact_repair_hard_pass_count": 0,
            "hard_pass_count": len(retained_hard_passes),
            "selection_pool_contains_only_vlm_hard_passes": True,
            "initial_capacity_target_routing": initial_capacity_routing,
            "exact_post_book_typed_repair_executed": False,
            "exact_post_book_typed_repair_gate": repair_vlm_gate,
        }
        return FinalVlmCycleResult(
            selection_pool=_bounded_final_review_pool(
                list(retained_hard_passes)
            ),
            initial_vlm_passes=[],
            initial_vlm_gate=initial_gate,
            repair_pool=[],
            repair_vlm_passes=[],
            repair_evidence=repair_evidence,
            final_vlm_gate=final_gate,
        )
    initial_opportunity_limit = (
        2 * max(0, int(target_count))
        if target_count is not None
        else None
    )
    initial_passes, initial_gate = _audit_final_book_geometry_with_vlm(
        bounded_review_pool,
        building_type=building_type,
        output_dir=output_dir,
        visual_directive=visual_directive,
        outcome_graph=outcome_graph,
        program_slug=program_slug,
        request_kind="exact_candidate_vlm",
        paid_opportunity_limit=initial_opportunity_limit,
    )
    initial_gate = {
        **initial_gate,
        "capacity_target_routing": initial_capacity_routing,
    }
    repair_pool, repair_counts = _repair_exact_post_book_candidates_from_vlm(
        bounded_review_pool,
        initial_gate,
        generation_site=generation_site,
        building_type=building_type,
        height=height,
        floors=floors,
        generation_context=generation_context,
        program_dimensional_context=program_dimensional_context,
        site_boundary_source=site_boundary_source,
        site_access_context=site_access_context,
        site_access_geometry=site_access_geometry,
        base_capacity_contract=base_capacity_contract,
        capacity_site=downstream_context.get("site_local_utm"),
        expected_finalization_context=(
            _expected_repair_finalization_context(
                base_capacity_contract,
                downstream_context,
            )
        ),
    )
    repair_hard_gate = None
    repair_selection_pool = list(repair_pool)
    if generation_context is not None and repair_pool:
        repair_hard_gate = evaluate_accepted_sources_downstream(
            repair_pool,
            **downstream_context,
        )
        repair_selection_pool = [
            candidate
            for candidate, row in zip(repair_pool, repair_hard_gate["rows"])
            if row["combined_hard_pass"]
        ]
    _capacity_routed_repair_pool, repair_capacity_routing = (
        route_capacity_target_hard_passes(
            repair_selection_pool,
            stage="repaired_final_book_paid_vlm",
        )
    )
    repair_capacity_routing = {
        **repair_capacity_routing,
        "authority": "diagnostic_only",
        "selection_effect": "none",
    }
    if repair_selection_pool:
        repair_vlm_passes, repair_vlm_gate = _audit_final_book_geometry_with_vlm(
            _bounded_final_review_pool(repair_selection_pool),
            building_type=building_type,
            output_dir=output_dir / "exact-post-book-typed-repair",
            visual_directive=visual_directive,
            outcome_graph=outcome_graph,
            program_slug=program_slug,
            request_kind="exact_candidate_vlm",
            paid_opportunity_limit=(
                3 * max(0, int(target_count))
                if target_count is not None
                else None
            ),
        )
    else:
        repair_vlm_passes = []
        repair_vlm_gate = {
            "schema_version": "arr.maas.final_book_vlm_portfolio_gate.v1",
            "required": True,
            "status": no_repair_status,
            "input_count": 0,
            "hard_pass_count": 0,
            "post_book_geometry_reviewed": False,
            "synthetic_fallback_used": False,
        }
    repair_vlm_gate = {
        **repair_vlm_gate,
        "capacity_target_routing": repair_capacity_routing,
    }
    _capacity_routed_selection_pool, final_capacity_routing = (
        route_capacity_target_hard_passes(
            [
                *retained_hard_passes,
                *initial_passes,
                *repair_vlm_passes,
            ],
            stage="final_vlm_selection_pool",
        )
    )
    final_capacity_routing = {
        **final_capacity_routing,
        "authority": "diagnostic_only",
        "selection_effect": "none",
    }
    capacity_valid_selection_pool = [
        *retained_hard_passes,
        *initial_passes,
        *repair_vlm_passes,
    ]
    selection_pool = _bounded_final_review_pool(capacity_valid_selection_pool)
    repair_evidence = {
        **repair_counts,
        "preselection_hard_gate": hard_gate_summary(repair_hard_gate, repair_pool),
        "final_book_vlm_gate": repair_vlm_gate,
        "accepted_after_second_vlm_count": len(repair_vlm_passes),
        "same_run_causal_loop_closed": True,
    }
    final_gate = {
        **initial_gate,
        "schema_version": "arr.maas.final_book_vlm_portfolio_gate.v2",
        "status": completion_status,
        "retained_prior_vlm_hard_pass_count": len(retained_hard_passes),
        "initial_hard_pass_count": len(initial_passes),
        "exact_repair_hard_pass_count": len(repair_vlm_passes),
        "hard_pass_count": len(selection_pool),
        "selection_pool_contains_only_vlm_hard_passes": True,
        "initial_capacity_target_routing": initial_capacity_routing,
        "capacity_target_routing": final_capacity_routing,
        "exact_post_book_typed_repair_executed": True,
        "exact_post_book_typed_repair_gate": repair_vlm_gate,
    }
    return FinalVlmCycleResult(
        selection_pool=selection_pool,
        initial_vlm_passes=initial_passes,
        initial_vlm_gate=initial_gate,
        repair_pool=repair_pool,
        repair_vlm_passes=repair_vlm_passes,
        repair_evidence=repair_evidence,
        final_vlm_gate=final_gate,
    )


__all__ = ["FinalVlmCycleResult", "run_final_vlm_cycle"]
