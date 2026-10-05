"""Atomic, evidence-preserving persistence for per-MASS passport sidecars."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping
import uuid


def passport_path_for_preview(preview_path: str | Path) -> Path:
    preview = Path(preview_path)
    return preview.with_suffix(f"{preview.suffix}.passport.json")


def write_mass_execution_passport(
    compilation: Any,
    preview_path: str | Path,
    *,
    vlm_result: Mapping[str, Any] | None = None,
    downstream_evidence: Mapping[str, Any] | None = None,
    geometry_graph_snapshot: Mapping[str, Any] | None = None,
    geometry_gate_evidence: Mapping[str, Any] | None = None,
    agent_collaboration: Mapping[str, Any] | None = None,
    elevation_evidence: Mapping[str, Any] | None = None,
) -> Path:
    """Write a sidecar without erasing later evidence during a rerender."""

    from backend.app.modules.design.generation.maas.geometry_language.execution_agent_context import build_mass_execution_agent_context
    from backend.app.modules.design.generation.maas.geometry_language.execution_passport import build_mass_execution_passport, enrich_mass_execution_passport

    output = passport_path_for_preview(preview_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    passport = build_mass_execution_passport(
        compilation,
        preview_path=preview_path,
        vlm_result=vlm_result,
        downstream_evidence=downstream_evidence,
        geometry_gate_evidence=geometry_gate_evidence,
        agent_collaboration=agent_collaboration,
        elevation_evidence=elevation_evidence,
    )
    existing = _load_matching_passport(
        output,
        program_hash=str(passport.get("program_hash") or ""),
        geometry_hash=str(passport.get("geometry_hash") or ""),
    )
    if existing:
        preserved_downstream = {
            str(row.get("id") or ""): row.get("evidence") or {}
            for row in existing.get("stages") or ()
            if isinstance(row, dict)
            and row.get("id") in {"site", "capacity", "law", "parking", "program_fit", "selector"}
            and row.get("status") != "not_evaluated"
        }
        if preserved_downstream:
            passport = enrich_mass_execution_passport(passport, downstream_evidence=preserved_downstream)
        if vlm_result is None:
            previous_vlm = next((
                row.get("evidence") for row in existing.get("stages") or ()
                if isinstance(row, dict)
                and row.get("id") == "vlm"
                and row.get("status") != "not_evaluated"
                and isinstance(row.get("evidence"), dict)
            ), None)
            if previous_vlm:
                passport = enrich_mass_execution_passport(passport, vlm_result=previous_vlm)
    if downstream_evidence or vlm_result is not None:
        passport = enrich_mass_execution_passport(
            passport,
            downstream_evidence=downstream_evidence,
            vlm_result=vlm_result,
        )
    agent_context = build_mass_execution_agent_context(
        passport,
        geometry_graph_snapshot=geometry_graph_snapshot,
    )
    if existing and not geometry_graph_snapshot:
        previous_context = existing.get("agent_context")
        if isinstance(previous_context, dict):
            agent_context["protected_ast_node_ids"] = list(
                previous_context.get("protected_ast_node_ids") or ()
            )
    passport["agent_context"] = agent_context
    temporary = output.with_suffix(f".{os.getpid()}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(passport, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(output)
    return output


def _load_matching_passport(output: Path, *, program_hash: str, geometry_hash: str) -> dict[str, Any]:
    try:
        value = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(value, dict):
        return {}
    if str(value.get("program_hash") or "") != program_hash:
        return {}
    if str(value.get("geometry_hash") or "") != geometry_hash:
        return {}
    return value


__all__ = ["passport_path_for_preview", "write_mass_execution_passport"]
