"""One bounded provider turn for missing exact-final-VLM typed edits."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
import os
from typing import Any, Callable
from urllib import error, request

from backend.app.modules.design.generation.maas.geometry_language.mutation import GeometryEdit
from backend.app.modules.design.generation.maas.paid_provider_budget import reserve_paid_provider_request
from backend.app.modules.design.generation.maas.preference.vlm_scorer import DEFAULT_VLM_MODEL


TYPED_EDIT_COMPLETION_SCHEMA = "arr.maas.final_vlm_typed_edit_completion.v1"
TYPED_EDIT_COMPLETION_PROMPT = "arr.maas.final_vlm_typed_edit_completion_prompt.v1"


def _edit_schema() -> dict[str, Any]:
    properties = {
        "operation": {"type": "string", "minLength": 1, "maxLength": 64},
        "target_node_id": {"type": "string", "maxLength": 160},
        "node_id": {"type": "string", "maxLength": 160},
        "node_kind": {"type": "string", "maxLength": 64},
        "operator": {"type": "string", "maxLength": 64},
        "input_ids": {
            "type": "array",
            "items": {"type": "string", "maxLength": 160},
            "maxItems": 8,
        },
        "input_index": {"type": "integer", "minimum": 0, "maximum": 23},
        "input_node_id": {"type": "string", "maxLength": 160},
        "parameter_name": {"type": "string", "maxLength": 64},
        "numeric_value": {"type": "number", "minimum": -1000, "maximum": 1000},
        "string_value": {"type": "string", "maxLength": 80},
        "boolean_value": {"type": "boolean"},
        "vector_value": {
            "type": "array",
            "items": {"type": "number", "minimum": -1000, "maximum": 1000},
            "maxItems": 4,
        },
        "semantic_role": {"type": "string", "maxLength": 80},
        "rationale": {"type": "string", "maxLength": 500},
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(properties),
    }


def _response_output_text(response: dict[str, Any]) -> str:
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    chunks: list[str] = []
    for item in response.get("output") or ():
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or ():
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                chunks.append(content["text"])
    return "\n".join(chunks)


def request_typed_edit_completion(
    completion_request: dict[str, Any],
    *,
    model: str | None = None,
    timeout_s: float = 90.0,
) -> dict[str, Any]:
    """Make exactly one paid provider request; callers own all retry policy."""

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    selected_model = (
        model
        or str(
            (completion_request.get("exact_final_vlm_audit") or {}).get("model")
            or ""
        ).strip()
        or os.getenv("MAAS_PREFERENCE_VLM_MODEL")
        or DEFAULT_VLM_MODEL
    )
    prompt = (
        "Complete the missing typed geometry edits for an exact final-VLM hard "
        "failure. Return 1 to 8 executable edits, using only node IDs, edit "
        "operations, operators, and parameters permitted by the supplied full "
        "canonical graph and its agent_edit_contract. Protected nodes are "
        "invariants. Preserve statutory law, parking, and program constraints. "
        "Use the exact audit actions as design requirements and the portfolio "
        "context to avoid converging on represented families. Do not invent an "
        "action-to-operator mapping; reason from the graph contract. Supply "
        "neutral defaults for fields unused by an edit operation.\n\n"
        + json.dumps(completion_request, sort_keys=True, separators=(",", ":"))
    )
    body = {
        "model": selected_model,
        "input": [{
            "role": "user",
            "content": [{"type": "input_text", "text": prompt}],
        }],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "maas_final_vlm_typed_edit_completion",
                "strict": True,
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "geometry_edits": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 8,
                            "items": _edit_schema(),
                        },
                        "rationale": {"type": "string", "maxLength": 1200},
                    },
                    "required": ["geometry_edits", "rationale"],
                },
            },
        },
    }
    http_request = request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    reserve_paid_provider_request("exact_candidate_vlm")
    try:
        with request.urlopen(http_request, timeout=float(timeout_s)) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"typed edit completion HTTP {exc.code}: {detail}") from exc
    output_text = _response_output_text(response_data)
    if not output_text:
        raise RuntimeError("typed edit completion returned no output text")
    try:
        parsed = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("typed edit completion returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("typed edit completion response must be an object")
    return {
        **parsed,
        "response_id": str(response_data.get("id") or ""),
        "model": str(response_data.get("model") or selected_model),
    }


def complete_empty_final_vlm_geometry_edits(
    audit_record: dict[str, Any],
    *,
    canonical_graph: dict[str, Any],
    portfolio_diversity_context: dict[str, Any],
    provider: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Complete one empty normalized edit list and persist the terminal result."""

    previous = audit_record.get("typed_edit_completion")
    if isinstance(previous, dict) and previous.get("requested"):
        return previous

    provider_actions = [
        deepcopy(action)
        for action in audit_record.get("provider_critic_actions") or ()
        if action
    ]
    graph_contract = (
        canonical_graph.get("agent_edit_contract")
        if isinstance(canonical_graph, dict)
        and isinstance(canonical_graph.get("agent_edit_contract"), dict)
        else {}
    )
    no_call_reasons: list[str] = []
    if audit_record.get("hard_pass") is not False:
        no_call_reasons.append("exact_final_vlm_not_hard_failed")
    if not provider_actions:
        no_call_reasons.append("blocking_provider_actions_missing")
    edits = audit_record.get("geometry_edits")
    if not isinstance(edits, list) or edits:
        no_call_reasons.append("normalized_geometry_edits_not_empty")
    if (
        not isinstance(canonical_graph, dict)
        or not isinstance(canonical_graph.get("nodes"), list)
        or not canonical_graph.get("nodes")
        or not graph_contract
    ):
        no_call_reasons.append("canonical_geometry_graph_missing")
    if no_call_reasons:
        result = {
            "schema_version": TYPED_EDIT_COMPLETION_SCHEMA,
            "eligible": False,
            "requested": False,
            "status": "not_eligible",
            "response_id": "",
            "model": "",
            "edit_count": 0,
            "geometry_edits": [],
            "failure_reasons": no_call_reasons,
        }
        audit_record["typed_edit_completion"] = result
        return result

    exact_audit = deepcopy(audit_record)
    exact_audit.pop("typed_edit_completion", None)
    completion_request = {
        "schema_version": TYPED_EDIT_COMPLETION_SCHEMA,
        "prompt_contract_version": TYPED_EDIT_COMPLETION_PROMPT,
        "exact_final_vlm_audit": exact_audit,
        "canonical_geometry_graph": deepcopy(canonical_graph),
        "protected_geometry_node_ids": deepcopy(
            graph_contract.get("protected_geometry_node_ids") or []
        ),
        "operator_parameter_contracts": deepcopy(
            graph_contract.get("operator_parameter_contracts") or {}
        ),
        "portfolio_diversity_context": deepcopy(portfolio_diversity_context),
        "required_geometry_edit_count": {"minimum": 1, "maximum": 8},
    }
    result = {
        "schema_version": TYPED_EDIT_COMPLETION_SCHEMA,
        "eligible": True,
        "requested": True,
        "status": "requested",
        "response_id": "",
        "model": "",
        "edit_count": 0,
        "geometry_edits": [],
        "failure_reasons": [],
    }
    # Persist before transport so any exception still closes the one-turn lane.
    audit_record["typed_edit_completion"] = result
    try:
        response = (provider or request_typed_edit_completion)(completion_request)
        raw_edits = response.get("geometry_edits") if isinstance(response, dict) else None
        edit_count = len(raw_edits) if isinstance(raw_edits, list) else 0
        result["response_id"] = str(
            response.get("response_id") or ""
        ) if isinstance(response, dict) else ""
        result["model"] = str(
            response.get("model") or ""
        ) if isinstance(response, dict) else ""
        if edit_count < 1 or edit_count > 8:
            result["status"] = "failed"
            result["failure_reasons"] = [
                f"completion_edit_count_out_of_bounds:{edit_count}"
            ]
            return result
        normalized = [GeometryEdit.from_dict(edit).to_dict() for edit in raw_edits]
        if any(not edit.get("operation") for edit in normalized):
            result["status"] = "failed"
            result["failure_reasons"] = ["completion_edit_operation_missing"]
            return result
        result.update({
            "status": "completed",
            "edit_count": len(normalized),
            "geometry_edits": normalized,
            "rationale": str(response.get("rationale") or "")[:1200],
        })
        audit_record["geometry_edits"] = normalized
        return result
    except Exception as exc:
        result["status"] = "failed"
        result["failure_reasons"] = [
            f"typed_edit_completion_provider_failure:{type(exc).__name__}:{str(exc)[:500]}"
        ]
        return result


def complete_empty_final_vlm_repair_records(
    audited_pool: list[Any],
    audit_gate: dict[str, Any],
    *,
    provider: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Complete eligible records before the existing non-empty repair filter."""

    candidates = {
        str(candidate.sequence.name): candidate
        for candidate in audited_pool
        if getattr(getattr(candidate, "sequence", None), "name", None)
    }
    existing_context = audit_gate.get("portfolio_diversity_context")
    pool_context = {
        "schema_version": "arr.maas.final_vlm_repair_portfolio_context.v1",
        "existing_context": deepcopy(existing_context)
        if isinstance(existing_context, dict)
        else {},
        "candidate_families": [{
            "source_sequence": str(candidate.sequence.name),
            "principle_kind": str(getattr(candidate, "principle_kind", "") or ""),
            "operation": str(getattr(candidate, "operation", "") or ""),
            "geometry_family": str(
                (
                    (candidate.source.metadata.get("geometry_program") or {}).get("metadata")
                    or {}
                ).get("family")
                or candidate.source.metadata.get("geometry_family")
                or ""
            ),
        } for candidate in audited_pool],
    }
    completion_records: list[dict[str, Any]] = []
    failures: Counter[str] = Counter()
    for audit_record in audit_gate.get("audit_records") or ():
        if not isinstance(audit_record, dict):
            continue
        if audit_record.get("hard_pass") is not False:
            continue
        if not isinstance(audit_record.get("geometry_edits"), list):
            continue
        if audit_record.get("geometry_edits"):
            continue
        source_sequence = str(audit_record.get("source_sequence") or "")
        candidate = candidates.get(source_sequence)
        canonical_graph = (
            candidate.source.metadata.get("geometry_graph_snapshot")
            if candidate is not None
            and isinstance(candidate.source.metadata.get("geometry_graph_snapshot"), dict)
            else {}
        )
        result = complete_empty_final_vlm_geometry_edits(
            audit_record,
            canonical_graph=canonical_graph,
            portfolio_diversity_context=pool_context,
            provider=provider,
        )
        completion_records.append({
            "source_sequence": source_sequence,
            **deepcopy(result),
        })
        for reason in result.get("failure_reasons") or ():
            failures[str(reason)] += 1
    return {
        "typed_edit_completion_eligible_count": sum(
            bool(record.get("eligible")) for record in completion_records
        ),
        "typed_edit_completion_requested_count": sum(
            bool(record.get("requested")) for record in completion_records
        ),
        "typed_edit_completion_completed_count": sum(
            record.get("status") == "completed" for record in completion_records
        ),
        "typed_edit_completion_failed_count": sum(
            record.get("status") == "failed" for record in completion_records
        ),
        "typed_edit_completion_failure_counts": dict(sorted(failures.items())),
        "typed_edit_completion_records": completion_records,
    }


__all__ = [
    "TYPED_EDIT_COMPLETION_PROMPT",
    "TYPED_EDIT_COMPLETION_SCHEMA",
    "complete_empty_final_vlm_geometry_edits",
    "complete_empty_final_vlm_repair_records",
    "request_typed_edit_completion",
]
