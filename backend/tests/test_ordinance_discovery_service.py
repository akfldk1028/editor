"""`modules/law/ordinances`: jurisdictions from a registry address, every search page walked, candidates kept only
for the parcel's own governments and the edition in force on the date. Governments, names and ids below are
fixtures (갑도·을시…), not records of any live lookup."""
import asyncio
import json
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.modules.law.ordinances import jurisdiction, search, service
from backend.app.modules.platform.routers.ask import create_ask_router

ORIGIN = 'http://127.0.0.1:3003'
PNU = '9999901200100010001'  # sido 99, sigungu 99990 — no real jurisdiction carries these codes
TODAY = date(2026, 10, 9)


def row(name, issuer, mst, effective, oid=None, kind='조례', promulgated=None):
    return {'자치법규명': name, '지자체기관명': issuer, '자치법규일련번호': mst, '시행일자': effective, '자치법규ID': oid or f'id-{name}',
            '자치법규종류': kind, '공포일자': promulgated or effective, '자치법규상세링크': f'/DRF/lawService.do?OC=secret&target=ordin&MST={mst}'}


def paged(rows_by_query):
    """A fake law.go.kr: rows per (query, nw), 100 a page, totalCnt reported."""
    calls = []

    def fetch(params):
        calls.append(dict(params))
        rows = rows_by_query.get((params['query'], params['nw']), [])
        start = (params['page'] - 1) * 100
        return {'OrdinSearch': {'totalCnt': len(rows), 'law': rows[start:start + 100]}}
    fetch.calls = calls
    return fetch


@pytest.fixture(autouse=True)
def fresh_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(jurisdiction, 'ORDINANCE_DIR', tmp_path)
    search.clear_cache()
    yield
    search.clear_cache()


# ---------------- jurisdiction ----------------

def test_levels_come_from_the_registry_address_and_a_general_gu_is_only_a_note():
    plain = jurisdiction.levels_from_address('갑도 을시 정동 1-2')
    assert [(l['level'], l['name'], l['issuer']) for l in plain['levels']] == [('sido', '갑도', '갑도'), ('sigungu', '을시', '갑도 을시')]
    gu = jurisdiction.levels_from_address('갑광역시 병구 정동 1')
    assert [(l['name'], l['issuer']) for l in gu['levels']] == [('갑광역시', '갑광역시'), ('병구', '갑광역시 병구')]
    general = jurisdiction.levels_from_address('갑도 을시 병구 정동 1')
    assert [l['name'] for l in general['levels']] == ['갑도', '을시'] and '일반구' in general['notes'][0]
    assert [l['name'] for l in jurisdiction.levels_from_address('갑특별자치시 정읍 1')['levels']] == ['갑특별자치시']
    assert jurisdiction.levels_from_address('')['reason'] == 'address_not_parsable'
    assert jurisdiction.levels_from_address('정동 1-2')['levels'] == []


def test_snapshot_cross_check_confirms_or_fails_closed(tmp_path):
    (tmp_path / '99990.json').write_text(json.dumps({'sigungu_name': '을시', 'ordinance': {'issuer': '갑도 을시청'}}), encoding='utf-8')
    resolved = jurisdiction.resolve(PNU, '갑도 을시 정동 1-2')
    assert resolved['status'] == 'resolved'
    sido, sigungu = resolved['levels']
    assert (sido['code'], sido['check']) == ('99', 'address_only')
    assert (sigungu['code'], sigungu['check'], sigungu['issuer']) == ('99990', 'ordinance_snapshot_match', '갑도 을시청')
    (tmp_path / '99990.json').write_text(json.dumps({'sigungu_name': '병시', 'ordinance': {}}), encoding='utf-8')
    conflict = jurisdiction.resolve(PNU, '갑도 을시 정동 1-2')
    assert conflict['status'] == 'conflict' and '병시' in conflict['reason']
    assert jurisdiction.resolve(PNU, None)['reason'] == 'address_unavailable'


def test_a_general_gu_code_is_checked_through_its_city_snapshot(tmp_path):
    (tmp_path / '99990.json').write_text(json.dumps({'sigungu_name': '을시', 'ordinance': {'issuer': '갑도 을시'}}), encoding='utf-8')
    resolved = jurisdiction.resolve('9999501200100010001', '갑도 을시 병구 정동 1')
    assert resolved['levels'][1]['code'] == '99990' and resolved['levels'][1]['check'] == 'ordinance_snapshot_match'


# ---------------- search ----------------

def test_every_page_is_walked_and_completeness_is_truthful():
    rows = [row(f'을시 조례 {i}', '갑도 을시', str(i), '20200101') for i in range(250)]
    fetch = paged({('q', 1): rows})
    result = search.search_all('q', 'current', fetch_json=fetch)
    assert (result['pages'], result['total'], result['complete'], result['error']) == (3, 250, True, None)
    assert len(result['rows']) == 250 and 'OC=' not in result['rows'][0]['자치법규상세링크']
    assert [c['page'] for c in fetch.calls] == [1, 2, 3]
    limited = search.search_all('q2', 'current', fetch_json=paged({('q2', 1): rows}), page_limit=2)
    assert limited['complete'] is False and limited['error'].startswith('page_limit_reached') and len(limited['rows']) == 200


def test_search_failures_are_reported_without_the_credential_and_not_cached():
    def fail(params):
        raise OSError('https://www.law.go.kr/DRF/lawSearch.do?OC=secret&target=ordin timed out')
    result = search.search_all('q', 'history', fetch_json=fail)
    assert result['complete'] is False and 'secret' not in result['error'] and 'OC=***' in result['error']
    assert search.search_all('q', 'history', fetch_json=lambda p: {'nope': 1})['error'] == 'ValueError: invalid official ordinance response'
    empty = search.search_all('none', 'current', fetch_json=lambda p: {'OrdinSearch': {'totalCnt': 0}})
    assert empty == {'rows': [], 'pages': 1, 'total': 0, 'complete': True, 'error': None}


def test_a_complete_search_is_reused_from_the_cache():
    fetch = paged({('q', 1): [row('을시 건축 조례', '갑도 을시', '1', '20200101')]})
    search.search_all('q', 'current', fetch_json=fetch)
    search.search_all('q', 'current', fetch_json=fetch)
    assert len(fetch.calls) == 1


# ---------------- service ----------------

def fixture_results():
    return {
        ('을시 도시계획 조례', 1): [row('을시 도시계획 조례', '갑도 을시', '2001', '20250925', oid='A'),
                                 row('을시 도시계획 조례 시행규칙', '갑도 을시', '2002', '20241209', oid='A-rule', kind='규칙'),
                                 row('을시 지하도상가 조례', '갑도 을시', '2003', '20230413', oid='X')],
        ('을시 도시계획 조례', 2): [row('을시 도시계획 조례', '갑도 을시', '1001', '20230101', oid='A'),
                                 row('을시 도시계획 조례', '갑도 을시', '1000', '20200101', oid='A'),
                                 row('을시도시계획조례', '갑도 을시', '900', '20030712', oid='OLD')],
        ('을시 건축 조례', 1): [row('을시 건축 조례', '갑도 을시', '3001', '20250415', oid='B'),
                             row('을시 건축 조례', '병도 을시', '3999', '20250415', oid='B-other'),
                             row('을시 녹색건축물 조성 지원 조례', '갑도 을시', '3002', '20220101', oid='C')],
        ('을시 주차장 설치 및 관리 조례', 1): [row('을시 주차장 설치 및 관리 조례', '갑도 을시', '4001', '20270101', oid='D')],
        ('을시 주차장 설치 및 관리 조례', 2): [row('을시 주차장 설치 및 관리 조례', '갑도 을시', '4000', '20210101', oid='D'),
                                        row('을시 주차장 조례', '갑도 을시', '3900', '20100101', oid='D-old')],
        ('갑도 건축 조례', 1): [row('갑도 건축기본조례', '갑도', '5001', '20240320', oid='E'),
                             row('을시 건축 조례', '갑도 을시', '3001', '20250415', oid='B')],
        ('갑도 경관 조례', 1): [row('갑도 경관 조례', '갑도', '6001', '20300101', oid='F')],
    }


REFS = [{'item_id': 'bcr-cap', 'title': '건폐율 상한', 'instrument': '을시 도시계획 조례', 'article': '제42조', 'status': 'applies'},
        {'item_id': 'parking', 'title': '부설주차장 설치기준', 'instrument': '을시 주차장 설치 및 관리 조례', 'article': None, 'status': 'conditional'},
        {'item_id': 'adjacent', 'title': '인접대지 이격', 'instrument': '건축조례', 'article': None, 'status': 'applies'}]


def discover(assessment_date='2026-10-09', refs=REFS, topics=(), address='갑도 을시 정동 1-2', results=None, fetch=None):
    fetch = fetch or paged(results if results is not None else fixture_results())
    out = service.discover_for_parcel(PNU, assessment_date, address=address, refs=refs, topics=list(topics), fetch_json=fetch, today=TODAY)
    return out, fetch


def test_topics_come_from_cited_ordinances_minus_their_government_and_the_statutory_delegations():
    levels = jurisdiction.levels_from_address('갑도 을시 정동 1')['levels']
    topics = service.topics_from_refs(REFS, levels, ['경관'])
    assert [t['topic'] for t in topics] == ['도시계획', '주차장 설치 및 관리', '건축', '주차장', '경관']
    assert topics[0]['from'] == ['을시 도시계획 조례'] and topics[2]['from'] == ['건축조례']
    assert topics[3]['from'] == ['statutory delegation'] and topics[4]['from'] == ['caller']


def test_candidates_are_kept_only_for_the_parcels_governments_and_the_edition_in_force():
    out, fetch = discover(topics=['경관'])
    assert out['jurisdiction']['status'] == 'resolved' and out['coverage_complete'] is False
    asked = {(c['query'], c['nw']) for c in fetch.calls}
    # Pass 1 current for every level × topic; pass 2 history only for the editions starting after the date; no topic history today.
    assert {('을시 도시계획 조례', 1), ('갑도 건축 조례', 1), ('갑도 경관 조례', 1), ('을시 주차장 설치 및 관리 조례', 2), ('갑도 경관 조례', 2)} <= asked
    assert ('을시 도시계획 조례', 2) not in asked and ('갑도 건축 조례', 2) not in asked
    names = {o['name']: o for o in out['ordinances']}
    # The other province's 을시 is a different government: excluded by name, never silently dropped.
    assert '을시 건축 조례' in names and names['을시 건축 조례']['issuer'] == '갑도 을시'
    assert {'name': '을시 건축 조례', 'issuer': '병도 을시', 'reason': 'jurisdiction_mismatch'} in out['excluded']
    plan = names['을시 도시계획 조례']
    assert (plan['edition_id'], plan['effective_date'], plan['url'], plan['editions_seen']) == ('2001', '2025-09-25', service.ORDINANCE_URL + '2001', 1)
    assert plan['status'] == {'jurisdiction': 'verified', 'edition': 'dated', 'body': 'not_fetched', 'in_force': 'current', 'relevance': 'exact'}
    assert plan['review_refs'] == [{'item_id': 'bcr-cap', 'title': '건폐율 상한', 'article': '제42조', 'status': 'applies', 'match': 'exact'}]
    assert names['을시 도시계획 조례 시행규칙']['kind'] == '규칙' and names['을시 도시계획 조례 시행규칙']['status']['relevance'] == 'topic'
    # The current edition starts after the date: its own history gives the edition in force; another id in that history is ignored.
    parking = names['을시 주차장 설치 및 관리 조례']
    assert (parking['edition_id'], parking['editions_seen']) == ('4000', 2) and parking['future_editions'] == [{'edition_id': '4001', 'effective_date': '2027-01-01'}]
    assert '을시 주차장 조례' not in names
    assert {'name': '갑도 경관 조례', 'issuer': '갑도', 'reason': 'not_yet_effective', 'first_effective_date': '2030-01-01'} in out['excluded']
    # The generic '건축조례' attaches to the innermost government's one 건축 조례; the 녹색건축물 one is topic-only.
    assert names['을시 건축 조례']['review_refs'][0]['match'] == 'generic_name'
    assert names['을시 녹색건축물 조성 지원 조례']['review_refs'] == []
    assert '을시 지하도상가 조례' not in names and out['search']['other_results'] == 1
    assert out['search']['complete'] is True and out['search']['errors'] == [] and out['historical'] == []
    assert out['ordinances'][0]['level'] == 'sigungu' and out['ordinances'][-1]['level'] == 'sido'


def test_an_earlier_assessment_date_selects_the_historical_edition_and_lists_history_only_ordinances_apart():
    out, fetch = discover(assessment_date='2024-06-01')
    plan = next(o for o in out['ordinances'] if o['name'] == '을시 도시계획 조례')
    assert (plan['edition_id'], plan['effective_date']) == ('1001', '2023-01-01') and plan['future_editions'][0]['edition_id'] == '2001'
    assert ('을시 건축 조례', 2) in {(c['query'], c['nw']) for c in fetch.calls}
    old = {o['name']: o for o in out['historical']}
    assert set(old) == {'을시도시계획조례', '을시 주차장 조례'}
    assert old['을시도시계획조례']['status'] == {'jurisdiction': 'verified', 'edition': 'history_only', 'body': 'not_fetched', 'in_force': 'unknown', 'relevance': 'exact'}
    assert all(o['name'] != '을시도시계획조례' for o in out['ordinances'])


def test_a_generic_name_stays_unattached_when_two_ordinances_could_be_meant():
    results = fixture_results()
    results[('을시 건축 조례', 1)].append(row('을시 공공건축조례', '갑도 을시', '3003', '20200101', oid='G'))
    out, _ = discover(results=results)
    for ordinance in out['ordinances']:
        assert all(ref['match'] != 'generic_name' for ref in ordinance['review_refs']), ordinance['name']


def test_a_generic_name_attaches_to_the_province_ordinance_when_the_district_has_none():
    # A 자치구 without its own 건축 조례: the 시도's one is the only ordinance the generic name can mean.
    results = {('병구 건축 조례', 1): [row('병구 건축물관리 조례', '갑광역시 병구', '1', '20240101', oid='M')],
               ('갑광역시 건축 조례', 1): [row('갑광역시 건축 조례', '갑광역시', '2', '20250101', oid='S'), row('갑광역시 건축 기본 조례', '갑광역시', '3', '20250101', oid='S2')]}
    out, _ = discover(refs=[{'item_id': 'adjacent', 'title': '인접대지 이격', 'instrument': '건축조례', 'article': None, 'status': 'applies'}],
                      address='갑광역시 병구 정동 1', results=results)
    attached = {o['name']: [r['match'] for r in o['review_refs']] for o in out['ordinances']}
    assert attached == {'병구 건축물관리 조례': [], '갑광역시 건축 조례': ['generic_name'], '갑광역시 건축 기본 조례': []}
    # When the district has its own, the district's wins over the province's.
    results[('병구 건축 조례', 1)].append(row('병구 건축 조례', '갑광역시 병구', '4', '20240101', oid='D'))
    search.clear_cache()
    out, _ = discover(refs=[{'item_id': 'adjacent', 'title': '인접대지 이격', 'instrument': '건축조례', 'article': None, 'status': 'applies'}],
                      address='갑광역시 병구 정동 1', results=results)
    attached = {o['name']: [r['match'] for r in o['review_refs']] for o in out['ordinances']}
    assert attached['병구 건축 조례'] == ['generic_name'] and attached['갑광역시 건축 조례'] == []


def test_search_errors_and_page_limits_surface_and_nothing_claims_completeness():
    results = fixture_results()

    def fetch(params):
        if params['query'] == '갑도 건축 조례':
            raise OSError('?OC=secret down')
        rows = results.get((params['query'], params['nw']), [])
        return {'OrdinSearch': {'totalCnt': len(rows), 'law': rows}}
    out, _ = discover(fetch=fetch)
    assert out['search']['complete'] is False and out['search']['errors'] == ['갑도 건축 조례 (current): OSError: ?OC=*** down']
    assert any(o['name'] == '을시 도시계획 조례' for o in out['ordinances'])


def test_an_unresolved_or_conflicting_jurisdiction_searches_nothing(tmp_path):
    out, fetch = discover(address=None)
    assert out['jurisdiction']['status'] == 'unresolved' and out['ordinances'] == [] and fetch.calls == []
    (tmp_path / '99990.json').write_text(json.dumps({'sigungu_name': '병시', 'ordinance': {}}), encoding='utf-8')
    out, fetch = discover()
    assert out['jurisdiction']['status'] == 'conflict' and fetch.calls == []


# ---------------- door ----------------

def client(monkeypatch):
    monkeypatch.setenv('LAW_OC', 'test-oc')
    fetch = paged(fixture_results())
    monkeypatch.setattr(search, 'fetch_page', lambda params, *, oc, timeout=30.0: fetch(params))

    async def resolver(pnu):
        return '갑도 을시 정동 1-2'
    monkeypatch.setattr(service, 'resolve_address', resolver)
    app = FastAPI()
    app.include_router(create_ask_router(ORIGIN))
    return TestClient(app), fetch


def test_the_door_returns_the_parcels_ordinances_for_the_same_origin_only(monkeypatch):
    api, fetch = client(monkeypatch)
    body = {'pnu': PNU, 'assessment_date': '2026-10-09', 'refs': [{'instrument': '을시 도시계획 조례', 'item_id': 'bcr-cap', 'article': '제42조'}]}
    response = api.post('/ordinances', json=body, headers={'Origin': ORIGIN})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['jurisdiction']['address'] == '갑도 을시 정동 1-2' and data['coverage_complete'] is False
    assert any(o['name'] == '을시 도시계획 조례' and o['review_refs'][0]['item_id'] == 'bcr-cap' for o in data['ordinances'])
    assert api.post('/ordinances', json=body, headers={'Origin': 'http://evil.test'}).status_code == 403
    assert api.post('/ordinances', json={**body, 'pnu': '123'}, headers={'Origin': ORIGIN}).status_code == 422
    assert api.post('/ordinances', json={**body, 'assessment_date': '2026-13-01'}, headers={'Origin': ORIGIN}).status_code == 422


def test_the_body_door_returns_the_verified_whole_text(monkeypatch):
    api, _ = client(monkeypatch)
    from backend.app.modules.law.ordinances import body as whole
    record = {'LawService': {'자치법규기본정보': {'자치법규명': '을시 도시계획 조례', '자치법규ID': 'A', '자치법규일련번호': '2001', '시행일자': '20250925'},
                             '조문': {'조': [{'조문번호': ['004200', '004200'], '조문여부': 'Y', '조제목': '건폐율', '조내용': '제42조(건폐율) 60퍼센트'}]}}}
    monkeypatch.setattr(whole, 'fetch_service', lambda mst, *, oc, timeout=60.0: record)
    whole.clear_cache()
    response = api.post('/ordinances/body', json={'name': '을시 도시계획 조례', 'edition_id': '2001', 'assessment_date': '2026-10-09'}, headers={'Origin': ORIGIN})
    assert response.status_code == 200 and response.json()['articles'][0]['article'] == '제42조'
    assert api.post('/ordinances/body', json={'name': '을시 도시계획 조례', 'edition_id': 'abc', 'assessment_date': '2026-10-09'}, headers={'Origin': ORIGIN}).status_code == 422
    assert api.post('/ordinances/body', json={'name': '을시 도시계획 조례', 'edition_id': '2001', 'assessment_date': '2026-10-09'}, headers={'Origin': 'http://evil.test'}).status_code == 403


def test_without_an_oc_the_door_says_so_instead_of_searching(monkeypatch):
    monkeypatch.delenv('LAW_OC', raising=False)
    monkeypatch.delenv('LAW_API_OC', raising=False)
    out = asyncio.run(service.discover(PNU, '2026-10-09', resolver=None))
    assert out['error'] == 'law_oc_not_configured' and out['ordinances'] == []
