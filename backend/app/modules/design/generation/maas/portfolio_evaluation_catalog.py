"""Validated read model for persisted MASS portfolio evaluations."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote


MANIFEST_SCHEMA = "arr.maas.portfolio_evaluation_manifest.v1"
LEDGER_SCHEMA = "arr.maas.portfolio_evaluation_ledger.v1"
_FILENAME = "maas-portfolio-evaluation.json"
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_CANDIDATE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]*$")
_HEX64_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def portfolio_evaluation_manifest(
    root: str | Path,
    run_id: str | None = None,
    *, include_runs: bool = True,
) -> dict[str, Any]:
    resolved_root = Path(root).resolve()
    selected_run = str(run_id or "").strip()
    if not selected_run:
        runs = _available_runs(resolved_root)
        if not runs:
            raise FileNotFoundError("no portfolio evaluation run")
        selected_run = runs[-1]
    run_directory = _run_directory(resolved_root, selected_run)
    payload = _read_object(run_directory / _FILENAME)
    if payload.get("schema_version") != MANIFEST_SCHEMA:
        raise ValueError("invalid portfolio evaluation schema")
    programs = payload.get("programs")
    if not isinstance(programs, list):
        raise ValueError("portfolio evaluation programs must be an array")
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for program in programs:
        if not isinstance(program, dict) or program.get(
            "schema_version"
        ) != LEDGER_SCHEMA:
            raise ValueError("invalid portfolio evaluation ledger")
        if str(program.get("run_id") or "") != selected_run:
            raise ValueError("portfolio evaluation run ID mismatch")
        program_slug = str(program.get("program_slug") or "")
        records = program.get("records")
        if not isinstance(records, list):
            raise ValueError("evaluation records must be an array")
        for raw_record in records:
            candidate = _validated_candidate(
                resolved_root,
                run_directory,
                selected_run,
                program_slug,
                raw_record,
            )
            key = (program_slug, candidate["candidate_id"])
            if key in seen:
                raise ValueError("duplicate portfolio evaluation candidate")
            seen.add(key)
            candidates.append(candidate)
    counts = Counter(
        str(candidate["overall_status"])
        for candidate in candidates
    )
    return {
        "schema_version": MANIFEST_SCHEMA,
        "run_id": selected_run,
        "pnu": str(payload.get("pnu") or ""),
        "candidate_count": len(candidates),
        "status_counts": dict(sorted(counts.items())),
        "candidates": candidates,
        **({"runs": portfolio_evaluation_runs(resolved_root)} if include_runs else {}),
    }


def portfolio_evaluation_render(
    root: str | Path,
    run_id: str,
    candidate_id: str,
) -> Path:
    manifest = portfolio_evaluation_manifest(root, run_id, include_runs=False)
    selected_id = str(candidate_id or "")
    _validate_id(selected_id, "candidate ID", _CANDIDATE_ID_PATTERN)
    matches = [
        candidate
        for candidate in manifest["candidates"]
        if candidate["candidate_id"] == selected_id
        and candidate["preview_path"]
    ]
    if len(matches) != 1:
        raise FileNotFoundError(selected_id)
    return _resolve_preview(
        Path(root).resolve(),
        _run_directory(Path(root).resolve(), str(run_id)),
        matches[0]["preview_path"],
    )


def _validated_candidate(
    root: Path,
    run_directory: Path,
    run_id: str,
    program_slug: str,
    value: Any,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("portfolio evaluation candidate must be an object")
    candidate = deepcopy(value)
    candidate_id = str(candidate.get("candidate_id") or "")
    _validate_id(candidate_id, "candidate ID", _CANDIDATE_ID_PATTERN)
    for field in ("program_hash", "geometry_hash"):
        if not _HEX64_PATTERN.fullmatch(str(candidate.get(field) or "")):
            raise ValueError(f"invalid evaluation {field}")
    integrity = [
        str(reason)
        for reason in candidate.get("integrity_failures") or ()
        if str(reason)
    ]
    vlm = (
        ((candidate.get("stages") or {}).get("vlm") or {}).get(
            "evidence"
        ) or {}
    )
    image_inputs = (
        vlm.get("vlm_image_inputs") or {}
        if isinstance(vlm, dict)
        else {}
    )
    image_candidate = (
        image_inputs.get("candidate") or {}
        if isinstance(image_inputs, dict)
        else {}
    )
    bound_geometry_hash = str(
        image_candidate.get("geometry_hash") or ""
    ) if isinstance(image_candidate, dict) else ""
    if (
        bound_geometry_hash
        and bound_geometry_hash != candidate["geometry_hash"]
        and "geometry_hash_mismatch" not in integrity
    ):
        integrity.append("geometry_hash_mismatch")
    preview_path = str(candidate.get("preview_path") or "").strip()
    if preview_path:
        _resolve_preview(root, run_directory, preview_path)
    if integrity:
        candidate["overall_status"] = "failed"
        candidate["integrity_failures"] = integrity
        reasons = list(candidate.get("terminal_reasons") or ())
        for failure in integrity:
            if failure not in reasons:
                reasons.insert(0, failure)
        candidate["terminal_reasons"] = reasons
    candidate.update({
        "run_id": run_id,
        "program_slug": program_slug,
        "preview_path": preview_path,
        "preview_url": (
            "/design/maas/portfolio-evaluations/"
            f"{quote(run_id, safe='')}/candidates/"
            f"{quote(candidate_id, safe='')}/render/"
            if preview_path
            else ""
        ),
    })
    return candidate


def _available_runs(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    run_files = [
        path
        for path in root.glob(f"*/{_FILENAME}")
        if _RUN_ID_PATTERN.fullmatch(path.parent.name)
    ]
    return [
        path.parent.name
        for path in sorted(
            run_files,
            key=lambda item: (item.stat().st_mtime_ns, item.parent.name),
        )
    ]


def portfolio_evaluation_runs(root: str | Path) -> list[dict[str, Any]]:
    root = Path(root).resolve()
    rows = []
    for run in _available_runs(root):
        path = _run_directory(root, run) / _FILENAME
        try:
            payload = _read_object(path)
            programs = payload.get('programs')
            if payload.get('schema_version') != MANIFEST_SCHEMA or not isinstance(programs, list):
                continue
            if any(not isinstance(p, dict) or p.get('schema_version') != LEDGER_SCHEMA
                   or p.get('run_id') != run or not isinstance(p.get('records'), list) for p in programs):
                continue
            rows.append({'run_id': run, 'candidate_count': sum(len(p['records']) for p in programs),
                         'pnu': str(payload.get('pnu') or ''),
                         'program_slugs': sorted({str(p.get('program_slug') or '') for p in programs}),
                         'archive_modified_at': datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()})
        except (OSError, ValueError, TypeError):
            continue
    return rows


def _run_directory(root: Path, run_id: str) -> Path:
    _validate_id(run_id, "run ID", _RUN_ID_PATTERN)
    directory = (root / run_id).resolve()
    if not directory.is_relative_to(root) or not directory.is_dir():
        raise FileNotFoundError(directory)
    return directory


def _resolve_preview(root: Path, run_directory: Path, value: str) -> Path:
    raw = Path(value)
    target = raw.resolve() if raw.is_absolute() else (
        run_directory / raw
    ).resolve()
    if (
        not target.is_relative_to(root)
        or not target.is_file()
        or target.suffix.lower() != ".png"
    ):
        raise FileNotFoundError(target)
    return target


def _validate_id(value: str, label: str, pattern: re.Pattern) -> None:
    if not pattern.fullmatch(value) or value in {".", ".."}:
        raise ValueError(f"invalid evaluation {label}")


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("portfolio evaluation document must be an object")
    return value


__all__ = [
    "MANIFEST_SCHEMA",
    "portfolio_evaluation_manifest",
    "portfolio_evaluation_render",
    "portfolio_evaluation_runs",
]
