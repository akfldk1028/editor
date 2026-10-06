import os
import sqlite3
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from backend.app.modules.design.dependencies import DesignAccess


Identifier = Annotated[str, Path(pattern=r'^[a-f0-9]{64}$')]


class ExecutionAttachment(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    catalog_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    scene_revision: int = Field(ge=0)


def create_execution_router(projects_service, allowed_origin, catalog=None):
    router = APIRouter(prefix='/projects/{project_id}/design', tags=['design-executions'])
    access = DesignAccess(projects_service, allowed_origin)

    def store():
        if catalog is not None:
            return catalog
        from backend.app.modules.design.execution_catalog import ExecutionCatalog
        directory = os.environ.get('EDITOR_DESIGN_DATA_DIR')
        if not directory:
            raise HTTPException(503, 'Design storage is not configured')
        return ExecutionCatalog(directory)

    async def read(operation):
        from backend.app.modules.design.execution_catalog import CatalogUnavailable
        try:
            return await run_in_threadpool(operation)
        except LookupError:
            raise HTTPException(404, 'Execution artifact not found') from None
        except CatalogUnavailable:
            raise HTTPException(503, 'Execution archive unavailable') from None
        except ValueError:
            raise HTTPException(409, 'Execution attachment conflict') from None
        except (OSError, sqlite3.Error):
            raise HTTPException(503, 'Execution storage unavailable') from None

    async def attached(project_id, catalog_id):
        access.binding(project_id)
        if not await read(lambda: store().is_attached('local', project_id, catalog_id)):
            raise HTTPException(404, 'Execution not attached to project')

    @router.get('/archive/executions')
    async def archive(project_id: str, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
        access.binding(project_id)
        return {'items': await read(lambda: store().list_executions(limit=limit, offset=offset)),
                'limit': limit, 'offset': offset}

    @router.get('/executions')
    async def executions(project_id: str, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
        access.binding(project_id)
        return {'items': await read(lambda: store().project_executions('local', project_id, limit=limit, offset=offset)),
                'limit': limit, 'offset': offset}

    @router.post('/executions', status_code=201)
    async def attach(project_id: str, body: ExecutionAttachment, request: Request):
        binding = await access.mutate(project_id, body, request)
        return await read(lambda: store().attach('local', project_id, binding.scene_id,
                                                binding.scene_revision, body.catalog_id))

    @router.get('/executions/{catalog_id}')
    async def detail(project_id: str, catalog_id: Identifier,
                     limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
        await attached(project_id, catalog_id)
        value = await read(lambda: store().get_execution(catalog_id))
        if value is None:
            raise HTTPException(404, 'Execution not found')
        return {'execution': value,
                'items': await read(lambda: store().artifacts(catalog_id, limit=limit, offset=offset)),
                'limit': limit, 'offset': offset}

    async def artifact_response(project_id, catalog_id, artifact_id, download):
        await attached(project_id, catalog_id)
        path, metadata = await read(lambda: store().resolve_artifact(catalog_id, artifact_id))
        mime = metadata['media_type']
        if mime not in ('image/png', 'application/json') or (not download and (mime != 'image/png' or not metadata['inline'])):
            raise HTTPException(404, 'Artifact is not available for inline display')
        suffix = 'png' if mime == 'image/png' else 'json'
        headers = {'ETag': '"' + metadata['sha256'] + '"', 'X-Content-Type-Options': 'nosniff',
                   'Cache-Control': 'private, max-age=31536000, immutable'}
        return FileResponse(path, media_type=mime, headers=headers,
                            filename=f'{artifact_id}.{suffix}' if download else None)

    @router.get('/executions/{catalog_id}/artifacts/{artifact_id}')
    async def preview(project_id: str, catalog_id: Identifier, artifact_id: Identifier):
        return await artifact_response(project_id, catalog_id, artifact_id, False)

    @router.get('/executions/{catalog_id}/artifacts/{artifact_id}/download')
    async def download(project_id: str, catalog_id: Identifier, artifact_id: Identifier):
        return await artifact_response(project_id, catalog_id, artifact_id, True)

    return router
