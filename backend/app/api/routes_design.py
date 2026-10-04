import os
import sqlite3

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from backend.app.api.design_access import DesignAccess
from backend.app.api.routes_execution_artifacts import create_execution_router
from backend.app.api.routes_native_design import create_native_design_router


class DesignAttachment(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    source_id: str = Field(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9_.-]+$')
    job_id: str = Field(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9_-]+$')
    scene_revision: int = Field(ge=0)


class DesignSelection(DesignAttachment):
    result_pk: int = Field(gt=0)


def create_design_router(projects_service, allowed_origin, repository=None, execution_catalog=None, native_design_service=None):
    router = APIRouter(prefix='/projects/{project_id}/design', tags=['design'])
    access = DesignAccess(projects_service, allowed_origin)
    binding, mutate = access.binding, access.mutate

    def store():
        if repository is not None:
            return repository
        from backend.app.modules.design.repository import DesignRepository
        directory = os.environ.get('EDITOR_DESIGN_DATA_DIR')
        if not directory:
            raise HTTPException(503, 'Design storage is not configured')
        return DesignRepository(directory)

    async def read(operation):
        try:
            return await run_in_threadpool(operation)
        except LookupError:
            raise HTTPException(404, 'Design record not found') from None
        except ValueError:
            raise HTTPException(409, 'Design record or binding conflict') from None
        except (OSError, sqlite3.Error):
            raise HTTPException(503, 'Design storage unavailable') from None

    @router.get('/archive/jobs')
    async def archive(project_id: str, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
        binding(project_id)
        return {'items': await read(lambda: store().list_jobs(limit=limit, offset=offset)), 'limit': limit, 'offset': offset}

    @router.get('/jobs')
    async def jobs(project_id: str):
        binding(project_id)
        return {'items': await read(lambda: store().project_jobs('local', project_id))}

    @router.post('/jobs', status_code=201)
    async def attach(project_id: str, body: DesignAttachment, request: Request):
        value = await mutate(project_id, body, request)
        return await read(lambda: store().attach_project('local', project_id, value.scene_id,
            value.scene_revision, body.source_id, body.job_id))

    async def attached(project_id, source_id, job_id):
        binding(project_id)
        jobs = await read(lambda: store().project_jobs('local', project_id))
        if not any(job['source_id'] == source_id and job['job_id'] == job_id for job in jobs):
            raise HTTPException(404, 'Design job not attached to project')

    @router.get('/jobs/{source_id}/{job_id}/results')
    async def results(project_id: str, source_id: str, job_id: str,
                      limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
        await attached(project_id, source_id, job_id)
        return {'items': await read(lambda: store().list_results(source_id, job_id, limit=limit, offset=offset)),
                'limit': limit, 'offset': offset}

    @router.get('/jobs/{source_id}/{job_id}')
    async def job_detail(project_id: str, source_id: str, job_id: str):
        await attached(project_id, source_id, job_id)
        value = await read(lambda: store().get_job(source_id, job_id))
        if value is None:
            raise HTTPException(404, 'Design job not found')
        return value

    @router.get('/jobs/{source_id}/{job_id}/results/{result_pk}')
    async def detail(project_id: str, source_id: str, job_id: str, result_pk: int):
        await attached(project_id, source_id, job_id)
        value = await read(lambda: store().get_result(source_id, job_id, result_pk))
        if value is None:
            raise HTTPException(404, 'Design record not found')
        return value

    @router.get('/selection')
    async def selected(project_id: str):
        binding(project_id)
        return await read(lambda: store().selected_result('local', project_id))

    @router.post('/selection')
    async def select(project_id: str, body: DesignSelection, request: Request):
        await mutate(project_id, body, request)
        return await read(lambda: store().select_result('local', project_id,
            body.source_id, body.job_id, body.result_pk))

    @router.get('/selection/mass')
    async def selected_mass(project_id: str):
        from backend.app.modules.design.mass_bridge import convert_saved_mass, MassBridgeError
        value = await selected(project_id)
        if value is None:
            raise HTTPException(404, 'No saved design selection')
        try:
            mass = await run_in_threadpool(convert_saved_mass, value['data'].get('mass_geojson'),
                project_id=project_id,
                source={key:value[key] for key in ('source_id', 'job_id', 'result_pk', 'row_sha256')})
            return {'mass': mass}
        except MassBridgeError as error:
            raise HTTPException(422, error.code) from None

    combined = APIRouter()
    combined.include_router(router)
    combined.include_router(create_execution_router(projects_service, allowed_origin, execution_catalog))
    combined.include_router(create_native_design_router(projects_service, allowed_origin, native_design_service))
    return combined
