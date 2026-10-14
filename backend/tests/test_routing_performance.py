import asyncio
from types import SimpleNamespace

from backend.app.modules.platform.routing import route
from backend.app.modules.platform.routing import judge as judging


def test_specific_phrases_do_not_also_vote_for_their_generic_substrings():
    assert route("\uC2E4 \uBC30\uCE58\uB791 \uD53C\uB09C \uB3D9\uC120 \uC7A1\uC544").agent == 'plan'
    assert route("\uCC28\uB7C9 \uB3D9\uC120\uACFC \uC2E4 \uBC30\uCE58").kind == 'ask'
    assert route("\uBC30\uCE58 \uC785\uBA74").kind == 'ask'


def test_model_outage_backoff_skips_repeated_calls_then_recovers(monkeypatch):
    from backend.app.modules.platform.routing.judge import FailureBackoff
    from backend.app.adapters import cli_model_client
    now=[0.0]
    backoff=FailureBackoff(now=lambda:now[0])
    calls=[]
    async def create(*args,**kwargs):
        calls.append(1)
        raise RuntimeError("You've hit your weekly limit")
    monkeypatch.setattr(cli_model_client,'ClaudeCodeChatCompletionClient',lambda **kwargs:SimpleNamespace(create=create))
    async def roster(*args):return {}
    errors=[]
    async def run():
        assert await judging.judge('help',roster=roster,on_error=errors.append,backoff=backoff) is None
        async def unused_context():
            raise AssertionError('circuit-open request must not fetch a catalog')
        assert await judging.judge('help',unused_context,roster=roster,on_error=errors.append,backoff=backoff) is None
        assert len(calls)==1 and errors[-1]=='model_circuit_open'
        now[0]=61
        await judging.judge('help',roster=roster,backoff=backoff)
        assert len(calls)==2
    asyncio.run(run())


def test_rules_http_route_does_not_fetch_unused_agent_catalog(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app.modules.platform.routers.ask import create_ask_router
    calls=[]
    class Owner:
        async def list_agents(self):
            calls.append(1)
            return []
    monkeypatch.setenv('EDITOR_ROUTING_JUDGE','rules')
    app=FastAPI();app.include_router(create_ask_router('http://testserver',owner=Owner()))
    with TestClient(app) as client:
        response=client.post('/ask',json={'text':'\uC2E4 \uBC30\uCE58\uB791 \uD53C\uB09C \uB3D9\uC120 \uC7A1\uC544'})
    assert response.status_code==200
    assert response.json()['route']['agent']=='plan'
    assert calls==[]


def test_model_still_receives_current_lazy_context():
    import json
    seen=[]
    async def situation():
        seen.append('fetched')
        return 'current project context'
    async def roster(*args):return {}
    class Client:
        async def create(self,messages,**kwargs):
            assert 'current project context' in messages[0].content
            return SimpleNamespace(content=json.dumps({'is_request_satisfied':{'reason':'r','answer':False},
                'next_speaker':{'reason':'r','answer':'plan'},'instruction_or_question':{'reason':'r','answer':'draw'}}))
    result=asyncio.run(judging.judge('draw',situation,client=Client(),roster=roster))
    assert result.next_speaker.answer=='plan' and seen==['fetched']


def test_auto_asks_the_model_first_and_keywords_only_decide_when_it_gives_nothing():
    """The rule table is the fallback, never a judge ahead of a live model - even for an uncontested keyword hit."""
    from backend.app.modules.platform.routing import decide
    seen=[]
    async def model(text,situation):
        seen.append(text)
        return None
    async def run():
        specific=await decide('실 배치랑 피난 동선 잡아',judge=model,enabled=True,policy='auto')
        assert seen==['실 배치랑 피난 동선 잡아']
        assert specific.agent=='plan' and specific.decided_by=='rules' and specific.fallback_reason=='model_unavailable'
        await decide('배치 입면',judge=model,enabled=True,policy='auto')
        assert seen[-1]=='배치 입면'
    asyncio.run(run())
