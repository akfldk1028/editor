"""Validate and resume one persisted Codex OAuth geometry-author batch."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any


class OauthBatchResumeError(ValueError):
    """A persisted author batch is unsafe to resume."""


_BUNDLE_FILES = (
    "eligible-path-scan.json",
    "exact-oauth-request.json",
    "provider-output-schema.json",
    "provider-prompt.txt",
)


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError) as exc:
        raise OauthBatchResumeError(
            f"invalid OAuth batch artifact: {path.name}"
        ) from exc
    if not isinstance(payload, dict):
        raise OauthBatchResumeError(
            f"invalid OAuth batch artifact: {path.name}"
        )
    return payload


def validate_batch_bundle(bundle_dir: Path | str) -> dict[str, Any]:
    """Fail closed before a resumed provider request can consume usage."""

    directory = Path(bundle_dir).resolve()
    request = _read_json(directory / "exact-oauth-request.json")
    scan = _read_json(directory / "eligible-path-scan.json")
    attempt = _read_json(directory / "provider-attempt-result.json")
    eligible_paths = scan.get("eligible_paths")
    eligible_ids = scan.get("eligible_path_ids")
    if not isinstance(eligible_paths, list) or not isinstance(eligible_ids, list):
        raise OauthBatchResumeError("eligible BOOK path evidence is invalid")
    counts = {
        "target_count": request.get("target_count"),
        "author_batch_count": request.get("author_batch_count"),
        "parser_expected_count": request.get("parser_expected_count"),
        "eligible_count": len(eligible_paths),
    }
    if set(counts.values()) != {20}:
        raise OauthBatchResumeError("shared batch count mismatch")
    request_ids = request.get("eligible_path_ids")
    if (
        request.get("provider_request_count") != 1
        or not isinstance(request_ids, list)
        or request_ids != eligible_ids
        or len(set(eligible_ids)) != 20
    ):
        raise OauthBatchResumeError("eligible BOOK path identity mismatch")
    eligible_hash = _canonical_hash(eligible_ids)
    if (
        request.get("eligible_path_ids_sha256") != eligible_hash
        or scan.get("eligible_path_ids_sha256") != eligible_hash
    ):
        raise OauthBatchResumeError("eligible BOOK path digest mismatch")
    unsigned_request = {
        key: value
        for key, value in request.items()
        if key != "request_sha256"
    }
    if request.get("request_sha256") != _canonical_hash(unsigned_request):
        raise OauthBatchResumeError("OAuth batch request digest mismatch")
    expected_artifacts = attempt.get("artifact_sha256")
    expected_artifacts = (
        expected_artifacts if isinstance(expected_artifacts, dict) else {}
    )
    artifact_hashes = {}
    for name in _BUNDLE_FILES:
        path = directory / name
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise OauthBatchResumeError(
                f"missing OAuth batch artifact: {name}"
            ) from exc
        if expected_artifacts.get(name) != digest:
            raise OauthBatchResumeError(
                f"OAuth batch artifact digest mismatch: {name}"
            )
        artifact_hashes[name] = digest
    return {
        "schema_version": "arr.maas.oauth_batch_resume_preflight.v1",
        "hard_pass": True,
        **counts,
        "distinct_eligible_path_count": len(set(eligible_ids)),
        "eligible_path_ids_sha256": eligible_hash,
        "request_sha256": request["request_sha256"],
        "artifact_sha256": artifact_hashes,
    }


def run_codex_batch(
    bundle_dir: Path | str,
    *,
    workspace_dir: Path | str,
    response_name: str = "provider-response-v2.json",
    model: str = "gpt-5.6-sol",
    timeout_seconds: int = 1800,
) -> tuple[Path, subprocess.CompletedProcess[str]]:
    """Execute one validated batch and append the schema-valid raw response."""

    directory = Path(bundle_dir).resolve()
    validate_batch_bundle(directory)
    response_path = directory / response_name
    if response_path.exists():
        raise OauthBatchResumeError("provider response already exists")
    temporary = directory / f".{response_name}.tmp"
    temporary.unlink(missing_ok=True)
    executable = shutil.which("codex.cmd") or shutil.which("codex")
    if not executable:
        raise OauthBatchResumeError("Codex CLI is unavailable")
    prompt = (directory / "provider-prompt.txt").read_text(encoding="utf-8")
    command = [
        executable,
        "exec",
        "-m",
        model,
        "--output-schema",
        str(directory / "provider-output-schema.json"),
        "--output-last-message",
        str(temporary),
        "--sandbox",
        "read-only",
        "--cd",
        str(Path(workspace_dir).resolve()),
        "-",
    ]
    return _execute_and_persist(
        command=command,
        prompt=prompt,
        temporary=temporary,
        response_path=response_path,
        timeout_seconds=timeout_seconds,
    )


def run_codex_repair(
    bundle_dir: Path | str,
    *,
    workspace_dir: Path | str,
    session_id: str,
    schema_name: str,
    prompt_name: str,
    response_name: str,
    model: str = "gpt-5.6-sol",
    timeout_seconds: int = 1800,
) -> tuple[Path, subprocess.CompletedProcess[str]]:
    """Resume one explicit OAuth session into new append-only artifacts."""

    directory = Path(bundle_dir).resolve()
    validate_batch_bundle(directory)
    names = (schema_name, prompt_name, response_name)
    if any(Path(name).name != name for name in names):
        raise OauthBatchResumeError("repair artifact names must be local files")
    if not str(session_id).strip():
        raise OauthBatchResumeError("repair session id is required")
    schema_path = directory / schema_name
    prompt_path = directory / prompt_name
    response_path = directory / response_name
    if not schema_path.is_file() or not prompt_path.is_file():
        raise OauthBatchResumeError("repair schema or prompt is missing")
    if response_path.exists():
        raise OauthBatchResumeError("provider response already exists")
    temporary = directory / f".{response_name}.tmp"
    temporary.unlink(missing_ok=True)
    executable = shutil.which("codex.cmd") or shutil.which("codex")
    if not executable:
        raise OauthBatchResumeError("Codex CLI is unavailable")
    prompt = prompt_path.read_text(encoding="utf-8")
    command = [
        executable,
        "exec",
        "--sandbox",
        "read-only",
        "resume",
        str(session_id).strip(),
        "-m",
        model,
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(temporary),
        "-",
    ]
    return _execute_and_persist(
        command=command,
        prompt=prompt,
        temporary=temporary,
        response_path=response_path,
        timeout_seconds=timeout_seconds,
    )


def run_codex_versioned_batch(
    bundle_dir: Path | str,
    *,
    workspace_dir: Path | str,
    schema_name: str,
    prompt_name: str,
    response_name: str,
    model: str = "gpt-5.6-sol",
    reasoning_effort: str = "low",
    timeout_seconds: int = 1800,
) -> tuple[Path, subprocess.CompletedProcess[str]]:
    """Start a fresh OAuth turn using append-only versioned artifacts."""

    directory = Path(bundle_dir).resolve()
    validate_batch_bundle(directory)
    names = (schema_name, prompt_name, response_name)
    if any(Path(name).name != name for name in names):
        raise OauthBatchResumeError("versioned artifact names must be local files")
    schema_path = directory / schema_name
    prompt_path = directory / prompt_name
    response_path = directory / response_name
    if not schema_path.is_file() or not prompt_path.is_file():
        raise OauthBatchResumeError("versioned schema or prompt is missing")
    if response_path.exists():
        raise OauthBatchResumeError("provider response already exists")
    temporary = directory / f".{response_name}.tmp"
    temporary.unlink(missing_ok=True)
    executable = shutil.which("codex.cmd") or shutil.which("codex")
    if not executable:
        raise OauthBatchResumeError("Codex CLI is unavailable")
    command = [
        executable,
        "exec",
        "-m",
        model,
        "-c",
        f'model_reasoning_effort="{str(reasoning_effort).strip()}"',
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(temporary),
        "--sandbox",
        "read-only",
        "--cd",
        str(Path(workspace_dir).resolve()),
        "-",
    ]
    return _execute_and_persist(
        command=command,
        prompt=prompt_path.read_text(encoding="utf-8"),
        temporary=temporary,
        response_path=response_path,
        timeout_seconds=timeout_seconds,
    )


def _execute_and_persist(
    *,
    command: list[str],
    prompt: str,
    temporary: Path,
    response_path: Path,
    timeout_seconds: int,
) -> tuple[Path, subprocess.CompletedProcess[str]]:
    completed = subprocess.run(
        command,
        input=prompt,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=max(60, int(timeout_seconds)),
        check=False,
    )
    if completed.returncode != 0 or not temporary.is_file():
        temporary.unlink(missing_ok=True)
        raise OauthBatchResumeError(
            "Codex OAuth batch request failed: "
            + (completed.stderr or completed.stdout)[-1000:]
        )
    raw = temporary.read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        temporary.unlink(missing_ok=True)
        raise OauthBatchResumeError(
            "Codex OAuth batch response is not valid JSON"
        ) from exc
    if not isinstance(payload, dict) or not isinstance(
        payload.get("programs"), list
    ):
        temporary.unlink(missing_ok=True)
        raise OauthBatchResumeError(
            "Codex OAuth batch response has no typed programs"
        )
    try:
        with response_path.open("xb") as handle:
            handle.write(raw)
    except FileExistsError as exc:
        raise OauthBatchResumeError(
            "provider response already exists"
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)
    return response_path, completed


__all__ = [
    "OauthBatchResumeError",
    "run_codex_batch",
    "run_codex_versioned_batch",
    "run_codex_repair",
    "validate_batch_bundle",
]
