from fastapi import APIRouter, HTTPException, Request

from backend.app.adapters.law_agent import LawAgentError, LawAgentUnavailable
from backend.app.core.tracing import JsonlTraceRecorder
from backend.app.modules.platform.ask import analyze_land, ask_law
from backend.app.modules.platform.situation import describe
from backend.app.schemas.ask import AskCreate, LawAnalysisCreate


def create_ask_router(allowed_origin, trace_recorder=None, agent=None, owner=None):
    """The conversation's doors (same-origin only, like a run submission): `POST /ask` routes and answers a typed
    question — the Orchestrator's judgment over the situation (site, goal catalog, which agents `owner` reports up) —
    and `POST /law-analysis` analyses one parcel with the Law Agent."""
    router = APIRouter()
    recorder = trace_recorder or JsonlTraceRecorder()
    kwargs = {'agent': agent} if agent is not None else {}

    async def agents():
        """Best effort: the Orchestrator catalog, or None when it is down (the situation then says so)."""
        if owner is None:
            return None
        try:
            return await owner.list_agents()
        except Exception:
            return None

    def same_origin(request: Request):
        origin = request.headers.get('origin')
        if request.headers.get('sec-fetch-site') == 'cross-site' or (origin and origin != allowed_origin):
            raise HTTPException(403, 'Cross-origin execution is not allowed')

    async def answer(operation):
        try:
            return await operation
        except LawAgentUnavailable:
            raise HTTPException(503, 'law_agent_unavailable') from None
        except LawAgentError as exc:
            raise HTTPException(502, f'law_agent_error: {exc}') from None

    @router.post('/ask')
    async def ask(body: AskCreate, request: Request):
        same_origin(request)
        situation = describe(pnu=body.pnu, address=body.address, assessment_date=body.assessment_date, agents=await agents())
        return await answer(ask_law(body.text, pnu=body.pnu, assessment_date=body.assessment_date, recorder=recorder,
                                    traceparent=request.headers.get('traceparent'), role=body.role, situation=situation,
                                    clause=body.clause.model_dump() if body.clause else None, **kwargs))

    @router.post('/law-analysis')
    async def law_analysis(body: LawAnalysisCreate, request: Request):
        same_origin(request)
        return await answer(analyze_land(body.pnu, building_type=body.building_type, floor_area_m2=body.floor_area_m2,
                                         assessment_date=body.assessment_date, recorder=recorder,
                                         traceparent=request.headers.get('traceparent'), **kwargs))

    return router
