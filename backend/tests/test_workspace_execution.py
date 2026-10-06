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
    "component",
    [
        {"provider": "builtins.eval", "config": {}},
        {"provider": "autogen_ext.tools.mcp.StdioMcpTool", "config": {}},
        {"provider": "autogen_ext.agents.web_surfer.MultimodalWebSurfer", "config": {}},
        {
            "provider": "autogen_ext.code_executors.local.LocalCommandLineCodeExecutor",
            "config": {},
        },
        {
            "provider": "autogen_core.tools.FunctionTool",
            "config": {"source_code": "def f(): pass", "name": "f"},
        },
        {"provider": "autogen_ext.tools.http.HttpTool", "config": {}},
        {
            "provider": "autogen_ext.tools.mcp.McpWorkbench",
            "config": {
                "server_params": {"type": "StdioServerParams", "command": "npx"}
            },
        },
    ],
)
def test_unsafe_template_component_is_rejected_before_loading(component):
    from backend.app.adapters.workspace.team import validate_components

    with pytest.raises(ValueError):
        validate_components(component)


def exported_assistant(name="assistant", model_client=None):
    # The shape AssistantAgent.dump_component() produces: an empty static workbench
    # is always present, so a template exported from a Studio is rejected unless
    # the container provider is allowed.
    return {
        "provider": "autogen_agentchat.agents.AssistantAgent",
        "component_type": "agent",
        "config": {
            "name": name,
            "description": "An agent",
            "reflect_on_tool_use": False,
            "tool_call_summary_format": "{result}",
            "model_client": model_client
            or {
                "provider": "autogen_ext.models.openai.OpenAIChatCompletionClient",
                "component_type": "model",
                "config": {"model": "gpt-4o-mini"},
            },
            "workbench": [
                {
                    "provider": "autogen_core.tools.StaticStreamWorkbench",
                    "component_type": "workbench",
                    "config": {"tools": []},
                }
            ],
        },
    }


def test_exported_assistant_agent_with_static_stream_workbench_validates():
    from backend.app.adapters.workspace.team import validate_components

    validate_components(exported_assistant())


def test_http_mcp_workbench_passes_policy_without_connecting():
    from backend.app.adapters.workspace.team import validate_components

    validate_components(
        {
            "provider": "autogen_ext.tools.mcp.McpWorkbench",
            "component_type": "workbench",
            "config": {
                "server_params": {
                    "type": "StreamableHttpServerParams",
                    "url": "http://127.0.0.1:9/mcp",
                }
            },
        }
    )


def test_start_passes_saved_environment_to_team_loader(tmp_path, monkeypatch):
    from backend.app.modules.workspace import execution as module
    from backend.app.modules.workspace.execution import WorkspaceExecution

    session = native_session(tmp_path)
    seen = []

    def spy(component, input_callback, environment=()):
        seen.append(list(environment))
        raise RuntimeError("loader stub")

    monkeypatch.setattr(module, "load_team", spy)
    saved = [{"name": "OPENAI_API_KEY", "value": "saved-secret-value"}]

    async def scenario():
        service = WorkspaceExecution(lambda: tmp_path)
        repo = service.repository()
        run = repo.create_run(session)
        service.start(run["run_id"], "task", [], saved)
        await service.tasks[run["run_id"]]
        state = repo.events(run["run_id"])
        await service.close()
        return state

    state = asyncio.run(scenario())
    assert seen == [saved]
    assert state["status"] == "error"
    assert "saved-secret-value" not in str(state["events"])


def test_capabilities_reports_http_only_mcp_and_editor_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("EDITOR_WORKSPACE_DATA_DIR", str(tmp_path))
    app = FastAPI()
    app.include_router(create_workspace_router(public_origin="http://testserver"))
    with TestClient(app) as client:
        body = client.get("/api/v1/workspace/runs/capabilities").json()
    assert body["template_mcp_execution"] == "http_only"
    assert "autogen_core.tools.StaticStreamWorkbench" in body["template_workbenches"]
    assert "backend.app.adapters.workspace.tools.LandAnalyzeTool" in body["template_tools"]
    assert (
        "autogen_ext.models.replay.ReplayChatCompletionClient"
        in body["supported_providers"]
    )


def replay_model(replies):
    return {
        "provider": "autogen_ext.models.replay.ReplayChatCompletionClient",
        "component_type": "model",
        "config": {"chat_completions": list(replies)},
    }


def test_replay_model_team_runs_to_completion_without_network(tmp_path, monkeypatch):
    # The first execution of a real AssistantAgent through the editor runner.
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
                        "participants": [exported_assistant(model_client=replay_model(["4"]))],
                        "termination_condition": {
                            "provider": "autogen_agentchat.conditions.MaxMessageTermination",
                            "component_type": "termination",
                            "config": {"max_messages": 2},
                        },
                    },
                }
            },
        )
        assert team.status_code == 201, team.text
        session = client.post(
            "/api/v1/workspace/sessions",
            json={"name": "Replay", "team_id": team.json()["id"]},
        ).json()
        run = client.post("/api/v1/workspace/runs", json={"session_id": session["id"]})
        path = "/api/v1/workspace/runs/" + str(run.json()["run_id"])
        assert client.post(path + "/start", json={"task": "What is 2+2?", "files": []}).status_code == 202
        for _ in range(200):
            state = client.get(path + "/events").json()
            if state["status"] in ("complete", "error"):
                break
            time.sleep(0.05)
        assert state["status"] == "complete", state
        assert any(
            e["type"] == "message" and e["data"].get("content") == "4"
            for e in state["events"]
        ), state["events"]


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
