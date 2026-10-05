"""Durable cache contract for service-facing MAAS review sets."""

from __future__ import annotations

from backend.app.modules.design.generation import paths as _design_paths

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "arr.maas.service_cache.v1"


def cache_root() -> Path:
    raw = os.getenv("MAAS_SERVICE_CACHE_DIR", "docs/ai-session-memory/maas-service-cache")
    path = Path(raw).expanduser()
    # service_cache.py lives at <workspace>/ARR/backend/design/maas. parents[4]
    # is the workspace root; parents[5] escaped to D:/Data and published cache
    # files outside the project.
    return path if path.is_absolute() else _design_paths.workspace_root() / path


def request_cache_key(payload: dict[str, Any]) -> str:
    contract = {
        "schema": SCHEMA_VERSION,
        "pnu": payload.get("pnu") or "",
        "building_type": payload.get("building_type") or "",
        "site_polygon": payload.get("site_polygon"),
        "mass_geojson": payload.get("mass_geojson"),
        "constraints": payload.get("constraints") or [],
        "sunlight_envelope": payload.get("sunlight_envelope"),
        "setback_geometries": payload.get("setback_geometries"),
        "max_variants": int(payload.get("max_variants") or 6),
        "preferred_operator": payload.get("preferred_operator") or "",
        "parking_options": payload.get("parking_options") or {},
    }
    encoded = json.dumps(contract, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def cache_path(key: str) -> Path:
    return cache_root() / f"{key}.json"


def is_verified_result(result: dict[str, Any]) -> bool:
    features = ((result.get("feature_collection") or {}).get("features") or [])
    projection = result.get("final_integer_projection") or {}
    completion = result.get("final_vlm_completion") or {}
    if len(features) < 20 or projection.get("status") not in {"optimal", "feasible"}:
        return False
    if int(completion.get("final_vlm_scored_count") or 0) != 20:
        return False
    return all(
        bool((((feature.get("properties") or {}).get("source_signature") or {}).get("coherence_evidence") or {}).get("hard_pass"))
        for feature in features[:20]
    )


def load_verified_result(key: str) -> dict[str, Any] | None:
    try:
        envelope = json.loads(cache_path(key).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    result = envelope.get("result") if isinstance(envelope, dict) else None
    return result if isinstance(result, dict) and is_verified_result(result) else None


def store_verified_result(key: str, result: dict[str, Any]) -> Path:
    if not is_verified_result(result):
        raise ValueError("refusing to cache unverified MAAS result")
    path = cache_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps({"schema_version": SCHEMA_VERSION, "key": key, "result": result}, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    return path


__all__ = ["is_verified_result", "load_verified_result", "request_cache_key", "store_verified_result"]
