"""The one module that knows where the Plan Agent is and how to talk to it.

The Plan Agent (agents/planm) serves REST routes for this product on the same app as its
A2A card: POST /planm/stage-bundle runs one PLANM stage on a run directory that travels with
the request (planm-stage-bundle/v1 - the agent runs on its own server and never sees this
disk), POST /planm/generate answers a floor-plan body. Everything else in the backend sees
only `run_planm_stage` and `PlanmClient.generate`; no other file names the URL.
"""
from __future__ import annotations

import io
import json
import os
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

import httpx

from backend.app.core.agent_network import network_headers
from backend.app.core.json_contracts import validate_planm_contract

PLANM_AGENT_URL_ENV = "PLANM_AGENT_URL"
DEFAULT_URL = "http://127.0.0.1:8309"


class PlanmClient:
    def __init__(self, base_url: str | None = None, *, transport: httpx.BaseTransport | None = None,
                 timeout: float = 300.0) -> None:
        self.base_url = (base_url or os.environ.get(PLANM_AGENT_URL_ENV) or DEFAULT_URL).rstrip("/")
        self.transport = transport
        self.timeout = timeout

    def post(self, route: str, body: dict[str, Any]) -> dict[str, Any]:
        """One POST; the errors map onto the run service's retryable set (OSError, RuntimeError, TimeoutError, ValueError)."""
        try:
            with httpx.Client(timeout=httpx.Timeout(self.timeout, connect=5), transport=self.transport,
                              headers=network_headers()) as client:
                response = client.post(self.base_url + route, json=body)
        except httpx.TimeoutException as error:
            raise TimeoutError(f"PLANM agent exceeded {self.timeout:g} seconds") from error
        except httpx.HTTPError as error:
            raise RuntimeError(f"PLANM agent unreachable at {self.base_url}: {error}") from error
        try:
            payload = response.json()
        except ValueError as error:
            raise ValueError(f"PLANM agent answered {response.status_code} without JSON") from error
        if not isinstance(payload, dict):
            raise ValueError("PLANM agent answered with a non-object")
        if response.status_code >= 500:
            raise RuntimeError(f"PLANM agent failed ({response.status_code}): {payload.get('error', '')}")
        return payload

    def health(self) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=httpx.Timeout(5, connect=3), transport=self.transport,
                              headers=network_headers()) as client:
                response = client.get(self.base_url + "/health")
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise RuntimeError(f"PLANM agent health unavailable at {self.base_url}: {error}") from error

    def post_bundle(self, route: str, query: dict[str, str], data: bytes) -> bytes:
        """POST a zip, receive a zip; the same error mapping as post()."""
        try:
            with httpx.Client(timeout=httpx.Timeout(self.timeout, connect=5), transport=self.transport,
                              headers=network_headers()) as client:
                response = client.post(self.base_url + route, params=query, content=data,
                                       headers={"Content-Type": "application/zip"})
        except httpx.TimeoutException as error:
            raise TimeoutError(f"PLANM agent exceeded {self.timeout:g} seconds") from error
        except httpx.HTTPError as error:
            raise RuntimeError(f"PLANM agent unreachable at {self.base_url}: {error}") from error
        if response.status_code >= 500:
            raise RuntimeError(f"PLANM agent failed ({response.status_code})")
        if response.status_code != 200 or response.headers.get("content-type", "").split(";")[0] != "application/zip":
            try:
                detail = response.json().get("error", "")
            except ValueError:
                raise ValueError(f"PLANM agent answered {response.status_code} without a bundle") from None
            raise RuntimeError(f"PLANM agent refused the stage request: {detail}")
        return response.content

    def generate(self, body: dict[str, Any]) -> dict[str, Any]:
        """A floor-plan document, or {"error": ..., receipt} when the agent refused the body (422)."""
        return self.post("/planm/generate", body)


def run_planm_stage(
    *,
    stage: str,
    input_path: Path,
    state_path: Path,
    output_dir: Path,
    run_root: Path,
    timeout_seconds: float = 300,
    client: PlanmClient | None = None,
) -> dict[str, Any]:
    owned_root = run_root.resolve()
    names = {}
    for label, path in (("input", input_path), ("state", state_path), ("output", output_dir)):
        try:
            names[label] = path.resolve().relative_to(owned_root).as_posix()
        except ValueError as error:
            raise ValueError(f"{label} path escapes the owned run root") from error
    output = output_dir.resolve()
    if output not in state_path.resolve().parents:
        raise ValueError("the state file must sit inside the output folder")
    # The run directory travels with the request: the input file and the whole output folder
    # (later stages read what earlier ones wrote), named relative to the run root.
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(input_path.resolve(), names["input"])
        if output.is_dir():
            for path in sorted(output.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(owned_root).as_posix())
    reply = (client or PlanmClient(timeout=timeout_seconds)).post_bundle(
        "/planm/stage-bundle", {"stage": stage, **names}, buffer.getvalue())
    result = _write_back(reply, owned_root, output)
    validate_planm_contract("skill-result.schema.json", result)
    return result


def _write_back(data: bytes, run_root: Path, output: Path) -> dict[str, Any]:
    """Unpack the agent's output folder into ours; every member must land inside it."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as error:
        raise ValueError("PLANM agent answered with a broken bundle") from error
    result = None
    with archive:
        for member in archive.infolist():
            name = member.filename
            if name == "skill-result.json":
                result = json.loads(archive.read(member).decode("utf-8"))
                continue
            relative = PurePosixPath(name)
            if (member.is_dir() or "\\" in name or relative.is_absolute()
                    or any(part in ("", ".", "..") for part in relative.parts)):
                continue
            destination = run_root.joinpath(*relative.parts).resolve()
            if output != destination and output not in destination.parents:
                raise ValueError(f"PLANM agent bundle wrote outside the output folder: {name}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(member))
    if not isinstance(result, dict):
        raise ValueError("PLANM agent bundle carries no skill result")
    return result
