from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from fastapi.responses import FileResponse

from backend.app.modules.planm_runs import (
    PlanmRunConflict,
    PlanmRunNotFound,
    PlanmRunService,
)
from backend.app.schemas.planm_run import PlanmApprovalRequest, PlanmRunCreateRequest
from backend.app.schemas.dwg import DwgInspectionRequest


def create_planm_runs_router(
    service: PlanmRunService,
    *,
    execute_inline: bool,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/planm/runs", tags=["planm-runs"])

    @router.post("", status_code=status.HTTP_201_CREATED)
    def create_run(
        request: PlanmRunCreateRequest,
        background_tasks: BackgroundTasks,
    ) -> dict:
        record = service.create(request.mass)
        if execute_inline:
            return service.execute(record["run_id"])
        background_tasks.add_task(service.execute, record["run_id"])
        return record

    @router.get("/{run_id}")
    def get_run(run_id: str) -> dict:
        return _translate_errors(lambda: service.get(run_id))

    @router.get("/{run_id}/alternatives")
    def get_alternatives(run_id: str) -> dict:
        return _translate_errors(lambda: service.alternatives(run_id))

    @router.get("/{run_id}/alternatives/{alternative_id}/preview")
    def get_alternative_preview(run_id: str, alternative_id: str) -> FileResponse:
        path = _translate_errors(lambda: service.preview(run_id, alternative_id))
        return FileResponse(path, media_type="image/png")

    @router.post("/{run_id}/approval")
    def approve(run_id: str, request: PlanmApprovalRequest) -> dict:
        return _translate_errors(
            lambda: service.approve(run_id, request.alternative_id)
        )

    @router.post("/{run_id}/dwg/handoff", status_code=status.HTTP_201_CREATED)
    def create_dwg_handoff(run_id: str) -> dict:
        return _translate_errors(lambda: service.create_dwg_handoff(run_id))

    @router.post("/{run_id}/dwg/inspection")
    def inspect_dwg_handoff(run_id: str, request: DwgInspectionRequest) -> dict:
        return _translate_errors(
            lambda: service.inspect_dwg_handoff(run_id, request.layer)
        )

    @router.get("/{run_id}/artifacts/{artifact_path:path}")
    def download_artifact(run_id: str, artifact_path: str) -> FileResponse:
        path = _translate_errors(lambda: service.artifact(run_id, artifact_path))
        return FileResponse(path)

    return router


def _translate_errors(operation):
    try:
        return operation()
    except PlanmRunNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PlanmRunConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
