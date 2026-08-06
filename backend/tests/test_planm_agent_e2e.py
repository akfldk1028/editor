from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


PLAN_ROOT = Path(__file__).parents[2]
BRIDGE = PLAN_ROOT / "agents" / "planm" / "runtime" / "planm_bridge.py"
SAMPLE = PLAN_ROOT / "datasets" / "manifests" / "sample_mass_office_commercial.json"


def _run(stage: str, state: Path, output_dir: Path) -> dict:
    environment = os.environ.copy()
    environment["PLANM_ENGINE_COMMAND_JSON"] = json.dumps(
        [sys.executable, "-m", "backend.app.adapters.planm_engine"]
    )
    environment["PLANM_ENGINE_CWD"] = str(PLAN_ROOT)
    completed = subprocess.run(
        [
            sys.executable,
            str(BRIDGE),
            stage,
            "--input",
            str(SAMPLE),
            "--state",
            str(state),
            "--output-dir",
            str(output_dir),
        ],
        cwd=PLAN_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    result = json.loads(completed.stdout)
    assert result["status"] == "success"
    return result


def test_planm_agent_delivers_distinct_reviewed_alternatives(tmp_path: Path) -> None:
    output_dir = tmp_path / "delivery"
    state = output_dir / "planm-state.json"

    for stage in ("normalize", "analyze", "alternatives", "review", "deliver"):
        _run(stage, state, output_dir)

    manifest = json.loads((output_dir / "planm-manifest.json").read_text(encoding="utf-8"))
    assert manifest["contract_version"] == "planm-delivery/v1"
    assert len(manifest["accepted_alternative_ids"]) >= 2
    assert manifest["internal_validation"] == "pass"
    assert manifest["render_validation"] == "pass"
    assert manifest["regulatory_screening"] in {"pass", "not_checked"}
    assert len(set(manifest["preview_sha256"].values())) >= 2

    for artifact in manifest["artifacts"]:
        path = Path(artifact["path"])
        assert not path.is_absolute()
        path = output_dir / path
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"]

    final_state = json.loads(state.read_text(encoding="utf-8"))
    assert final_state["stage"] == "delivered"
