"""Append-only, credential-free evidence for versioned MASS executions."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping


VERSION_MEMORY_SCHEMA = "arr.maas.version_memory.v1"
_VERSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "credential",
    "password",
    "secret",
    "access_token",
    "refresh_token",
)


def _safe_payload(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        return "<depth-limited>"
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key in sorted(value, key=lambda item: str(item))[:128]:
            key = str(raw_key)
            normalized = key.lower().replace("-", "_")
            if any(part in normalized for part in _SENSITIVE_KEY_PARTS):
                continue
            result[key[:160]] = _safe_payload(
                value[raw_key],
                depth=depth + 1,
            )
        return result
    if isinstance(value, (list, tuple)):
        return [_safe_payload(item, depth=depth + 1) for item in value[:256]]
    if isinstance(value, str):
        return value[:2_000]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return str(value)[:2_000]


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def write_version_snapshot(
    output_dir: Path,
    *,
    version_id: str,
    parent_version_id: str,
    stage: str,
    payload: dict[str, Any],
) -> Path:
    """Create one immutable version record, allowing byte-equivalent replay."""

    version = str(version_id).strip()
    parent = str(parent_version_id or "").strip()
    if not _VERSION_ID.fullmatch(version):
        raise ValueError("invalid MASS version memory id")
    if parent and not _VERSION_ID.fullmatch(parent):
        raise ValueError("invalid MASS parent version memory id")
    safe_payload = _safe_payload(payload)
    payload_json = _canonical_json(safe_payload)
    payload_sha256 = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    identity = {
        "schema_version": VERSION_MEMORY_SCHEMA,
        "version_id": version,
        "parent_version_id": parent,
        "stage": str(stage or "unknown")[:120],
        "payload_sha256": payload_sha256,
        "payload": safe_payload,
    }
    memory_dir = Path(output_dir).resolve() / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    target = memory_dir / f"{version}.json"
    if target.exists():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError) as exc:
            raise ValueError(
                "version memory snapshot already exists with different content"
            ) from exc
        comparable = {
            key: existing.get(key)
            for key in identity
        } if isinstance(existing, dict) else {}
        if comparable == identity:
            return target
        raise ValueError(
            "version memory snapshot already exists with different content"
        )
    record = {
        **identity,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    encoded = (
        json.dumps(record, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    try:
        with target.open("xb") as handle:
            handle.write(encoded)
    except FileExistsError:
        return write_version_snapshot(
            output_dir,
            version_id=version,
            parent_version_id=parent,
            stage=stage,
            payload=payload,
        )
    return target


def write_progress_checkpoint(
    output_dir: Path,
    *,
    version_id: str,
    stage: str,
    payload: dict[str, Any],
) -> Path:
    """Persist one idempotent checkpoint for one distinct progress state."""

    parent = str(version_id).strip()
    if not _VERSION_ID.fullmatch(parent):
        raise ValueError("invalid MASS version memory id")
    safe_payload = _safe_payload(payload)
    checkpoint_hash = hashlib.sha256(
        _canonical_json({
            "stage": str(stage),
            "payload": safe_payload,
        }).encode("utf-8")
    ).hexdigest()
    checkpoint_id = f"{parent[:80]}--cp-{checkpoint_hash[:16]}"
    return write_version_snapshot(
        output_dir,
        version_id=checkpoint_id,
        parent_version_id=parent,
        stage=f"progress:{str(stage or 'running')[:100]}",
        payload=safe_payload,
    )


__all__ = [
    "VERSION_MEMORY_SCHEMA",
    "write_progress_checkpoint",
    "write_version_snapshot",
]
