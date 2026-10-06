"""What an MCP server-parameter document may say, checked before anything connects.

Shared by the interactive MCP explorer (modules/workspace/mcp_connections.py) and the
template tool policy (adapters/workspace/tool_policy.py); pure validation, no I/O.
"""
import json
from urllib.parse import urlsplit


def validate_params(params):
    if len(json.dumps(params)) > 64000:
        raise ValueError("MCP configuration is too large")
    kind = params.get("type")
    if kind == "StdioServerParams":
        if not isinstance(params.get("command"), str) or not params["command"].strip():
            raise ValueError("MCP command is required")
        if not isinstance(params.get("args", []), list) or not all(
            isinstance(x, str) for x in params.get("args", [])
        ):
            raise ValueError("MCP args must be strings")
    elif kind in ("SseServerParams", "StreamableHttpServerParams"):
        if not isinstance(params.get("url"), str):
            raise ValueError("MCP URL must be a string")
        url = urlsplit(params.get("url", ""))
        if (
            url.scheme not in ("http", "https")
            or not url.hostname
            or url.username
            or url.password
        ):
            raise ValueError("MCP requires an HTTP(S) URL without embedded credentials")
    else:
        raise ValueError("Unsupported MCP transport")
    for name in ("env", "headers"):
        if name in params and (
            not isinstance(params[name], dict)
            or not all(
                isinstance(k, str) and isinstance(v, str)
                for k, v in params[name].items()
            )
        ):
            raise ValueError(f"MCP {name} must contain strings")
