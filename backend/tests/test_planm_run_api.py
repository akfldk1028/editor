from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import create_app


PLAN_ROOT = Path(__file__).parents[2]


def test_create_app_uses_deployment_runs_root(tmp_path: Path, monkeypatch) -> None:
    runs_root = tmp_path / "deployed-runs"
    monkeypatch.setenv("PLANM_RUNS_ROOT", str(runs_root))

    app = create_app(repository_root=PLAN_ROOT)

    assert app.state.planm_runs.runs_root == runs_root.resolve()


def _mass() -> dict:
    return {
        "project_id": "run-api",
        "floors": 5,
        "footprint_polygon": [[0, 0], [30, 0], [30, 12], [0, 12]],
        "site_edges": [{"edge_index": 0, "kind": "street"}],
        "access_candidates": [{"edge_index": 0, "position": 0.5}],
        "use_mix": {"neighborhood_commercial": 0.2, "office": 0.8},
    }


def test_planm_run_api_executes_reviews_approves_and_downloads(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "backend.app.modules.planm_runs.service.inspect_dwg_handoff",
        lambda **_: {
            "status": "passed",
            "drawing_id": "drawing-1",
            "skill_run_id": "skill-run-1",
            "warning_codes": [],
            "result": {
                "matches": [
                    {
                        "id": "h:9",
                        "handle": "9",
                        "type": "LINE",
                        "layer": "F001_ROOMS",
                        "bbox": {"min": [0, 0, 0], "max": [10, 0, 0]},
                        "reason": "layer equals query",
                        "confidence": 1,
                    }
                ]
            },
        },
    )
    app = create_app(
        repository_root=PLAN_ROOT,
        runs_root=tmp_path / "runs",
        execute_inline=True,
    )
    client = TestClient(app)

    created = client.post(
        "/api/v1/planm/runs",
        json={"contract_version": "planm-run-create/v1", "mass": _mass()},
    )

    assert created.status_code == 201, created.text
    run = created.json()
    assert run["contract_version"] == "planm-run/v1"
    assert run["status"] == "delivered"
    assert "C:\\" not in created.text
    run_id = run["run_id"]

    status = client.get(f"/api/v1/planm/runs/{run_id}")
    assert status.status_code == 200
    assert status.json()["stage"] == "delivered"

    alternatives = client.get(f"/api/v1/planm/runs/{run_id}/alternatives")
    assert alternatives.status_code == 200
    accepted = alternatives.json()["accepted_alternative_ids"]
    assert len(accepted) >= 2

    preview = client.get(
        f"/api/v1/planm/runs/{run_id}/alternatives/{accepted[0]}/preview"
    )
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/png"
    assert len(preview.content) > 1_000

    approval = client.post(
        f"/api/v1/planm/runs/{run_id}/approval",
        json={
            "contract_version": "planm-approval/v1",
            "alternative_id": accepted[0],
        },
    )
    assert approval.status_code == 200
    assert approval.json()["status"] == "approved"
    assert approval.json()["approved_alternative_id"] == accepted[0]

    handoff = client.post(f"/api/v1/planm/runs/{run_id}/dwg/handoff")
    assert handoff.status_code == 201, handoff.text
    handoff_result = handoff.json()
    assert handoff_result["contract_version"] == "planm-cad-handoff/v1"
    assert handoff_result["alternative_id"] == accepted[0]
    assert handoff_result["drawing_path"] == "cad-handoff/approved-plan.dxf"
    assert handoff_result["source_floor_count"] == 5
    assert handoff_result["entity_count"] > 20
    assert handoff_result["dwg_validation"] == "not_checked"

    dxf = client.get(
        f"/api/v1/planm/runs/{run_id}/artifacts/cad-handoff/approved-plan.dxf"
    )
    assert dxf.status_code == 200
    assert b"SECTION" in dxf.content
    assert b"F001_ROOMS" in dxf.content

    inspection = client.post(
        f"/api/v1/planm/runs/{run_id}/dwg/inspection",
        json={
            "contract_version": "planm-dwg-inspection-request/v1",
            "layer": "F001_ROOMS",
        },
    )
    assert inspection.status_code == 200, inspection.text
    evidence = inspection.json()
    assert evidence["contract_version"] == "planm-dwg-inspection/v1"
    assert evidence["status"] == "passed"
    assert evidence["evidence"]["result"]["matches"][0]["handle"] == "9"
    assert "C:\\" not in inspection.text

    retained = client.get(
        f"/api/v1/planm/runs/{run_id}/artifacts/cad-handoff/inspection.json"
    )
    assert retained.status_code == 200
    assert retained.json()["layer"] == "F001_ROOMS"

    download = client.get(
        f"/api/v1/planm/runs/{run_id}/artifacts/planm-manifest.json"
    )
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("application/json")
    assert download.json()["contract_version"] == "planm-delivery/v1"


def test_planm_run_api_rejects_unaccepted_approval(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            repository_root=PLAN_ROOT,
            runs_root=tmp_path / "runs",
            execute_inline=True,
        )
    )
    run = client.post(
        "/api/v1/planm/runs",
        json={"contract_version": "planm-run-create/v1", "mass": _mass()},
    ).json()

    response = client.post(
        f"/api/v1/planm/runs/{run['run_id']}/approval",
        json={
            "contract_version": "planm-approval/v1",
            "alternative_id": "not-an-accepted-option",
        },
    )

    assert response.status_code == 409
