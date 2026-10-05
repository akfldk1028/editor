"""Capacity-diagnostic routing between geometry gates and paid VLM review."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable, Mapping, TypeVar

from backend.app.modules.design.generation.maas.book_language.candidate_analysis import _capacity_target_gate


CandidateT = TypeVar("CandidateT")
CAPACITY_ROUTING_SCHEMA = "arr.maas.capacity_target_routing.v1"
CAPACITY_REVIEW_CONTEXT_SCHEMA = "arr.maas.capacity_review_context.v1"


def build_capacity_review_context(
    source_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the bounded capacity/floor context shown to the paid VLM."""

    alternative = source_metadata.get("capacity_alternative_projection")
    measurement = source_metadata.get("source_capacity_measurement")
    floor_contract = source_metadata.get("shared_floor_contract")
    alternative = alternative if isinstance(alternative, dict) else {}
    measurement = measurement if isinstance(measurement, dict) else {}
    floor_contract = floor_contract if isinstance(floor_contract, dict) else {}
    return {
        "schema_version": CAPACITY_REVIEW_CONTEXT_SCHEMA,
        "capacity_alternative": deepcopy(alternative),
        "capacity_measurement": deepcopy(measurement),
        "floor_contract_hash": str(
            floor_contract.get("floor_contract_hash") or ""
        ),
        "floor_capacity_plan_hash": str(
            floor_contract.get("floor_capacity_plan_hash") or ""
        ),
        "target_floor_areas_m2": [
            round(max(0.0, float(value)), 4)
            for value in floor_contract.get("target_floor_areas_m2", ())
        ],
        "floor_totals": deepcopy(floor_contract.get("totals") or {}),
        "capacity_target_authority": "diagnostic_only",
        "hard_gates_are_authoritative": False,
        "visual_review_must_not_relax_legal_or_parking_gates": True,
    }


def route_capacity_target_hard_passes(
    candidates: Iterable[CandidateT],
    *,
    stage: str,
) -> tuple[list[CandidateT], dict[str, Any]]:
    """Route every MASS candidate while retaining capacity diagnostics."""

    pool = list(candidates)
    gates = [_capacity_target_gate(candidate) for candidate in pool]
    measured_count = sum(gate is not None for gate in gates)
    routed = pool
    pass_count = sum(gate is True for gate in gates)
    advisory_miss_count = sum(gate is False for gate in gates)
    status = (
        "capacity_target_diagnostic_passthrough"
        if measured_count
        else ("legacy_unmeasured_passthrough" if pool else "empty_input")
    )
    return routed, {
        "schema_version": CAPACITY_ROUTING_SCHEMA,
        "stage": str(stage),
        "status": status,
        "input_count": len(pool),
        "measured_count": measured_count,
        "hard_pass_count": pass_count,
        "advisory_miss_count": advisory_miss_count,
        "rejected_before_paid_vlm_count": 0,
        "legacy_unmeasured_count": len(pool) - measured_count,
        "capacity_target_authority": "diagnostic_only",
        "paid_vlm_boundary": True,
    }


__all__ = [
    "CAPACITY_REVIEW_CONTEXT_SCHEMA",
    "CAPACITY_ROUTING_SCHEMA",
    "build_capacity_review_context",
    "route_capacity_target_hard_passes",
]
