"""Adapt one-MASS bundles to the existing chronological archive read model."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.dsl import program_to_dsl
from backend.app.modules.design.generation.maas.mass_product_evidence import floor_capacity_plan_hash, serialize_mass_product_evidence


RUN_PREFIX = "single-execution:"


def single_execution_run_id(execution_id: str) -> str:
    return f"{RUN_PREFIX}{execution_id}"


def single_execution_id(run_id: str) -> str:
    value = str(run_id or "")
    if not value.startswith(RUN_PREFIX):
        raise ValueError(f"not a single execution run: {value}")
    execution_id = value[len(RUN_PREFIX):]
    if not execution_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for character in execution_id):
        raise ValueError("invalid single execution id")
    return execution_id


def is_single_execution_run(run_id: str | None) -> bool:
    return str(run_id or "").startswith(RUN_PREFIX)


def single_execution_program(root: str | Path, run_id: str) -> GeometryProgram:
    directory = _directory(root, single_execution_id(run_id))
    return GeometryProgram.from_dict(_read_json(directory / "program.json"))


def single_execution_passport(root: str | Path, run_id: str) -> dict[str, Any]:
    directory = _directory(root, single_execution_id(run_id))
    return _read_json(directory / "mass.png.passport.json")


def single_execution_preview(root: str | Path, run_id: str) -> Path:
    directory = _directory(root, single_execution_id(run_id))
    preview = (directory / "mass.png").resolve()
    if not preview.is_file():
        raise FileNotFoundError(preview)
    return preview


def single_execution_runs(root: str | Path) -> list[dict[str, Any]]:
    resolved_root = Path(root).resolve()
    rows: list[dict[str, Any]] = []
    if not resolved_root.is_dir():
        return rows
    for manifest_path in resolved_root.glob("*/execution.json"):
        try:
            manifest = _read_json(manifest_path)
            if manifest.get("geometry_ready") is not True:
                continue
            execution_id = str(manifest.get("execution_id") or manifest_path.parent.name)
            passport = _read_json(manifest_path.parent / "mass.png.passport.json")
            rows.append(_run_row(manifest, passport, manifest_path, execution_id))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return sorted(rows, key=lambda row: (row["created_at"], row["run_id"]))


def single_execution_archive_manifest(
    root: str | Path,
    run_id: str,
    *,
    other_runs: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    execution_id = single_execution_id(run_id)
    directory = _directory(root, execution_id)
    manifest_path = directory / "execution.json"
    manifest = _read_json(manifest_path)
    passport = _read_json(directory / "mass.png.passport.json")
    program = GeometryProgram.from_dict(_read_json(directory / "program.json"))
    run = _run_row(manifest, passport, manifest_path, execution_id)
    all_runs = _merge_runs((*other_runs, *single_execution_runs(root)))
    metadata = program.metadata or {}
    book = metadata.get("book_recursive_projection") if isinstance(metadata.get("book_recursive_projection"), dict) else {}
    projection = metadata.get("program_projection") if isinstance(metadata.get("program_projection"), dict) else {}
    stages = {str(row.get("id") or ""): row for row in passport.get("stages") or () if isinstance(row, dict)}
    capacity = _evidence(stages.get("capacity"))
    mass_product = serialize_mass_product_evidence(
        program=program,
        capacity=capacity,
        passport=passport,
    )
    result_id = quote(run_id, safe="")
    mass = {
        "archive_key": f"{run_id}:1",
        "index": 1,
        "variant_id": execution_id,
        "label": str(passport.get("program_name") or program.name),
        "operation_label": _operation_label(program),
        "source_sequence": "single_execution",
        "execution_mode": str(manifest.get("execution_mode") or "legacy_unspecified"),
        "source_run_id": str(manifest.get("source_run_id") or ""),
        "source_mass_index": int(manifest.get("source_mass_index") or 0),
        "run_id": run_id,
        "program_type": str(projection.get("program_id") or metadata.get("family") or "unassigned"),
        "program_label": str(projection.get("program_label") or projection.get("program_id") or "NOT EVALUATED"),
        "program_hash": str(manifest.get("program_hash") or passport.get("program_hash") or ""),
        "geometry_hash": str(manifest.get("geometry_hash") or passport.get("geometry_hash") or ""),
        "visual_hash": str(
            manifest.get("visual_hash")
            or passport.get("visual_hash")
            or ""
        ),
        "dsl": program_to_dsl(program),
        "node_count": len(program.nodes),
        "operator_path": [node.operator for node in program.topological_nodes()],
        "book_principle_id": _book_principle_id(book),
        "book_scope": str(book.get("scope_label") or metadata.get("book_scope") or "NOT EVALUATED"),
        "book_orientation": str(
            book.get("scope_orientation")
            or book.get("orientation")
            or metadata.get("book_orientation")
            or "NOT EVALUATED"
        ),
        "capacity_alternative_id": str(capacity.get("alternative_id") or "NOT EVALUATED"),
        "capacity_target_utilization": _number_or_none(capacity.get("target_utilization")),
        "capacity_achieved_utilization": _number_or_none(capacity.get("achieved_utilization")),
        **mass_product,
        "score": None,
        "hard_pass": bool(passport.get("final_hard_pass")),
        "geometry_ready": bool(manifest.get("geometry_ready")),
        "vlm_evaluated": stages.get("vlm", {}).get("status") not in {None, "not_evaluated"},
        "preview_url": f"/design/maas/executed-masses/1/?run_id={result_id}",
        "passport_url": f"/design/maas/executed-masses/1/passport/?run_id={result_id}",
        "image_role": "single_mass_execution_render",
    }
    return {
        "schema_version": "arr.maas.executed_mass_archive.v1",
        "run_id": run_id,
        "pnu": run["pnu"],
        "run_status": "single_mass_geometry_ready",
        "numeric_status": "not_applicable",
        "source_archive": str(manifest_path),
        "mass_count": 1,
        "selected_run_id": run_id,
        "run_count": len(all_runs),
        "archive_revision": f"{run['created_at']}:{manifest_path.stat().st_mtime_ns}",
        "runs": all_runs,
        "book_images_included": False,
        "image_authority": "actual single GeometryProgram compiler render",
        "portfolio_vlm_audit": {},
        "masses": [mass],
    }


def _run_row(
    manifest: dict[str, Any],
    passport: dict[str, Any],
    manifest_path: Path,
    execution_id: str,
) -> dict[str, Any]:
    site = next((row for row in passport.get("stages") or () if isinstance(row, dict) and row.get("id") == "site"), {})
    vlm = next((row for row in passport.get("stages") or () if isinstance(row, dict) and row.get("id") == "vlm"), {})
    manifest_vlm = manifest.get("vlm_review") if isinstance(manifest.get("vlm_review"), dict) else {}
    vlm_evidence = _evidence(vlm)
    created_at = str(manifest.get("created_at") or datetime.fromtimestamp(
        manifest_path.stat().st_mtime,
        tz=timezone.utc,
    ).isoformat())
    return {
        "run_id": single_execution_run_id(execution_id),
        "created_at": created_at,
        "geometry_hash": str(manifest.get("geometry_hash") or passport.get("geometry_hash") or ""),
        "thumbnail_url": f"/design/maas/single-executions/{execution_id}/thumbnail/",
        "pnu": str(_evidence(site).get("pnu") or ""),
        "site_context_status": _site_context_status(site),
        "selected_mass_count": 1,
        "status": "single_mass_ready",
        "replayable": True,
        "run_type": "single_execution",
        "execution_mode": str(manifest.get("execution_mode") or "legacy_unspecified"),
        "source_run_id": str(manifest.get("source_run_id") or ""),
        "source_mass_index": int(manifest.get("source_mass_index") or 0),
        "full_flow_status": str(manifest.get("full_flow_status") or ""),
        "vlm_status": str(
            manifest_vlm.get("status")
            or vlm.get("status")
            or vlm_evidence.get("status")
            or "not_evaluated"
        ),
        "vlm_hard_pass": bool(
            manifest_vlm.get("hard_pass")
            if "hard_pass" in manifest_vlm
            else vlm_evidence.get("hard_pass")
        ),
        "floor_capacity_plan_hash": floor_capacity_plan_hash(passport=passport),
    }


def _site_context_status(site_stage: Any) -> str:
    evidence = _evidence(site_stage)
    pnu = str(evidence.get("pnu") or "").strip()
    matrix = evidence.get("placement_matrix4")
    parcel = evidence.get("parcel_geometry")
    matrix_values = (
        [value for row in matrix for value in row]
        if isinstance(matrix, list)
        and len(matrix) == 4
        and all(isinstance(row, list) and len(row) == 4 for row in matrix)
        else ()
    )
    if pnu and len(matrix_values) == 16 and isinstance(parcel, dict):
        return "site_bound"
    if pnu:
        return "source_gate_only"
    return "unresolved"


def _directory(root: str | Path, execution_id: str) -> Path:
    resolved_root = Path(root).resolve()
    directory = (resolved_root / execution_id).resolve()
    if not directory.is_relative_to(resolved_root) or not directory.is_dir():
        raise FileNotFoundError(directory)
    return directory


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object in {path}")
    return value


def _merge_runs(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {str(row.get("run_id") or ""): dict(row) for row in rows if row.get("run_id")}
    return sorted(by_id.values(), key=lambda row: (str(row.get("created_at") or ""), row["run_id"]))


def _operation_label(program: GeometryProgram) -> str:
    operators = [node.operator for node in program.topological_nodes()]
    return " -> ".join(operators[-3:]) if operators else "NO OPERATOR"


def _book_principle_id(book: dict[str, Any]) -> str:
    explicit = str(book.get("principle_id") or "").strip()
    if explicit:
        return explicit
    verbs = [str(value).strip() for value in book.get("ordered_verbs") or () if str(value).strip()]
    if verbs:
        return f"book:operative:{verbs[-1]}"
    return "NOT EVALUATED"


def _evidence(stage: Any) -> dict[str, Any]:
    return dict(stage.get("evidence") or {}) if isinstance(stage, dict) else {}


def _number_or_none(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


__all__ = [
    "is_single_execution_run",
    "single_execution_archive_manifest",
    "single_execution_passport",
    "single_execution_preview",
    "single_execution_program",
    "single_execution_run_id",
    "single_execution_runs",
]
