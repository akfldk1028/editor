from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.adapters.pascal_mcp import (
    PascalMcpError,
    PascalMcpSettings,
    PascalMcpUnavailable,
)
from backend.app.api.routes_pascal import create_pascal_router

SQUARE = [[0.0, 0.0], [6.0, 0.0], [6.0, 4.0], [0.0, 4.0]]
RUN_ID = "a" * 32


class FakeRunService:
    def __init__(self, run_dir: Path, *, approved: str | None = "alternative-a") -> None:
        self._run_dir = run_dir
        self._approved = approved

    def get(self, run_id: str) -> dict:
        return {"run_id": run_id, "approved_alternative_id": self._approved}

    def run_dir(self, run_id: str) -> Path:
        return self._run_dir


class FakePascalClient:
    editor_url = "http://localhost:3002"

    def __init__(self, *, fail_with: Exception | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._fail_with = fail_with

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._fail_with is not None:
            raise self._fail_with
        self.calls.append((name, arguments))
        if name == "create_from_template":
            return {"templateId": "empty-studio"}
        if name == "save_scene":
            return {"id": "scene123", "version": 1}
        if name == "get_scene":
            return {
                "nodes": {
                    "level_xyz": {"id": "level_xyz", "type": "level"},
                    "wall_template": {"id": "wall_template", "type": "wall"},
                }
            }
        if name == "apply_patch":
            return {"appliedOps": 1, "deletedIds": ["wall_template"], "createdIds": []}
        if name == "apply_floor_plan":
            return {
                "totals": {"rooms": 1, "walls": 4, "doors": 1},
                "warnings": [],
            }
        return {}


def _write_geometry(run_dir: Path, alternative_id: str = "alternative-a") -> None:
    target = (
        run_dir / "artifacts" / "alternatives" / alternative_id / "floor_001" / "f1.geometry.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "contract_version": "planm-floor-geometry/v1",
                "project_id": "proj-1",
                "candidate_id": "cand-1",
                "floor_index": 1,
                "units": "m",
                "rooms": [
                    {
                        "room_id": "wc_1",
                        "space_type": "toilet",
                        "category": "room",
                        "polygon": SQUARE,
                    }
                ],
                "openings": [
                    {
                        "opening_id": "wc-door",
                        "kind": "door",
                        "connects": ["wc_1", "corridor_1"],
                        "start": [2.55, 0.0],
                        "end": [3.45, 0.0],
                        "clear_width": 0.9,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _client(
    run_dir: Path,
    *,
    approved: str | None = "alternative-a",
    settings: PascalMcpSettings | None = PascalMcpSettings(url="http://localhost:3917/mcp"),
    pascal: FakePascalClient | None = None,
) -> tuple[TestClient, FakePascalClient]:
    fake = pascal or FakePascalClient()
    app = FastAPI()
    app.include_router(
        create_pascal_router(
            FakeRunService(run_dir, approved=approved),
            settings_factory=lambda: settings,
            client_factory=lambda _settings: fake,
        )
    )
    return TestClient(app), fake


def test_publishes_the_approved_alternative_and_returns_the_editor_url(tmp_path: Path) -> None:
    _write_geometry(tmp_path)
    client, pascal = _client(tmp_path)

    response = client.post(f"/api/v1/planm/runs/{RUN_ID}/pascal", json={})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["contract_version"] == "planm-pascal-publish/v1"
    assert body["alternative_id"] == "alternative-a"
    assert body["published"] is True
    assert body["scene_id"] == "scene123"
    assert body["editor_url"] == "http://localhost:3002/scene/scene123"
    assert body["totals"]["rooms"] == 1

    called = [name for name, _ in pascal.calls]
    # The empty template comes first so a second publish does not stack on the
    # geometry the previous one left in the MCP session.
    assert called == [
        "create_from_template",
        "get_scene",
        "apply_patch",
        "save_scene",
        "get_scene",
        "apply_floor_plan",
    ]
    assert pascal.calls[0][1] == {"id": "empty-studio"}
    # The template's own sample room is cleared, not left in the published scene.
    assert pascal.calls[2][1] == {"patches": [{"op": "delete", "id": "wall_template"}]}

    # The scene is bound before the plan is applied, and the first level targets
    # the scene's existing ground level.
    plan = pascal.calls[-1][1]["plan"]
    assert plan["levels"][0]["levelId"] == "level_xyz"
    room = plan["levels"][0]["rooms"][0]
    assert room["type"] == "bathroom"
    assert room["openings"] == [{"kind": "door", "wall": 0, "t": 0.5, "width": 0.9}]


def test_plan_only_returns_the_conversion_without_contacting_pascal(tmp_path: Path) -> None:
    _write_geometry(tmp_path)
    client, pascal = _client(tmp_path)

    response = client.post(
        f"/api/v1/planm/runs/{RUN_ID}/pascal", json={"plan_only": True}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["published"] is False
    assert body["plan"]["levels"][0]["rooms"][0]["name"] == "wc 1"
    assert pascal.calls == []


def test_dry_run_validates_without_binding_a_scene(tmp_path: Path) -> None:
    _write_geometry(tmp_path)
    client, pascal = _client(tmp_path)

    response = client.post(f"/api/v1/planm/runs/{RUN_ID}/pascal", json={"dry_run": True})

    assert response.status_code == 201
    body = response.json()
    assert body["published"] is False
    assert body["dry_run"] is True
    assert body["scene_id"] is None
    assert [name for name, _ in pascal.calls] == ["apply_floor_plan"]
    assert pascal.calls[0][1]["dryRun"] is True


def test_an_unapproved_run_without_an_explicit_alternative_is_a_conflict(
    tmp_path: Path,
) -> None:
    _write_geometry(tmp_path)
    client, _ = _client(tmp_path, approved=None)

    response = client.post(f"/api/v1/planm/runs/{RUN_ID}/pascal", json={})

    assert response.status_code == 409
    assert "approve" in response.json()["detail"]


def test_an_alternative_without_geometry_explains_how_to_fix_it(tmp_path: Path) -> None:
    # A run from before the geometry artifact existed.
    (tmp_path / "artifacts" / "alternatives" / "alternative-a").mkdir(parents=True)
    client, _ = _client(tmp_path)

    response = client.post(f"/api/v1/planm/runs/{RUN_ID}/pascal", json={})

    assert response.status_code == 409
    assert "re-run" in response.json()["detail"]


def test_no_configured_endpoint_says_so_instead_of_failing_obscurely(
    tmp_path: Path,
) -> None:
    _write_geometry(tmp_path)
    client, _ = _client(tmp_path, settings=None)

    response = client.post(f"/api/v1/planm/runs/{RUN_ID}/pascal", json={})

    assert response.status_code == 503
    assert "PASCAL_MCP_URL" in response.json()["detail"]


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (PascalMcpUnavailable("connection refused"), 503),
        (PascalMcpError("apply_floor_plan: bad polygon"), 502),
    ],
)
def test_pascal_side_failures_are_reported_with_a_useful_status(
    tmp_path: Path, error: Exception, expected_status: int
) -> None:
    _write_geometry(tmp_path)
    client, _ = _client(tmp_path, pascal=FakePascalClient(fail_with=error))

    response = client.post(f"/api/v1/planm/runs/{RUN_ID}/pascal", json={})

    assert response.status_code == expected_status


def test_an_explicit_alternative_overrides_the_approved_one(tmp_path: Path) -> None:
    _write_geometry(tmp_path, alternative_id="alternative-c")
    client, _ = _client(tmp_path)

    response = client.post(
        f"/api/v1/planm/runs/{RUN_ID}/pascal",
        json={"alternative_id": "alternative-c", "plan_only": True},
    )

    assert response.status_code == 201
    assert response.json()["alternative_id"] == "alternative-c"
