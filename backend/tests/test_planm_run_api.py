from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.adapters.planm_agent import PlanmClient
from backend.app.main import create_app
from backend.tests.planm_fixtures import fake_planm_stage


PLAN_ROOT = Path(__file__).parents[2]


def _live_agent() -> bool:
    if not os.environ.get("PLANM_AGENT_URL"):
        return False
    try:
        return "plan_stage" in PlanmClient().health().get("tools", [])
    except RuntimeError:
        return False


@pytest.fixture
def fake_agent(monkeypatch):
    monkeypatch.setattr("backend.app.modules.planm_runs.service.run_planm_stage", fake_planm_stage)


def _mass() -> dict:
    return {
        "project_id": "run-api",
        "floors": 5,
        "footprint_polygon": [[0, 0], [30, 0], [30, 12], [0, 12]],
        "site_edges": [{"edge_index": 0, "kind": "street"}],
        "access_candidates": [{"edge_index": 0, "position": 0.5}],
        "use_mix": {"neighborhood_commercial": 0.2, "office": 0.8},
    }


def test_create_app_uses_deployment_runs_root(tmp_path: Path, monkeypatch) -> None:
    runs_root = tmp_path / "deployed-runs"
    monkeypatch.setenv("PLANM_RUNS_ROOT", str(runs_root))
    app = create_app(repository_root=PLAN_ROOT)
    assert app.state.planm_runs.runs_root == runs_root.resolve()


def test_create_app_reads_the_attempt_budget_from_the_environment(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PLANM_MAX_STAGE_ATTEMPTS", "2")
    app = create_app(repository_root=PLAN_ROOT, runs_root=tmp_path / "runs")
    assert app.state.planm_runs.maximum_stage_attempts == 2


def test_execute_endpoint_exposes_explicit_run_recovery(tmp_path: Path, monkeypatch) -> None:
    app = create_app(repository_root=PLAN_ROOT, runs_root=tmp_path / "runs", execute_inline=False)
    service = app.state.planm_runs
    record = service.create(_mass())
    monkeypatch.setattr(service, "execute", lambda run_id: {**service.get(run_id), "status": "running",
                                                            "stage": "analyze", "next_stage": "analyze"})
    response = TestClient(app).post(f"/api/v1/planm/runs/{record['run_id']}/execute")
    assert response.status_code == 200
    assert response.json()["next_stage"] == "analyze"


def test_planm_run_api_runs_the_stages_approves_and_downloads(tmp_path: Path, fake_agent) -> None:
    app = create_app(repository_root=PLAN_ROOT, runs_root=tmp_path / "runs", execute_inline=True)
    client = TestClient(app)
    created = client.post("/api/v1/planm/runs", json={"contract_version": "planm-run-create/v1", "mass": _mass()})
    assert created.status_code == 201, created.text
    run = created.json()
    assert run["status"] == "delivered" and run["stage"] == "delivered"
    assert "C:\\" not in created.text
    run_id = run["run_id"]

    alternatives = client.get(f"/api/v1/planm/runs/{run_id}/alternatives").json()
    accepted = alternatives["accepted_alternative_ids"]
    assert len(accepted) >= 2
    first = alternatives["alternatives"][0]
    assert {"alternative_id", "accepted", "preview_pngs", "strategy", "rank", "score",
            "internal_validation", "render_validation", "regulatory_screening"} <= set(first)

    preview = client.get(f"/api/v1/planm/runs/{run_id}/alternatives/{accepted[0]}/preview")
    assert preview.status_code == 200 and preview.headers["content-type"] == "image/png"
    assert len(preview.content) > 100

    locked = client.get(f"/api/v1/planm/runs/{run_id}/artifacts/planm-manifest.json")
    assert locked.status_code == 409, "artifacts require an approved run"

    approval = client.post(f"/api/v1/planm/runs/{run_id}/approval",
                           json={"contract_version": "planm-approval/v1", "alternative_id": accepted[0]})
    assert approval.status_code == 200
    assert approval.json()["approved_alternative_id"] == accepted[0]

    download = client.get(f"/api/v1/planm/runs/{run_id}/artifacts/planm-manifest.json")
    assert download.status_code == 200
    assert download.json()["contract_version"] == "planm-delivery/v1"
    review = client.get(f"/api/v1/planm/runs/{run_id}/artifacts/alternatives/{accepted[0]}/building.review.json")
    assert review.status_code == 200 and review.json()["accepted"] is True


def test_planm_run_api_rejects_unaccepted_approval(tmp_path: Path, fake_agent) -> None:
    client = TestClient(create_app(repository_root=PLAN_ROOT, runs_root=tmp_path / "runs", execute_inline=True))
    run = client.post("/api/v1/planm/runs", json={"contract_version": "planm-run-create/v1", "mass": _mass()}).json()
    response = client.post(f"/api/v1/planm/runs/{run['run_id']}/approval",
                           json={"contract_version": "planm-approval/v1", "alternative_id": "not-an-accepted-option"})
    assert response.status_code == 409


def test_planm_run_records_unresolved_code_facts_from_normalize(tmp_path: Path, fake_agent) -> None:
    client = TestClient(create_app(repository_root=PLAN_ROOT, runs_root=tmp_path / "runs", execute_inline=True))
    created = client.post("/api/v1/planm/runs", json={"contract_version": "planm-run-create/v1", "mass": _mass()})
    assert created.status_code == 201, created.text
    record = client.get(f"/api/v1/planm/runs/{created.json()['run_id']}").json()
    assert record["unresolved_facts"] == ["jurisdiction", "effective_date", "floor_code_context", "travel_limit_classification"]


def test_planm_run_unresolved_facts_shrink_when_the_brief_supplies_them(tmp_path: Path, fake_agent) -> None:
    client = TestClient(create_app(repository_root=PLAN_ROOT, runs_root=tmp_path / "runs", execute_inline=True))
    mass = _mass()
    mass["building_code_context"] = {"jurisdiction": "KR", "effective_date": "2026-07-28",
                                     "travel_limit_classification": "general_30", "sprinklered": True,
                                     "qualifying_sprinkler_protection": True, "floor_facts": []}
    created = client.post("/api/v1/planm/runs", json={"contract_version": "planm-run-create/v1", "mass": mass})
    assert created.status_code == 201, created.text
    record = client.get(f"/api/v1/planm/runs/{created.json()['run_id']}").json()
    assert record["unresolved_facts"] == ["floor_code_context"]


@pytest.mark.skipif(not _live_agent(), reason="PLANM_AGENT_URL does not answer with plan_stage")
def test_live_plan_agent_delivers_reviews_approves_and_hands_off_to_cad(tmp_path: Path, monkeypatch) -> None:
    """The real thing: every stage over HTTP, then the CAD handoff on the agent's SVG artifacts."""
    monkeypatch.setattr("backend.app.modules.planm_runs.service.inspect_dwg_handoff",
                        lambda **_: {"status": "passed", "drawing_id": "d", "skill_run_id": "s", "warning_codes": [],
                                     "result": {"matches": [{"id": "h:9", "handle": "9", "type": "LINE", "layer": "F001_ROOMS",
                                                             "bbox": {"min": [0, 0, 0], "max": [10, 0, 0]},
                                                             "reason": "layer equals query", "confidence": 1}]}})
    monkeypatch.setenv("PLANM_RUNS_ROOT", str(tmp_path / "runs"))
    client = TestClient(create_app(repository_root=PLAN_ROOT, runs_root=tmp_path / "runs", execute_inline=True))
    created = client.post("/api/v1/planm/runs", json={"contract_version": "planm-run-create/v1", "mass": _mass()})
    assert created.status_code == 201, created.text
    run = created.json()
    assert run["status"] == "delivered", run
    run_id = run["run_id"]
    accepted = client.get(f"/api/v1/planm/runs/{run_id}/alternatives").json()["accepted_alternative_ids"]
    assert len(accepted) >= 2
    assert client.post(f"/api/v1/planm/runs/{run_id}/approval",
                       json={"contract_version": "planm-approval/v1", "alternative_id": accepted[0]}).status_code == 200
    handoff = client.post(f"/api/v1/planm/runs/{run_id}/dwg/handoff")
    assert handoff.status_code == 201, handoff.text
    assert handoff.json()["dwg_validation"] == "not_checked"
    dxf = client.get(f"/api/v1/planm/runs/{run_id}/artifacts/cad-handoff/approved-plan.dxf")
    assert dxf.status_code == 200 and b"SECTION" in dxf.content
    inspection = client.post(f"/api/v1/planm/runs/{run_id}/dwg/inspection",
                             json={"contract_version": "planm-dwg-inspection-request/v1", "layer": "F001_ROOMS"})
    assert inspection.status_code == 200 and inspection.json()["status"] == "passed"
