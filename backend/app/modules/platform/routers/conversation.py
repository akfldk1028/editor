from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from backend.app.adapters.orchestrator import OwnerContractError, OwnerUnavailable
from backend.app.adapters.orchestrator_conversation import ConversationRejected, OrchestratorConversation
from backend.app.modules.platform import host
from backend.app.modules.platform.ask import locate_site
from backend.app.modules.platform.conversation_activation import activate
from backend.app.modules.platform.routing.roles import site
from backend.app.schemas.conversation import ConversationSnapshot, ConversationSubmit


def create_conversation_router(projects_service, owner, allowed_origin, activation=None):
    router = APIRouter()
    remote = OrchestratorConversation(owner)
    ensure_providers = activation if activation is not None else activate

    async def exchange(project_id, conversation_id, body=None):
        binding = projects_service().repository.get('local', project_id)
        if binding is None:
            raise HTTPException(404, 'Project not found')
        if body is not None:
            try:
                await ensure_providers()
            except (host.HostUnavailable, host.HostRefused):
                raise HTTPException(503, 'Conversation providers unavailable') from None
        try:
            return await remote.exchange(binding.owner_project_id, binding.branch_id, conversation_id, body)
        except ConversationRejected as exc:
            raise HTTPException(exc.status_code, 'Conversation request rejected by owner') from None
        except OwnerUnavailable:
            raise HTTPException(503, 'Conversation owner unavailable') from None
        except OwnerContractError:
            raise HTTPException(502, 'Conversation owner contract invalid') from None

    @router.get('/projects/{project_id}/conversation', response_model=ConversationSnapshot)
    async def get_conversation(project_id: str, conversation_id: str = Query(
            default='main', pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$')):
        return await exchange(project_id, conversation_id)

    @router.post('/projects/{project_id}/conversation', response_model=ConversationSnapshot, status_code=202)
    async def submit_conversation(project_id: str, request: Request):
        origin = request.headers.get('origin')
        if request.headers.get('sec-fetch-site') == 'cross-site' or (origin and origin != allowed_origin):
            raise HTTPException(403, 'Cross-origin conversation changes are not allowed')
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > 65536:
                raise HTTPException(413, 'Conversation request is too large')
            chunks.append(chunk)
        try:
            body = ConversationSubmit.model_validate_json(b''.join(chunks))
        except ValidationError:
            raise HTTPException(422, 'Invalid conversation request') from None
        claim = site.locate(body.text, {})
        if claim:
            # A message that is one address or PNU names the site: the editor's own claim (the Site role's
            # deterministic pattern, same as `/ask`), answered by its own geocoder and never sent to the owner —
            # the map opens on the parcel and selects it, and later messages carry that site as context.
            # 200 `{located}` instead of the 202 snapshot; the owner's conversation does not record the address.
            if projects_service().repository.get('local', project_id) is None:
                raise HTTPException(404, 'Project not found')
            return JSONResponse({'located': await locate_site(claim['query'])})
        return await exchange(project_id, body.conversation_id, body.model_dump(exclude_none=True))

    return router
