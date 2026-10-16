import asyncio
import json
from types import SimpleNamespace

from backend.app.modules.platform.routing.roles import site
from backend.app.modules.platform.routing.site_mention import site_named


class FakeModel:
    def __init__(self, answer):
        self.answer = answer
        self.prompts = []

    async def create(self, messages, **kwargs):
        self.prompts.append(messages[0].content)
        if isinstance(self.answer, Exception):
            raise self.answer
        return SimpleNamespace(content=json.dumps(self.answer, ensure_ascii=False))


def test_the_model_names_the_site_inside_a_sentence_and_says_no_when_none_is_written():
    model = FakeModel({'reason': '지번이 적혀 있어요', 'names_site': True, 'address': '산곡동 684-1'})
    assert asyncio.run(site_named('산곡동 684-1에 어린이집을 지으려고 해요', client=model, enabled=True)) == '산곡동 684-1'
    assert '산곡동 684-1에 어린이집을 지으려고 해요' in model.prompts[0]
    none = FakeModel({'reason': '지명만 있어요', 'names_site': False, 'address': None})
    assert asyncio.run(site_named('의정부 쪽에 어린이집을 짓고 싶어요', client=none, enabled=True)) is None
    # names_site without an address, or an address with names_site false, is "no site" — never an invented one.
    assert asyncio.run(site_named('아무 말', client=FakeModel({'reason': '', 'names_site': True, 'address': ''}), enabled=True)) is None
    assert asyncio.run(site_named('테헤란로 152', client=FakeModel({'reason': '', 'names_site': False, 'address': '테헤란로 152'}), enabled=True)) is None


def test_a_lot_number_of_the_current_site_is_not_a_new_site_and_the_judge_hears_which_site_that_is():
    current = {'pnu': '4115011300106840001', 'address': '경기도 의정부시 산곡동 684-1'}
    # The model, told the current site, says the message refers back to it.
    model = FakeModel({'reason': '이 대지를 가리켜요', 'names_site': False, 'address': None})
    assert asyncio.run(site_named('이 대지(684-1)가 접한 도로 폭 근거는?', current=current, client=model, enabled=True)) is None
    assert '경기도 의정부시 산곡동 684-1' in model.prompts[0] and '4115011300106840001' in model.prompts[0]
    # Even when it answers the bare lot number, that number is the current site's own: not a move to the first 684-1 nationwide.
    bare = FakeModel({'reason': '번지가 있어요', 'names_site': True, 'address': '684-1'})
    assert asyncio.run(site_named('이 대지(684-1)가 접한 도로는?', current=current, client=bare, enabled=True)) is None
    assert asyncio.run(site_named('이 대지(684-1)가 접한 도로는?', current=current, enabled=False)) is None
    # A different site named in full still moves the conversation.
    other = FakeModel({'reason': '다른 주소예요', 'names_site': True, 'address': '강릉시 상시동리 684-1'})
    assert asyncio.run(site_named('강릉시 상시동리 684-1은 어때요', current=current, client=other, enabled=True)) == '강릉시 상시동리 684-1'
    # Without a current site the prompt carries no site line and the answer is the model's.
    assert asyncio.run(site_named('이 대지(684-1)', client=FakeModel({'reason': '', 'names_site': True, 'address': '684-1'}), enabled=True)) == '684-1'


def test_rules_decide_when_the_model_is_off_or_fails():
    assert asyncio.run(site_named('산곡동 684-1에 어린이집을 지으려고 해요', enabled=False)) == '산곡동 684-1'
    assert asyncio.run(site_named('서울 테헤란로 152번지 근처요', enabled=False)) == '서울 테헤란로 152'
    assert asyncio.run(site_named('어린이집을 짓고 싶어요', enabled=False)) is None
    broken = FakeModel(RuntimeError('cli down'))
    assert asyncio.run(site_named('산곡동 684-1에 어린이집', client=broken, enabled=True)) == '산곡동 684-1'


def test_find_takes_the_first_address_shape_and_leaves_particles():
    assert site.find('4115011300106840001 필지에 뭘 지을 수 있어요?') == '4115011300106840001'
    assert site.find('경기도 의정부시 산곡동 산 12-3번지에 창고') == '경기도 의정부시 산곡동 산 12-3번지'
    assert site.find('용적률이 궁금해요') is None
