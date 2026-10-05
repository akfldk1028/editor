"""Reference-image VLM adapter for bounded MAAS component-graph edits."""

from __future__ import annotations

from backend.app.modules.design.generation import paths as _design_paths

import base64
import hashlib
import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from backend.app.modules.design.generation.maas.grammar.component_graph import MassComponentGraph


REFERENCE_INTENT_SCHEMA_VERSION = "arr.maas.reference_intent.v1"
DEFAULT_REFERENCE_INTENT_MODEL = "gpt-5.4-mini"
EDITABLE_PARAMETERS = (
    "factor", "ratio", "upper_ratio", "top_ratio", "width_ratio",
    "depth_ratio", "slab_ratio", "distance_ratio", "shift_ratio", "angle", "n",
)


class ReferenceIntentError(RuntimeError):
    pass


def interpret_reference_intent_with_openai_vlm(
    *,
    graph: MassComponentGraph,
    references: list[dict[str, Any]],
    instruction: str = "",
    model: str | None = None,
    timeout: float = 120.0,
    response_override: dict[str, Any] | None = None,
    learning_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Translate reference images into bounded graph operations, never geometry."""
    image_content = _reference_content(references)
    if not image_content:
        raise ReferenceIntentError("no readable reference image was provided")
    selected_model = model or os.getenv("MAAS_REFERENCE_INTENT_VLM_MODEL") or DEFAULT_REFERENCE_INTENT_MODEL
    cache_path = _intent_cache_path(graph, references, instruction, selected_model, learning_profile or {})
    if response_override is None:
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(cached, dict) and isinstance(cached.get("operations"), list):
                return {**cached, "cache_hit": True}
        except (OSError, ValueError, TypeError):
            pass
    body = {
        "model": selected_model,
        "input": [
            {
                "role": "system",
                "content": [{
                    "type": "input_text",
                    "text": (
                        "You are an architectural massing reference interpreter. Extract transferable "
                        "massing principles from the images, not facade style, material, signage, or literal copying. "
                        "You may only propose bounded edits to the supplied existing component nodes. "
                        "Never assess law, zoning, FAR, BCR, height approval, or parking."
                    ),
                }],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": _prompt(graph, instruction, learning_profile or {})}, *image_content],
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "maas_reference_graph_intent",
                "strict": True,
                "schema": _response_schema(graph),
            }
        },
    }
    data = response_override or _request_openai(body, timeout=timeout)
    output_text = _extract_text(data)
    if not output_text:
        raise ReferenceIntentError("reference VLM response did not include output text")
    try:
        parsed = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise ReferenceIntentError("reference VLM response was not valid JSON") from exc
    normalized = _normalize(parsed, graph=graph, model=selected_model, response_id=str(data.get("id") or ""))
    normalized["cache_hit"] = False
    if response_override is None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache_path.with_suffix(f".{os.getpid()}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps(normalized, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        temporary.replace(cache_path)
    return normalized


def _intent_cache_path(
    graph: MassComponentGraph,
    references: list[dict[str, Any]],
    instruction: str,
    model: str,
    learning_profile: dict[str, Any],
) -> Path:
    identities: list[dict[str, str]] = []
    for reference in references[:3]:
        local = str(reference.get("local_path") or "")
        identity = str(reference.get("data_url") or reference.get("image_url") or local)
        if local:
            path = Path(local)
            if not path.is_absolute():
                path = Path.cwd() / path
            if path.exists() and path.is_file():
                identity = f"{path.resolve()}:{path.stat().st_size}:{path.stat().st_mtime_ns}"
        identities.append({"id": str(reference.get("id") or ""), "image": identity})
    payload = {
        "schema": REFERENCE_INTENT_SCHEMA_VERSION,
        "model": model,
        "instruction": instruction,
        "graph": graph.to_dict(),
        "references": identities,
        "learning_profile": learning_profile,
    }
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")).hexdigest()
    root = _design_paths.workspace_root() / "docs" / "ai-session-memory" / "reference-corpus" / "reference-intent-cache"
    return root / f"{digest}.json"


def _prompt(graph: MassComponentGraph, instruction: str, learning_profile: dict[str, Any]) -> str:
    inventory = []
    for node in graph.nodes[1:]:
        editable = {
            key: value for key, value in node.operation.params.items()
            if key in EDITABLE_PARAMETERS and isinstance(value, int | float)
        }
        inventory.append({
            "node_id": node.node_id,
            "role": node.role,
            "verb": node.operation.verb,
            "optional": node.optional,
            "editable_parameters": editable,
        })
    return (
        "Interpret the attached architectural references as early-stage massing precedents. "
        "Return one to three conservative operations. Prefer one operation when enough. "
        "Use scale_parameter for relative similarity, set_parameter only for a clear dimensional intent, "
        "and remove_optional_node only when simplification is visually essential. "
        "Describe the visible reference principle and why each edit transfers it.\n"
        f"Client instruction: {instruction or 'Match the transferable massing principle.'}\n"
        f"Project feedback calibration (soft evidence only): {json.dumps(learning_profile, ensure_ascii=False, sort_keys=True)}\n"
        f"Editable component inventory: {json.dumps(inventory, ensure_ascii=False, sort_keys=True)}"
    )


def _response_schema(graph: MassComponentGraph) -> dict[str, Any]:
    node_ids = [node.node_id for node in graph.nodes[1:]] or ["no_editable_node"]
    operation = {
        "type": "object",
        "additionalProperties": False,
        "required": ["type", "node_id", "parameter", "factor", "value", "reason"],
        "properties": {
            "type": {"type": "string", "enum": ["scale_parameter", "set_parameter", "remove_optional_node"]},
            "node_id": {"type": "string", "enum": node_ids},
            "parameter": {"type": ["string", "null"], "enum": [*EDITABLE_PARAMETERS, None]},
            "factor": {"type": ["number", "null"], "minimum": 0.75, "maximum": 1.25},
            "value": {"type": ["number", "null"]},
            "reason": {"type": "string"},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["reference_principles", "operations", "confidence", "warnings"],
        "properties": {
            "reference_principles": {"type": "array", "minItems": 1, "maxItems": 5, "items": {"type": "string"}},
            "operations": {"type": "array", "minItems": 1, "maxItems": 3, "items": operation},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "warnings": {"type": "array", "items": {"type": "string"}},
        },
    }


def _normalize(data: dict[str, Any], *, graph: MassComponentGraph, model: str, response_id: str) -> dict[str, Any]:
    nodes = {node.node_id: node for node in graph.nodes[1:]}
    operations: list[dict[str, Any]] = []
    rationales: list[str] = []
    for raw in (data.get("operations") or [])[:3]:
        if not isinstance(raw, dict):
            continue
        operation_type = str(raw.get("type") or "")
        node = nodes.get(str(raw.get("node_id") or ""))
        if node is None:
            raise ReferenceIntentError("reference VLM selected an unknown component node")
        operation: dict[str, Any] = {"type": operation_type, "node_id": node.node_id}
        if operation_type == "remove_optional_node":
            if not node.optional:
                raise ReferenceIntentError("reference VLM attempted to remove a required component")
        else:
            parameter = str(raw.get("parameter") or "")
            if parameter not in EDITABLE_PARAMETERS or not isinstance(node.operation.params.get(parameter), int | float):
                raise ReferenceIntentError("reference VLM selected a non-editable component parameter")
            operation["parameter"] = parameter
            if operation_type == "scale_parameter":
                factor = raw.get("factor")
                if not isinstance(factor, int | float):
                    raise ReferenceIntentError("reference VLM scale operation omitted its factor")
                operation["factor"] = round(max(0.75, min(1.25, float(factor))), 4)
            elif operation_type == "set_parameter":
                value = raw.get("value")
                if not isinstance(value, int | float):
                    raise ReferenceIntentError("reference VLM set operation omitted its value")
                operation["value"] = float(value)
            else:
                raise ReferenceIntentError("reference VLM returned an unsupported operation")
        operation["inference_source"] = "openai_reference_vlm_v1"
        operations.append(operation)
        rationales.append(str(raw.get("reason") or ""))
    if not operations:
        raise ReferenceIntentError("reference VLM returned no valid graph operations")
    return {
        "schema_version": REFERENCE_INTENT_SCHEMA_VERSION,
        "provider": "openai",
        "model": model,
        "response_id": response_id,
        "reference_principles": [str(item) for item in data.get("reference_principles") or []][:5],
        "operations": operations,
        "operation_rationales": rationales,
        "confidence": round(max(0.0, min(1.0, float(data.get("confidence") or 0.0))), 3),
        "warnings": [str(item) for item in data.get("warnings") or []],
    }


def _reference_content(references: list[dict[str, Any]]) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = []
    for index, reference in enumerate(references[:3], start=1):
        if not isinstance(reference, dict):
            continue
        image_url = _reference_image_url(reference)
        if not image_url:
            continue
        content.extend([
            {"type": "input_text", "text": f"Reference image {index}: {reference.get('title') or reference.get('id') or 'client reference'}"},
            {"type": "input_image", "image_url": image_url},
        ])
    return content


def _reference_image_url(reference: dict[str, Any]) -> str:
    direct = str(reference.get("data_url") or reference.get("image_url") or "")
    if direct.startswith(("data:image/", "https://", "http://")):
        if direct.startswith("data:image/") and len(direct) > 15_000_000:
            raise ReferenceIntentError("reference image payload exceeds the 10 MB service limit")
        return direct
    local = str(reference.get("local_path") or "")
    if not local:
        return ""
    path = Path(local)
    if not path.is_absolute():
        path = Path.cwd() / path
    path = path.resolve()
    workspace = _design_paths.workspace_root()
    allowed_roots = ((workspace / "docs").resolve(), (_design_paths.backend_root() / "media").resolve())
    if not any(path == root or root in path.parents for root in allowed_roots):
        raise ReferenceIntentError("local reference path is outside approved docs/media roots")
    if not path.exists() or not path.is_file():
        return ""
    if path.stat().st_size > 10_000_000:
        raise ReferenceIntentError("reference image exceeds the 10 MB service limit")
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def _request_openai(body: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ReferenceIntentError("OPENAI_API_KEY is not set; reference VLM is required")
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    retries = max(0, int(os.getenv("MAAS_REFERENCE_INTENT_VLM_RETRIES", "1")))
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code < 500 and exc.code != 429:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
                raise ReferenceIntentError(f"reference VLM failed: HTTP {exc.code}: {detail}") from exc
        except Exception as exc:
            last_error = exc
        if attempt < retries:
            time.sleep(1.25 * (attempt + 1))
    raise ReferenceIntentError(f"reference VLM failed after {retries + 1} attempts: {last_error}") from last_error


def _extract_text(response: dict[str, Any]) -> str:
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    chunks: list[str] = []
    for item in response.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                chunks.append(content["text"])
    return "\n".join(chunks)


__all__ = [
    "DEFAULT_REFERENCE_INTENT_MODEL",
    "REFERENCE_INTENT_SCHEMA_VERSION",
    "ReferenceIntentError",
    "interpret_reference_intent_with_openai_vlm",
]
