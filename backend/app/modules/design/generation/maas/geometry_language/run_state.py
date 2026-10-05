"""Small durable lifecycle record for long-running MASS portfolio executions."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import wraps
import json
import os
from pathlib import Path
from time import sleep
from typing import Any, Callable, TypeVar

from backend.app.modules.design.generation.maas.agents.maas_geometry_agent.version_memory import write_progress_checkpoint, write_version_snapshot


RUN_STATE_FILENAME = "maas-run-state.json"
RUN_STATE_SCHEMA = "arr.maas.run_state.v1"

_T = TypeVar("_T")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_run_state(output_dir: Path, payload: dict[str, Any]) -> Path:
    """Atomically persist a bounded, credential-free execution state record."""
    directory = Path(output_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / RUN_STATE_FILENAME
    temporary = directory / f".{RUN_STATE_FILENAME}.{os.getpid()}.tmp"
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for attempt in range(5):
        try:
            temporary.replace(target)
            break
        except PermissionError:
            if attempt == 4:
                raise
            sleep(0.02 * (attempt + 1))
    return target


def _read_run_state(output_dir: Path) -> dict[str, Any]:
    target = Path(output_dir).resolve() / RUN_STATE_FILENAME
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def update_run_progress(output_dir: Path, **progress: Any) -> Path:
    """Merge bounded progress into a running lifecycle record."""

    directory = Path(output_dir).resolve()
    current = _read_run_state(directory)
    if not current:
        current = {
            "schema_version": RUN_STATE_SCHEMA,
            "run_id": directory.name,
            "created_at": _now(),
            "pid": os.getpid(),
        }
    if not isinstance(current, dict):
        current = {}
    safe_progress = {
        key: value for key, value in progress.items()
        if key in {
            "phase", "program", "cycle_index", "cycle_budget",
            "selection_pool_count", "selected_mass_count",
            "required_scope_count", "selected_scope_count", "stop_reason",
            "diagnostic_target", "evaluated_count", "compiled_count",
            "program_passed_count", "candidate_cap",
        }
    }
    checkpoint_path = write_progress_checkpoint(
        directory,
        version_id=directory.name,
        stage=str(safe_progress.get("phase") or "running"),
        payload=safe_progress,
    )
    return write_run_state(directory, {
        **current,
        **safe_progress,
        "schema_version": RUN_STATE_SCHEMA,
        "run_id": directory.name,
        "pid": int(current.get("pid") or os.getpid()),
        "status": "running",
        "updated_at": _now(),
        "progress_checkpoint_path": str(checkpoint_path),
    })


def tracked_mass_command(function: Callable[..., _T]) -> Callable[..., _T]:
    """Decorate a Django command handle so normal failures remain discoverable."""
    @wraps(function)
    def wrapped(command: Any, *args: Any, **options: Any) -> _T:
        output_dir = Path(str(options["output_dir"])).resolve()
        created_at = _now()
        try:
            from backend.app.modules.design.generation.maas.book_language.quality_diversity_archive import qd_archive_policy

            quality_diversity = qd_archive_policy()
        except (ImportError, ValueError):
            quality_diversity = {}
        base = {
            "schema_version": RUN_STATE_SCHEMA,
            "run_id": output_dir.name,
            "pnu": str(options.get("pnu") or ""),
            "programs": list(options.get("program") or ()),
            "recursive_only": bool(options.get("recursive_only")),
            "live_vlm_requested": bool(
                options.get("live_vlm")
                or options.get("progressive_target") is not None
            ),
            "outcome_graph_path": str(options.get("outcome_graph") or ""),
            "quality_diversity_archive": quality_diversity,
            "created_at": created_at,
            "pid": os.getpid(),
            "parent_version_id": str(
                options.get("parent_version_id") or ""
            ),
        }
        write_run_state(output_dir, {
            **base,
            "updated_at": created_at,
            "status": "running",
            "selected_mass_count": 0,
        })
        try:
            command_result = function(command, *args, **options)
        except BaseException as exc:
            current = _read_run_state(output_dir)
            raw_error_evidence = getattr(exc, "evidence", None)
            error_evidence = None
            if isinstance(raw_error_evidence, dict):
                try:
                    serialized_evidence = json.dumps(
                        raw_error_evidence,
                        ensure_ascii=False,
                    )
                    if len(serialized_evidence) <= 16_000:
                        error_evidence = json.loads(serialized_evidence)
                except (TypeError, ValueError):
                    error_evidence = None
            version_memory_path = write_version_snapshot(
                output_dir,
                version_id=output_dir.name,
                parent_version_id=base["parent_version_id"],
                stage="failed",
                payload={
                    "pnu": base["pnu"],
                    "programs": base["programs"],
                    "selected_mass_count": int(
                        current.get("selected_mass_count") or 0
                    ),
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:1000],
                    **(
                        {"error_evidence": error_evidence}
                        if error_evidence is not None
                        else {}
                    ),
                },
            )
            write_run_state(output_dir, {
                **base,
                **current,
                "updated_at": _now(),
                "status": "failed",
                "selected_mass_count": int(current.get("selected_mass_count") or 0),
                "error_type": type(exc).__name__,
                "error": str(exc)[:1000],
                **(
                    {"error_evidence": error_evidence}
                    if error_evidence is not None
                    else {}
                ),
                "version_memory_path": str(version_memory_path),
            })
            raise
        evidence_result = command_result
        if not isinstance(evidence_result, dict):
            summary_path = output_dir / "maas-book-programs-summary.json"
            if summary_path.is_file():
                try:
                    persisted = json.loads(summary_path.read_text(encoding="utf-8"))
                except (OSError, ValueError, TypeError):
                    persisted = None
                if isinstance(persisted, dict):
                    evidence_result = persisted
        selected_count = 0
        if isinstance(evidence_result, dict):
            selected_count = sum(
                int(item.get("selected_count") or 0)
                for item in evidence_result.get("programs") or ()
                if isinstance(item, dict)
            )
        result_status = (
            str(evidence_result.get("status") or "unknown")
            if isinstance(evidence_result, dict)
            else "unknown"
        )
        current = _read_run_state(output_dir)
        version_memory_path = write_version_snapshot(
            output_dir,
            version_id=output_dir.name,
            parent_version_id=base["parent_version_id"],
            stage="completed",
            payload={
                "pnu": base["pnu"],
                "programs": base["programs"],
                "result_status": result_status,
                "selected_mass_count": selected_count,
            },
        )
        write_run_state(output_dir, {
            **base,
            **current,
            "updated_at": _now(),
            "status": (
                "completed"
                if result_status == "pass"
                else "completed_with_failed_gate"
            ),
            "selected_mass_count": selected_count,
            "result_status": result_status,
            "version_memory_path": str(version_memory_path),
        })
        return command_result

    return wrapped


__all__ = [
    "RUN_STATE_FILENAME",
    "RUN_STATE_SCHEMA",
    "tracked_mass_command",
    "update_run_progress",
    "write_run_state",
]
