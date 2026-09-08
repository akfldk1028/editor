"""Product route: publish an approved PLANM alternative into the Pascal editor."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend.app.adapters.pascal_mcp import (
    PascalMcpClient,
    PascalMcpError,
    PascalMcpSettings,
    PascalMcpUnavailable,
)
from backend.app.modules.pascal_bridge.service import (
    PascalBridgeError,
    build_plan,
    publish_to_pascal,
)
from backend.app.modules.planm_runs import PlanmRunNotFound, PlanmRunService

CONTRACT_VERSION = "planm-pascal-publish/v1"


class PascalPublishRequest(BaseModel):
    contract_version: str = Field(default=CONTRACT_VERSION)
    alternative_id: str | None = Field(
        default=None,
        description="Defaults to the run's approved alternative.",
    )
    scene_name: str | None = None
    furnish: bool = True
    level_height: float | None = Field(default=None, gt=0)
    dry_run: bool = False
    plan_only: bool = Field(
        default=False,
        description="Return the converted plan without contacting Pascal.",
    )


def create_pascal_router(
    service: PlanmRunService,
    *,
    settings_factory: Callable[[], PascalMcpSettings | None] = PascalMcpSettings.from_env,
    client_factory: Callable[[PascalMcpSettings], Any] = PascalMcpClient,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/planm/runs", tags=["pascal"])

    @router.post("/{run_id}/pascal", status_code=status.HTTP_201_CREATED)
    def publish(run_id: str, request: PascalPublishRequest) -> dict:
        try:
            record = service.get(run_id)
        except PlanmRunNotFound as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error

        alternative_id = request.alternative_id or record.get("approved_alternative_id")
        if not alternative_id:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "the run has no approved alternative; approve one or name alternative_id",
            )

        run_dir = service.run_dir(run_id)
        try:
            conversion = build_plan(
                run_dir,
                alternative_id,
                furnish=request.furnish,
                level_height=request.level_height,
                plan_name=request.scene_name,
            )
        except PascalBridgeError as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error

        response: dict[str, Any] = {
            "contract_version": CONTRACT_VERSION,
            "run_id": run_id,
            "alternative_id": alternative_id,
            "plan": conversion.plan,
            "conversion_warnings": conversion.warnings,
            "unplaced_openings": conversion.unplaced_openings,
        }

        if request.plan_only:
            response["published"] = False
            return response

        settings = settings_factory()
        if settings is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "PASCAL_MCP_URL is not set, so there is nowhere to publish. "
                "Start the Pascal MCP server with --http and set it, or call with "
                "plan_only=true to get the converted plan.",
            )

        try:
            published = publish_to_pascal(
                client_factory(settings),
                conversion.plan,
                scene_name=request.scene_name or f"{alternative_id} ({run_id})",
                dry_run=request.dry_run,
            )
        except PascalMcpUnavailable as error:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error)) from error
        except PascalMcpError as error:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error

        response["published"] = not request.dry_run
        # `published` carries the plan as actually applied — the same conversion
        # with the target level filled in — so it deliberately replaces the
        # pre-publish copy above. A dry run returns no plan, leaving that copy.
        response.update(published)
        return response

    return router


__all__ = ["CONTRACT_VERSION", "PascalPublishRequest", "create_pascal_router"]
