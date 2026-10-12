"""The interim role router: deterministic patterns, keyword scoring, and asking when unsure — measured on a golden set."""
import json
from pathlib import Path

from backend.app.modules.platform.routing import route
from backend.app.modules.platform.routing.roles import ROLES

GOLDEN = json.loads((Path(__file__).parent / 'fixtures' / 'routing' / 'golden.json').read_text(encoding='utf-8'))['cases']


def test_patterns_claim_ordinance_articles_and_statute_ids_with_their_args():
    chosen = route('의정부시 도시계획 조례 제42조', assessment_date='2026-10-08')
    assert (chosen.kind, chosen.agent, chosen.skill, chosen.confidence) == ('skill', 'law', 'law_ordinance', 0.95)
    assert chosen.args == {'name': '의정부시 도시계획 조례', 'article': '제42조', 'limit': 3, 'assessment_date': '2026-10-08'}
    statute = route('국토의 계획 및 이용에 관한 법률(시행령)::제6장::제84조::8')
    assert (statute.skill, statute.args) == ('law_article', {'full_id': '국토의 계획 및 이용에 관한 법률(시행령)::제6장::제84조::8'})


def test_keywords_route_law_to_a_skill_and_other_roles_to_a_goal_handoff():
    law = route('자연녹지지역 건폐율이 얼마야')
    assert (law.kind, law.agent, law.skill, law.args['query'], law.confidence) == ('skill', 'law', 'law_search', '자연녹지지역 건폐율이 얼마야', 0.7)
    mass = route('매스 쌓아 봐')
    assert (mass.kind, mass.agent, mass.goal, mass.skill) == ('goal', 'mass', 'mass', None)
    site = route('접도 도로 폭이 몇 미터야')
    assert (site.kind, site.agent, site.goal) == ('goal', 'site_context', 'limits')


def test_unsure_requests_become_a_question_with_every_role_as_a_choice_and_a_picked_role_wins():
    ask = route('뭐 할 수 있어?')
    assert ask.kind == 'ask' and ask.agent is None and [c.agent for c in ask.choices] == [r.agent for r in ROLES]
    assert ask.to_dict()['choices'][0] == {'agent': 'law', 'label': '법령·조례 검색 (Law Agent)'}
    tie = route('배치 입면')
    assert tie.kind == 'ask' and '둘 다' in tie.reason
    picked = route('뭐 할 수 있어?', role='mass')
    assert (picked.kind, picked.agent, picked.goal, picked.confidence) == ('goal', 'mass', 'mass', 0.9)
    picked_law = route('조경 의무 면적', role='law')
    assert (picked_law.kind, picked_law.skill, picked_law.args['query']) == ('skill', 'law_search', '조경 의무 면적')


def test_golden_set_is_never_routed_to_a_wrong_role_and_mostly_to_the_right_one():
    right, asked, wrong = 0, [], []
    for case in GOLDEN:
        chosen = route(case['text'])
        if chosen.kind == 'ask':
            asked.append(case['text'])
            if case['agent'] is None:
                right += 1
        elif chosen.agent in (case['agent'] if isinstance(case['agent'], list) else [case['agent']]):
            right += 1
        else:
            wrong.append((case['text'], case['agent'], chosen.agent))
    # A wrong role is worse than a question: the router may ask, it may not misdirect.
    assert wrong == []
    assert right / len(GOLDEN) >= 0.9, f'{right}/{len(GOLDEN)} right; asked: {asked}'


def test_decide_lets_the_orchestrators_ledger_name_the_speaker_or_itself_and_falls_back_to_rules():
    import asyncio

    from backend.app.modules.platform.routing import decide
    from backend.app.modules.platform.routing.judge import Ledger, team_description, participants

    def ledger(speaker, reason, instruction, satisfied=False):
        async def _judge(text, situation=''):
            return Ledger.model_validate({'is_request_satisfied': {'reason': reason, 'answer': satisfied},
                                          'next_speaker': {'reason': reason, 'answer': speaker},
                                          'instruction_or_question': {'reason': 'r', 'answer': instruction}})
        return _judge

    async def silent(text, situation=''):
        return None

    replied = asyncio.run(decide('안녕, 뭐 할 수 있어?', judge=ledger('orchestrator', '인사와 소개는 제가 답할 수 있어요', '안녕하세요! 지금은 법규·한계 검토가 열려 있어요.', satisfied=True), enabled=True))
    assert (replied.kind, replied.agent, replied.decided_by, replied.instruction) == ('answer', 'orchestrator', 'llm', '안녕하세요! 지금은 법규·한계 검토가 열려 있어요.')

    judged = asyncio.run(decide('배치 방법 알려줘', judge=ledger('masterplan', '배치 질문이에요', '이 대지의 배치 대안을 만들어 주세요'), enabled=True))
    assert (judged.kind, judged.agent, judged.goal, judged.confidence, judged.decided_by) == ('goal', 'masterplan', 'masterplan', 0.85, 'llm')
    assert (judged.reason, judged.instruction) == ('배치 질문이에요', '이 대지의 배치 대안을 만들어 주세요')
    assert judged.to_dict()['instruction'] == '이 대지의 배치 대안을 만들어 주세요'
    asked = asyncio.run(decide('경계 정리하고 매스 올려', judge=ledger('orchestrator', '둘에 걸쳐요', '대지 경계 정리와 매스, 어느 쪽부터 할까요?'), enabled=True))
    assert asked.kind == 'ask' and asked.decided_by == 'llm' and asked.reason == '대지 경계 정리와 매스, 어느 쪽부터 할까요?' and len(asked.choices) == len(ROLES)
    fallback = asyncio.run(decide('매스 쌓아 봐', judge=silent, enabled=True))
    assert (fallback.kind, fallback.agent, fallback.decided_by, fallback.instruction) == ('goal', 'mass', 'rules', None)
    # A pattern or a picked role never waits for the model.
    pattern = asyncio.run(decide('의정부시 도시계획 조례 제42조', judge=silent, enabled=True))
    assert (pattern.skill, pattern.decided_by) == ('law_ordinance', 'pattern')
    picked = asyncio.run(decide('뭐 할 수 있어?', role='cost', judge=silent, enabled=True))
    assert (picked.agent, picked.goal, picked.decided_by) == ('cost', 'cost', 'user')
    off = asyncio.run(decide('매스 쌓아 봐', judge=ledger('cost', 'x', 'x'), enabled=False))
    assert (off.agent, off.decided_by) == ('mass', 'rules')
    # The team is described as Magentic-One does: one `name: description` line per participant, the Orchestrator last.
    lines = team_description().splitlines()
    assert [line.split(':')[0] for line in lines] == participants() and lines[-1].startswith('orchestrator: ') and all('  ' not in line for line in lines)


def test_judge_refuses_a_speaker_outside_the_team_and_retries_then_gives_up():
    import asyncio

    from backend.app.modules.platform.routing import judge as judging

    class Client:
        def __init__(self, answers):
            self.answers, self.calls = list(answers), 0

        async def create(self, messages, *, json_output=None):
            self.calls += 1
            assert 'Who should speak next?' in messages[0].content and 'law: ' in messages[0].content and 'Is the request fully satisfied' in messages[0].content
            return type('R', (), {'content': self.answers.pop(0)})()

    sat = '"is_request_satisfied": {"reason": "r", "answer": false}, '
    async def no_cards(agents):
        return {}

    bad = '{' + sat + '"next_speaker": {"reason": "r", "answer": "nobody"}, "instruction_or_question": {"reason": "r", "answer": "x"}}'
    good = '{' + sat + '"next_speaker": {"reason": "r", "answer": "scene"}, "instruction_or_question": {"reason": "r", "answer": "주변 3D를 보여 주세요"}}'
    client = Client([bad, good])
    ledger = asyncio.run(judging.judge('주변을 3D로', client=client, roster=no_cards))
    assert ledger.next_speaker.answer == 'scene' and client.calls == 2
    client = Client([bad] * (judging.MAX_JSON_RETRIES + 1))
    assert asyncio.run(judging.judge('x', client=client, roster=no_cards)) is None and client.calls == judging.MAX_JSON_RETRIES + 1
    assert asyncio.run(judging.judge('x', client=Client(['not json']), roster=no_cards)) is None


def test_team_is_described_by_the_agents_live_cards_and_falls_back_to_the_role_line():
    import asyncio

    from backend.app.modules.platform.routing import cards
    from backend.app.modules.platform.routing.judge import team_description
    from backend.app.modules.platform.status.registry import Registry

    law_card = {'name': 'LawAgent', 'description': 'Korean building-law agent:   a parcel\'s zoning, the 42 regulations.',
                'skills': [{'id': f'law_{i}', 'name': f'skill {i}', 'description': f'does {i}'} for i in range(14)]}
    fetched = []

    async def fetch(url):
        fetched.append(url)
        return cards._card(law_card) if ':8301/' in url else None

    clock = [0.0]
    cache = {}
    live = asyncio.run(cards.roster(['law', 'mass', 'nobody'], fetch=fetch, now=lambda: clock[0], cache=cache, registry=Registry()))
    assert live['law']['name'] == 'LawAgent' and live['mass'] is None and live['nobody'] is None
    assert [u for u in fetched if ':8301/' in u] == ['http://127.0.0.1:8301/.well-known/agent-card.json']
    text = team_description(live)
    law_line = next(line for line in text.splitlines() if line.startswith('law: '))
    assert law_line.startswith("law: Korean building-law agent: a parcel's zoning, the 42 regulations. Skills: law_0: does 0; ")
    assert law_line.endswith('law_11: does 11 (+2 more)')
    mass_line = next(line for line in text.splitlines() if line.startswith('mass: '))
    assert 'volumes' in mass_line and 'Skills:' not in mass_line, mass_line
    # Cached for a minute: the second roster call does not fetch again.
    before = len(fetched)
    asyncio.run(cards.roster(['law'], fetch=fetch, now=lambda: clock[0] + 30, cache=cache, registry=Registry()))
    assert len(fetched) == before
    assert cards.card_url('law') == 'http://127.0.0.1:8301/.well-known/agent-card.json' and cards.card_url('nobody') is None


def test_a_message_that_is_an_address_or_a_pnu_is_claimed_for_the_map_and_a_question_with_a_number_is_not():
    for text in ('경기도 의정부시 산곡동 684-1', '서울 강남구 역삼동 737', '역삼동 산 12번지', '서울특별시 강남구 테헤란로 152', '4115011300106840001'):
        chosen = route(text)
        assert (chosen.kind, chosen.agent, chosen.skill, chosen.confidence, chosen.decided_by) == ('skill', 'site_context', 'site_locate', 0.95, 'pattern'), text
        assert chosen.args == {'query': text}
    for text in ('자연녹지지역 건폐율 20', '용적률 300', '의정부시 도시계획 조례 제42조', '산곡동 684-1 법규 검토해줘'):
        assert route(text).skill != 'site_locate', text


def test_a_registered_agent_without_a_role_module_is_a_participant_the_model_may_name_and_the_user_may_pick():
    """The team grows with the registry: an agent with an A2A card but no roles/<agent>.py is described by its card,
    may be named by the ledger or picked as a role, and the door hands the question to it (kind 'agent')."""
    import asyncio

    from backend.app.modules.platform.routing import decide
    from backend.app.modules.platform.routing.judge import Ledger, participants, team_description

    extra = ['structure']
    assert participants(extra)[-2:] == ['structure', 'orchestrator']
    lines = team_description({'structure': {'name': 'StructureAgent', 'description': 'Frames and walls for a mass.',
                                            'skills': [{'id': 'structure_frame', 'name': 'frame', 'description': 'Propose a frame.'}]}}, extra).splitlines()
    assert 'structure: Frames and walls for a mass. Skills: structure_frame: Propose a frame.' in lines
    assert any(line.startswith('structure: ') and 'registered in the network' in line for line in team_description(None, extra).splitlines())

    def ledger(speaker, instruction):
        async def _judge(text, situation=''):
            return Ledger.model_validate({'is_request_satisfied': {'reason': 'r', 'answer': False},
                                          'next_speaker': {'reason': '구조 질문이에요', 'answer': speaker},
                                          'instruction_or_question': {'reason': 'r', 'answer': instruction}})
        return _judge

    named = asyncio.run(decide('이 매스에 기둥 간격 어떻게 잡아?', judge=ledger('structure', '이 매스의 골조 안을 내 주세요'), enabled=True, extras=extra))
    assert (named.kind, named.agent, named.skill, named.decided_by, named.confidence) == ('agent', 'structure', None, 'llm', 0.85)
    assert (named.reason, named.instruction, named.args) == ('구조 질문이에요', '이 매스의 골조 안을 내 주세요', {'text': '이 매스에 기둥 간격 어떻게 잡아?'})

    async def silent(text, situation=''):
        return None
    picked = asyncio.run(decide('기둥 간격', role='structure', judge=silent, enabled=True, extras=extra))
    assert (picked.kind, picked.agent, picked.decided_by) == ('agent', 'structure', 'user')
    # Without the registry entry the same role is unknown and rules decide as before.
    unknown = asyncio.run(decide('기둥 간격', role='structure', judge=silent, enabled=True, extras=[]))
    assert unknown.kind != 'agent'
    # When the model asks, the registered agent is among the choices.
    asked = asyncio.run(decide('뭐부터?', judge=ledger('orchestrator', '어느 쪽부터 할까요?'), enabled=True, extras=extra))
    assert asked.kind == 'ask' and asked.choices[-1].agent == 'structure'


def test_a_registered_agent_is_named_for_a_person_from_its_card_or_its_id_and_cards_are_fetched_together():
    import asyncio

    from backend.app.modules.platform.routing import cards

    assert cards.display_name('structure') == 'Structure Agent'
    assert cards.display_name('site-context') == 'Site context Agent'
    assert cards.display_name('x', {'name': 'StructureAgent', 'description': '', 'skills': []}) == 'StructureAgent'
    started = []

    async def fetch(url):
        started.append(url)
        await asyncio.sleep(0.05)
        return None
    cache = {}
    clock = [0.0]
    from backend.app.modules.platform.status.registry import Registry
    import time
    t0 = time.perf_counter()
    live = asyncio.run(cards.roster(['law', 'mass', 'site_context'], fetch=fetch, now=lambda: clock[0], cache=cache, registry=Registry()))
    assert set(live) == {'law', 'mass', 'site_context'} and len(started) == 3
    assert time.perf_counter() - t0 < 0.12, 'misses are fetched together, not one after another'
