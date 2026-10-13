import httpx
from pydantic import ValidationError

from backend.app.adapters.orchestrator import OwnerContractError, OwnerUnavailable
from backend.app.core.agent_network import network_headers
from backend.app.schemas.conversation import ConversationSnapshot


class ConversationRejected(Exception):
    """The owner refused the request; `code` says why in one word the editor and the ledger can name."""
    def __init__(self, status_code, reason=''):
        self.status_code = status_code
        self.reason = reason
        # The Orchestrator refuses a turn while one is still answering (this conversation or another in the project).
        self.code = 'conversation_busy' if 'working' in reason else 'conversation_rejected'


class OrchestratorConversation:
    def __init__(self, owner):
        self.owner = owner

    async def exchange(self, project, branch, conversation_id, body=None):
        if not self.owner.base_url:
            raise OwnerUnavailable()
        identity = dict(project=project, branch=branch, conversation_id=conversation_id)
        method = 'GET' if body is None else 'POST'
        kwargs = {'params': identity} if body is None else {'json': {**body, **identity}}
        try:
            async with httpx.AsyncClient(timeout=15, transport=self.owner.transport,
                    follow_redirects=False, headers={**network_headers(), **self.owner.trace_headers(None),
                                                    'X-Editor-Client': 'local'}) as client:
                async with client.stream(method, self.owner.base_url.rstrip('/') + '/editor/v1/conversation', **kwargs) as response:
                    if response.status_code >= 400:
                        try:
                            reason = str((await response.aread() and response.json()).get('reason') or '')[:300]
                        except (ValueError, AttributeError):
                            reason = ''
                        raise ConversationRejected(response.status_code, reason)
                    if response.status_code != (200 if body is None else 202):
                        raise OwnerContractError()
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > 2 * 1024 * 1024:
                            raise OwnerContractError()
                        chunks.append(chunk)
            snapshot = ConversationSnapshot.model_validate_json(b''.join(chunks))
            if (snapshot.owner_project_id != project or snapshot.branch_id != branch
                    or snapshot.conversation_id != conversation_id):
                raise OwnerContractError()
            return snapshot
        except httpx.HTTPError as exc:
            raise OwnerUnavailable() from exc
        except (ValidationError, ValueError) as exc:
            raise OwnerContractError() from exc
