from fastapi import APIRouter, Header, HTTPException, Request

from backend.app.adapters.orchestrator import OwnerUnavailable, OwnerContractError, OwnerRejected
from backend.app.modules.platform.projects import BindingConflict
from backend.app.modules.platform.runs import RunService
from backend.app.schemas.platform import RunCreate


def create_run_router(projects_service, owner, allowed_origin):
    router = APIRouter()

    def service():
        return RunService(projects_service(), owner)

    async def respond(operation, *, submission=False):
        try:
            return await operation
        except LookupError:
            raise HTTPException(404, 'Project or run not found') from None
        except (BindingConflict, OwnerRejected):
            raise HTTPException(409, 'Request identity or source version conflict') from None
        except OwnerUnavailable:
            raise HTTPException(503, 'external_outcome_unknown' if submission else 'Owner unavailable') from None
        except OwnerContractError:
            raise HTTPException(502, 'Invalid owner run contract') from None

    @router.get('/projects/{project_id}/context')
    async def context(project_id: str):
        return await respond(service().context('local', project_id))

    @router.get('/projects/{project_id}/runs')
    async def runs(project_id: str):
        return await respond(service().list('local', project_id))

    @router.get('/runs/{run_id}')
    async def run(run_id: str, project_id: str):
        return await respond(service().get('local', project_id, run_id))

    @router.get('/runs/{run_id}/request')
    async def review_request(run_id: str, project_id: str):
        return await respond(service().review_request('local', project_id, run_id))

    @router.post('/projects/{project_id}/runs', status_code=202)
    async def submit(project_id: str, body: RunCreate, request: Request,
        idempotency_key: str = Header(min_length=1,max_length=128,pattern=r'^[A-Za-z0-9_-]+$')):
        origin = request.headers.get('origin')
        if request.headers.get('sec-fetch-site') == 'cross-site' or (origin and origin != allowed_origin):
            raise HTTPException(403, 'Cross-origin execution is not allowed')
        return await respond(service().submit('local',project_id,idempotency_key,body), submission=True)

    return router
