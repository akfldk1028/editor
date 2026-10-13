from fastapi import APIRouter, Header, HTTPException, Request

from backend.app.adapters.orchestrator import OwnerUnavailable, OwnerContractError, OwnerRejected
from backend.app.core.tracing import JsonlTraceRecorder
from backend.app.modules.platform.projects import BindingConflict
from backend.app.modules.platform.runs import RunService
from backend.app.schemas.platform import RunCreate, RunResume
from backend.app.schemas.site_run import PNU


def create_run_router(projects_service, owner, allowed_origin, trace_recorder=None, ledger=None):
    router = APIRouter()
    # Submissions record their span here; the trace route reads the same recorder.
    recorder = trace_recorder or JsonlTraceRecorder()

    def service():
        return RunService(projects_service(), owner, recorder, ledger)

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

    @router.get('/projects/{project_id}/runs/latest')
    async def latest_run(project_id: str, goal: str = 'limits', pnu: str | None = None):
        """The newest run of `goal`, for `pnu` when given (run_results.parse shape under `results`)."""
        if pnu is not None and not PNU.fullmatch(pnu):
            raise HTTPException(422, 'PNU requires 19 digits')
        return await respond(service().latest('local', project_id, goal, pnu))

    @router.get('/runs/{run_id}')
    async def run(run_id: str, project_id: str):
        return await respond(service().get('local', project_id, run_id))

    @router.get('/runs/{run_id}/results')
    async def run_results(run_id: str, project_id: str):
        """The run's communications read into one UI shape (modules/platform/run_results/parse.py)."""
        return await respond(service().results('local', project_id, run_id))

    @router.get('/runs/{run_id}/request')
    async def review_request(run_id: str, project_id: str):
        return await respond(service().review_request('local', project_id, run_id))

    @router.get('/runs/{run_id}/trace')
    async def trace(run_id: str, project_id: str):
        """Spans the editor recorded for this run (today ± 1 day, at most 500 rows)."""
        try:
            service().binding('local', project_id)
        except LookupError:
            raise HTTPException(404, 'Project or run not found') from None
        return recorder.spans_for_run(run_id)

    @router.post('/projects/{project_id}/runs/{run_id}/resume', status_code=202)
    async def resume(project_id: str, run_id: str, body: RunResume, request: Request):
        """The person's answer to a waiting run's question (e.g. which district lot the parcel is)."""
        origin = request.headers.get('origin')
        if request.headers.get('sec-fetch-site') == 'cross-site' or (origin and origin != allowed_origin):
            raise HTTPException(403, 'Cross-origin execution is not allowed')
        return await respond(service().resume('local', project_id, run_id, body.input))

    @router.post('/projects/{project_id}/runs', status_code=202)
    async def submit(project_id: str, body: RunCreate, request: Request,
        idempotency_key: str = Header(min_length=1,max_length=128,pattern=r'^[A-Za-z0-9_-]+$')):
        origin = request.headers.get('origin')
        if request.headers.get('sec-fetch-site') == 'cross-site' or (origin and origin != allowed_origin):
            raise HTTPException(403, 'Cross-origin execution is not allowed')
        return await respond(service().submit('local',project_id,idempotency_key,body,
                                              traceparent=request.headers.get('traceparent')), submission=True)

    return router
