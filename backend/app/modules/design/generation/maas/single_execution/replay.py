"""Shared replay context extraction for HTTP and management entry points."""

from __future__ import annotations

from typing import Any


_DOWNSTREAM_STAGE_IDS = frozenset({
    "site",
    "capacity",
    "law",
    "parking",
    "program_fit",
    "selector",
})


def downstream_evidence_from_passport(
    passport: dict[str, Any],
) -> dict[str, Any]:
    """Preserve evaluated source-stage evidence when one MASS is replayed."""

    evidence: dict[str, Any] = {}
    for stage in passport.get("stages") or ():
        if (
            not isinstance(stage, dict)
            or stage.get("id") not in _DOWNSTREAM_STAGE_IDS
            or stage.get("status") == "not_evaluated"
        ):
            continue
        stage_id = str(stage.get("id"))
        stage_status = str(stage.get("status") or "")
        stage_evidence = dict(stage.get("evidence") or {})
        stage_evidence.setdefault("status", stage_status)
        stage_evidence.setdefault("evaluated", True)
        if "hard_pass" not in stage_evidence:
            stage_evidence["hard_pass"] = stage_status in {"passed", "accepted"}
        evidence[stage_id] = stage_evidence
    capacity = evidence.get("capacity")
    shared_floor_contract = (
        capacity.get("shared_floor_contract")
        if isinstance(capacity, dict)
        else None
    )
    if (
        isinstance(shared_floor_contract, dict)
        and shared_floor_contract.get("schema_version")
        == "arr.maas.shared_floor_contract.v1"
    ):
        plan_hash = str(
            shared_floor_contract.get("floor_capacity_plan_hash")
            or (
                shared_floor_contract.get("identity", {})
                if isinstance(
                    shared_floor_contract.get("identity"),
                    dict,
                )
                else {}
            ).get("floor_capacity_plan_hash")
            or ""
        )
        if isinstance(capacity, dict) and plan_hash:
            capacity.setdefault("floor_capacity_plan_hash", plan_hash)
        evidence["shared_floor_contract"] = dict(shared_floor_contract)
    return evidence


__all__ = ["downstream_evidence_from_passport"]
