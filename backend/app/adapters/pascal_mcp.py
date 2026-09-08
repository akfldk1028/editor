"""Thin adapter onto the Pascal MCP server's Streamable HTTP transport.

PLAN never imports Pascal code. It speaks the published MCP tool contract over
HTTP, exactly as any other client would, so the two products stay independent.

Start the far side with:

    bun run backend/mcp/src/bin/pascal-mcp.ts --http --port 3917

and point `PASCAL_MCP_URL` at it. With nothing configured the router still
returns the converted plan; it just does not push it anywhere.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

DEFAULT_TIMEOUT_SECONDS = 60.0


class PascalMcpUnavailable(RuntimeError):
    """The Pascal MCP endpoint is not configured or could not be reached."""


class PascalMcpError(RuntimeError):
    """The Pascal MCP endpoint answered with an error."""


@dataclass(frozen=True)
class PascalMcpSettings:
    url: str
    auth_token: str | None = None
    editor_url: str = "http://localhost:3002"
    timeout: float = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "PascalMcpSettings | None":
        source = env if env is not None else os.environ
        url = source.get("PASCAL_MCP_URL")
        if not url:
            return None
        timeout_raw = source.get("PASCAL_MCP_TIMEOUT")
        return cls(
            url=url,
            auth_token=source.get("PASCAL_MCP_AUTH_TOKEN") or None,
            editor_url=source.get("PASCAL_EDITOR_URL", "http://localhost:3002"),
            timeout=float(timeout_raw) if timeout_raw else DEFAULT_TIMEOUT_SECONDS,
        )


PROTOCOL_VERSION = "2025-06-18"


class PascalMcpClient:
    """Minimal JSON-RPC caller for the handful of tools this bridge needs."""

    def __init__(self, settings: PascalMcpSettings) -> None:
        self._settings = settings
        self._request_id = 0
        self._session_id: str | None = None
        self._initialized = False

    @property
    def editor_url(self) -> str:
        return self._settings.editor_url.rstrip("/")

    def _ensure_session(self) -> None:
        """Run the Streamable HTTP handshake once per client.

        The transport rejects every call with "Server not initialized" until
        `initialize` has run, and subsequent calls must carry the session id it
        hands back.
        """
        if self._initialized:
            return
        self._rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "planm-pascal-bridge", "version": "1.0.0"},
            },
            expect_session=True,
        )
        # Guard on a flag, not on the session id: a server that answers without
        # one would otherwise re-handshake on every single call.
        self._initialized = True
        self._notify("notifications/initialized")

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self._ensure_session()
        payload = self._rpc(
            "tools/call", {"name": name, "arguments": arguments}
        )
        content = payload.get("content") or []
        if payload.get("isError"):
            text = content[0].get("text", "") if content else "unknown error"
            raise PascalMcpError(f"{name}: {text}")
        structured = payload.get("structuredContent")
        if isinstance(structured, dict):
            return structured
        if content and isinstance(content[0], dict) and "text" in content[0]:
            try:
                return json.loads(content[0]["text"])
            except json.JSONDecodeError as error:
                raise PascalMcpError(
                    f"{name}: response was not JSON ({error})"
                ) from error
        return {}

    def _headers(self) -> dict[str, str]:
        headers = {
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
            "mcp-protocol-version": PROTOCOL_VERSION,
        }
        if self._settings.auth_token:
            headers["authorization"] = f"Bearer {self._settings.auth_token}"
        if self._session_id:
            headers["mcp-session-id"] = self._session_id
        return headers

    def _notify(self, method: str) -> None:
        """Fire-and-forget message; the transport answers 202 with no body."""
        body = json.dumps({"jsonrpc": "2.0", "method": method}).encode("utf-8")
        request = urllib.request.Request(
            self._settings.url, data=body, headers=self._headers(), method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=self._settings.timeout):
                pass
        except urllib.error.HTTPError:  # pragma: no cover - notification is advisory
            pass
        except (urllib.error.URLError, OSError) as error:
            raise PascalMcpUnavailable(
                f"could not reach the Pascal MCP server at {self._settings.url}: {error}"
            ) from error

    def _rpc(
        self,
        method: str,
        params: dict[str, Any],
        *,
        expect_session: bool = False,
    ) -> dict[str, Any]:
        self._request_id += 1
        body = json.dumps(
            {"jsonrpc": "2.0", "id": self._request_id, "method": method, "params": params}
        ).encode("utf-8")

        request = urllib.request.Request(
            self._settings.url, data=body, headers=self._headers(), method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=self._settings.timeout) as response:
                raw = response.read().decode("utf-8")
                if expect_session:
                    self._session_id = response.headers.get("mcp-session-id")
        except urllib.error.HTTPError as error:  # pragma: no cover - network shape
            raise PascalMcpError(
                f"{method} failed with HTTP {error.code}: {error.read().decode('utf-8', 'replace')[:400]}"
            ) from error
        except (urllib.error.URLError, OSError) as error:
            raise PascalMcpUnavailable(
                f"could not reach the Pascal MCP server at {self._settings.url}: {error}"
            ) from error

        message = _decode_rpc_body(raw)
        if "error" in message:
            detail = message["error"]
            raise PascalMcpError(
                f"{method}: {detail.get('message', detail)} ({detail.get('code')})"
            )
        result = message.get("result")
        return result if isinstance(result, dict) else {}


def _decode_rpc_body(raw: str) -> dict[str, Any]:
    """Accept both a plain JSON body and a Streamable HTTP `text/event-stream`."""
    text = raw.strip()
    if text.startswith("{"):
        return json.loads(text)
    for line in text.splitlines():
        if line.startswith("data:"):
            candidate = line[len("data:") :].strip()
            if candidate:
                return json.loads(candidate)
    raise PascalMcpError(f"unrecognised MCP response body: {text[:200]}")


__all__ = [
    "PascalMcpClient",
    "PascalMcpError",
    "PascalMcpSettings",
    "PascalMcpUnavailable",
]
