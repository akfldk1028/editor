"""Bounded paid-VLM review for one immutable single-MASS execution."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from backend.app.modules.design.generation.maas.geometry_language.compiler import compile_geometry_program
from backend.app.modules.design.generation.maas.geometry_language.execution_passport import enrich_mass_execution_passport
from backend.app.modules.design.generation.maas.geometry_language.vlm_adapter import retrieve_geometry_reference_matches, score_geometry_program_with_openai_vlm

from backend.app.modules.design.generation.maas.single_execution.catalog import single_execution_passport, single_execution_program, single_execution_run_id
from backend.app.modules.design.generation.maas.single_execution.persistence import write_json_atomic


def review_single_mass_with_vlm(
    output_root: str | Path,
    execution_id: str,
    *,
    reference_limit: int = 3,
    building_type: str = "",
    model: str | None = None,
) -> dict[str, Any]:
    """Review one rendered MASS with at most three references and no retries."""

    limit = max(0, min(3, int(reference_limit)))
    root = Path(output_root).resolve()
    run_id = single_execution_run_id(execution_id)
    directory = (root / execution_id).resolve()
    try:
        directory.relative_to(root)
    except ValueError as exc:
        raise ValueError("execution path escapes single-execution root") from exc
    preview_path = directory / "mass.png"
    passport_path = directory / "mass.png.passport.json"
    manifest_path = directory / "execution.json"
    if not preview_path.is_file() or not manifest_path.is_file():
        raise ValueError(f"single MASS execution is not geometry-ready: {execution_id}")

    program = single_execution_program(root, run_id)
    compilation = compile_geometry_program(program)
    passport = single_execution_passport(root, run_id)
    if compilation.status != "compiled":
        raise ValueError("persisted single MASS program no longer compiles")
    if str(passport.get("geometry_hash") or "") != compilation.geometry_hash:
        raise ValueError("persisted MASS geometry hash does not match its program")

    resolved_building_type = _resolve_building_type(
        program.metadata or {},
        explicit=building_type,
    )
    references = retrieve_geometry_reference_matches(
        program,
        building_type=resolved_building_type,
        limit=max(1, limit),
    ) if limit else []
    references = references[:limit]
    result = score_geometry_program_with_openai_vlm(
        program,
        compilation,
        preview_path,
        reference_matches=references,
        building_type=resolved_building_type,
        model=model,
        write_passport_sidecar=False,
        max_retries=0,
    )

    candidate_sha = hashlib.sha256(preview_path.read_bytes()).hexdigest()
    result["hard_pass"] = bool(result.get("program_fit_hard_pass"))
    result["evidence_binding"] = {
        "schema_version": "arr.maas.vlm_evidence_binding.v1",
        "execution_id": execution_id,
        "program_hash": program.program_hash(),
        "geometry_hash": compilation.geometry_hash,
        "candidate_sha256": candidate_sha,
        "prompt_contract_version": str(result.get("prompt_contract_version") or ""),
        "model": str(result.get("model") or ""),
    }
    result["cost_observation"] = _cost_observation(result, limit)

    enriched = enrich_mass_execution_passport(passport, vlm_result=result)
    write_json_atomic(passport_path, enriched)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["full_flow_status"] = str(enriched.get("status") or "in_progress")
    manifest["vlm_review"] = {
        "status": next(
            (stage.get("status") for stage in enriched.get("stages") or [] if stage.get("id") == "vlm"),
            "not_evaluated",
        ),
        "hard_pass": bool(result.get("hard_pass")),
        "model": str(result.get("model") or ""),
        "response_id": str(result.get("response_id") or ""),
        "cache_hit": bool(result.get("cache_hit")),
        "cost_observation": result["cost_observation"],
        "evidence_binding": result["evidence_binding"],
    }
    write_json_atomic(manifest_path, manifest)
    return {
        "schema_version": "arr.maas.single_execution_vlm_review.v1",
        "execution_id": execution_id,
        "archive_run_id": run_id,
        "status": manifest["vlm_review"]["status"],
        "hard_pass": bool(result.get("hard_pass")),
        "full_flow_status": manifest["full_flow_status"],
        "model": str(result.get("model") or ""),
        "response_id": str(result.get("response_id") or ""),
        "cache_hit": bool(result.get("cache_hit")),
        "concept_scores": dict(result.get("concept_scores") or {}),
        "critic_actions": list(result.get("critic_actions") or ()),
        "rationale": str(result.get("rationale") or ""),
        "reference_count": len(references),
        "cost_observation": result["cost_observation"],
        "evidence_binding": result["evidence_binding"],
    }


def _cost_observation(result: dict[str, Any], reference_limit: int) -> dict[str, Any]:
    usage_rows: list[dict[str, Any]] = []
    candidate_usage = result.get("api_usage")
    if isinstance(candidate_usage, dict) and candidate_usage:
        usage_rows.append(candidate_usage)
    gate = result.get("reference_massing_gate")
    gate = gate if isinstance(gate, dict) else {}
    reference_rows = [
        *(gate.get("rejected") or ()),
    ]
    causal = result.get("maas_causal_context")
    causal = causal if isinstance(causal, dict) else {}
    for item in causal.get("reference_matches") or ():
        audit = item.get("massing_image_audit") if isinstance(item, dict) else None
        if isinstance(audit, dict):
            reference_rows.append(audit)
    for item in reference_rows:
        usage = item.get("api_usage") if isinstance(item, dict) else None
        if isinstance(usage, dict) and usage:
            usage_rows.append(usage)
    totals = {
        key: sum(int(row.get(key) or 0) for row in usage_rows)
        for key in ("input_tokens", "output_tokens", "total_tokens")
    }
    return {
        "schema_version": "arr.maas.vlm_cost_observation.v1",
        "reference_limit": reference_limit,
        "max_http_attempts": 1 + reference_limit,
        "retries": 0,
        "candidate_cache_hit": bool(result.get("cache_hit")),
        "usage": totals,
        "usage_record_count": len(usage_rows),
    }


def _resolve_building_type(metadata: dict[str, Any], *, explicit: str = "") -> str:
    projection = metadata.get("program_projection")
    projection = projection if isinstance(projection, dict) else {}
    return str(
        explicit
        or metadata.get("building_type")
        or metadata.get("program_id")
        or projection.get("building_type")
        or projection.get("program_id")
        or metadata.get("family")
        or "generic"
    )


__all__ = ["review_single_mass_with_vlm"]
