import sqlite3
from contextlib import asynccontextmanager

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from backend.app.modules.workspace.execution import WorkspaceExecution
from backend.app.modules.workspace.execution_repository import ExecutionConflict
from backend.app.adapters.workspace.team import SUPPORTED_PROVIDERS
from backend.app.adapters.workspace.tool_policy import (
    CONTAINER_PROVIDERS,
    EDITOR_TOOL_PROVIDERS,
    MCP_PROVIDERS,
)


class ExecutionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    session_id: int = Field(gt=0)


class Attachment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=255)
    type: str = Field(min_length=1, max_length=200)
    content: str = Field(max_length=12 * 1024 * 1024)


class ExecutionStart(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    task: str = Field(min_length=1, max_length=100000)
    files: list[Attachment] = Field(default_factory=list, max_length=8)


class ExecutionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    response: str = Field(min_length=1, max_length=100000)


def create_execution_router(directory, environment):
    service = WorkspaceExecution(directory)

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            await service.close()

    router = APIRouter(prefix="/runs", lifespan=lifespan)

    @router.get("/capabilities")
    async def capabilities():
        return {
            "execution_mode": "single_worker",
            "supported_providers": sorted(SUPPORTED_PROVIDERS),
            "template_code_execution": False,
            "template_mcp_execution": "http_only",
            "template_mcp_providers": sorted(MCP_PROVIDERS),
            "template_tools": sorted(EDITOR_TOOL_PROVIDERS),
            "template_workbenches": sorted(CONTAINER_PROVIDERS),
        }

    def call(operation):
        try:
            return operation()
        except LookupError:
            raise HTTPException(404, "Session or run not found") from None
        except ExecutionConflict as error:
            raise HTTPException(409, str(error)) from None
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        except (sqlite3.Error, OSError):
            raise HTTPException(503, "Execution storage is unavailable") from None

    @router.post("", status_code=201)
    async def create(body: ExecutionCreate):
        return call(lambda: service.repository().create_run(body.session_id))

    @router.get("/{identifier}/events")
    async def events(identifier: str, after: int = Query(default=0, ge=0)):
        return call(lambda: service.repository().events(identifier, after))

    @router.post("/{identifier}/start", status_code=202)
    async def start(identifier: str, body: ExecutionStart):
        call(
            lambda: service.start(
                identifier,
                body.task,
                [item.model_dump() for item in body.files],
                environment(),
            )
        )
        return {"run_id": identifier, "status": "active"}

    @router.post("/{identifier}/input")
    async def user_input(identifier: str, body: ExecutionInput):
        call(lambda: service.input(identifier, body.response))
        return {"accepted": True}

    @router.post("/{identifier}/stop")
    async def stop(identifier: str):
        call(lambda: service.stop(identifier))
        return {"accepted": True}

    return router
