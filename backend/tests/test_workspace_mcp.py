import sys
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.api.routes_workspace import create_workspace_router


def test_real_stdio_mcp_tools_resources_disconnect_and_origin(tmp_path, monkeypatch):
    monkeypatch.setenv("EDITOR_WORKSPACE_DATA_DIR", str(tmp_path))
    server = tmp_path / "mcp_fixture.py"
    server.write_text(
        """from mcp.server.fastmcp import FastMCP
mcp=FastMCP("Native test fixture")
@mcp.tool()
def add(a:int,b:int)->int: return a+b
@mcp.resource("test://note")
def note()->str: return "Native resource"
mcp.run()
""",
        encoding="utf-8",
    )
    app = FastAPI()
    app.include_router(create_workspace_router(public_origin="http://testserver"))
    with TestClient(app) as client:
        body = {
            "server_params": {
                "type": "StdioServerParams",
                "command": sys.executable,
                "args": [str(server)],
            }
        }
        base = "/api/v1/workspace/mcp/connections"
        assert (
            client.post(
                base, headers={"Origin": "https://foreign.invalid"}, json=body
            ).status_code
            == 403
        )
        response = client.post(base, json=body)
        assert response.status_code == 201, response.text
        endpoint = base + "/" + response.json()["connection_id"]
        tools = client.post(endpoint + "/operations", json={"operation": "list_tools"})
        assert tools.status_code == 200, tools.text
        assert tools.json()["data"]["tools"][0]["name"] == "add"
        result = client.post(
            endpoint + "/operations",
            json={
                "operation": "call_tool",
                "tool_name": "add",
                "arguments": {"a": 2, "b": 3},
            },
        )
        assert result.json()["data"]["content"][0]["text"] == "5", result.text
        resource = client.post(
            endpoint + "/operations",
            json={"operation": "read_resource", "uri": "test://note"},
        )
        assert resource.json()["data"]["contents"][0]["text"] == "Native resource"
        assert client.delete(endpoint).status_code == 200
        assert (
            client.post(
                endpoint + "/operations", json={"operation": "list_tools"}
            ).status_code
            == 404
        )


def test_invalid_mcp_transport_is_not_started(tmp_path, monkeypatch):
    monkeypatch.setenv("EDITOR_WORKSPACE_DATA_DIR", str(tmp_path))
    app = FastAPI()
    app.include_router(create_workspace_router(public_origin="http://testserver"))
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/workspace/mcp/connections",
            json={
                "server_params": {
                    "type": "StreamableHttpServerParams",
                    "url": "file:///secret",
                }
            },
        )
        assert response.status_code == 422
