from fastapi import APIRouter, HTTPException, Request

from backend.app.adapters.law_agent import LawAgentError, LawAgentUnavailable
from backend.app.core.tracing import JsonlTraceRecorder
from backend.app.modules.law.ordinances import service as ordinances
from backend.app.modules.platform.ask import analyze_land, ask_law
from backend.app.modules.platform.situation import describe
from backend.app.schemas.ask import AskCreate, LawAnalysisCreate, OrdinanceBodyCreate, OrdinanceDiscoveryCreate


def create_ask_router(allowed_origin, trace_recorder=None, agent=None, owner=None, ledger=None):
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
                                    clause=body.clause.model_dump() if body.clause else None, ledger=ledger, conversation_id=body.conversation_id, **kwargs))

    @router.post('/law-analysis')
    async def law_analysis(body: LawAnalysisCreate, request: Request):
        same_origin(request)
        return await answer(analyze_land(body.pnu, ledger=ledger, conversation_id=body.conversation_id, building_type=body.building_type, floor_area_m2=body.floor_area_m2,
                                         assessment_date=body.assessment_date, recorder=recorder,
                                         traceparent=request.headers.get('traceparent'), **kwargs))

    @router.post('/ordinances')
    async def ordinance_discovery(body: OrdinanceDiscoveryCreate, request: Request):
        """The ordinances that can bind the parcel on the date: official records (law.go.kr), the parcel's own
        jurisdictions (registry address by PNU), the edition in force on the date, every search page walked.
        Candidates to read with their official URL — not applicability, not a body."""
        same_origin(request)
        return await ordinances.discover(body.pnu, body.assessment_date, refs=[ref.model_dump() for ref in body.refs], topics=body.topics)

    @router.post('/ordinances/body')
    async def ordinance_body(body: OrdinanceBodyCreate, request: Request):
        """The whole text of one discovered edition (articles, annexes, supplementary provisions) from the official
        record, accepted only when it is that name, that edition, in force on the date. A `error` key says why not."""
        same_origin(request)
        return await ordinances.body(body.name, body.edition_id, body.assessment_date)

    return router
