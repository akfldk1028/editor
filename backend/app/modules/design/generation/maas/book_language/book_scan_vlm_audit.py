"""Cost-guarded, content-addressed VLM audit for the 69 BOOK scans."""

from __future__ import annotations

from backend.app.modules.design.generation import paths as _design_paths

import base64
import hashlib
import json
import os
from pathlib import Path
import urllib.request
from typing import Any, Iterable

from backend.app.modules.design.generation.maas.preference.vlm_scorer import DEFAULT_VLM_MODEL, VlmScoringError, _consume_live_vlm_request_budget

from backend.app.modules.design.generation.maas.book_language.registry import build_book_language_registry


SCHEMA_VERSION = "arr.maas.book_scan_vlm_audit.v1"
PROMPT_VERSION = "arr.maas.book_scan_vlm_prompt.v1"


def _workspace_root() -> Path:
    return _design_paths.workspace_root()


def cache_root() -> Path:
    configured = os.getenv("MAAS_BOOK_SCAN_VLM_CACHE_DIR", "").strip()
    return Path(configured).resolve() if configured else (
        _workspace_root() / "docs" / "ai-session-memory" / "reference-corpus" / "book-scan-vlm-cache"
    )


def _page_record(page: int) -> dict[str, Any]:
    if not 1 <= int(page) <= 69:
        raise ValueError("BOOK page must be between 1 and 69")
    record = next(
        (item for item in build_book_language_registry()["pages"] if int(item["page"]) == int(page)),
        None,
    )
    if not record:
        raise ValueError(f"BOOK page {page} is not registered")
    return record


def _cache_path(page: int, model: str) -> tuple[Path, str, Path]:
    record = _page_record(page)
    image_path = Path(str(record["source_path"])).resolve()
    image_hash = hashlib.sha256(image_path.read_bytes()).hexdigest()
    key = hashlib.sha256(json.dumps({
        "schema": SCHEMA_VERSION,
        "prompt": PROMPT_VERSION,
        "model": model,
        "page": int(page),
        "image_hash": image_hash,
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return cache_root() / f"{key}.json", image_hash, image_path


def audit_status(*, model: str | None = None) -> dict[str, Any]:
    selected_model = model or os.getenv("MAAS_BOOK_SCAN_VLM_MODEL") or DEFAULT_VLM_MODEL
    cached_pages = []
    missing_pages = []
    for page in range(1, 70):
        path, _image_hash, _image_path = _cache_path(page, selected_model)
        (cached_pages if path.is_file() else missing_pages).append(page)
    return {
        "schema_version": SCHEMA_VERSION,
        "prompt_version": PROMPT_VERSION,
        "model": selected_model,
        "cache_only_default": True,
        "cached_pages": cached_pages,
        "missing_pages": missing_pages,
        "cached_count": len(cached_pages),
        "missing_count": len(missing_pages),
        "complete": not missing_pages,
    }


def _extract_text(payload: dict[str, Any]) -> str:
    for output in payload.get("output") or ():
        for content in output.get("content") or ():
            if content.get("type") == "output_text" and content.get("text"):
                return str(content["text"])
    return str(payload.get("output_text") or "")


def audit_page(*, page: int, confirm_live: bool = False, model: str | None = None) -> dict[str, Any]:
    """Return cached audit or make exactly one explicitly confirmed request."""

    selected_model = model or os.getenv("MAAS_BOOK_SCAN_VLM_MODEL") or DEFAULT_VLM_MODEL
    path, image_hash, image_path = _cache_path(page, selected_model)
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached.get("schema_version") == SCHEMA_VERSION:
            return {**cached, "cache_hit": True}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    if not confirm_live:
        return {
            "schema_version": SCHEMA_VERSION,
            "page": int(page),
            "status": "cache_miss",
            "cache_hit": False,
            "live_request_made": False,
        }
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise VlmScoringError("OPENAI_API_KEY is not set")

    image_url = "data:image/jpeg;base64," + base64.b64encode(image_path.read_bytes()).decode("ascii")
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["visible_sections", "visible_entities", "base_models", "operatives", "procedure_or_variation_notes", "confidence", "needs_review"],
        "properties": {
            "visible_sections": {"type": "array", "items": {"type": "string"}},
            "visible_entities": {"type": "array", "items": {"type": "string"}},
            "base_models": {"type": "array", "items": {"type": "string"}},
            "operatives": {"type": "array", "items": {"type": "string"}},
            "procedure_or_variation_notes": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "needs_review": {"type": "boolean"},
        },
    }
    body = {
        "model": selected_model,
        "input": [{
            "role": "user",
            "content": [
                {"type": "input_text", "text": (
                    f"Audit BOOK scan page {page} as architectural source evidence. "
                    "Transcribe only visibly supported form-language content. Distinguish base model, operative, "
                    "combination/aggregation, and case-study evidence. Never invent executable geometry."
                )},
                {"type": "input_image", "image_url": image_url},
            ],
        }],
        "text": {"format": {"type": "json_schema", "name": "book_scan_audit", "strict": True, "schema": schema}},
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    _consume_live_vlm_request_budget(kind="book_scan_vlm")
    try:
        with urllib.request.urlopen(request, timeout=150) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
        parsed = json.loads(_extract_text(response_payload))
    except Exception as exc:
        raise VlmScoringError(f"BOOK scan VLM audit failed for page {page}: {exc}") from exc
    result = {
        "schema_version": SCHEMA_VERSION,
        "prompt_version": PROMPT_VERSION,
        "page": int(page),
        "status": "audited",
        "model": selected_model,
        "response_id": str(response_payload.get("id") or ""),
        "image_hash": image_hash,
        "cache_hit": False,
        "live_request_made": True,
        **parsed,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    return result


def audit_pages(*, pages: Iterable[int], confirm_live: bool = False, model: str | None = None) -> list[dict[str, Any]]:
    return [audit_page(page=int(page), confirm_live=confirm_live, model=model) for page in pages]


__all__ = ["SCHEMA_VERSION", "PROMPT_VERSION", "audit_page", "audit_pages", "audit_status", "cache_root"]
