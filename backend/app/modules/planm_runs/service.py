from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from backend.app.adapters.planm_agent import run_planm_stage
from backend.app.adapters.dwg_client import inspect_dwg_handoff
from backend.app.modules.cad_handoff import create_dxf_handoff


STAGES = ("normalize", "analyze", "alternatives", "review", "deliver")


class PlanmRunNotFound(LookupError):
    pass


class PlanmRunConflict(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path.name}")
    return value


class PlanmRunService:
    def __init__(self, *, repository_root: Path, runs_root: Path) -> None:
        self.repository_root = repository_root.resolve()
        self.runs_root = runs_root.resolve()
        self.runs_root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def create(self, mass: dict[str, Any]) -> dict[str, Any]:
        run_id = uuid4().hex
        run_dir = self._run_dir(run_id)
        input_path = run_dir / "input" / "mass.json"
        output_dir = run_dir / "artifacts"
        input_path.parent.mkdir(parents=True)
        output_dir.mkdir(parents=True)
        _write_json(input_path, mass)
        now = _now()
        record = {
            "contract_version": "planm-run/v1",
            "run_id": run_id,
            "project_id": mass.get("project_id"),
            "status": "queued",
            "stage": "queued",
            "created_at": now,
            "updated_at": now,
            "approved_alternative_id": None,
            "violations": [],
        }
        _write_json(run_dir / "run.json", record)
        return record

    def execute(self, run_id: str) -> dict[str, Any]:
        run_dir = self._existing_run_dir(run_id)
        input_path = run_dir / "input" / "mass.json"
        output_dir = run_dir / "artifacts"
        state_path = output_dir / "planm-state.json"
        for stage in STAGES:
            self._update(run_id, status="running", stage=stage)
            try:
                result = run_planm_stage(
                    stage=stage,
                    input_path=input_path,
                    state_path=state_path,
                    output_dir=output_dir,
                    repository_root=self.repository_root,
                    run_root=run_dir,
                )
            except (OSError, RuntimeError, TimeoutError, ValueError) as error:
                return self._update(
                    run_id,
                    status="blocked",
                    stage=stage,
                    violations=[
                        {
                            "code": "agent_process_failed",
                            "message": f"{type(error).__name__}: {error}",
                        }
                    ],
                )
            if result["status"] != "success":
                return self._update(
                    run_id,
                    status=result["status"],
                    stage=stage,
                    violations=result.get("violations", []),
                )
        return self._update(run_id, status="delivered", stage="delivered")

    def get(self, run_id: str) -> dict[str, Any]:
        return _read_json(self._existing_run_dir(run_id) / "run.json")

    def alternatives(self, run_id: str) -> dict[str, Any]:
        path = self._existing_run_dir(run_id) / "artifacts" / "alternatives.json"
        if not path.is_file():
            raise PlanmRunConflict("alternatives are not available")
        return _read_json(path)

    def approve(self, run_id: str, alternative_id: str) -> dict[str, Any]:
        record = self.get(run_id)
        if record["status"] not in {"delivered", "approved"}:
            raise PlanmRunConflict("run is not ready for approval")
        accepted = self.alternatives(run_id).get("accepted_alternative_ids", [])
        if alternative_id not in accepted:
            raise PlanmRunConflict("alternative is not accepted")
        return self._update(
            run_id,
            status="approved",
            approved_alternative_id=alternative_id,
        )

    def preview(self, run_id: str, alternative_id: str) -> Path:
        alternatives = self.alternatives(run_id)
        match = next(
            (
                item
                for item in alternatives.get("alternatives", [])
                if item.get("alternative_id") == alternative_id and item.get("accepted")
            ),
            None,
        )
        if match is None or not match.get("preview_pngs"):
            raise PlanmRunNotFound("accepted alternative preview not found")
        artifact_root = self._existing_run_dir(run_id) / "artifacts"
        candidate = (artifact_root / match["preview_pngs"][0]).resolve()
        try:
            candidate.relative_to(artifact_root.resolve())
        except ValueError as error:
            raise PlanmRunConflict("preview path escapes the run") from error
        if not candidate.is_file() or candidate.suffix.lower() != ".png":
            raise PlanmRunNotFound("accepted alternative preview not found")
        return candidate

    def artifact(self, run_id: str, relative_path: str) -> Path:
        record = self.get(run_id)
        if record["status"] != "approved":
            raise PlanmRunConflict("artifacts require an approved run")
        artifact_root = self._existing_run_dir(run_id) / "artifacts"
        candidate = (artifact_root / relative_path).resolve()
        try:
            candidate.relative_to(artifact_root.resolve())
        except ValueError as error:
            raise PlanmRunConflict("artifact path escapes the run") from error
        if not candidate.is_file():
            raise PlanmRunNotFound("artifact not found")
        return candidate

    def create_dwg_handoff(self, run_id: str) -> dict[str, Any]:
        record = self.get(run_id)
        if record["status"] != "approved" or not record.get("approved_alternative_id"):
            raise PlanmRunConflict("DWG handoff requires an approved run")
        run_dir = self._existing_run_dir(run_id)
        artifact_root = run_dir / "artifacts"
        alternative_dir = (
            artifact_root / "alternatives" / record["approved_alternative_id"]
        ).resolve()
        try:
            alternative_dir.relative_to(artifact_root.resolve())
        except ValueError as error:
            raise PlanmRunConflict("approved alternative path escapes the run") from error
        if not alternative_dir.is_dir():
            raise PlanmRunNotFound("approved alternative artifacts not found")
        drawing_path = "cad-handoff/approved-plan.dxf"
        try:
            return create_dxf_handoff(
                alternative_dir=alternative_dir,
                output_path=artifact_root / drawing_path,
                drawing_path=drawing_path,
            )
        except (OSError, KeyError, TypeError, ValueError) as error:
            raise PlanmRunConflict(f"CAD handoff failed: {error}") from error

    def inspect_dwg_handoff(self, run_id: str, layer: str) -> dict[str, Any]:
        record = self.get(run_id)
        if record["status"] != "approved" or not record.get("approved_alternative_id"):
            raise PlanmRunConflict("DWG inspection requires an approved run")
        artifact_root = self._existing_run_dir(run_id) / "artifacts"
        handoff_root = artifact_root / "cad-handoff"
        manifest_path = handoff_root / "manifest.json"
        if not manifest_path.is_file():
            raise PlanmRunConflict("create the DWG handoff before inspection")
        manifest = _read_json(manifest_path)
        drawing_path = Path(manifest["drawing_path"])
        if drawing_path.parent.as_posix() != "cad-handoff":
            raise PlanmRunConflict("CAD handoff drawing path is invalid")
        try:
            evidence = inspect_dwg_handoff(
                repository_root=self.repository_root,
                workspace_root=handoff_root,
                drawing_path=drawing_path.name,
                layer=layer,
            )
        except (OSError, RuntimeError, TimeoutError, ValueError) as error:
            raise PlanmRunConflict(f"DWG inspection failed: {error}") from error
        result = {
            "contract_version": "planm-dwg-inspection/v1",
            "alternative_id": record["approved_alternative_id"],
            "drawing_path": manifest["drawing_path"],
            "layer": layer,
            "status": evidence["status"],
            "evidence": evidence,
        }
        _write_json(handoff_root / "inspection.json", result)
        manifest["dwg_validation"] = evidence["status"]
        manifest["inspection_path"] = "cad-handoff/inspection.json"
        _write_json(manifest_path, manifest)
        return result

    def _update(self, run_id: str, **changes: Any) -> dict[str, Any]:
        with self._lock:
            path = self._existing_run_dir(run_id) / "run.json"
            record = _read_json(path)
            record.update(changes)
            record["updated_at"] = _now()
            _write_json(path, record)
            return record

    def _run_dir(self, run_id: str) -> Path:
        if len(run_id) != 32 or any(character not in "0123456789abcdef" for character in run_id):
            raise PlanmRunNotFound("run not found")
        return self.runs_root / run_id

    def _existing_run_dir(self, run_id: str) -> Path:
        path = self._run_dir(run_id)
        if not (path / "run.json").is_file():
            raise PlanmRunNotFound("run not found")
        return path
