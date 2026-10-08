from fastapi import APIRouter, HTTPException, Request

from backend.app.adapters.law_agent import LawAgentError, LawAgentUnavailable
from backend.app.core.tracing import JsonlTraceRecorder
from backend.app.modules.platform.ask import ask_law
from backend.app.schemas.ask import AskCreate


def create_ask_router(allowed_origin, trace_recorder=None, agent=None):
    """`POST /ask`: a typed question goes to the Law Agent (same-origin only, like a run submission)."""
    router = APIRouter()
    recorder = trace_recorder or JsonlTraceRecorder()

    @router.post('/ask')
    async def ask(body: AskCreate, request: Request):
        origin = request.headers.get('origin')
        if request.headers.get('sec-fetch-site') == 'cross-site' or (origin and origin != allowed_origin):
            raise HTTPException(403, 'Cross-origin execution is not allowed')
        kwargs = {'agent': agent} if agent is not None else {}
        try:
            return await ask_law(body.text, pnu=body.pnu, assessment_date=body.assessment_date, recorder=recorder,
                                 traceparent=request.headers.get('traceparent'), **kwargs)
        except LawAgentUnavailable:
            raise HTTPException(503, 'law_agent_unavailable') from None
        except LawAgentError as exc:
            raise HTTPException(502, f'law_agent_error: {exc}') from None

    return router
