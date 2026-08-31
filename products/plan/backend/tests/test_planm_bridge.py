from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


PLAN_ROOT = Path(__file__).parents[2]
BRIDGE = (
    PLAN_ROOT
    / "agents"
    / "planm"
    / "runtime"
    / "planm_bridge.py"
)


def _engine_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["PLANM_ENGINE_COMMAND_JSON"] = json.dumps(
        [sys.executable, "-m", "backend.app.adapters.planm_engine"]
    )
    environment["PLANM_ENGINE_CWD"] = str(PLAN_ROOT)
    return environment


def _sample_payload() -> dict:
    return {
        "project_id": "planm-bridge",
        "floors": 1,
        "footprint_polygon": [[0, 0], [30, 0], [30, 12], [0, 12]],
        "site_edges": [{"edge_index": 0, "kind": "street"}],
        "access_candidates": [{"edge_index": 0, "position": 0.5}],
        "use_mix": {"office": 1.0},
    }


def test_bridge_normalize_writes_versioned_state(tmp_path: Path) -> None:
    input_path = tmp_path / "mass.json"
    state_path = tmp_path / "planm-state.json"
    input_path.write_text(json.dumps(_sample_payload()), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(BRIDGE),
            "normalize",
            "--input",
            str(input_path),
            "--state",
            str(state_path),
            "--output-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=_engine_environment(),
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["contract_version"] == "skill-result/v1"
    assert result["skill_name"] == "normalize-plan-request"
    assert result["status"] == "success"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["contract_version"] == "planm-state/v1"
    assert state["stage"] == "normalized"
    assert state["project_id"] == "planm-bridge"
    assert "jurisdiction" in state["unresolved_facts"]


def test_bridge_normalize_reports_invalid_input_without_state(tmp_path: Path) -> None:
    input_path = tmp_path / "invalid.json"
    state_path = tmp_path / "planm-state.json"
    input_path.write_text("{}", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(BRIDGE),
            "normalize",
            "--input",
            str(input_path),
            "--state",
            str(state_path),
            "--output-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=_engine_environment(),
    )

    assert completed.returncode == 2
    result = json.loads(completed.stdout)
    assert result["status"] == "needs_input"
    assert result["violations"][0]["code"] == "invalid_mass_input"
    assert not state_path.exists()
