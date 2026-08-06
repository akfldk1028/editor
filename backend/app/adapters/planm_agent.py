from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any


def build_planm_host_command(repository_root: Path) -> list[str]:
    node = shutil.which("node") or shutil.which("node.exe")
    if node is None:
        raise RuntimeError("Node.js is required to host the PLANM agent")
    host = repository_root / "agents" / "planm" / "runtime" / "gitagent_host.mjs"
    return [node, str(host)]


def run_planm_stage(
    *,
    stage: str,
    input_path: Path,
    state_path: Path,
    output_dir: Path,
    repository_root: Path,
    run_root: Path,
    timeout_seconds: float = 300,
) -> dict[str, Any]:
    owned_root = run_root.resolve()
    for label, path in (
        ("input", input_path),
        ("state", state_path),
        ("output", output_dir),
    ):
        try:
            path.resolve().relative_to(owned_root)
        except ValueError as error:
            raise ValueError(f"{label} path escapes the owned run root") from error
    environment = os.environ.copy()
    environment["PLANM_AGENT_DIR"] = str(repository_root / "agents" / "planm")
    environment["PLANM_GITAGENT_RUNTIME_ENTRY"] = str(
        repository_root / "external" / "gitagent-runtime" / "dist" / "exports.js"
    )
    environment["PLANM_PYTHON_EXECUTABLE"] = sys.executable
    environment["PLANM_ENGINE_COMMAND_JSON"] = json.dumps(
        [sys.executable, "-m", "backend.app.adapters.planm_engine"]
    )
    environment["PLANM_ENGINE_CWD"] = str(repository_root)
    environment["PLANM_ENGINE_TIMEOUT_SECONDS"] = str(max(0.01, timeout_seconds * 0.9))
    try:
        completed = subprocess.run(
            [
                *build_planm_host_command(repository_root),
                stage,
                "--input",
                str(input_path),
                "--state",
                str(state_path),
                "--output-dir",
                str(output_dir),
            ],
            cwd=repository_root,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        raise TimeoutError(
            f"PLANM agent exceeded {timeout_seconds:g} seconds"
        ) from error
    if not completed.stdout.strip():
        raise RuntimeError(
            f"PLANM agent exited {completed.returncode}: {completed.stderr.strip()}"
        )
    result = json.loads(completed.stdout)
    if not isinstance(result, dict) or result.get("contract_version") != "skill-result/v1":
        raise ValueError("PLANM agent returned an unsupported result contract")
    return result
