"""Normalization rules for truthful per-MASS execution evidence."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
from typing import Any, Mapping


DOWNSTREAM_STAGE_KEYS = (
    "site", "capacity", "law", "parking", "program_fit", "selector",
)
DOWNSTREAM_ALIASES = {
    "site": ("site", "site_evidence", "source_site"),
    "capacity": ("capacity", "capacity_alternative_projection", "source_capacity_measurement"),
    "law": ("law", "legal_projection", "legal_hard_gate"),
    "parking": ("parking", "parking_hard_gate", "parking_precheck"),
    "program_fit": ("program_fit", "program_fit_gate", "spatial_evaluation"),
    "selector": ("selector", "selection", "selection_result"),
}
_VALID_STATUSES = frozenset({
    "passed", "failed", "evaluated", "not_evaluated", "cache_hit", "live_scored",
    "needs_evidence", "accepted", "rejected",
})
_HARD_ACCEPTANCE_STAGES = frozenset({
    "base_model", "recursive_geometry", "program", "site", "capacity", "law",
    "parking", "program_fit", "compiler", "geometry_gate", "render", "selector",
    "agent_collaboration",
})


def stage(
    stage_id: str,
    label: str,
    status: str,
    *,
    node_ids: list[str] | None = None,
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = status if status in _VALID_STATUSES else "not_evaluated"
    return {
        "id": stage_id,
        "label": label,
        "status": normalized,
        "required_for_final": stage_id in _HARD_ACCEPTANCE_STAGES or stage_id == "vlm",
        "node_ids": list(node_ids or ()),
        "evidence": deepcopy(dict(evidence or {})),
    }


def stage_from_downstream(stage_id: str, evidence: Mapping[str, Any]) -> dict[str, Any]:
    labels = {
        "site": "Site / parcel",
        "capacity": "FAR / capacity alternatives",
        "law": "Legal hard gate",
        "parking": "Parking hard gate",
        "program_fit": "Program-fit gate",
        "selector": "Final selector",
    }
    raw_status = str(evidence.get("status") or "")
    if raw_status in {"passed", "failed", "evaluated", "needs_evidence"}:
        status = raw_status
    elif evidence.get("hard_pass") is True or evidence.get("selected") is True:
        status = "passed"
    elif evidence.get("hard_pass") is False and evidence.get("evaluated") is True:
        status = "failed"
    elif evidence.get("evaluated") is True:
        status = "evaluated"
    else:
        status = "not_evaluated"
    return stage(stage_id, labels[stage_id], status, evidence=evidence)


def normalize_downstream_evidence(
    metadata: Mapping[str, Any],
    supplied: Mapping[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    merged = {**dict(metadata), **dict(supplied or {})}
    result: dict[str, dict[str, Any]] = {}
    for stage_id in DOWNSTREAM_STAGE_KEYS:
        values = [
            merged.get(key) for key in DOWNSTREAM_ALIASES[stage_id]
            if isinstance(merged.get(key), dict)
        ]
        if not values:
            result[stage_id] = {
                "status": "not_evaluated",
                "reason": f"{stage_id}_evidence_not_supplied",
            }
            continue
        combined: dict[str, Any] = {}
        for value in values:
            combined.update(deepcopy(value))
        combined.setdefault("evaluated", True)
        result[stage_id] = combined
    return result


def merge_agent_stage_evidence(
    downstream: Mapping[str, Mapping[str, Any]],
    collaboration: Mapping[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Project materialized specialist results onto their canonical flow stages."""

    result = {
        str(stage_id): deepcopy(dict(evidence))
        for stage_id, evidence in downstream.items()
    }
    payload = dict(collaboration or {})
    rows = payload.get("evidence")
    rows = rows if isinstance(rows, list) else []
    stage_by_agent = {
        "law_graph_agent": "law",
        "master_plan_agent": "parking",
        "selector": "selector",
    }
    status_map = {
        "passed": "passed",
        "accepted": "passed",
        "failed": "failed",
        "rejected": "failed",
        "needs_evidence": "needs_evidence",
    }
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        agent = str(row.get("agent") or "")
        stage_id = stage_by_agent.get(agent)
        status = status_map.get(str(row.get("status") or ""))
        if not stage_id or not status:
            continue
        current = result.get(stage_id, {})
        if (
            str(current.get("status") or "") != "not_evaluated"
            or current.get("evaluated") is True
            or "hard_pass" in current
            or current.get("selected") is True
        ):
            continue
        result[stage_id] = {
            "status": status,
            "evaluated": True,
            "source": "agent_collaboration",
            "source_agent": agent,
            "evidence_id": str(row.get("evidence_id") or ""),
            "summary": str(row.get("summary") or ""),
            "identity": deepcopy(dict(row.get("identity") or {})),
            "specialist_evidence": deepcopy(dict(row.get("evidence") or {})),
        }
    return result


def preview_evidence(preview_path: str | Path | None) -> dict[str, Any]:
    if preview_path is None:
        return {"status": "not_evaluated", "reason": "preview_not_rendered"}
    path = Path(preview_path)
    if not path.is_file():
        return {"status": "not_evaluated", "path": str(path), "reason": "preview_file_missing"}
    content = path.read_bytes()
    return {
        "status": "passed",
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(content).hexdigest(),
        "byte_count": len(content),
        "views": ["isometric", "opposite", "front", "top"],
    }


def vlm_evidence(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {"status": "not_evaluated", "reason": "vlm_not_run"}
    result = deepcopy(dict(value))
    scores = result.get("concept_scores")
    if not isinstance(scores, dict):
        scores = {}
    status = "cache_hit" if result.get("cache_hit") is True else "live_scored"
    if result.get("error") or result.get("status") in {"failed", "error"}:
        status = "failed"
    image_inputs = result.get("vlm_image_inputs")
    image_inputs = deepcopy(image_inputs) if isinstance(image_inputs, dict) else {}
    causal_context = result.get("maas_causal_context")
    causal_context = causal_context if isinstance(causal_context, dict) else {}
    return {
        "status": status,
        "model": str(result.get("model") or ""),
        "response_id": str(result.get("response_id") or ""),
        "cache_hit": bool(result.get("cache_hit")),
        "hard_pass": (
            result.get("hard_pass")
            if "hard_pass" in result
            else result.get("program_fit_hard_pass")
        ),
        "program_fit_hard_pass": result.get("program_fit_hard_pass"),
        "concept_scores": scores,
        "critic_actions": [str(item) for item in result.get("critic_actions") or ()],
        "rationale": str(result.get("rationale") or ""),
        "geometry_edits": list(result.get("geometry_edits") or ()),
        "image_inputs": image_inputs,
        "reference_assessments": list(
            result.get("reference_assessments")
            or causal_context.get("reference_assessments")
            or ()
        ),
        "retrieved_reference_candidates": list(causal_context.get("reference_matches") or ()),
        "reference_massing_gate": deepcopy(result.get("reference_massing_gate") or {}),
        "critique": str(result.get("critique") or result.get("reasoning") or ""),
        "error": str(result.get("error") or ""),
        "api_usage": deepcopy(result.get("api_usage") or {}),
        "cost_observation": deepcopy(result.get("cost_observation") or {}),
        "evidence_binding": deepcopy(result.get("evidence_binding") or {}),
        "prompt_contract_version": str(result.get("prompt_contract_version") or ""),
        "provider": str(result.get("provider") or ""),
    }


def status_activation(status: str) -> float:
    materialized = status == "completed" or (
        status in _VALID_STATUSES and status != "not_evaluated"
    )
    return 1.0 if materialized else 0.0


def passport_state(stages: list[dict[str, Any]]) -> dict[str, Any]:
    """Separate execution completeness from final hard-gate acceptance."""

    required = [row for row in stages if row.get("required_for_final")]
    flow_complete = bool(required) and all(row.get("status") != "not_evaluated" for row in required)
    stage_map = {str(row.get("id") or ""): row for row in stages}
    hard_pass = all(
        stage_map.get(stage_id, {}).get("status") == "passed"
        for stage_id in _HARD_ACCEPTANCE_STAGES
    )
    vlm_stage = stage_map.get("vlm", {})
    vlm_status = vlm_stage.get("status")
    vlm_payload = vlm_stage.get("evidence")
    vlm_payload = vlm_payload if isinstance(vlm_payload, Mapping) else {}
    vlm_complete = vlm_status in {"passed", "evaluated", "cache_hit", "live_scored", "failed"}
    vlm_pass = bool(
        vlm_status == "passed"
        or (
            vlm_status in {"evaluated", "cache_hit", "live_scored"}
            and vlm_payload.get("hard_pass") is True
            and vlm_payload.get("program_fit_hard_pass") is not False
        )
    )
    accepted = bool(hard_pass and vlm_pass)
    if accepted:
        status = "accepted"
    elif any(row.get("status") == "needs_evidence" for row in required):
        status = "needs_evidence"
    elif flow_complete:
        status = "rejected"
    else:
        status = "in_progress"
    return {
        "status": status,
        "full_flow_complete": flow_complete,
        "final_hard_pass": accepted,
    }


__all__ = [
    "DOWNSTREAM_ALIASES",
    "DOWNSTREAM_STAGE_KEYS",
    "merge_agent_stage_evidence",
    "normalize_downstream_evidence",
    "passport_state",
    "preview_evidence",
    "stage",
    "stage_from_downstream",
    "status_activation",
    "vlm_evidence",
]
