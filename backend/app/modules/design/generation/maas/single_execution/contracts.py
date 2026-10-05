"""Stable result contract shared by HTTP, CLI, and future MASS agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SingleMassExecutionResult:
    execution_id: str
    execution_mode: str
    source_run_id: str
    source_mass_index: int
    created_at: str
    status: str
    geometry_ready: bool
    full_flow_status: str
    program_hash: str
    geometry_hash: str
    floor_capacity_plan_hash: str
    timings_ms: dict[str, float]
    gate_issues: tuple[dict[str, Any], ...]
    output_directory: Path
    program_path: Path
    preview_path: Path
    passport_path: Path
    manifest_path: Path
    passport: dict[str, Any] = field(repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "arr.maas.single_execution.v1",
            "execution_id": self.execution_id,
            "execution_mode": self.execution_mode,
            "source_run_id": self.source_run_id,
            "source_mass_index": self.source_mass_index,
            "created_at": self.created_at,
            "status": self.status,
            "geometry_ready": self.geometry_ready,
            "full_flow_status": self.full_flow_status,
            "program_hash": self.program_hash,
            "geometry_hash": self.geometry_hash,
            "floor_capacity_plan_hash": self.floor_capacity_plan_hash,
            "timings_ms": dict(self.timings_ms),
            "gate_issues": list(self.gate_issues),
            "artifacts": {
                "directory": str(self.output_directory.resolve()),
                "program": str(self.program_path.resolve()),
                "preview": str(self.preview_path.resolve()) if self.preview_path.is_file() else "",
                "passport": str(self.passport_path.resolve()),
                "manifest": str(self.manifest_path.resolve()),
            },
        }


__all__ = ["SingleMassExecutionResult"]
