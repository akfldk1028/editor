"""A refused conversation request carries the owner's reason as a code the editor and the ledger can name."""
import asyncio

import httpx
import pytest

from backend.app.adapters.orchestrator_conversation import ConversationRejected, OrchestratorConversation


class Owner:
    base_url = 'http://orchestrator.test'

    def __init__(self, transport):
        self.transport = transport

    def trace_headers(self, _):
        return {}


@pytest.mark.parametrize(('reason', 'code'), [('another conversation in this project is working', 'conversation_busy'),
                                              ('message_id already has different content', 'conversation_rejected')])
def test_the_owners_reason_becomes_a_code(reason, code):
    transport = httpx.MockTransport(lambda request: httpx.Response(409, json={'detail': 'conversation request rejected', 'reason': reason}))
    with pytest.raises(ConversationRejected) as caught:
        asyncio.run(OrchestratorConversation(Owner(transport)).exchange('p', 'b', 'c', {'message_id': 'm', 'text': 'hi'}))
    assert (caught.value.status_code, caught.value.code) == (409, code)
