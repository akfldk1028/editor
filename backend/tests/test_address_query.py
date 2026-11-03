"""Site search: normalize, classify and rank (pure), and the provider statuses over a mocked VWorld."""
import asyncio

import httpx
import pytest

from backend.app.modules.land.address_query import classify, lot_parts, normalize, region_matches, road_parts, valid_pnu
from backend.app.modules.land.address_rank import address_candidates, place_candidates, rank_addresses


@pytest.mark.parametrize('typed, normalized', [
    ('산곡동684-1', '산곡동 684-1'),
    ('산곡동 684번지 1', '산곡동 684-1'),
    ('산곡동 684 번지', '산곡동 684'),
    ('테헤란로152', '테헤란로 152'),
    ('서울 중구 세종대로110', '서울 중구 세종대로 110'),
    ('서울 중구 을지로1가 1', '서울 중구 을지로1가 1'),
    ('전북특별자치도 전주시 완산구 효자동2가 1', '전북특별자치도 전주시 완산구 효자동2가 1'),
    ('테헤란로10길 10', '테헤란로10길 10'),
    ('청운동 산1', '청운동 산 1'),
    ('청운동 산 1', '청운동 산 1'),
    ('  산곡동   684 - 1. ', '산곡동 684-1'),
    ('산곡동 ６８４－１', '산곡동 684-1'),
    ('서울특별시 중구 세종대로 110 (태평로1가)', '서울특별시 중구 세종대로 110 태평로1가'),
    ('서울 중구 세종대로 11O', '서울 중구 세종대로 11O'),
])
def test_normalize_spaces_numbers_and_san_without_fixing_typos(typed, normalized):
    assert normalize(typed) == normalized


# Every query from the 2026-11-03 measurement (r1t: 34, r6u: 8) and its class.
CLASSES = [
    ('4115011300106840001', 'pnu'), ('4115011300206840001', 'pnu'), ('1111010100100010000', 'pnu'),
    ('41150-11300-1-0684-0001', 'pnu'),
    ('경기도 의정부시 산곡동 684-1', 'lot'), ('의정부시 산곡동 684-1', 'lot'), ('산곡동 684-1', 'lot'),
    ('의정부 산곡동 684-1', 'lot'), ('경기 의정부시 산곡동 684-1', 'lot'), ('산곡동684-1', 'lot'), ('산곡동 684번지 1', 'lot'),
    ('서울특별시 중구 세종대로 110', 'road'), ('세종대로 110', 'road'), ('서울 중구 세종대로110', 'road'),
    ('서울 중구 세종로 110', 'road'), ('서울 강남구 테헤란로 152', 'road'), ('테헤란로152', 'road'),
    ('서울 중구 을지로1가 1', 'lot'), ('서울 중구 을지로1가', 'area'), ('서울특별시 종로구 청운동 산 1', 'lot'),
    ('강원특별자치도 평창군 대관령면 횡계리 1', 'lot'), ('강원도 평창군 대관령면 횡계리 1', 'lot'),
    ('제주특별자치도 제주시 첨단로 242', 'road'), ('부산 해운대구 우동 1408', 'lot'), ('세종특별자치시 한누리대로 2130', 'road'),
    ('전북특별자치도 전주시 완산구 효자동2가 1', 'lot'), ('서울시청', 'place'), ('강남역', 'place'), ('롯데월드타워', 'place'),
    ('의정부시청', 'place'), ('판교역로 235', 'road'), ('경기도 성남시 분당구 판교역로 235', 'road'), ('대구 수성구 범어동', 'area'),
    ('광주광역시 서구 내방로 111', 'road'),
    ('신촌동 1', 'lot'), ('중앙동 1', 'lot'), ('산곡동 100', 'lot'), ('산곡동 684-1 인천', 'lot'), ('중앙로 1', 'road'),
    ('서울 중구 세종대로 11O', 'road'), ('서울 중구 세종대로 1100', 'road'), ('강남대로 396', 'road'),
    # and the shapes named in the redesign
    ('중앙로1가 1', 'lot'), ('테헤란로10길 10', 'road'), ('판교로255번길 9', 'road'), ('대구', 'area'), ('수성구', 'area'),
]


@pytest.mark.parametrize('typed, kind', CLASSES)
def test_every_measured_query_has_its_class(typed, kind):
    assert classify(typed).kind == kind


def test_lot_parts_carry_san_main_sub_and_the_regions_around_them():
    lot = classify('서울특별시 종로구 청운동 산 1')
    assert (lot.name, lot.san, lot.main, lot.sub, lot.context, lot.regions) == ('청운동', True, 1, None, ['서울특별시', '종로구'], ['서울특별시', '종로구'])
    tail = classify('산곡동 684-1 인천')
    assert (tail.name, tail.main, tail.sub, tail.regions) == ('산곡동', 684, 1, ['인천'])
    assert tail.provider_text() == '산곡동 684-1' and tail.provider_text(with_context=True) == '인천광역시 산곡동 684-1'
    digit_dong = classify('서울 중구 을지로1가 1')
    assert (digit_dong.name, digit_dong.main) == ('을지로1가', 1)


def test_a_road_keeps_an_unreadable_number_unreadable():
    typo = classify('서울 중구 세종대로 11O')
    assert (typo.kind, typo.name, typo.main, typo.number_text) == ('road', '세종대로', None, None)
    road = classify('서울 중구 세종대로 11-1')
    assert (road.name, road.main, road.sub, road.regions) == ('세종대로', 11, 1, ['서울', '중구'])


def test_pnu_hyphens_and_the_san_digit():
    assert classify('41150-11300-1-0684-0001').pnu == '4115011300106840001'
    assert classify('4115011300106840001').valid and classify('4115011300206840001').valid
    bad = classify('4115011300306840001')
    assert bad.kind == 'pnu' and not bad.valid and not valid_pnu('4115011300006840001')


def test_area_levels_and_sido_rewrites():
    assert classify('대구 수성구 범어동').level == 'L4'
    assert classify('대구 수성구').level == 'L2'
    assert classify('강원도').level == 'L1'
    assert classify('강원도 평창군').provider_text() == '강원특별자치도 평창군'
    assert classify('전라남도 목포시').provider_text() == '전남광주통합특별시 목포시'
    # Bare 광주 is also 경기도 광주시: never rewritten.
    assert classify('광주 오포읍').provider_text() == '광주 오포읍'


def test_region_words_match_their_short_and_old_forms():
    words = '경기도 의정부시 산곡동 684-1'.split()
    assert region_matches('의정부', words) and region_matches('경기', words) and region_matches('의정부시', words)
    assert not region_matches('인천', words)
    assert region_matches('강원도', '강원특별자치도 평창군'.split()) and region_matches('광주광역시', '전남광주통합특별시 서구'.split())
    assert region_matches('광주', '경기도 광주시 오포읍'.split())


def test_reading_provider_address_text():
    assert lot_parts('경기도 성남시 수정구 신촌동 산 1-3') == ('신촌동', True, 1, 3)
    assert lot_parts('서울특별시 중구 태평로1가 31대') == ('태평로1가', False, 31, 0)
    assert road_parts('서울특별시 중구 세종대로 110 (태평로1가)') == ('세종대로', 110, None)
    assert road_parts('강원특별자치도 원주시 중앙로 1-2 (인동)') == ('중앙로', 1, 2)


def item(pnu, parcel, road='', x=127.0, y=37.5):
    return {'id': pnu, 'address': {'parcel': parcel, 'road': road}, 'point': {'x': str(x), 'y': str(y)}}


def ranked(text, items, bbox=None):
    query = classify(text)
    return rank_addresses(query, address_candidates(query, items, bbox))


def test_one_exact_lot_is_unique():
    status, rows = ranked('의정부 산곡동 684-1', [item('4115011300106840001', '경기도 의정부시 산곡동 684-1')])
    assert status == 'unique' and rows[0]['pnu'] == '4115011300106840001' and rows[0]['exact'] and 'substituted' not in rows[0]


def test_the_same_lot_in_several_places_is_ambiguous():
    status, rows = ranked('신촌동 1', [
        item('4113110900100010001', '경기도 성남시 수정구 신촌동 1-1'), item('4148012000100010000', '경기도 파주시 신촌동 1'),
        item('3011013100100010000', '대전광역시 동구 신촌동 1'), item('4113111100100010000', '경기도 성남시 수정구 심곡동 1'),
        item('1141011400200010000', '서울특별시 서대문구 신촌동 산 1')])
    assert status == 'ambiguous'
    assert [row['pnu'] for row in rows] == ['4148012000100010000', '3011013100100010000', '1141011400200010000']
    assert [row['exact'] for row in rows] == [True, True, False] and rows[2]['substituted']


def test_a_lot_whose_only_twin_is_a_san_lot_elsewhere_is_ambiguous():
    status, rows = ranked('산곡동 100', [item('2823710300101000000', '인천광역시 부평구 산곡동 100'),
                                       item('4115011300201000000', '경기도 의정부시 산곡동 산 100')])
    assert status == 'ambiguous' and [row['pnu'] for row in rows] == ['2823710300101000000', '4115011300201000000']


def test_a_missing_lot_is_offered_as_a_marked_substitute_never_as_the_answer():
    status, rows = ranked('서울특별시 종로구 청운동 산 1', [
        item('1111010100100010000', '서울특별시 종로구 청운동 1'), item('1111010100200010001', '서울특별시 종로구 청운동 산 1-1')])
    assert status == 'ambiguous' and rows[0]['pnu'] == '1111010100200010001' and rows[0]['substituted'] and not rows[0]['exact']
    status, rows = ranked('서울 중구 을지로1가 1', [item('1114010500100010001', '서울특별시 중구 을지로2가 1-1')])
    assert status == 'ambiguous' and rows[0]['substituted']


def test_a_contradicting_region_turns_an_exact_number_into_a_substitute():
    status, rows = ranked('산곡동 684-1 인천', [item('4115011300106840001', '경기도 의정부시 산곡동 684-1')])
    assert status == 'ambiguous' and not rows[0]['exact'] and rows[0]['substituted']


def test_roads_match_name_and_building_number_and_collapse_entrances():
    hall = [item('1114010300100310000', '태평로1가 31', '서울특별시 중구 세종대로 110 (태평로1가)'),
            item('1114010300100310000', '태평로1가 31', '서울특별시 중구 세종대로 110 (태평로1가)', x=127.1)]
    status, rows = ranked('서울 중구 세종대로110', hall)
    assert status == 'unique' and rows[0]['pnu'] == '1114010300100310000' and rows[0]['road'].startswith('서울특별시 중구 세종대로 110')
    status, rows = ranked('중앙로 1', [item('5113010400102640022', '인동 264-22', '강원특별자치도 원주시 중앙로 1 (인동)'),
                                     item('5111010100100150000', '봉의동 15', '강원특별자치도 춘천시 중앙로 1 (봉의동)')])
    assert status == 'ambiguous' and all(row['exact'] for row in rows)
    status, rows = ranked('서울 중구 세종대로 11O', [item('1114011800100060023', '남대문로5가 6-23', '서울특별시 중구 세종대로 11 (남대문로5가)')])
    assert status == 'ambiguous' and rows[0]['substituted']


def test_distance_to_the_map_orders_equally_good_matches():
    items = [item('3011013100100010000', '대전광역시 동구 신촌동 1', x=127.5, y=36.4),
             item('4148012000100010000', '경기도 파주시 신촌동 1', x=126.7, y=37.7)]
    _, rows = ranked('신촌동 1', items, bbox=[126.6, 37.6, 126.8, 37.8])
    assert rows[0]['pnu'] == '4148012000100010000'


def test_places_group_by_lot_and_prefer_the_named_building_over_a_bus_stop():
    hits = [
        {'title': '강남역', 'category': '도로시설 > 버스정류장', 'address': {'parcel': '서울특별시 강남구 역삼동 804', 'road': ''}, 'point': {'x': '127.03', 'y': '37.50'}},
        {'title': '강남역', 'category': '철도시설 > 철도/지하철 > 지하철역', 'address': {'parcel': '서울특별시 강남구 역삼동 858', 'road': ''}, 'point': {'x': '127.02', 'y': '37.49'}},
        {'title': '서울특별시청', 'category': '지방행정기관', 'address': {'parcel': '서울특별시 중구 태평로1가 31대', 'road': ''}, 'point': {'x': '126.97', 'y': '37.56'}},
    ]
    rows = place_candidates(classify('강남역'), hits)
    assert rows[0]['jibun'] == '서울특별시 강남구 역삼동 858' and rows[0]['exact'] and rows[0]['kind'] == 'place'
    assert place_candidates(classify('서울특별시청'), hits)[0]['jibun'] == '서울특별시 중구 태평로1가 31'
    spaced = [{'title': '한화오벨리스크', 'address': {'parcel': '서울특별시 서초구 서초동 1327-27 대'}, 'point': {'x': '127.02', 'y': '37.49'}}]
    assert place_candidates(classify('한화오벨리스크'), spaced)[0]['jibun'] == '서울특별시 서초구 서초동 1327-27'


# --- the provider door, mocked ---------------------------------------------------------------------

def client_for(handle):
    from backend.app.modules.land.vworld import VworldClient
    return VworldClient('private-key', transport=httpx.MockTransport(handle))


def ok(items, total=None):
    return httpx.Response(200, json={'response': {'status': 'OK', 'record': {'total': str(total or len(items))}, 'result': {'items': items}}})


def test_key_and_quota_refusals_are_unavailable_not_not_found():
    for code in ('INVALID_KEY', 'OVER_REQUEST_LIMIT'):
        def refuse(request, code=code):
            return httpx.Response(200, json={'response': {'status': 'ERROR', 'error': {'code': code, 'text': 'x'}}})
        found = asyncio.run(client_for(refuse).search('산곡동 684-1'))
        assert found['status'] == 'unavailable' and 'private-key' not in str(found)
        assert ('한도' in found['error']) if code == 'OVER_REQUEST_LIMIT' else (code in found['error'])
    from backend.app.modules.land.vworld import VworldClient
    assert asyncio.run(VworldClient('').search('산곡동 684-1'))['status'] == 'unavailable'


def test_search_runs_the_lot_class_and_returns_the_route_shape():
    seen = []

    def handle(request):
        params = request.url.params
        seen.append((params.get('type'), params.get('category'), params.get('query')))
        if params.get('type') == 'address':
            return ok([item('4115011300106840001', '경기도 의정부시 산곡동 684-1', x=127.108, y=37.730)])
        return httpx.Response(200, json={'response': {'status': 'NOT_FOUND'}})

    found = asyncio.run(client_for(handle).search('의정부 산곡동684-1'))
    assert found['status'] == 'unique' and found['kind'] == 'lot' and found['normalized'] == '의정부 산곡동 684-1'
    assert found['candidates'][0] == {'pnu': '4115011300106840001', 'kind': 'lot', 'jibun': '경기도 의정부시 산곡동 684-1', 'road': None,
                                      'label': '경기도 의정부시 산곡동 684-1', 'point': [127.108, 37.73], 'exact': True}
    assert ('address', 'parcel', '산곡동 684-1') in seen and ('place', None, '의정부 산곡동 684-1') in seen


def test_getcoord_is_kept_only_when_it_answers_what_was_typed():
    def handle(request, refined_number):
        if request.url.path.endswith('/search'):
            return httpx.Response(200, json={'response': {'status': 'NOT_FOUND'}})
        return httpx.Response(200, json={'response': {'status': 'OK', 'result': {'point': {'x': '127', 'y': '37'}}, 'refined': {
            'text': f'서울특별시 종로구 청운동 산 {refined_number}',
            'structure': {'level4L': '청운동', 'level4LC': '1111010100200010001', 'level5': refined_number}}}})
    substituted = asyncio.run(client_for(lambda request: handle(request, '1-1')).search('청운동 산 1'))
    assert substituted['status'] == 'none'
    same = asyncio.run(client_for(lambda request: handle(request, '1')).search('청운동 산 1'))
    assert same['status'] == 'unique' and same['candidates'][0]['pnu'] == '1111010100200010001'


def test_chat_claims_the_address_shapes_the_old_patterns_missed():
    from backend.app.modules.platform.routing.roles import site
    for text in ('서울 중구 을지로1가 1', '산곡동684-1', '테헤란로152', '산곡동 684번지 1', '41150-11300-1-0684-0001',
                 '전북특별자치도 전주시 완산구 효자동2가 1', '테헤란로10길 10'):
        assert site.locate(text, {}) == {'query': text}, text
    for text in ('산곡동 684-1 법규 검토해줘', '용적률 300', '자연녹지지역 건폐율 20', '41150-11300-3-0684-0001'):
        assert site.locate(text, {}) is None, text
    assert site.find('을지로1가 1에 지으려면') == '을지로1가 1'
    assert site.find('산곡동684-1에 어린이집을 지으려고 해요') == '산곡동 684-1'
    assert site.find('테헤란로152 근처 대지') == '테헤란로 152'
