from __future__ import annotations

from pathlib import Path
import json


PLAN_ROOT = Path(__file__).parents[2]
STAGES = ("normalize", "analyze", "alternatives", "review", "deliver")


def _mass() -> dict:
    return {
        "project_id": "durable-run",
        "floors": 1,
        "footprint_polygon": [[0, 0], [30, 0], [30, 12], [0, 12]],
        "site_edges": [{"edge_index": 0, "kind": "street"}],
        "access_candidates": [{"edge_index": 0, "position": 0.5}],
        "use_mix": {"office": 1.0},
    }


def _result(stage: str, status: str, code: str | None = None) -> dict:
    violations = [] if code is None else [
        {
            "code": code,
            "message": code,
            "severity": "hard",
            "retryable": status == "retryable",
        }
    ]
    return {
        "contract_version": "skill-result/v1",
        "skill_name": stage,
        "status": status,
        "outputs": {},
        "violations": violations,
        "artifacts": [],
        "provenance": {},
    }


def _service(tmp_path: Path):
    from backend.app.modules.planm_runs.service import PlanmRunService

    return PlanmRunService(repository_root=PLAN_ROOT, runs_root=tmp_path / "runs")


def test_transient_stage_failure_retries_and_persists_attempt_history(
    tmp_path: Path, monkeypatch
) -> None:
    service = _service(tmp_path)
    run = service.create(_mass())
    calls: list[str] = []

    def fake_stage(*, stage: str, **_) -> dict:
        calls.append(stage)
        if stage == "analyze" and calls.count("analyze") == 1:
            return _result(stage, "retryable", "engine_timeout")
        return _result(stage, "success")

    monkeypatch.setattr(
        "backend.app.modules.planm_runs.service.run_planm_stage",
        fake_stage,
    )

    result = service.execute(run["run_id"])

    assert result["status"] == "delivered"
    assert calls == ["normalize", "analyze", "analyze", "alternatives", "review", "deliver"]
    assert result["stage_attempts"] == {
        "normalize": 1,
        "analyze": 2,
        "alternatives": 1,
        "review": 1,
        "deliver": 1,
    }
    assert [item["status"] for item in result["execution_history"]][1:3] == [
        "retryable",
        "success",
    ]


def test_transient_retry_exhaustion_becomes_a_bounded_block(
    tmp_path: Path, monkeypatch
) -> None:
    service = _service(tmp_path)
    run = service.create(_mass())
    calls: list[str] = []

    def always_timeout(*, stage: str, **_) -> dict:
        calls.append(stage)
        return _result(stage, "retryable", "engine_timeout")

    monkeypatch.setattr(
        "backend.app.modules.planm_runs.service.run_planm_stage",
        always_timeout,
    )

    result = service.execute(run["run_id"])

    assert calls == ["normalize", "normalize", "normalize"]
    assert result["status"] == "blocked"
    assert result["next_stage"] == "normalize"
    assert result["stage_attempts"]["normalize"] == 3
    assert result["violations"][0]["code"] == "stage_attempts_exhausted"


def test_blocked_run_resumes_at_the_unfinished_stage_and_delivery_is_idempotent(
    tmp_path: Path, monkeypatch
) -> None:
    service = _service(tmp_path)
    run = service.create(_mass())
    first_calls: list[str] = []

    def block_analyze(*, stage: str, **_) -> dict:
        first_calls.append(stage)
        if stage == "analyze":
            return _result(stage, "blocked", "missing_external_fact")
        return _result(stage, "success")

    monkeypatch.setattr(
        "backend.app.modules.planm_runs.service.run_planm_stage",
        block_analyze,
    )
    blocked = service.execute(run["run_id"])

    assert blocked["status"] == "blocked"
    assert blocked["next_stage"] == "analyze"
    assert first_calls == ["normalize", "analyze"]

    resumed_calls: list[str] = []

    def succeed(*, stage: str, **_) -> dict:
        resumed_calls.append(stage)
        return _result(stage, "success")

    monkeypatch.setattr(
        "backend.app.modules.planm_runs.service.run_planm_stage",
        succeed,
    )
    delivered = service.execute(run["run_id"])
    assert delivered["status"] == "delivered"
    assert resumed_calls == ["analyze", "alternatives", "review", "deliver"]

    resumed_calls.clear()
    assert service.execute(run["run_id"])["status"] == "delivered"
    assert resumed_calls == []


def test_run_reconciles_agent_state_written_before_backend_progress(
    tmp_path: Path, monkeypatch
) -> None:
    service = _service(tmp_path)
    run = service.create(_mass())
    run_dir = service.runs_root / run["run_id"]
    state_path = run_dir / "artifacts" / "planm-state.json"
    state_path.write_text(
        json.dumps(
            {
                "contract_version": "planm-state/v1",
                "project_id": "durable-run",
                "stage": "analyzed",
                "status": "success",
                "input_path": "mass.json",
                "output_dir": ".",
                "attempts": {
                    "normalize-plan-request": 1,
                    "analyze-building-mass": 1,
                },
                "candidate_fingerprints": [],
                "accepted_alternative_ids": [],
                "unresolved_facts": [],
                "violations": [],
                "artifacts": [],
                "history": [
                    {
                        "skill_name": "normalize-plan-request",
                        "status": "success",
                        "attempt": 1,
                        "finished_at": "2026-08-31T00:00:00+00:00",
                    },
                    {
                        "skill_name": "analyze-building-mass",
                        "status": "success",
                        "attempt": 1,
                        "finished_at": "2026-08-31T00:00:01+00:00",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    calls: list[str] = []

    def succeed(*, stage: str, **_) -> dict:
        calls.append(stage)
        return _result(stage, "success")

    monkeypatch.setattr(
        "backend.app.modules.planm_runs.service.run_planm_stage",
        succeed,
    )

    assert service.execute(run["run_id"])["status"] == "delivered"
    assert calls == ["alternatives", "review", "deliver"]


def test_duplicate_execution_returns_the_current_record_without_running_a_stage(
    tmp_path: Path, monkeypatch
) -> None:
    service = _service(tmp_path)
    run = service.create(_mass())
    duplicate_service = _service(tmp_path)
    monkeypatch.setattr(
        "backend.app.modules.planm_runs.service.run_planm_stage",
        lambda **_: (_ for _ in ()).throw(AssertionError("duplicate stage ran")),
    )
    lock = service._execution_lock(run["run_id"])

    with lock:
        duplicate = duplicate_service.execute(run["run_id"])

    assert duplicate["status"] == "queued"
    assert duplicate["stage_attempts"] == {}
