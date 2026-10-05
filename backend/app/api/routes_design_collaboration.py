"""Design collaboration contracts over the existing shared-agent owner boundary."""
import os
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from backend.app.adapters.orchestrator import OrchestratorClient, OwnerContractError, OwnerUnavailable
from backend.app.adapters.platform_scenes import PlatformScenes
from backend.app.modules.design.collaboration import recorded_bus_events, recorded_transcript
from backend.app.modules.platform.projects import ProjectService
from backend.app.modules.platform.repository import ProjectRepository
from backend.app.modules.platform.runs import RunService


class CollaborationMessage(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    from_agent: str = Field(min_length=1, max_length=200)
    to_agent: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=8000)
    event_type: str | None = Field(default=None, max_length=200)
    metadata: dict = Field(default_factory=dict)
    project_id: str | None = Field(default=None, min_length=1, max_length=200)
    run_id: str | None = Field(default=None, min_length=1, max_length=200)


def create_design_collaboration_router(client=None, *, project_service=None, public_origin=None):
    owner = client or OrchestratorClient(os.environ.get('EDITOR_ORCHESTRATOR_URL'))
    origin = public_origin or os.environ.get('EDITOR_PUBLIC_URL', 'http://127.0.0.1:5173')
    router = APIRouter(prefix='/api/v1/design/collaboration', tags=['design-collaboration'])

    def projects():
        nonlocal project_service
        if project_service is None:
            directory = os.environ.get('EDITOR_PLATFORM_DATA_DIR')
            if not directory:
                raise HTTPException(503, 'Platform storage is not configured')
            project_service = ProjectService(ProjectRepository(directory), owner,
                                            PlatformScenes(os.environ.get('EDITOR_SCENE_URL')))
        return project_service

    async def respond(operation):
        try:
            return await operation()
        except LookupError:
            raise HTTPException(404, 'Project or run not found') from None
        except OwnerUnavailable:
            raise HTTPException(503, 'Orchestrator collaboration unavailable') from None
        except OwnerContractError:
            raise HTTPException(502, 'Invalid Orchestrator collaboration contract') from None
        except (OSError, sqlite3.Error):
            raise HTTPException(503, 'Platform storage unavailable') from None

    async def transcript_for(project_id, run_id):
        if not all(isinstance(value, str) and value.strip() and len(value) <= 200 for value in (project_id, run_id)):
            raise HTTPException(400, detail=dict(code='collaboration_context_required',
                                                message='Select an Editor project and run before reading or sending collaboration messages.'))
        run = await respond(lambda: RunService(projects(), owner).get('local', project_id, run_id))
        return recorded_transcript(project_id, run)

    @router.get('/health')
    async def health():
        agents = await respond(owner.list_agents)
        return dict(service='editor-design-collaboration', status=True,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    components={'bus': {'connected_agents': [agent.agent_id for agent in agents
                                                            if agent.connection_status == 'available']}},
                    agents=[agent.model_dump() for agent in agents],
                    source='orchestrator_agent_observations', direct_message_supported=False,
                    communications_scope='project_run')

    @router.get('/transcript')
    async def transcript(project_id: str | None = Query(None, max_length=200),
                         run_id: str | None = Query(None, max_length=200)):
        return await transcript_for(project_id, run_id)

    @router.get('/bus/log')
    async def bus_log(project_id: str | None = Query(None, max_length=200),
                      run_id: str | None = Query(None, max_length=200),
                      limit: int = Query(50, ge=1, le=200)):
        value = await transcript_for(project_id, run_id)
        if not value['available']:
            raise HTTPException(503, 'Recorded communications are unavailable for this run')
        return recorded_bus_events(value, limit)

    @router.post('/bus/send')
    async def send(body: CollaborationMessage, request: Request):
        if request.headers.get('sec-fetch-site') == 'cross-site' or (
            request.headers.get('origin') and request.headers['origin'] != origin
        ):
            raise HTTPException(403, 'Cross-origin collaboration changes are not allowed')
        await transcript_for(body.project_id or body.metadata.get('project_id'),
                             body.run_id or body.metadata.get('run_id'))
        # The shared owner's Editor gateway currently accepts only health-template runs.
        # A log write must not masquerade as dispatch to a specialist agent.
        raise HTTPException(409, detail=dict(code='direct_agent_message_unsupported',
                                            message='The shared Orchestrator does not expose direct agent message dispatch. No message was sent.'))

    return router
