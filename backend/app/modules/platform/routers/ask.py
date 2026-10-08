from fastapi import APIRouter, HTTPException, Request

from backend.app.adapters.law_agent import LawAgentError, LawAgentUnavailable
from backend.app.core.tracing import JsonlTraceRecorder
from backend.app.modules.platform.ask import analyze_land, ask_law
from backend.app.schemas.ask import AskCreate, LawAnalysisCreate


def create_ask_router(allowed_origin, trace_recorder=None, agent=None):
    """The Law Agent's doors for the conversation and the law artifact (same-origin only, like a run submission):
    `POST /ask` answers a typed question, `POST /law-analysis` analyses one parcel."""
    router = APIRouter()
    recorder = trace_recorder or JsonlTraceRecorder()
    kwargs = {'agent': agent} if agent is not None else {}

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
        return await answer(ask_law(body.text, pnu=body.pnu, assessment_date=body.assessment_date, recorder=recorder,
                                    traceparent=request.headers.get('traceparent'), role=body.role, **kwargs))

    @router.post('/law-analysis')
    async def law_analysis(body: LawAnalysisCreate, request: Request):
        same_origin(request)
        return await answer(analyze_land(body.pnu, building_type=body.building_type, floor_area_m2=body.floor_area_m2,
                                         assessment_date=body.assessment_date, recorder=recorder,
                                         traceparent=request.headers.get('traceparent'), **kwargs))

    return router
