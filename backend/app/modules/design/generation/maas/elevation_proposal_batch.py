"""Explicit second-stage facade proposals for an inspected MASS batch."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.app.modules.design.generation.maas.agents.elevation_agent import generate_elevation_image_proposal, generate_multi_view_elevation_proposal, select_facade_strategy
from backend.app.modules.design.generation.maas.aesthetic.contracts import AestheticProvider
from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.compiler import compile_geometry_program
from backend.app.modules.design.generation.maas.geometry_language.execution_activation import refresh_elevation_proposal_graph, refresh_multi_view_elevation_graph
from backend.app.modules.design.generation.maas.single_execution.persistence import write_json_atomic


def generate_execution_elevation_proposal(
    output_root: str | Path,
    execution_id: str,
    *,
    adapter: AestheticProvider,
) -> dict[str, Any]:
    """Generate ALT 01 once for an existing immutable-geometry execution."""

    root = Path(output_root).resolve()
    directory = (root / execution_id).resolve()
    if not directory.is_relative_to(root):
        raise ValueError("execution path escapes MASS archive")
    program_path = directory / "program.json"
    preview_path = directory / "mass.png"
    passport_path = directory / "mass.png.passport.json"
    execution_path = directory / "execution.json"
    bundle_path = directory / "elevation" / "manifest.json"
    proposal_path = directory / "elevation" / "proposals" / "alt-01" / "proposal.json"
    if proposal_path.is_file():
        payload = json.loads(proposal_path.read_text(encoding="utf-8"))
        return {**payload, "skipped_existing": True}
    program = GeometryProgram.from_dict(
        json.loads(program_path.read_text(encoding="utf-8"))
    )
    compilation = compile_geometry_program(program)
    passport = json.loads(passport_path.read_text(encoding="utf-8"))
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    if compilation.status != "compiled":
        raise ValueError("persisted MASS no longer compiles")
    identity = (
        str(passport.get("program_hash") or ""),
        str(passport.get("geometry_hash") or ""),
    )
    if identity != (program.program_hash(), str(compilation.geometry_hash or "")):
        raise ValueError("MASS passport identity no longer matches compiled geometry")
    if (
        str(bundle.get("program_hash") or "") != identity[0]
        or str(bundle.get("geometry_hash") or "") != identity[1]
    ):
        raise ValueError("elevation bundle identity does not match selected MASS")

    strategy = select_facade_strategy(program, compilation)
    proposal = generate_elevation_image_proposal(
        bundle,
        preview_path,
        adapter=adapter,
        strategy=strategy,
    )
    elevation = passport.get("elevation_evidence")
    elevation = dict(elevation) if isinstance(elevation, dict) else {}
    elevation["facade_strategy"] = strategy
    elevation["image_proposal"] = proposal
    passport["elevation_evidence"] = elevation
    passport["activation_graph"] = refresh_elevation_proposal_graph(
        dict(passport.get("activation_graph") or {}),
        proposal,
    )
    write_json_atomic(passport_path, passport)

    execution = json.loads(execution_path.read_text(encoding="utf-8"))
    execution["elevation_image_proposal"] = {
        "status": str(proposal.get("status") or ""),
        "provider": str(proposal.get("provider") or ""),
        "model": str(
            (proposal.get("provider_metadata") or {}).get("model") or ""
        ),
        "request_count": int(proposal.get("request_count") or 0),
        "retry_count": int(proposal.get("retry_count") or 0),
        "manifest_path": str(proposal.get("manifest_path") or ""),
    }
    write_json_atomic(execution_path, execution)
    return {**proposal, "skipped_existing": False}


def generate_execution_multi_view_elevation_proposal(
    output_root: str | Path,
    execution_id: str,
    *,
    adapter: AestheticProvider,
    critic: Any,
) -> dict[str, Any]:
    """Generate bounded four-view facade evidence for one persisted execution."""

    root = Path(output_root).resolve()
    directory = (root / execution_id).resolve()
    if not directory.is_relative_to(root):
        raise ValueError("execution path escapes MASS archive")
    program_path = directory / "program.json"
    passport_path = directory / "mass.png.passport.json"
    execution_path = directory / "execution.json"
    bundle_path = directory / "elevation" / "manifest.json"
    program = GeometryProgram.from_dict(
        json.loads(program_path.read_text(encoding="utf-8"))
    )
    compilation = compile_geometry_program(program)
    passport = json.loads(passport_path.read_text(encoding="utf-8"))
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    if compilation.status != "compiled":
        raise ValueError("persisted MASS no longer compiles")
    identity = (
        str(passport.get("program_hash") or ""),
        str(passport.get("geometry_hash") or ""),
    )
    if identity != (program.program_hash(), str(compilation.geometry_hash or "")):
        raise ValueError("MASS passport identity no longer matches compiled geometry")
    if (
        str(bundle.get("execution_id") or "") != str(execution_id)
        or str(bundle.get("program_hash") or "") != identity[0]
        or str(bundle.get("geometry_hash") or "") != identity[1]
    ):
        raise ValueError("elevation bundle identity does not match selected MASS")

    strategy = select_facade_strategy(program, compilation)
    proposal = generate_multi_view_elevation_proposal(
        bundle,
        adapter=adapter,
        critic=critic,
        strategy=strategy,
    )
    elevation = passport.get("elevation_evidence")
    elevation = dict(elevation) if isinstance(elevation, dict) else {}
    elevation["facade_strategy"] = strategy
    elevation["multi_view_proposal"] = proposal
    passport["elevation_evidence"] = elevation
    passport["activation_graph"] = refresh_multi_view_elevation_graph(
        dict(passport.get("activation_graph") or {}),
        proposal,
    )
    write_json_atomic(passport_path, passport)

    execution = json.loads(execution_path.read_text(encoding="utf-8"))
    execution["multi_view_elevation_proposal"] = {
        "status": str(proposal.get("status") or ""),
        "paid_request_attempt_count": int(
            proposal.get("paid_request_attempt_count") or 0
        ),
        "retry_count": int(proposal.get("retry_count") or 0),
        "manifest_path": str(proposal.get("manifest_path") or ""),
        "accepted": proposal.get("status") == "accepted",
    }
    write_json_atomic(execution_path, execution)
    return proposal


def generate_batch_elevation_proposals(
    output_root: str | Path,
    *,
    batch_id: str,
    adapter: AestheticProvider,
    limit: int = 10,
) -> dict[str, Any]:
    """Run an explicit bounded proposal stage with no automatic retries."""

    root = Path(output_root).resolve()
    batch_path = root / f"{batch_id}.batch.json"
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    if str(batch.get("status") or "") != "complete":
        raise ValueError("elevation proposals require a complete MASS batch")
    ceiling = max(0, min(10, int(limit)))
    proposals: list[dict[str, Any]] = []
    provider_calls = 0
    paid_attempts = 0
    for execution_id in (batch.get("execution_ids") or ())[:ceiling]:
        proposal = generate_execution_elevation_proposal(
            root,
            str(execution_id),
            adapter=adapter,
        )
        proposals.append({
            "execution_id": str(execution_id),
            "status": str(proposal.get("status") or ""),
            "provider": str(proposal.get("provider") or ""),
            "model": str((proposal.get("provider_metadata") or {}).get("model") or ""),
            "skipped_existing": bool(proposal.get("skipped_existing")),
            "artifact": dict(proposal.get("artifact") or {}),
            "issues": list(proposal.get("issues") or ()),
        })
        if not proposal.get("skipped_existing"):
            provider_calls += 1
            if str(proposal.get("status") or "") != "not_configured":
                paid_attempts += 1
    batch["elevation_proposal_stage"] = {
        "schema_version": "arr.maas.batch_elevation_proposals.v1",
        "limit": ceiling,
        "provider_call_count": provider_calls,
        "paid_request_attempt_count": paid_attempts,
        "cumulative_paid_request_attempt_count": _cumulative_paid_attempts(
            root,
            batch.get("execution_ids") or (),
        ),
        "retry_count": 0,
        "proposals": proposals,
    }
    batch["paid_image_request_count"] = batch["elevation_proposal_stage"][
        "cumulative_paid_request_attempt_count"
    ]
    write_json_atomic(batch_path, batch)
    return batch["elevation_proposal_stage"]


def _cumulative_paid_attempts(root: Path, execution_ids: Any) -> int:
    count = 0
    for execution_id in execution_ids:
        manifest = (
            root
            / str(execution_id)
            / "elevation"
            / "proposals"
            / "alt-01"
            / "proposal.json"
        )
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if (
            int(payload.get("request_count") or 0) > 0
            and str(payload.get("status") or "") != "not_configured"
        ):
            count += 1
    return count


__all__ = [
    "generate_batch_elevation_proposals",
    "generate_execution_elevation_proposal",
    "generate_execution_multi_view_elevation_proposal",
]
