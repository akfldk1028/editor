import time
import asyncio
import pytest

from fastapi.testclient import TestClient
from fastapi import FastAPI

from backend.app.api.routes_workspace import create_workspace_router


def test_actual_user_proxy_execution_input_history_and_duplicate_start(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("EDITOR_WORKSPACE_DATA_DIR", str(tmp_path))
    app = FastAPI()
    app.include_router(create_workspace_router(public_origin="http://testserver"))
    with TestClient(app) as client:
        team = client.post(
            "/api/v1/workspace/teams",
            json={
                "component": {
                    "provider": "autogen_agentchat.teams.RoundRobinGroupChat",
                    "component_type": "team",
                    "config": {
                        "participants": [
                            {
                                "provider": "autogen_agentchat.agents.UserProxyAgent",
                                "component_type": "agent",
                                "config": {"name": "human"},
                            }
                        ],
                        "max_turns": 1,
                    },
                }
            },
        ).json()
        session = client.post(
            "/api/v1/workspace/sessions",
            json={"name": "Real input test", "team_id": team["id"]},
        ).json()
        run = client.post("/api/v1/workspace/runs", json={"session_id": session["id"]})
        assert run.status_code == 201, run.text
        path = "/api/v1/workspace/runs/" + str(run.json()["run_id"])
        assert (
            client.post(
                path + "/start", json={"task": "Please answer", "files": []}
            ).status_code
            == 202
        )
        assert (
            client.post(
                path + "/start", json={"task": "duplicate", "files": []}
            ).status_code
            == 409
        )
        for _ in range(100):
            state = client.get(path + "/events").json()
            if state["status"] == "awaiting_input":
                break
            time.sleep(0.05)
        assert state["status"] == "awaiting_input", state
        assert any(e["type"] == "input_request" for e in state["events"])
        assert (
            client.post(path + "/input", json={"response": "Native answer"}).status_code
            == 200
        )
        for _ in range(100):
            state = client.get(path + "/events").json()
            if state["status"] == "complete":
                break
            time.sleep(0.05)
        assert state["status"] == "complete", state
        history = client.get(f"/api/v1/workspace/sessions/{session['id']}/runs").json()[
            "runs"
        ]
        assert history[-1]["status"] == "complete"
        assert any(
            m["config"].get("content") == "Native answer"
            for m in history[-1]["messages"]
        )
        assert (
            client.post(path + "/input", json={"response": "late"}).status_code == 409
        )
        assert (
            client.post(
                "/api/v1/workspace/runs",
                headers={"Origin": "https://foreign.invalid"},
                json={"session_id": session["id"]},
            ).status_code
            == 403
        )


def test_unknown_session_cannot_start_and_foreign_provider_is_rejected(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("EDITOR_WORKSPACE_DATA_DIR", str(tmp_path))
    app = FastAPI()
    app.include_router(create_workspace_router(public_origin="http://testserver"))
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/v1/workspace/runs", json={"session_id": 99999}
            ).status_code
            == 404
        )


def native_session(tmp_path):
    from backend.app.modules.workspace.sessions import SessionRepository

    return SessionRepository(tmp_path).create(
        "saved",
        1,
        {
            "provider": "autogen_agentchat.teams.RoundRobinGroupChat",
            "component_type": "team",
            "config": {
                "participants": [
                    {
                        "provider": "autogen_agentchat.agents.UserProxyAgent",
                        "component_type": "agent",
                        "config": {"name": "human"},
                    }
                ],
                "max_turns": 1,
            },
        },
    )["id"]


def test_archive_refuses_reserved_session_and_duplicate_creation_is_atomic(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from backend.app.modules.workspace.sessions import (
        SessionRepository,
        SessionArchiveConflict,
    )
    from backend.app.modules.workspace.execution_repository import (
        ExecutionRepository,
        ExecutionConflict,
    )

    session = native_session(tmp_path)
    repo = ExecutionRepository(tmp_path)

    def create():
        try:
            return repo.create_run(session)
        except ExecutionConflict:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        created = [run for run in pool.map(lambda _: create(), range(4)) if run]
    assert len(created) == 1
    with pytest.raises(SessionArchiveConflict):
        SessionRepository(tmp_path).archive(session)
    repo.finish(created[0]["run_id"], "stopped", {})
    assert SessionRepository(tmp_path).archive(session)["archived"]


def test_exclusive_executor_reconciles_only_after_previous_owner_releases(tmp_path):
    from backend.app.modules.workspace.execution import WorkspaceExecution
    from backend.app.modules.workspace.execution_repository import ExecutionConflict

    session = native_session(tmp_path)
    first, second = WorkspaceExecution(lambda: tmp_path), WorkspaceExecution(
        lambda: tmp_path
    )
    repo = first.repository()
    run = repo.create_run(session)
    repo.claim(run["run_id"], "interrupted")
    with pytest.raises(ExecutionConflict):
        second.repository()
    assert repo.get_run(run["run_id"])["status"] == "active"
    asyncio.run(first.close())
    recovered = second.repository().get_run(run["run_id"])
    assert recovered["status"] == "error"
    assert len(second.repository().runs(session)["runs"]) == 1
    asyncio.run(second.close())


def test_terminal_execution_cannot_be_reopened_by_late_events(tmp_path):
    from backend.app.modules.workspace.execution_repository import (
        ExecutionRepository,
        ExecutionConflict,
    )

    session = native_session(tmp_path)
    repo = ExecutionRepository(tmp_path)
    run = repo.create_run(session)
    repo.finish(run["run_id"], "complete", {"done": True}, state={})
    with pytest.raises(ExecutionConflict):
        repo.event(run["run_id"], {"type": "input_request"}, "awaiting_input")
    assert repo.get_run(run["run_id"])["status"] == "complete"
    assert repo.previous_state({"session_id": session}) == {}


@pytest.mark.parametrize(
    "provider",
    [
        "builtins.eval",
        "autogen_ext.tools.mcp.StdioMcpTool",
        "autogen_ext.agents.web_surfer.MultimodalWebSurfer",
        "autogen_ext.code_executors.local.LocalCommandLineCodeExecutor",
    ],
)
def test_unsafe_template_component_is_rejected_before_loading(provider):
    from backend.app.adapters.workspace_team import validate_components

    with pytest.raises(ValueError):
        validate_components({"provider": provider, "config": {}})


@pytest.mark.parametrize("shutdown", [False, True])
def test_stop_before_coroutine_enters_is_durable(tmp_path, shutdown):
    from backend.app.modules.workspace.execution import WorkspaceExecution
    from backend.app.modules.workspace.execution_repository import ExecutionRepository

    session = native_session(tmp_path)

    async def scenario():
        service = WorkspaceExecution(lambda: tmp_path)
        repo = service.repository()
        run = repo.create_run(session)
        service.start(run["run_id"], "never enter the coroutine", [])
        if not shutdown:
            service.stop(run["run_id"])
        await service.close()
        persisted = ExecutionRepository(tmp_path)
        assert persisted.get_run(run["run_id"])["status"] == "stopped"
        assert len(persisted.runs(session)["runs"]) == 1

    asyncio.run(scenario())


def test_terminal_history_can_be_drained_across_event_pages(tmp_path):
    from backend.app.modules.workspace.execution_repository import ExecutionRepository

    session = native_session(tmp_path)
    repo = ExecutionRepository(tmp_path)
    identifier = repo.create_run(session)["run_id"]
    repo.claim(identifier, "long stream")
    for n in range(501):
        repo.event(identifier, {"type": "message_chunk", "data": {"content": str(n)}})
    repo.finish(
        identifier, "complete", {}, terminal_event={"type": "result", "data": {}}
    )
    first = repo.events(identifier)
    assert first["status"] == "complete" and first["has_more"]
    assert len(first["events"]) == 500
    second = repo.events(identifier, first["events"][-1]["seq"])
    assert not second["has_more"] and len(second["events"]) == 2
    assert second["events"][-1]["type"] == "result"
