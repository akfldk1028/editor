"""Typed bridge from board-level VLM actions to next-run diversity policy."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Any

from backend.app.modules.design.generation.maas.book_language.candidate_analysis import _Candidate, _chassis_family, _geometry_program_family
from backend.app.modules.design.generation.maas.geometry_language.chassis_taxonomy import core_chassis_families


def enrich_portfolio_vlm_feedback(
    audit: dict[str, Any],
    *,
    rows: list[dict[str, Any]],
    candidates: list[_Candidate],
) -> dict[str, Any]:
    """Attach measured family action counts to a board VLM response.

    The critic already returns typed candidate IDs with KEEP/REPLACE actions.
    Resolve those IDs against the exact selected ASTs here, rather than
    parsing free-form rationale for family names.  A family with at least two
    replacement votes and more replacements than keeps becomes a next-run
    supply cap candidate; no individual geometry gains approval from this.
    """
    descriptors = [{
        "candidate_id": str(row.get("variant_id") or ""),
        "geometry_family": _geometry_program_family(candidate),
        "chassis_family": _chassis_family(candidate),
    } for row, candidate in zip(rows, candidates)]
    return enrich_portfolio_vlm_feedback_from_descriptors(
        audit,
        candidate_descriptors=descriptors,
    )


def enrich_portfolio_vlm_feedback_from_descriptors(
    audit: dict[str, Any],
    *,
    candidate_descriptors: list[dict[str, Any]],
) -> dict[str, Any]:
    """Resolve critic actions against persisted exact-AST descriptors.

    Post-run board audits no longer have live ``_Candidate`` objects. They do
    retain each selected result's exact geometry/chassis descriptor, so this
    shared boundary produces the same typed next-run feedback without
    recompiling geometry or parsing free-form VLM prose.
    """

    result = deepcopy(audit)
    family_by_candidate_id = {
        str(item.get("candidate_id") or ""): str(item.get("geometry_family") or "")
        for item in candidate_descriptors
        if isinstance(item, dict)
    }
    chassis_by_candidate_id = {
        str(item.get("candidate_id") or ""): str(item.get("chassis_family") or "")
        for item in candidate_descriptors
        if isinstance(item, dict)
    }
    action_counts: dict[str, Counter[str]] = {}
    chassis_action_counts: dict[str, Counter[str]] = {}
    for action in result.get("candidate_actions") or ():
        if not isinstance(action, dict):
            continue
        candidate_id = str(action.get("candidate_id") or "")
        family = family_by_candidate_id.get(candidate_id, "")
        decision = str(action.get("decision") or "")
        if not family or decision not in {"keep", "replace"}:
            if decision not in {"keep", "replace"}:
                continue
        if family:
            action_counts.setdefault(family, Counter())[decision] += 1
        chassis = chassis_by_candidate_id.get(candidate_id, "")
        if chassis:
            chassis_action_counts.setdefault(chassis, Counter())[decision] += 1
    serialized = {
        family: {
            "keep": int(counts.get("keep", 0)),
            "replace": int(counts.get("replace", 0)),
        }
        for family, counts in sorted(action_counts.items())
    }
    overrepresented = [
        family for family, counts in serialized.items()
        if counts["replace"] >= 2 and counts["replace"] > counts["keep"]
    ]
    serialized_chassis = {
        chassis: {
            "keep": int(counts.get("keep", 0)),
            "replace": int(counts.get("replace", 0)),
        }
        for chassis, counts in sorted(chassis_action_counts.items())
    }
    overrepresented_chassis = [
        chassis for chassis, counts in serialized_chassis.items()
        if counts["replace"] >= 2
        and counts["replace"] > counts["keep"]
    ]
    present_chassis = {
        chassis for chassis in chassis_by_candidate_id.values() if chassis
    }
    underrepresented_chassis = [] if bool(result.get("hard_pass")) else [
        f"recursive_chassis:{chassis}"
        for chassis in core_chassis_families()
        if f"recursive_chassis:{chassis}" not in present_chassis
    ]
    result["geometry_family_action_counts"] = serialized
    result["overrepresented_geometry_families"] = overrepresented
    result["chassis_family_action_counts"] = serialized_chassis
    result["overrepresented_chassis_families"] = overrepresented_chassis
    result["underrepresented_chassis_families"] = underrepresented_chassis
    result["typed_family_feedback_contract"] = (
        "candidate_id_to_exact_ast_family_and_normalized_chassis; "
        "next_run_supply_caps_and_missing_chassis_review_anchors_only"
    )
    return result


__all__ = [
    "enrich_portfolio_vlm_feedback",
    "enrich_portfolio_vlm_feedback_from_descriptors",
]
