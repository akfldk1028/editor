"""Original design workspace contracts backed by Editor-owned land services."""
import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from shapely.geometry import shape
from starlette.concurrency import run_in_threadpool

from backend.app.adapters.vworld import VworldClient
from backend.app.modules.land.parcel_geometry import parcel_geometry
from backend.app.modules.land.projection import wgs84_to_utm
from backend.app.modules.design.artifacts import ArtifactArchiveError
from backend.app.modules.design.workspace_archive import WorkspaceArchive


class BoundaryRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    pnu: str = Field(min_length=1, max_length=500)


def create_design_workspace_router(*, public_origin=None, address_client=None):
    router = APIRouter(prefix='/api/v1/design', tags=['design-workspace'])
    origin = public_origin or os.environ.get('EDITOR_PUBLIC_URL', 'http://127.0.0.1:5173')
    addresses = address_client or VworldClient(os.environ.get('VWORLD_API_KEY', ''))

    @router.post('/site-boundary')
    async def boundary(body: BoundaryRequest, request: Request):
        if request.headers.get('sec-fetch-site') == 'cross-site' or (
            request.headers.get('origin') and request.headers['origin'] != origin
        ):
            raise HTTPException(403, 'Cross-origin changes are not allowed')
        pnu = body.pnu.strip()
        if not (len(pnu) == 19 and pnu.isascii() and pnu.isdigit()):
            resolved = await addresses.resolve_address(pnu)
            if not resolved.get('success') or not resolved.get('pnu'):
                raise HTTPException(404, '주소에 해당하는 필지를 찾지 못했습니다.')
            pnu = resolved['pnu']
        result = await addresses.fetch_parcel_geometry(pnu)
        if not result.get('success') or not result.get('geometry'):
            raise HTTPException(404, '필지 경계를 찾지 못했습니다.')
        try:
            geometry = parcel_geometry(result['geometry'], largest=True)
            area = wgs84_to_utm(shape(geometry)).area
        except (ValueError, TypeError, KeyError):
            raise HTTPException(422, '필지 경계가 올바르지 않습니다.') from None
        return {'pnu': pnu, 'geometry': geometry, 'area_m2': area,
                'valid': area > 0, 'errors': [], 'execution_owner': 'editor'}

    @router.get('/maas/language-system')
    def language_system():
        path = Path(__file__).resolve().parents[1] / 'modules/design/data/language-system.json'
        return json.loads(path.read_text(encoding='utf-8'))

    def archive():
        directory = os.environ.get('EDITOR_DESIGN_DATA_DIR')
        if not directory:
            raise HTTPException(503, 'Design storage is not configured')
        return WorkspaceArchive(directory)

    async def read_archive(operation):
        try:
            return await run_in_threadpool(operation)
        except LookupError:
            raise HTTPException(404, 'Archived design evidence not found') from None
        except (ArtifactArchiveError, OSError, ValueError):
            raise HTTPException(503, 'Archived design evidence is unavailable or inconsistent') from None

    @router.get('/maas/executed-masses')
    async def masses(run_id: str | None = Query(None, max_length=200)):
        return await read_archive(lambda: archive().manifest(run_id))

    @router.get('/maas/executed-masses/{index}/passport')
    async def passport(index: int, run_id: str = Query(..., min_length=1, max_length=200)):
        return await read_archive(lambda: archive().passport(run_id, index))

    @router.get('/maas/executed-masses/{index}')
    async def preview(index: int, run_id: str = Query(..., min_length=1, max_length=200)):
        path = await read_archive(lambda: archive().preview(run_id, index))
        return FileResponse(path, media_type='image/png', headers={'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store'})

    return router
