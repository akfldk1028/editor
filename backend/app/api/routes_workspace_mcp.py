from contextlib import asynccontextmanager
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from backend.app.modules.workspace.mcp_connections import McpConnections


class McpConnect(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    server_params: dict


class McpOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    operation: Literal["list_tools", "call_tool", "list_resources", "read_resource"]
    tool_name: str | None = Field(default=None, max_length=500)
    arguments: dict = Field(default_factory=dict)
    uri: str | None = Field(default=None, max_length=4096)

    @model_validator(mode="after")
    def required_parameters(self):
        if self.operation == "call_tool" and not self.tool_name:
            raise ValueError("Tool name is required")
        if self.operation == "read_resource" and not self.uri:
            raise ValueError("Resource URI is required")
        return self


def create_mcp_router():
    service = McpConnections()

    @asynccontextmanager
    async def lifespan(app):
        yield
        await service.close()

    router = APIRouter(prefix="/mcp/connections", lifespan=lifespan)

    async def call(operation):
        try:
            return await operation
        except LookupError as error:
            raise HTTPException(404, str(error)) from None
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        except (RuntimeError, TimeoutError):
            raise HTTPException(
                502, "MCP connection failed or timed out; reconnect before retrying"
            ) from None

    @router.post("", status_code=201)
    async def connect(body: McpConnect):
        return await call(service.connect(body.server_params))

    @router.post("/{identifier}/operations")
    async def operation(identifier: str, body: McpOperation):
        return await call(
            service.operation(identifier, body.model_dump(exclude_none=True))
        )

    @router.delete("/{identifier}")
    async def disconnect(identifier: str):
        await call(service.disconnect(identifier))
        return {"disconnected": True}

    return router
