import os
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from backend.app.schemas.workspace import SettingsUpdate

from backend.app.modules.workspace.settings import SettingsConflict, SettingsRepository
from backend.app.api.routes_workspace_catalog import create_catalog_router


def create_workspace_router(*, public_origin=None):
    origin = public_origin or os.environ.get('EDITOR_PUBLIC_URL', 'http://127.0.0.1:5173')

    def same_origin(request: Request, response: Response):
        response.headers['Cache-Control'] = 'no-store'
        if request.headers.get('sec-fetch-site') == 'cross-site' or (request.headers.get('origin') and request.headers['origin'] != origin):
            raise HTTPException(403, 'Cross-origin workspace access is not allowed')

    router = APIRouter(prefix='/api/v1/workspace', tags=['workspace'], dependencies=[Depends(same_origin)])

    def directory():
        storage_root = os.environ.get('EDITOR_WORKSPACE_DATA_DIR')
        if not storage_root:
            platform = os.environ.get('EDITOR_PLATFORM_DATA_DIR')
            if not platform:
                raise HTTPException(503, 'Workspace storage is not configured')
            storage_root = Path(platform) / 'workspace'
        return storage_root

    def settings():
        return SettingsRepository(directory())

    @router.get('/settings')
    def get_settings():
        try:
            return settings().get()
        except (sqlite3.Error, OSError):
            raise HTTPException(503, 'Workspace storage is unavailable') from None

    @router.put('/settings')
    def update_settings(body: SettingsUpdate):
        try:
            return settings().update(body.version, body.config.model_dump(exclude_none=True))
        except SettingsConflict as error:
            raise HTTPException(409, str(error)) from None
        except (sqlite3.Error, OSError):
            raise HTTPException(503, 'Workspace storage is unavailable') from None

    @router.get('/health')
    def health():
        return {'status': True, 'service': 'editor-workspace'}

    @router.get('/version')
    def version():
        return {'version': '1.0.0', 'service': 'editor-workspace'}

    router.include_router(create_catalog_router(directory))
    return router
