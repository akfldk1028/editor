"""Bridge to the cloned d4descent research code.

ARR uses the checked-out clone as an external research backend instead of
duplicating its source into ``ARR/backend``. Import errors are reported as
evidence so the legal massing endpoint keeps running while the research
dependencies are installed or changed.
"""

from __future__ import annotations

from backend.app.modules.design.generation import paths as _design_paths

import importlib
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return _design_paths.workspace_root()


def d4descent_source_path() -> Path:
    return _repo_root() / "clone" / "d4descent" / "src"


def d4descent_license_summary() -> dict[str, Any]:
    return {
        "name": "d4descent",
        "remote": "https://github.com/milmillin/d4descent.git",
        "license": "CC BY-NC 4.0 per clone/d4descent README",
        "mode": "external_clone_bridge",
        "integration_rule": "Use the clone path directly; do not duplicate/vendor d4descent source inside ARR.",
    }


@lru_cache(maxsize=2)
def _inspect_d4descent_backend_cached(should_import: bool) -> dict[str, Any]:
    """Return availability and imported interface names for d4descent.

    ARR attempts the import by default because d4descent is an explicit research
    dependency for MAAS optimization experiments. Import errors are captured in
    evidence instead of breaking the legal massing endpoint.
    """
    src = d4descent_source_path()
    info: dict[str, Any] = {
        **d4descent_license_summary(),
        "source_path": str(src),
        "exists": src.exists(),
        "status": "missing" if not src.exists() else "available_not_imported",
        "interfaces": {
            "optimizer": "d4descent.optimizer.optimize",
            "optimizer_args": "d4descent.optimizer.OptimizeArgs",
            "task_protocol": "d4descent.tasks._base.Task",
            "object_collection": "d4descent.object_collection.ObjectCollection",
        },
    }
    if not src.exists() or not should_import:
        return info

    try:
        optimizer = importlib.import_module("d4descent.optimizer")
        task_base = importlib.import_module("d4descent.tasks._base")
        object_collection = importlib.import_module("d4descent.object_collection")
        info["status"] = "imported"
        info["imported"] = {
            "optimize": hasattr(optimizer, "optimize"),
            "OptimizeArgs": hasattr(optimizer, "OptimizeArgs"),
            "Task": hasattr(task_base, "Task"),
            "ObjectCollection": hasattr(object_collection, "ObjectCollection"),
        }
    except Exception as exc:  # pragma: no cover - dependency-dependent.
        info["status"] = "import_failed"
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info


def inspect_d4descent_backend(*, enable_import: bool | None = None) -> dict[str, Any]:
    should_import = enable_import if enable_import is not None else os.getenv("MAAS_D4DESCENT_IMPORT", "0") == "1"
    return dict(_inspect_d4descent_backend_cached(bool(should_import)))


def d4descent_design_evidence(*, enable_import: bool | None = None) -> dict[str, Any]:
    backend = inspect_d4descent_backend(enable_import=enable_import)
    return {
        "name": "d4descent",
        "source": "clone/d4descent",
        "status": backend["status"],
        "backend": backend,
        "absorbed_pattern": {
            "object": "candidate mass / floor-plate stack",
            "task": "legal candidate ranking task",
            "loss": "capacity + diversity + compactness + sequence richness",
            "optimizer": "external d4descent bridge; ARR legal repair/evaluation remains deterministic",
            "rewrite": "ARR grammar/morphology operators",
        },
    }


__all__ = [
    "d4descent_design_evidence",
    "d4descent_license_summary",
    "d4descent_source_path",
    "inspect_d4descent_backend",
]
