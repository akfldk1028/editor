from __future__ import annotations

import os
import ipaddress
import json
from pathlib import Path
from pathlib import PureWindowsPath
import signal
import socket
import subprocess
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def build_dwg_mcp_command(repository_root: Path) -> list[str]:
    executable = "npm.cmd" if os.name == "nt" else "npm"
    return [
        executable,
        "--prefix",
        str(repository_root.resolve() / "agents" / "dwg"),
        "run",
        "mcp",
    ]


def build_dwg_gateway_command(repository_root: Path) -> list[str]:
    executable = "npm.cmd" if os.name == "nt" else "npm"
    return [
        executable,
        "--prefix",
        str(repository_root.resolve() / "agents" / "dwg"),
        "run",
        "gateway",
    ]


def inspect_dwg_handoff(
    *,
    repository_root: Path,
    workspace_root: Path,
    drawing_path: str,
    layer: str,
    startup_timeout_seconds: float = 120,
) -> dict[str, Any]:
    repository = repository_root.resolve()
    workspace = workspace_root.resolve()
    _validate_drawing_path(workspace, drawing_path)
    if not layer or len(layer) > 64 or any(ord(character) < 32 for character in layer):
        raise ValueError("DWG inspection layer is invalid")
    port = _available_loopback_port()
    env = os.environ.copy()
    env.update(
        {
            "DWG_WORKSPACE": str(workspace),
            "DWG_DRAWING_PATH": drawing_path,
            "DWG_GATEWAY_PORT": str(port),
            "DWG_HOST_DIALOGS": "off",
            "DWG_EXPORT_ROOT": str(workspace / "dwg-output"),
        }
    )
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    process = subprocess.Popen(
        build_dwg_gateway_command(repository),
        cwd=repository / "agents" / "dwg",
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        start_new_session=os.name != "nt",
    )
    try:
        client = DwgLoopbackClient(
            f"http://127.0.0.1:{port}", timeout_seconds=min(60, startup_timeout_seconds)
        )
        deadline = time.monotonic() + startup_timeout_seconds
        while True:
            if process.poll() is not None:
                raise RuntimeError("DWG gateway exited during startup")
            try:
                client.health()
                break
            except RuntimeError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("DWG gateway startup timed out")
                time.sleep(0.2)
        drawing = client.drawing()
        drawing_id = drawing.get("drawingId")
        if not isinstance(drawing_id, str) or not drawing_id:
            raise ValueError("DWG gateway drawing response has no drawingId")
        skill = client.run_skill(
            {
                "skillId": "inspect-drawing",
                "version": "1.0.0",
                "documentId": drawing_id,
                "input": {"path": drawing_path, "layer": layer},
            }
        )
        if skill.get("status") != "passed":
            warning_codes = skill.get("warningCodes", [])
            bounded_codes = ",".join(
                str(code) for code in warning_codes[:8]
            ) if isinstance(warning_codes, list) else "unknown"
            raise RuntimeError(
                f"DWG inspect-drawing skill failed ({bounded_codes or 'no warning code'})"
            )
        return _portable_evidence(
            {
                "status": "passed",
                "drawing_id": drawing_id,
                "skill_run_id": skill.get("runId"),
                "warning_codes": skill.get("warningCodes", []),
                "result": skill.get("result"),
            },
            workspace,
        )
    finally:
        _stop_process_tree(process)


class DwgLoopbackClient:
    def __init__(self, base_url: str = "http://127.0.0.1:4317", timeout_seconds: float = 30):
        parsed = urlparse(base_url)
        if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("DWG gateway must use an unauthenticated loopback HTTP URL")
        try:
            is_loopback = ipaddress.ip_address(parsed.hostname).is_loopback
        except ValueError:
            is_loopback = parsed.hostname.lower() == "localhost"
        if not is_loopback:
            raise ValueError("DWG gateway host must be loopback")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("DWG gateway base URL must not include a path, query, or fragment")
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not path.startswith("/api/") or ".." in path:
            raise ValueError("DWG requests must use a public /api route")
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self._base_url}{path}",
            data=body,
            method=method.upper(),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise RuntimeError(f"DWG gateway returned HTTP {error.code}") from error
        except URLError as error:
            raise RuntimeError(f"DWG gateway unavailable: {error.reason}") from error
        if not isinstance(result, dict):
            raise ValueError("DWG gateway returned a non-object JSON response")
        return result

    def health(self) -> dict[str, Any]:
        return self.request_json("GET", "/api/health")

    def drawing(self) -> dict[str, Any]:
        return self.request_json("GET", "/api/drawing")

    def run_skill(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request_json("POST", "/api/skills/run", payload)

    def export_capabilities(self) -> dict[str, Any]:
        return self.request_json("GET", "/api/export/capabilities")


def _validate_drawing_path(workspace: Path, drawing_path: str) -> Path:
    supplied = Path(drawing_path)
    if (
        not drawing_path
        or supplied.is_absolute()
        or PureWindowsPath(drawing_path).is_absolute()
        or ".." in supplied.parts
    ):
        raise ValueError("DWG drawing path must be workspace-relative")
    candidate = (workspace / supplied).resolve()
    try:
        candidate.relative_to(workspace)
    except ValueError as error:
        raise ValueError("DWG drawing path escapes the workspace") from error
    if not candidate.is_file():
        raise ValueError("DWG drawing does not exist")
    return candidate


def _available_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def _portable_evidence(value: Any, workspace: Path) -> Any:
    if isinstance(value, dict):
        return {str(key): _portable_evidence(item, workspace) for key, item in value.items()}
    if isinstance(value, list):
        return [_portable_evidence(item, workspace) for item in value]
    if isinstance(value, str) and (Path(value).is_absolute() or PureWindowsPath(value).is_absolute()):
        try:
            return Path(value).resolve().relative_to(workspace).as_posix()
        except ValueError:
            return "[external-path-redacted]"
    return value


def _stop_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
