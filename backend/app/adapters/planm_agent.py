"""The one module that knows where the Plan Agent is and how to talk to it.

The Plan Agent (agents/planm) serves two REST routes for this product on the same app
as its A2A card: POST /planm/stage runs one PLANM stage on a run directory, POST
/planm/generate answers a floor-plan body. Everything else in the backend sees only
`run_planm_stage` and `PlanmClient.generate`; no other file names the URL.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx

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
            with httpx.Client(timeout=httpx.Timeout(self.timeout, connect=5), transport=self.transport) as client:
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
            with httpx.Client(timeout=httpx.Timeout(5, connect=3), transport=self.transport) as client:
                response = client.get(self.base_url + "/health")
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise RuntimeError(f"PLANM agent health unavailable at {self.base_url}: {error}") from error

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
    for label, path in (("input", input_path), ("state", state_path), ("output", output_dir)):
        try:
            path.resolve().relative_to(owned_root)
        except ValueError as error:
            raise ValueError(f"{label} path escapes the owned run root") from error
    request = {
        "contract_version": "planm-stage-request/v1",
        "stage": stage,
        "input_path": str(input_path.resolve()),
        "state_path": str(state_path.resolve()),
        "output_dir": str(output_dir.resolve()),
    }
    validate_planm_contract("planm-stage-request.schema.json", request)
    result = (client or PlanmClient(timeout=timeout_seconds)).post("/planm/stage", request)
    if "error" in result and "contract_version" not in result:
        raise RuntimeError(f"PLANM agent refused the stage request: {result['error']}")
    validate_planm_contract("skill-result.schema.json", result)
    return result
