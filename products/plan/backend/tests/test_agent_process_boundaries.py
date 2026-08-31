from __future__ import annotations

import json
import ast
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import subprocess
import sys
from threading import Thread

import pytest


PLAN_ROOT = Path(__file__).parents[2]
PLANM_BRIDGE = PLAN_ROOT / "agents" / "planm" / "runtime" / "planm_bridge.py"


def test_planm_bridge_has_no_backend_python_imports() -> None:
    source = PLANM_BRIDGE.read_text(encoding="utf-8")

    assert "from backend.app" not in source
    assert "import backend.app" not in source
    assert "backend" not in source.lower()


def test_planm_engine_adapter_is_a_thin_process_host() -> None:
    path = PLAN_ROOT / "backend" / "app" / "adapters" / "planm_engine.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert len(source.splitlines()) <= 10
    assert any(
        isinstance(node, ast.ImportFrom)
        and node.module == "backend.app.modules.planm_execution.service"
        for node in tree.body
    )


def test_backend_planm_adapter_runs_versioned_normalize_stage(tmp_path: Path) -> None:
    from backend.app.adapters.planm_agent import run_planm_stage

    input_path = tmp_path / "mass.json"
    state_path = tmp_path / "planm-state.json"
    output_dir = tmp_path / "run"
    input_path.write_text(
        json.dumps(
            {
                "project_id": "adapter-boundary",
                "floors": 1,
                "footprint_polygon": [[0, 0], [30, 0], [30, 12], [0, 12]],
                "site_edges": [{"edge_index": 0, "kind": "street"}],
                "access_candidates": [{"edge_index": 0, "position": 0.5}],
                "use_mix": {"office": 1.0},
            }
        ),
        encoding="utf-8",
    )

    result = run_planm_stage(
        stage="normalize",
        input_path=input_path,
        state_path=state_path,
        output_dir=output_dir,
        repository_root=PLAN_ROOT,
        run_root=tmp_path,
    )

    assert result["contract_version"] == "skill-result/v1"
    assert result["status"] == "success"
    assert state_path.is_file()


def test_backend_planm_adapter_builds_gitagent_host_command() -> None:
    from backend.app.adapters.planm_agent import build_planm_host_command

    command = build_planm_host_command(PLAN_ROOT)

    assert Path(command[0]).name.lower() in {"node", "node.exe"}
    assert command[1] == str(
        PLAN_ROOT / "agents" / "planm" / "runtime" / "gitagent_host.mjs"
    )
    assert "planm_bridge.py" not in " ".join(command)


def test_dwg_client_builds_independent_mcp_process_command() -> None:
    from backend.app.adapters.dwg_client import build_dwg_mcp_command

    command = build_dwg_mcp_command(PLAN_ROOT)

    assert command[0] in {"npm", "npm.cmd"}
    assert command[1:] == [
        "--prefix",
        str(PLAN_ROOT.parents[1] / "products" / "dwg"),
        "run",
        "mcp",
    ]


def test_dwg_client_builds_independent_gateway_process_command() -> None:
    from backend.app.adapters.dwg_client import build_dwg_gateway_command

    command = build_dwg_gateway_command(PLAN_ROOT)

    assert command[0] in {"npm", "npm.cmd"}
    assert command[1:] == [
        "--prefix",
        str(PLAN_ROOT.parents[1] / "products" / "dwg"),
        "run",
        "gateway",
    ]


def test_planm_adapter_rejects_paths_outside_owned_run_root(tmp_path: Path) -> None:
    from backend.app.adapters.planm_agent import run_planm_stage

    input_path = tmp_path / "mass.json"
    input_path.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="run root"):
        run_planm_stage(
            stage="normalize",
            input_path=input_path,
            state_path=tmp_path.parent / "escaped-state.json",
            output_dir=tmp_path / "output",
            repository_root=PLAN_ROOT,
            run_root=tmp_path,
        )


def test_dwg_loopback_client_uses_public_health_endpoint() -> None:
    from backend.app.adapters.dwg_client import DwgLoopbackClient

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            assert self.path == "/api/health"
            payload = json.dumps({"ok": True, "service": "dwg-provider-gateway"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = DwgLoopbackClient(f"http://127.0.0.1:{server.server_port}")
        assert client.health()["ok"] is True
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_dwg_loopback_client_rejects_public_network_hosts() -> None:
    from backend.app.adapters.dwg_client import DwgLoopbackClient

    with pytest.raises(ValueError, match="loopback"):
        DwgLoopbackClient("https://example.com")


def test_planm_bridge_returns_blocked_result_when_engine_times_out(tmp_path: Path) -> None:
    fake_engine = tmp_path / "slow_engine.py"
    fake_engine.write_text("import time\ntime.sleep(5)\n", encoding="utf-8")
    env = os.environ.copy()
    env["PLANM_ENGINE_COMMAND_JSON"] = json.dumps(
        [sys.executable, str(fake_engine)]
    )
    env["PLANM_ENGINE_CWD"] = str(tmp_path)
    env["PLANM_ENGINE_TIMEOUT_SECONDS"] = "0.05"

    completed = subprocess.run(
        [
            sys.executable,
            str(PLANM_BRIDGE),
            "normalize",
            "--input",
            str(tmp_path / "input.json"),
            "--state",
            str(tmp_path / "state.json"),
            "--output-dir",
            str(tmp_path),
        ],
        cwd=PLAN_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=2,
    )

    assert completed.returncode == 4
    result = json.loads(completed.stdout)
    assert result["status"] == "blocked"
    assert result["violations"][0]["code"] == "engine_timeout"


def test_backend_adapter_converts_outer_watchdog_timeout(tmp_path: Path) -> None:
    from backend.app.adapters.planm_agent import run_planm_stage

    repository = tmp_path / "repository"
    host = repository / "agents" / "planm" / "runtime" / "gitagent_host.mjs"
    host.parent.mkdir(parents=True)
    host.write_text("setTimeout(() => {}, 5000);\n", encoding="utf-8")
    run_root = tmp_path / "run"
    run_root.mkdir()
    input_path = run_root / "input.json"
    input_path.write_text("{}", encoding="utf-8")

    with pytest.raises(TimeoutError, match="PLANM agent"):
        run_planm_stage(
            stage="normalize",
            input_path=input_path,
            state_path=run_root / "state.json",
            output_dir=run_root / "output",
            repository_root=repository,
            run_root=run_root,
            timeout_seconds=0.05,
        )
