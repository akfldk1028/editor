"""Bind a MasterPlanagent layout hand-off to one compiled MASS as master_plan_agent evidence.

MasterPlanagent (agents/MasterPlanagent) produces `masterplan.layout.v1` with a
`handoff` block: pnu, input_hash, geometry_hash, metric_geometry_hash, status,
evaluated, hard_pass. This adapter accepts that object for the specialist
chain's `master_plan_agent` seat and fails closed:

- a layout for another parcel, an unevaluated layout, or a layout whose
  features no longer hash to its own hand-off is `failed`, never ignored;
- `passed` only when the layout itself says hard_pass with status passed;
- anything else is `needs_evidence`, with the layout's own blocking reasons.

Nothing here re-measures geometry: MasterPlanagent's validation and ARR's
`design.maas.masterplan.validation` did that on the serialized features.
"""
from __future__ import annotations

from typing import Any, Mapping

from backend.app.modules.design.generation.maas.agents.shared.types import AgentEvidence, ExecutionIdentity
from backend.app.modules.design.generation.maas.masterplan.geometry import digest

LAYOUT_SCHEMA = "masterplan.layout.v1"
EVIDENCE_ID = "evidence:master_plan_agent"
AGENT_ID = "master_plan_agent"
_METRIC_KEYS = ("site_area_m2", "building_footprint_m2", "coverage_ratio_pct", "bcr_limit_pct",
                "required_parking_stalls", "provided_parking_stalls", "parking_strategy", "basement_levels")


def is_masterplan_layout(value: Any) -> bool:
    return isinstance(value, Mapping) and value.get("schema_version") == LAYOUT_SCHEMA and isinstance(value.get("handoff"), Mapping)


def identity_reasons(identity: ExecutionIdentity, layout: Mapping[str, Any]) -> list[str]:
    handoff = layout.get("handoff") or {}
    reasons: list[str] = []
    if layout.get("schema_version") != LAYOUT_SCHEMA:
        reasons.append(f"layout schema {layout.get('schema_version')!r} is not {LAYOUT_SCHEMA}")
    pnu = str(handoff.get("pnu") or layout.get("pnu") or "")
    if pnu != identity.pnu:
        reasons.append(f"pnu mismatch: layout {pnu or 'missing'} vs mass {identity.pnu}")
    if handoff.get("evaluated") is not True:
        reasons.append("layout hand-off was not evaluated")
    if not handoff.get("geometry_hash"):
        reasons.append("layout hand-off carries no geometry hash")
    elif isinstance(layout.get("features"), list) and digest(layout["features"]) != handoff["geometry_hash"]:
        reasons.append("layout features do not hash to the hand-off geometry hash")
    if handoff.get("input_hash") and isinstance(layout.get("metric_request"), Mapping) \
            and digest(layout["metric_request"]) != handoff["input_hash"]:
        reasons.append("layout request does not hash to the hand-off input hash")
    return reasons


def evidence_from_masterplan_layout(identity: ExecutionIdentity, layout: Mapping[str, Any]) -> AgentEvidence:
    handoff = dict(layout.get("handoff") or {})
    reasons = identity_reasons(identity, layout)
    if reasons:
        status = "failed"
    elif handoff.get("hard_pass") is True and handoff.get("status") == "passed":
        status = "passed"
    elif handoff.get("status") == "failed":
        status = "failed"
    else:
        status = "needs_evidence"
    metrics = layout.get("metrics") if isinstance(layout.get("metrics"), Mapping) else {}
    validation = layout.get("validation") if isinstance(layout.get("validation"), Mapping) else {}
    evidence = {
        "schema_version": "arr.maas.master_plan_handoff.v1",
        "source": "masterplanagent",
        "layout_schema": layout.get("schema_version"),
        "layout_status": layout.get("status"),
        "handoff": {k: handoff.get(k) for k in ("pnu", "input_hash", "geometry_hash", "metric_geometry_hash",
                                                 "status", "evaluated", "hard_pass", "scope")},
        "identity_reasons": reasons,
        "blocking": list(layout.get("blocking") or []),
        "metrics": {k: metrics.get(k) for k in _METRIC_KEYS},
        "geometry_status": validation.get("geometry_status"),
        "failed_checks": [c.get("id") for c in validation.get("checks", []) if isinstance(c, Mapping) and c.get("status") == "failed"],
        "pending_reviews": list(validation.get("pending_reviews") or []),
    }
    summary = (f"masterplan layout {status}: {reasons[0]}" if reasons
               else f"masterplan layout {status}; parking {metrics.get('provided_parking_stalls')}/"
                    f"{metrics.get('required_parking_stalls')} ({metrics.get('parking_strategy')})")
    return AgentEvidence(evidence_id=EVIDENCE_ID, agent=AGENT_ID, status=status, summary=summary,
                         identity=identity, evidence=evidence)


__all__ = ["LAYOUT_SCHEMA", "evidence_from_masterplan_layout", "identity_reasons", "is_masterplan_layout"]
