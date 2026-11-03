"""Site search review fixes (2026-11-03): one regression per reviewed item, over a mocked VWorld."""
import asyncio

import httpx
import pytest

from backend.app.modules.land.address_query import classify, region_matches
from backend.app.modules.land.address_rank import address_candidates, rank_addresses


def client_for(handle):
    from backend.app.modules.land.vworld import VworldClient
    return VworldClient('private-key', transport=httpx.MockTransport(handle))


def ok(items, total=None):
    return httpx.Response(200, json={'response': {'status': 'OK', 'record': {'total': str(total or len(items))}, 'result': {'items': items}}})


def not_found(request=None):
    return httpx.Response(200, json={'response': {'status': 'NOT_FOUND'}})


def refuse(code='OVER_REQUEST_LIMIT'):
    return lambda request: httpx.Response(200, json={'response': {'status': 'ERROR', 'error': {'code': code, 'text': 'x'}}})


def item(pnu, parcel, road='', x=127.0, y=37.5):
    return {'id': pnu, 'address': {'parcel': parcel, 'road': road}, 'point': {'x': str(x), 'y': str(y)}}


def ranked(text, items):
    query = classify(text)
    return rank_addresses(query, address_candidates(query, items))


def coord_reply(text, level4l, level5, code='', level1='', level2=''):
    return httpx.Response(200, json={'response': {'status': 'OK', 'result': {'point': {'x': '127', 'y': '37'}}, 'refined': {
        'text': text, 'structure': {'level1': level1, 'level2': level2, 'level4L': level4l, 'level4LC': code, 'level5': level5}}}})


def search_empty_then(coord):
    return lambda request: not_found() if request.url.path.endswith('/search') else coord


def test_r1_a_typed_pnu_during_a_key_or_quota_refusal_is_unavailable_not_none():
    found = asyncio.run(client_for(refuse()).search('4115011300106840001'))
    assert found['status'] == 'unavailable' and '한도' in found['error']
    geometry = asyncio.run(client_for(refuse('INVALID_KEY')).fetch_parcel_geometry('4115011300106840001'))
    assert geometry['success'] is False and geometry['unavailable'] == 'INVALID_KEY' and 'private-key' not in str(geometry)
    missing = asyncio.run(client_for(not_found).search('4115011300106840001'))
    assert missing['status'] == 'none'


def test_r2_a_city_word_without_suffix_must_be_in_the_address():
    assert classify('용인 신촌동 1').regions == ['용인']
    status, rows = ranked('용인 신촌동 1', [item('1141011400100010000', '서울특별시 서대문구 신촌동 1')])
    assert status == 'ambiguous' and not rows[0]['exact'] and rows[0]['substituted']
    status, _ = ranked('용인 신촌동 1', [item('4146010100100010000', '경기도 용인시 처인구 신촌동 1')])
    assert status == 'unique'


def test_r3_a_pnu_with_spaces_is_normalized_on_the_server():
    from backend.app.modules.land.pnu import normalize_pnu
    assert normalize_pnu('41150 11300 1 0684 0001') == '4115011300106840001'
    with pytest.raises(ValueError):
        normalize_pnu('１２３４５６７８９０１２３４５６７８９')


def test_r4_resolve_keeps_a_point_for_an_area_or_a_place():
    def handle(request):
        if request.url.params.get('type') == 'place':
            return ok([{'title': '서울시청', 'category': '지방행정기관', 'address': {'parcel': '서울특별시 중구 태평로1가 31'},
                        'point': {'x': '126.97', 'y': '37.56'}}])
        return not_found()
    found = asyncio.run(client_for(handle).resolve_address('서울시청'))
    assert found['success'] is True and found['pnu'] is None and found['coordinates'] == {'x': 126.97, 'y': 37.56}


def test_r5_old_gwangju_and_jeonnam_match_only_their_own_part_of_the_merged_sido():
    gwangju = '전남광주통합특별시 서구 치평동 1200'.split()
    mokpo = '전남광주통합특별시 목포시 용당동 1'.split()
    assert region_matches('광주광역시', gwangju) and region_matches('광주', gwangju) and not region_matches('전남', gwangju)
    assert region_matches('전남', mokpo) and region_matches('전라남도', mokpo) and not region_matches('광주광역시', mokpo)
    assert region_matches('전남광주', mokpo) and region_matches('전남광주', gwangju)
    status, rows = ranked('전남 서구 치평동 1200', [item('1224012000112000000', '전남광주통합특별시 서구 치평동 1200')])
    assert status == 'ambiguous' and not rows[0]['exact']


def test_r6_getcoord_is_dropped_when_its_regions_contradict_the_input():
    handle = search_empty_then(coord_reply('경기도 의정부시 산곡동 684-1', '산곡동', '684-1', '4115011300106840001', '경기도', '의정부시'))
    assert asyncio.run(client_for(handle).search('인천 산곡동 684-1'))['status'] == 'none'
    assert asyncio.run(client_for(handle).search('의정부 산곡동 684-1'))['status'] == 'unique'


def test_question_getcoord_road_answers_carry_the_road_name_in_level4l():
    """Live, 2026-11-03: ROAD refined.structure is level3 법정동, level4L 로·길, level5 건물번호 (테헤란로 152 → 테헤란로, 152)."""
    road = search_empty_then(coord_reply('서울특별시 강남구 테헤란로 152 (역삼동)', '테헤란로', '152', '', '서울특별시', '강남구'))
    found = asyncio.run(client_for(road).search('테헤란로 152'))
    assert found['status'] == 'ambiguous' and found['candidates'][0]['road'].startswith('서울특별시 강남구 테헤란로 152')
    # The provider's own substitution (3.1대로 → 3·15대로) is never kept.
    substitute = search_empty_then(coord_reply('경상남도 창원시 마산합포구 3·15대로 110', '3·15대로', '110'))
    assert asyncio.run(client_for(substitute).search('3.1대로 110'))['status'] == 'none'


def test_r7_one_exact_match_on_a_truncated_page_is_not_unique():
    def handle(request):
        if request.url.params.get('type') == 'address':
            return ok([item('4115011300106840001', '경기도 의정부시 산곡동 684-1')], total=5000)
        return not_found()
    assert asyncio.run(client_for(handle).search('산곡동 684-1'))['status'] == 'ambiguous'


def test_r8_places_near_the_map_not_named_like_the_input_do_not_stop_the_nationwide_search():
    seen = []

    def handle(request):
        params = request.url.params
        if params.get('type') != 'place':
            return not_found()
        seen.append(params.get('bbox'))
        if params.get('bbox'):
            return ok([{'title': '해운대해수욕장', 'address': {'parcel': '부산광역시 해운대구 우동 1408'}, 'point': {'x': '129.16', 'y': '35.16'}}])
        return ok([{'title': '서울시청', 'address': {'parcel': '서울특별시 중구 태평로1가 31'}, 'point': {'x': '126.97', 'y': '37.56'}}])
    found = asyncio.run(client_for(handle).search('서울시청', bbox=[129.1, 35.1, 129.2, 35.2]))
    assert found['candidates'][0]['label'] == '서울시청' and len(seen) == 2 and seen[1] is None


def test_r10_a_refusal_in_the_second_class_is_not_turned_into_none():
    handle = lambda request: refuse()(request) if request.url.params.get('type') == 'place' else not_found()
    assert asyncio.run(client_for(handle).search('산곡동 684-1'))['status'] == 'unavailable'


@pytest.mark.parametrize('body', [
    {'status': 'OK', 'result': [], 'record': 'x'}, {'status': 'OK', 'result': {'items': 'x'}},
    {'status': 'OK', 'result': {'items': [1, None]}, 'record': {'total': 'NaN'}}, {'status': 'ERROR', 'error': 'x'},
])
def test_r11_odd_provider_shapes_read_as_nothing_found_never_an_exception(body):
    found = asyncio.run(client_for(lambda request: httpx.Response(200, json={'response': body})).search('산곡동 684-1'))
    assert found['status'] == 'none'
    assert asyncio.run(client_for(lambda request: httpx.Response(200, json=[1])).search('산곡동 684-1'))['status'] == 'unavailable'


def test_r11_the_search_route_never_answers_500_on_an_odd_body():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app.modules.land.routers.analysis import create_land_router
    app = FastAPI()
    app.include_router(create_land_router(address_client=client_for(lambda request: httpx.Response(200, json={'response': {'status': 'OK', 'result': 'x'}}))))
    reply = TestClient(app).post('/api/v1/land/search', json={'query': '산곡동 684-1'})
    assert reply.status_code == 200 and reply.json()['status'] == 'none'


@pytest.mark.parametrize('typed, kind, name, main', [
    ('을지로 1가 1', 'lot', '을지로1가', 1), ('종로 1가 1', 'lot', '종로1가', 1), ('종로1가1', 'lot', '종로1가', 1),
    ('서울 중구 을지로 1가', 'area', '을지로1가', None), ('3.1대로 110', 'road', '3.1대로', 110), ('3·15대로 110', 'road', '3.15대로', 110),
])
def test_r12_r13_spaced_ga_numbers_and_dotted_road_names(typed, kind, name, main):
    query = classify(typed)
    assert (query.kind, query.name, query.main) == (kind, name, main)


def test_r13_a_dotted_road_name_matches_the_providers_middle_dot():
    status, rows = ranked('3.15대로 110', [item('4812514700100080008', '중앙동1가 8-8', '경상남도 창원시 마산합포구 3·15대로 110 (중앙동1가)')])
    assert status == 'unique' and rows[0]['pnu'] == '4812514700100080008'


def test_r14_a_count_after_a_word_ending_in_ga_or_ri_is_not_a_lot():
    from backend.app.modules.platform.routing.roles import site
    for text in ('우리 아이가 2명 있어요', '우리 아이가 2 있어요', '운동 3번 했어요', '거리 100미터'):
        assert site.find(text) is None, text
    assert site.locate('우리 2', {}) is None
    assert site.find('산곡동 684-1번지에서 봐요') == '산곡동 684-1'
    assert site.locate('을지로 1가 1', {}) == {'query': '을지로 1가 1'}


def test_r15_an_ambiguous_located_site_reaches_the_conversation():
    """routers/conversation.py keeps `located` when it is ambiguous; locate_site marks it so."""
    from backend.app.modules.platform.ask import locate_site

    class Addresses:
        async def resolve_address(self, address):
            return {'success': False, 'address': address, 'pnu': None, 'status': 'ambiguous', 'error': '여러 곳'}
    located = asyncio.run(locate_site('신촌동 1', addresses=Addresses()))
    assert located['ambiguous'] is True and located['pnu'] is None and located['coordinates'] is None
    source = open('backend/app/modules/platform/routers/conversation.py', encoding='utf-8').read()
    assert "located.get('ambiguous')" in source


def test_r17_one_deadline_and_a_call_budget(monkeypatch):
    import importlib
    module = importlib.import_module('backend.app.modules.land.vworld.search')  # the package re-exports `search` the function
    calls = []

    def busy(request):
        calls.append(request.url.params.get('type'))
        # Everything is "more than a page" and never the typed lot: every optional step is tried.
        return ok([item('1141011400100010001', '서울특별시 서대문구 신촌동 1-1')], total=5000)
    found = asyncio.run(client_for(busy).search('용인 신촌동 1'))
    assert len(calls) <= module.MAX_CALLS and found['status'] == 'ambiguous'

    async def slow(request):
        await asyncio.sleep(5)
        return ok([])
    monkeypatch.setattr(module, 'DEADLINE_S', 0.2)
    found = asyncio.run(client_for(slow).search('산곡동 684-1'))
    assert found['status'] == 'unavailable' and '오래' in found['error']
