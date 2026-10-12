from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from backend.app.adapters.orchestrator import OwnerContractError, OwnerUnavailable
from backend.app.adapters.orchestrator_conversation import ConversationRejected, OrchestratorConversation
from backend.app.modules.platform import host
from backend.app.modules.platform.ask import locate_site
from backend.app.modules.platform.conversation_activation import activate
from backend.app.modules.platform.routing.roles import site
from backend.app.modules.platform.routing.site_mention import site_named
from backend.app.schemas.conversation import ConversationSnapshot, ConversationSubmit


def settle_turns(ledger, snapshot) -> None:
    """A person's message stays a running call in the 협업 장부 until the reply to it is in the conversation: then the
    call ends with that reply (everything the Orchestrator said before the person's next message), or as failed."""
    if ledger is None:
        return
    turns = ledger.open_calls(conversation_id=snapshot.conversation_id, tool='conversation')
    if not turns:
        return
    messages = snapshot.messages
    for turn in turns:
        asked = next((index for index, message in enumerate(messages) if message.id == turn.attrs.get('message_id')), None)
        if asked is None:
            continue
        replies, answered = [], False
        for message in messages[asked + 1:]:
            if message.role == 'user':
                answered = True
                break
            replies.append(message)
        if replies and (answered or snapshot.status != 'working'):
            ledger.finish(turn, output_text='\n\n'.join(message.text for message in replies), state='completed')
        elif snapshot.status == 'failed' and not answered:
            ledger.finish(turn, status='ERROR', error_type=snapshot.error or 'conversation_failed')


def create_conversation_router(projects_service, owner, allowed_origin, activation=None, ledger=None):
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
            snapshot = await remote.exchange(binding.owner_project_id, binding.branch_id, conversation_id, body)
            settle_turns(ledger, snapshot)
            return snapshot
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
        # A sentence that names a site ("산곡동 684-1에 어린이집을…") goes to the owner as written, but the editor locates
        # the site first (the model judges whether a site is named — `routing/site_mention`): the message carries that
        # parcel as its context, and the answer carries `located` so the map moves there. Nothing named (or not
        # geocodable) → the message goes through untouched.
        payload = body.model_dump(exclude_none=True)
        # A confirmation turn is not a message about a site, and an address or PNU always carries a digit: the model
        # is asked only when the message could name one.
        named = await site_named(body.text) if body.confirmation is None and any(ch.isdigit() for ch in body.text) else None
        located = await locate_site(named) if named else None
        if located is not None and not (located['pnu'] or located['coordinates']):
            located = None
        if located is not None:
            context = payload.setdefault('context', {})
            if located['pnu']:
                context['pnu'] = located['pnu']
            if located['address']:
                context['address'] = located['address']
        # The 협업 장부: the person's message to the Orchestrator is one call of this conversation; it runs until its reply
        # arrives by polling (`settle_turns`, matched by the message id).
        turn = ledger.begin(from_agent='user', to_agent='orchestrator', tool='conversation', conversation_id=body.conversation_id, input_text=body.text,
                            attrs={'message_id': body.message_id}) if ledger else None
        try:
            snapshot = await exchange(project_id, body.conversation_id, payload)
        except HTTPException as exc:
            if turn is not None:
                ledger.finish(turn, status='ERROR', error_type=f'http_{exc.status_code}')
            raise
        if located is None:
            return snapshot
        return JSONResponse({**snapshot.model_dump(), 'located': located}, status_code=202)

    return router
