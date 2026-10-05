"""Agent revision trace assembly for MAAS selection."""

from __future__ import annotations

from collections import Counter
from typing import Any, Callable

from backend.app.modules.design.generation.maas.performance_objectives import early_massing_performance_proxy

OrderGate = Callable[[dict[str, Any]], tuple[bool, tuple[str, ...]]]
Classifier = Callable[[dict[str, Any]], str | None]


def _is_evolved_candidate(feature: dict[str, Any]) -> bool:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    mass_shape = str(props.get("mass_shape") or "")
    if "__evo_" in mass_shape or "__critic_" in mass_shape:
        return True
    notes = props.get("notes")
    if isinstance(notes, list) and any("evolution_operator=" in str(note) or "__evo_" in str(note) for note in notes):
        return True
    sequence = props.get("maas_verb_sequence")
    if isinstance(sequence, list):
        for call in sequence:
            if not isinstance(call, dict):
                continue
            if "__evo_" in str(call.get("verb") or "") or "__evo_" in str(call.get("params") or ""):
                return True
    return False


def build_agent_revision_trace(
    *,
    selected: list[dict[str, Any]],
    legal_candidate_pool: list[dict[str, Any]],
    agent_reviews: list[dict[str, Any]],
    order_gate: OrderGate,
    source_family: Classifier,
    formal_principle: Classifier,
    evolution_trace: dict[str, Any] | None = None,
    critic_geometry_loop: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record how agent critique changed the final review set.

    This is a selection-revision trace. A future generator-level loop should
    mutate MassDSL geometry after critique and then re-run legal/parking gates.
    """
    selected_shapes = {
        str((feature.get("properties") or {}).get("mass_shape") or "")
        for feature in selected
    }
    excluded = [
        feature
        for feature in legal_candidate_pool
        if str((feature.get("properties") or {}).get("mass_shape") or "") not in selected_shapes
    ]
    order_failures = Counter(
        issue
        for feature in excluded
        for issue in order_gate(feature)[1]
    )
    selected_order_issues = Counter(
        issue
        for feature in selected
        for issue in order_gate(feature)[1]
    )
    selected_performance: list[float] = []
    candidate_summaries: list[dict[str, Any]] = []
    for rank, feature in enumerate(selected[:20], start=1):
        props = feature.setdefault("properties", {})
        performance = props.get("performance_proxy_evidence")
        if not isinstance(performance, dict):
            performance = early_massing_performance_proxy(feature)
            props["performance_proxy_evidence"] = performance
        selected_performance.append(float(performance.get("aggregate_performance_proxy") or 0.0))
        order_pass, order_issues = order_gate(feature)
        candidate_summaries.append(
            {
                "rank": rank,
                "variant_id": props.get("variant_id"),
                "mass_shape": props.get("mass_shape"),
                "family": source_family(feature) or "unknown",
                "formal_principle": formal_principle(feature) or "unknown",
                "revision_decision": "kept_after_agent_gates" if order_pass else "kept_with_open_issues",
                "order_gate_pass": order_pass,
                "order_issues": list(order_issues),
                "performance_proxy": performance.get("aggregate_performance_proxy"),
                "selection_trace_stages": [
                    event.get("stage")
                    for event in (props.get("selection_trace") or [])
                    if isinstance(event, dict) and event.get("stage")
                ],
            }
        )
    legal_pool_evolved_count = sum(1 for feature in legal_candidate_pool if _is_evolved_candidate(feature))
    selected_evolved_count = sum(1 for feature in selected if _is_evolved_candidate(feature))
    has_geometry_mutation = bool(
        (
            isinstance(critic_geometry_loop, dict)
            and int(critic_geometry_loop.get("accepted_child_count") or 0) > 0
        )
        or (
            isinstance(evolution_trace, dict)
            and int(evolution_trace.get("accepted_child_count") or 0) > 0
        )
    ) and legal_pool_evolved_count > 0
    return {
        "schema_version": "arr.maas.agent_revision_trace.v1",
        "revision_type": (
            "critic_to_geometry_mutation"
            if has_geometry_mutation
            else "selection_revision_not_geometry_mutation"
        ),
        "paper_alignment_note": (
            "Agent review now includes first-generation MassDSL geometry "
            "mutation that survived legal candidate generation before "
            "parking/final selection."
            if has_geometry_mutation
            else (
                "Agent reviews currently revise the final candidate set through "
                "legal/parking/order/performance gates. They do not yet regenerate "
                "new MassDSL geometry after critique."
            )
        ),
        "agent_review_count": len(agent_reviews),
        "candidate_pool_count": len(legal_candidate_pool),
        "legal_pool_evolved_candidate_count": legal_pool_evolved_count,
        "selected_evolved_candidate_count": selected_evolved_count,
        "final_count": len(selected),
        "agents": [
            str(review.get("agent") or "")
            for review in agent_reviews
            if isinstance(review, dict) and review.get("agent")
        ],
        "applied_revision_rules": [
            {
                "agent": "law_graph_agent",
                "action": "preserve legal envelope and FAR/BCR/height gates as hard constraints",
            },
            {
                "agent": "master_plan_agent",
                "action": "keep only mass-stage parking-feasible candidates in final review set",
            },
            {
                "agent": "grammar_critic_agent",
                "action": "penalize unclear language mixes, stair-like overuse, fragments, and weak hierarchy",
            },
            {
                "agent": "preference_distiller_agent",
                "action": "rank with reference/VLM preference evidence when available and geometry proxy otherwise",
            },
            {
                "agent": "maas_geometry_agent",
                "action": "prefer source geometry, source repair retention, and selection trace evidence",
            },
        ],
        "excluded_order_failure_counts": dict(order_failures),
        "selected_order_issue_counts": dict(selected_order_issues),
        "selected_family_counts": dict(Counter(source_family(feature) or "unknown" for feature in selected)),
        "selected_formal_principle_counts": dict(Counter(formal_principle(feature) or "unknown" for feature in selected)),
        "selected_average_performance_proxy": (
            round(sum(selected_performance) / len(selected_performance), 4)
            if selected_performance
            else 0.0
        ),
        "evolution_trace_summary": {
            "schema_version": evolution_trace.get("schema_version"),
            "method": evolution_trace.get("method"),
            "status": evolution_trace.get("status"),
            "accepted_child_count": evolution_trace.get("accepted_child_count"),
            "rejected_child_count": evolution_trace.get("rejected_child_count"),
            "legal_pool_evolved_candidate_count": legal_pool_evolved_count,
            "selected_evolved_candidate_count": selected_evolved_count,
            "paper_alignment_status": evolution_trace.get("paper_alignment_status"),
        } if isinstance(evolution_trace, dict) else None,
        "candidate_revisions": candidate_summaries,
        "next_required_step": (
            "multi_generation_pareto_evolution_loop"
            if has_geometry_mutation
            else "geometry_mutation_revision_loop"
        ),
    }


__all__ = ["build_agent_revision_trace"]
