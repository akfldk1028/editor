from __future__ import annotations

import json
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest


PLAN_ROOT = Path(__file__).parents[2]


def test_dwg_client_builds_independent_mcp_process_command() -> None:
    from backend.app.adapters.dwg_client import build_dwg_mcp_command

    command = build_dwg_mcp_command(PLAN_ROOT)

    assert command[0] in {"npm", "npm.cmd"}
    assert command[1:] == [
        "--prefix",
        str(PLAN_ROOT / "infra" / "services" / "dwg"),
        "run",
        "mcp",
    ]


def test_dwg_client_builds_independent_gateway_process_command() -> None:
    from backend.app.adapters.dwg_client import build_dwg_gateway_command

    command = build_dwg_gateway_command(PLAN_ROOT)

    assert command[0] in {"npm", "npm.cmd"}
    assert command[1:] == [
        "--prefix",
        str(PLAN_ROOT / "infra" / "services" / "dwg"),
        "run",
        "gateway",
    ]


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
