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
        elif chosen.agent == case['agent']:
            right += 1
        else:
            wrong.append((case['text'], case['agent'], chosen.agent))
    # A wrong role is worse than a question: the router may ask, it may not misdirect.
    assert wrong == []
    assert right / len(GOLDEN) >= 0.9, f'{right}/{len(GOLDEN)} right; asked: {asked}'
