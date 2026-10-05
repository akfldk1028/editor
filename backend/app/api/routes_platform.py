import os

from fastapi import APIRouter, HTTPException, Request

from backend.app.adapters.orchestrator import OrchestratorClient, OwnerContractError, OwnerUnavailable
from backend.app.schemas.platform import AgentSummary
from backend.app.schemas.platform import ProjectBinding, ProjectCreate, SceneRevisionRefresh
from backend.app.adapters.platform_scenes import PlatformScenes
from backend.app.modules.platform.repository import ProjectRepository
from backend.app.modules.platform.projects import ProjectService, BindingConflict, BindingNotFound
from backend.app.api.routes_platform_runs import create_run_router
from backend.app.api.routes_design import create_design_router
from backend.app.api.routes_scene_assets import create_scene_assets_router


def create_platform_router(
    client: OrchestratorClient | None = None, *, project_service=None, public_origin=None,
    design_repository=None, execution_catalog=None, native_design_service=None,
) -> APIRouter:
    owner = client or OrchestratorClient(os.environ.get('EDITOR_ORCHESTRATOR_URL'))
    router = APIRouter(prefix='/api/v1/platform', tags=['platform'])
    allowed_origin = public_origin or os.environ.get('EDITOR_PUBLIC_URL', 'http://127.0.0.1:5173')

    @router.get('/health')
    async def health():
        return {'service': 'editor-platform', 'public_origin': allowed_origin,
                'scene_url': os.environ.get('EDITOR_SCENE_URL'),
                'storage_configured': all(os.environ.get(key) for key in (
                    'EDITOR_PLATFORM_DATA_DIR', 'EDITOR_LAND_DATA_DIR', 'EDITOR_DESIGN_DATA_DIR')),
                'owner_configured': bool(os.environ.get('EDITOR_ORCHESTRATOR_URL'))}

    def projects_service():
        nonlocal project_service
        if project_service is None:
            data_dir = os.environ.get('EDITOR_PLATFORM_DATA_DIR')
            if not data_dir:
                raise HTTPException(503, 'Platform storage is not configured')
            project_service = ProjectService(ProjectRepository(data_dir), owner,
                PlatformScenes(os.environ.get('EDITOR_SCENE_URL')))
        return project_service

    @router.get('/agents', response_model=list[AgentSummary])
    async def agents():
        try:
            return await owner.list_agents()
        except OwnerUnavailable:
            raise HTTPException(503, 'Orchestrator catalog unavailable') from None
        except OwnerContractError:
            raise HTTPException(502, 'Orchestrator catalog contract invalid') from None

    @router.get('/projects', response_model=list[ProjectBinding])
    async def projects():
        return projects_service().repository.list('local')

    @router.get('/projects/{project_id}', response_model=ProjectBinding)
    async def project(project_id: str):
        value = projects_service().repository.get('local', project_id)
        if value is None:
            raise HTTPException(404, 'Project not found')
        return value

    @router.post('/projects', response_model=ProjectBinding, status_code=201)
    async def create_project(body: ProjectCreate, request: Request):
        origin = request.headers.get('origin')
        if request.headers.get('sec-fetch-site') == 'cross-site' or (origin and origin != allowed_origin):
            raise HTTPException(403, 'Cross-origin project changes are not allowed')
        try:
            return await projects_service().create('local', body)
        except BindingConflict:
            raise HTTPException(409, 'Project, branch or scene revision does not match') from None
        except OwnerUnavailable:
            raise HTTPException(503, 'Project source unavailable') from None
        except OwnerContractError:
            raise HTTPException(502, 'Project source contract invalid') from None

    @router.post('/projects/{project_id}/scene-revision', response_model=ProjectBinding)
    async def refresh_scene_revision(project_id: str, body: SceneRevisionRefresh, request: Request):
        origin = request.headers.get('origin')
        if request.headers.get('sec-fetch-site') == 'cross-site' or (origin and origin != allowed_origin):
            raise HTTPException(403, 'Cross-origin project changes are not allowed')
        try:
            return await projects_service().refresh_scene_revision('local', project_id, body)
        except BindingNotFound:
            raise HTTPException(404, 'Project not found') from None
        except BindingConflict:
            raise HTTPException(409, 'Project, branch or scene revision changed; reload before retrying') from None
        except OwnerUnavailable:
            raise HTTPException(503, 'Project source unavailable') from None
        except OwnerContractError:
            raise HTTPException(502, 'Project source contract invalid') from None

    router.include_router(create_run_router(projects_service, owner, allowed_origin))
    router.include_router(create_scene_assets_router())
    router.include_router(create_design_router(projects_service, allowed_origin, design_repository,
                                              execution_catalog, native_design_service))
    return router
