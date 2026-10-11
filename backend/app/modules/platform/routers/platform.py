import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from backend.app.adapters.orchestrator import OrchestratorClient, OwnerContractError, OwnerUnavailable
from backend.app.schemas.platform import AgentSummary
from backend.app.schemas.platform import ProjectBinding, ProjectCreate, SceneRevisionRefresh
from backend.app.adapters.platform_scenes import PlatformScenes
from backend.app.modules.platform.repository import ProjectRepository
from backend.app.modules.platform.projects import ProjectService, BindingConflict, BindingNotFound
from backend.app.modules.platform.routers.ask import create_ask_router
from backend.app.modules.platform.routers.conversation import create_conversation_router
from backend.app.modules.platform.routers.host import create_host_router
from backend.app.modules.platform.routers.runs import create_run_router
from backend.app.modules.design.routers.projects import create_design_router
from backend.app.modules.platform.routers.scene_assets import create_scene_assets_router
from backend.app.modules.platform.routers.status import create_status_router


def create_platform_router(
    client: OrchestratorClient | None = None, *, project_service=None, public_origin=None,
    design_repository=None, execution_catalog=None, native_design_service=None, status_service=None,
    trace_recorder=None, conversation_activation=None,
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
        # Without the Orchestrator the answer is still a shape, not a bare string: the status
        # artifact and the agents page both read `orchestrator.state`.
        try:
            return await owner.list_agents()
        except OwnerUnavailable:
            return JSONResponse({'agents': [], 'orchestrator': {'state': 'down', 'error': 'Orchestrator catalog unavailable'}},
                                status_code=503)
        except OwnerContractError:
            return JSONResponse({'agents': [], 'orchestrator': {'state': 'invalid', 'error': 'Orchestrator catalog contract invalid'}},
                                status_code=502)

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

    router.include_router(create_run_router(projects_service, owner, allowed_origin, trace_recorder))
    router.include_router(create_conversation_router(projects_service, owner, allowed_origin, conversation_activation))
    router.include_router(create_ask_router(allowed_origin, trace_recorder, owner=owner))
    router.include_router(create_host_router(allowed_origin))
    router.include_router(create_status_router(owner, status_service))
    router.include_router(create_scene_assets_router())
    router.include_router(create_design_router(projects_service, allowed_origin, design_repository,
                                              execution_catalog, native_design_service))
    return router
