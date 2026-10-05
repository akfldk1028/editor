from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from backend.app.api.routes_pascal import create_pascal_router
from backend.app.api.routes_platform import create_platform_router
from backend.app.api.routes_land import create_land_router
from backend.app.api.routes_law import create_law_router
from backend.app.api.routes_design_workspace import create_design_workspace_router
from backend.app.api.routes_design_runtime import create_design_runtime_router
from backend.app.api.routes_design_collaboration import create_design_collaboration_router
from backend.app.api.routes_workspace import create_workspace_router
from backend.app.adapters.orchestrator import OrchestratorClient
from backend.app.modules.platform.projects import ProjectService
from backend.app.api.routes_planm_runs import create_planm_runs_router
from backend.app.modules.generation_loop.service import run_generation_loop
from backend.app.modules.planm_runs import PlanmRunService


def create_app(
    *,
    repository_root: Path | None = None,
    runs_root: Path | None = None,
    execute_inline: bool = False,
    platform_client: OrchestratorClient | None = None,
    platform_projects: ProjectService | None = None,
    platform_public_origin: str | None = None,
) -> FastAPI:
    configured_root = os.environ.get("PLANM_REPOSITORY_ROOT")
    root = (
        repository_root
        or (Path(configured_root) if configured_root else Path(__file__).resolve().parents[2])
    ).resolve()
    configured_runs_root = os.environ.get("PLANM_RUNS_ROOT")
    service = PlanmRunService(
        repository_root=root,
        runs_root=(
            runs_root
            or (Path(configured_runs_root) if configured_runs_root else root / "logs" / "runs" / "planm-api")
        ),
    )
    application = FastAPI(title="PLANM API", version="1.0.0")
    application.include_router(
        create_planm_runs_router(service, execute_inline=execute_inline)
    )
    application.include_router(create_pascal_router(service))
    application.include_router(create_platform_router(platform_client, project_service=platform_projects,
        public_origin=platform_public_origin))
    application.include_router(create_land_router(public_origin=platform_public_origin))
    application.include_router(create_law_router(public_origin=platform_public_origin))
    application.include_router(create_design_workspace_router(public_origin=platform_public_origin))
    application.include_router(create_design_collaboration_router(platform_client,
        project_service=platform_projects, public_origin=platform_public_origin))
    application.include_router(create_design_runtime_router(public_origin=platform_public_origin))
    application.include_router(create_workspace_router(public_origin=platform_public_origin))
    application.state.planm_runs = service
    return application


app = create_app()

__all__ = ["app", "create_app", "run_generation_loop"]
