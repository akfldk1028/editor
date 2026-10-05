"""One-call OpenAI critic for four identity-bound creative facade views."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from backend.app.modules.design.generation.maas.agents.elevation_agent.multi_view_contract import FACADE_VIEWS


_ISSUE_CODES = (
    "material_mismatch",
    "floor_mismatch",
    "opening_mismatch",
    "corner_mismatch",
    "roof_mismatch",
    "mass_contradiction",
)


class OpenAIElevationCritic:
    name = "openai-responses-multi-view-critic"

    def evaluate(
        self,
        *,
        identity: Mapping[str, str],
        strategy: Mapping[str, Any],
        artifacts: Mapping[str, Mapping[str, Any]],
        montage_path: Path,
    ) -> dict[str, Any]:
        model = os.getenv("OPENAI_ELEVATION_CRITIC_MODEL", "gpt-5.4-mini")
        evidence = _base_evidence(identity, model, artifacts, montage_path)
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return {
                **evidence,
                "status": "not_configured",
                "issues": [{
                    "code": "provider_not_configured",
                    "views": list(FACADE_VIEWS),
                    "message": "OPENAI_API_KEY is not set.",
                    "repair_instruction": "",
                }],
            }
        try:
            from openai import OpenAI
        except Exception as exc:  # pragma: no cover - deployment dependency
            return _provider_failure(evidence, f"openai package unavailable: {exc}")

        try:
            content: list[dict[str, Any]] = [{
                "type": "input_text",
                "text": _critic_prompt(identity, strategy),
            }]
            for view in FACADE_VIEWS:
                artifact = artifacts.get(view)
                artifact = artifact if isinstance(artifact, Mapping) else {}
                source = artifact.get("source")
                source = source if isinstance(source, Mapping) else {}
                source_path = Path(str(source.get("path") or "")).resolve()
                output = artifact.get("artifact")
                output = output if isinstance(output, Mapping) else {}
                output_path = Path(str(output.get("path") or "")).resolve()
                if not source_path.is_file():
                    raise ValueError(
                        f"{view} locked source does not exist: {source_path}"
                    )
                if not output_path.is_file():
                    raise ValueError(
                        f"{view} generated output does not exist: {output_path}"
                    )
                content.append({
                    "type": "input_text",
                    "text": f"{view.upper()} locked source:",
                })
                content.append({
                    "type": "input_image",
                    "image_url": _image_data_url(source_path),
                    "detail": "high",
                })
                content.append({
                    "type": "input_text",
                    "text": f"{view.upper()} generated output:",
                })
                content.append({
                    "type": "input_image",
                    "image_url": _image_data_url(output_path),
                    "detail": "high",
                })
            request = {
                "model": model,
                "input": [{"role": "user", "content": content}],
                "text": {"format": _response_format()},
            }
            client = OpenAI(api_key=api_key)
            raw_api = getattr(client.responses, "with_raw_response", None)
            if raw_api is not None:
                raw_response = raw_api.create(**request)
                response = raw_response.parse()
                headers = getattr(raw_response, "headers", {}) or {}
                evidence["request_id"] = str(
                    headers.get("x-request-id")
                    or headers.get("request-id")
                    or ""
                )
            else:  # pragma: no cover - old SDK compatibility
                response = client.responses.create(**request)
            evidence["response_id"] = str(getattr(response, "id", "") or "")
            if not evidence["request_id"]:
                evidence["request_id"] = str(
                    getattr(response, "_request_id", "") or ""
                )
            usage = getattr(response, "usage", None)
            if usage is not None:
                evidence["usage"] = _serializable_usage(usage)
            refusal = _response_refusal(response)
            if refusal:
                return _provider_failure(
                    evidence,
                    f"critic refusal: {refusal}",
                    code="critic_refusal",
                )
            output_text = str(getattr(response, "output_text", "") or "")
            if not output_text:
                return _provider_failure(
                    evidence,
                    "critic response did not include output text",
                    code="missing_critic_output",
                )
            parsed = json.loads(output_text)
            return _validated_result(evidence, parsed)
        except Exception as exc:
            return _provider_failure(evidence, str(exc))


def _response_format() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "name": "multi_view_elevation_critic",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["status", "failed_views", "issues", "summary"],
            "properties": {
                "status": {"type": "string", "enum": ["pass", "fail"]},
                "failed_views": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(FACADE_VIEWS)},
                },
                "issues": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "code",
                            "views",
                            "message",
                            "repair_instruction",
                        ],
                        "properties": {
                            "code": {
                                "type": "string",
                                "enum": list(_ISSUE_CODES),
                            },
                            "views": {
                                "type": "array",
                                "items": {
                                    "type": "string",
                                    "enum": list(FACADE_VIEWS),
                                },
                            },
                            "message": {"type": "string"},
                            "repair_instruction": {"type": "string"},
                        },
                    },
                },
                "summary": {"type": "string"},
            },
        },
    }


def _critic_prompt(
    identity: Mapping[str, str],
    strategy: Mapping[str, Any],
) -> str:
    return (
        "Inspect the four supplied orthographic facade views in exact order "
        "front, right, back, left. Each view is supplied as a locked-source and "
        "generated-output pair. The locked source is authoritative for silhouette, "
        "height, storey count, and component boundaries. They must describe one "
        "immutable MASS. "
        "Judge cross-view material palette, floor datums, opening rhythm, corner "
        "returns, roof/parapet treatment, and contradictions with the locked mass. "
        "A view fails when it invents or removes a volume, changes roofline or floor "
        "count, adds intermediate floor bands or stacked window rows to a locked "
        "single-storey source, or cannot meet its adjacent views at the corners. "
        "Do not reinterpret a prominent full-width horizontal beam or repeated "
        "stacked glazing rows as harmless mullions when they visually create extra "
        "storeys. Return only the "
        "required structured result. "
        f"Identity: {json.dumps(dict(identity), sort_keys=True)}. "
        f"Shared facade strategy: {json.dumps(dict(strategy), sort_keys=True)}."
    )


def _base_evidence(
    identity: Mapping[str, str],
    model: str,
    artifacts: Mapping[str, Mapping[str, Any]],
    montage_path: Path,
) -> dict[str, Any]:
    input_hashes: dict[str, str] = {}
    for view in FACADE_VIEWS:
        artifact = artifacts.get(view)
        artifact = artifact if isinstance(artifact, Mapping) else {}
        output = artifact.get("artifact")
        output = output if isinstance(output, Mapping) else {}
        input_hashes[view] = str(output.get("sha256") or "")
    return {
        "schema_version": "arr.elevation_agent.multi_view_critic.v1",
        "status": "failed",
        "identity": dict(identity),
        "model": model,
        "response_id": "",
        "request_id": "",
        "usage": {},
        "request_count": 1,
        "paid_request_attempt_count": 1,
        "retry_count": 0,
        "failed_views": list(FACADE_VIEWS),
        "issues": [],
        "summary": "",
        "input_image_sha256": input_hashes,
        "montage_sha256": (
            hashlib.sha256(montage_path.read_bytes()).hexdigest()
            if montage_path.is_file()
            else ""
        ),
    }


def _validated_result(
    evidence: dict[str, Any],
    parsed: Any,
) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        return _provider_failure(
            evidence,
            "critic output is not an object",
            code="invalid_critic_output",
        )
    raw_status = str(parsed.get("status") or "")
    if raw_status not in {"pass", "fail"}:
        return _provider_failure(
            evidence,
            "critic output has an invalid status",
            code="invalid_critic_output",
        )
    failed_views = [
        view
        for view in FACADE_VIEWS
        if view in {
            str(item)
            for item in parsed.get("failed_views") or ()
            if str(item) in FACADE_VIEWS
        }
    ]
    issues = [
        dict(item)
        for item in parsed.get("issues") or ()
        if isinstance(item, dict)
    ]
    status = "passed" if raw_status == "pass" and not failed_views else "failed"
    return {
        **evidence,
        "status": status,
        "failed_views": failed_views,
        "issues": issues,
        "summary": str(parsed.get("summary") or ""),
    }


def _provider_failure(
    evidence: dict[str, Any],
    message: str,
    *,
    code: str = "provider_error",
) -> dict[str, Any]:
    return {
        **evidence,
        "status": "failed",
        "failed_views": list(FACADE_VIEWS),
        "issues": [{
            "code": code,
            "views": list(FACADE_VIEWS),
            "message": message,
            "repair_instruction": "",
        }],
        "summary": message,
    }


def _response_refusal(response: Any) -> str:
    for output in getattr(response, "output", ()) or ():
        for content in getattr(output, "content", ()) or ():
            if str(getattr(content, "type", "") or "") == "refusal":
                return str(getattr(content, "refusal", "") or "")
    return ""


def _image_data_url(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _serializable_usage(usage: Any) -> dict[str, Any]:
    if hasattr(usage, "model_dump"):
        value = usage.model_dump()
        return dict(value) if isinstance(value, dict) else {}
    if isinstance(usage, dict):
        return dict(usage)
    return {}


__all__ = ["OpenAIElevationCritic"]
