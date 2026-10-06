import os
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from backend.app.modules.design.dependencies import DesignAccess


class NativeJobCreate(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    request_id: str = Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9._:-]*$')
    scene_revision: int = Field(ge=0)
    payload: dict


class ExecutionRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    request_id: str = Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9._:-]*$')
    scene_revision: int = Field(ge=0)
    seed: int = Field(ge=0, lt=2**64)
    unverified_search: bool


class CancelRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    scene_revision: int = Field(ge=0)


def create_native_design_router(projects_service, allowed_origin, service=None):
    router = APIRouter(prefix='/projects/{project_id}/design/native-jobs', tags=['native-design'])
    access = DesignAccess(projects_service, allowed_origin)

    def store():
        if service is not None:
            return service
        from backend.app.modules.design.native_service import NativeDesignService
        directory = os.environ.get('EDITOR_DESIGN_DATA_DIR')
        if not directory:
            raise HTTPException(503, 'Design storage is not configured')
        return NativeDesignService(directory)

    async def operation(callback):
        from backend.app.modules.design.job_spec import JobSpecError
        from backend.app.modules.design.native_service import NativeJobConflict, NativeJobUnavailable
        from backend.app.modules.design.execution import ExecutionConflict
        try:
            return await run_in_threadpool(callback)
        except JobSpecError as error:
            raise HTTPException(422, {'code': error.code, 'message': str(error)}) from None
        except ValueError:
            raise HTTPException(422, {'code': 'invalid_input', 'message': 'Input exceeds supported JSON limits or contains invalid values'}) from None
        except (NativeJobConflict, ExecutionConflict):
            raise HTTPException(409, 'Request identity already has different inputs or scene binding') from None
        except LookupError:
            raise HTTPException(404, 'Design execution resource not found') from None
        except (NativeJobUnavailable, OSError):
            raise HTTPException(503, 'Native design storage unavailable') from None

    @router.get('')
    async def jobs(project_id: str, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
        access.binding(project_id)
        return {'items': await operation(lambda: store().list_jobs('local', project_id, limit=limit, offset=offset)),
                'limit': limit, 'offset': offset}

    @router.post('', status_code=201)
    async def create(project_id: str, body: NativeJobCreate, request: Request):
        binding = await access.mutate(project_id, body, request)
        return await operation(lambda: store().create('local', project_id, binding.scene_id,
            binding.scene_revision, body.request_id, body.payload))

    @router.get('/{job_id}')
    async def detail(project_id: str, job_id: Annotated[str, Path(pattern=r'^[a-f0-9]{32}$')]):
        access.binding(project_id)
        job = await operation(lambda: store().get_job('local', project_id, job_id))
        if job is None:
            raise HTTPException(404, 'Native design job not found')
        return job

    def executions():
        from backend.app.modules.design.execution import ExecutionService
        return ExecutionService(store().repository.path.parent)

    def attempt_store(project_id,job_id,attempt_id):
        execution=executions()
        attempt=execution.get('local',project_id,attempt_id)
        if attempt is None or attempt['job_id']!=job_id:
            raise LookupError('Attempt not found')
        return execution

    @router.post('/{job_id}/attempts', status_code=202)
    async def execute(project_id: str, job_id: Annotated[str, Path(pattern=r'^[a-f0-9]{32}$')], body: ExecutionRequest, request: Request):
        await access.mutate(project_id,body,request)
        return await operation(lambda:executions().enqueue('local',project_id,job_id,
            body.request_id,body.seed,body.scene_revision,body.unverified_search))

    @router.get('/{job_id}/attempts')
    async def attempts(project_id: str, job_id: Annotated[str, Path(pattern=r'^[a-f0-9]{32}$')],
                       limit: int=Query(20,ge=1,le=100),offset: int=Query(0,ge=0,lt=2**63)):
        access.binding(project_id)
        await detail(project_id,job_id)
        return {'items':await operation(lambda:executions().store.list('local',project_id,job_id,limit,offset)),
                'limit':limit,'offset':offset}

    @router.get('/{job_id}/attempts/{attempt_id}')
    async def attempt(project_id: str, job_id: str, attempt_id: Annotated[str, Path(pattern=r'^[a-f0-9]{32}$')]):
        access.binding(project_id)
        return await operation(lambda:attempt_store(project_id,job_id,attempt_id).get('local',project_id,attempt_id))

    @router.get('/{job_id}/attempts/{attempt_id}/events')
    async def events(project_id: str,job_id: str,attempt_id: str,after: int=Query(0,ge=0,lt=2**63)):
        access.binding(project_id)
        return {'items':await operation(lambda:attempt_store(project_id,job_id,attempt_id).events('local',project_id,attempt_id,after))}

    @router.get('/{job_id}/attempts/{attempt_id}/result')
    async def result(project_id: str,job_id: str,attempt_id: str):
        access.binding(project_id)
        return await operation(lambda:attempt_store(project_id,job_id,attempt_id).result('local',project_id,attempt_id))

    @router.post('/{job_id}/attempts/{attempt_id}/cancel')
    async def cancel(project_id: str,job_id: str,attempt_id: str,body: CancelRequest,request: Request):
        await access.mutate(project_id,body,request)
        return await operation(lambda:attempt_store(project_id,job_id,attempt_id).cancel('local',project_id,attempt_id))

    return router
