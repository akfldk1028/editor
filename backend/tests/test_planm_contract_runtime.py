from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest


PLAN_ROOT = Path(__file__).parents[2]


def _request() -> dict:
    return {
        "contract_version": "planm-stage-request/v1",
        "stage": "normalize",
        "input_path": "input/mass.json",
        "state_path": "artifacts/planm-state.json",
        "output_dir": "artifacts",
    }


def test_runtime_validator_enforces_the_checked_in_request_schema() -> None:
    from backend.app.core.json_contracts import validate_planm_contract

    validate_planm_contract(PLAN_ROOT, "planm-stage-request.schema.json", _request())
    invalid = {**_request(), "unexpected": True}

    with pytest.raises(ValueError, match="planm-stage-request.schema.json"):
        validate_planm_contract(
            PLAN_ROOT,
            "planm-stage-request.schema.json",
            invalid,
        )


def test_backend_adapter_rejects_a_result_that_only_spoofs_the_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.app.adapters.planm_agent import run_planm_stage

    monkeypatch.setattr(
        "backend.app.adapters.planm_agent.subprocess.run",
        lambda *_, **__: SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"contract_version": "skill-result/v1"}),
            stderr="",
        ),
    )
    run_root = tmp_path / "run"
    run_root.mkdir()
    input_path = run_root / "mass.json"
    input_path.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="skill-result.schema.json"):
        run_planm_stage(
            stage="normalize",
            input_path=input_path,
            state_path=run_root / "planm-state.json",
            output_dir=run_root / "artifacts",
            repository_root=PLAN_ROOT,
            run_root=run_root,
        )
