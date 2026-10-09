"""The lot's review list (analysis.review): provisions grouped, why they apply, four statuses, gaps kept."""
import asyncio

from backend.app.modules.land.review import build, build_review
from backend.app.modules.land.review.refs import parse
from backend.app.modules.regulations import overlays


def test_article_strings_become_structured_references():
    assert [(r['instrument'], r['kind'], r['article'], r['clause']) for r in parse('건축법 제61조제1항, 시행령 제86조제1항 (2023.9.12 개정)')] == [
        ('건축법', 'act', '제61조', '제1항'), ('건축법 시행령', 'decree', '제86조', '제1항')]
    assert [r['article'] for r in parse('건축법 제46-47조')] == ['제46조', '제47조']
    assert parse('국토계획법 §76, 시행령 §71')[1]['instrument'] == '국토의 계획 및 이용에 관한 법률 시행령'
    assert parse('주차장법 제19조; 의정부시 주차장 설치 및 관리 조례 부설주차장 설치기준 별표')[-1] == {
        'instrument': '의정부시 주차장 설치 및 관리 조례', 'kind': 'ordinance', 'article': None, 'clause': None}
    assert parse(None) == [] and parse('') == []


NAMES = ['제1종일반주거지역', '과밀억제권역', '공공주택지구', '지구단위계획구역', '가축사육제한구역', '상대보호구역']


def analysis():
    return {
        'zone_info': {'zones': ['제1종일반주거지역'], 'unmatched': NAMES[1:]},
        'land_info': {'land_area_m2': 279.9},
        'regulations': {
            'bcr': {'limit_pct': None, 'article': '의정부시 도시계획 조례 제42조', 'national_ceiling_pct': 60},
            'far': {'limit_pct': None, 'article': '의정부시 도시계획 조례 제46조', 'national_ceiling_pct': 200},
            'sunlight_setback': {'applies': True, 'rules': [{'condition': 'H <= 10m', 'setback_m': 1.5}], 'article': '건축법 제61조제1항, 시행령 제86조제1항'},
            'landscaping': {'threshold_m2': 200, 'tiers': [{'min_floor_area_m2': 0, 'min_pct': 5}], 'article': '의정부시 건축 조례 제29조'},
            'extended': {},
        },
        'overlay_regulations': overlays.resolve_overlays(NAMES),
        'assessment': {'municipal_coverage': {'sources': [{'name': '의정부시 도시계획 조례', 'url': 'https://law.go.kr/x', 'edition_id': '2072835', 'effective_date': '20250925'}],
                                              'missing_evidence': ['unresolved_zoning:공공주택지구', 'missing_ordinance_snapshot']}},
    }


def test_review_groups_reasons_statuses_and_gaps_for_one_lot():
    review = build(analysis(), assessment_date='2026-10-09')
    by_id = {item['id']: item for item in review['items']}
    assert [g['id'] for g in review['groups']] == ['use', 'bcr_far', 'height_sunlight', 'road_setback', 'parking_landscape', 'district']
    assert by_id['sunlight']['status'] == 'applies' and by_id['sunlight']['group'] == 'height_sunlight'
    assert by_id['landscaping']['status'] == 'applies' and '279.9㎡' in by_id['landscaping']['reason']
    assert by_id['bcr-cap']['status'] == 'needs_check' and '60% 이내' in by_id['bcr-cap']['reason']
    ordinance = next(r for r in by_id['bcr-cap']['refs'] if r['kind'] == 'ordinance')
    assert (ordinance['edition_id'], ordinance['effective_date'], ordinance['url']) == ('2072835', '20250925', 'https://law.go.kr/x')
    assert by_id['district-공공주택지구']['status'] == 'needs_source'
    assert by_id['district-지구단위계획구역']['status'] == 'needs_source'
    assert by_id['district-상대보호구역']['status'] == 'needs_check' and '교육환경' in by_id['district-상대보호구역']['refs'][0]['instrument']
    assert by_id['district-가축사육제한구역']['status'] == 'conditional'
    assert 'split-zoning' not in by_id, 'one 용도지역: the other designations are not zones'
    gaps = [gap['what'] for gap in review['gaps']]
    assert any('지구단위계획 결정도서' in g for g in gaps) and any('missing_ordinance_snapshot' in g for g in gaps)
    assert not any('공공주택지구' in g and '상한표' in g for g in gaps), 'it has its own item'


def test_article_texts_attach_only_on_an_exact_match_and_a_miss_is_a_gap_not_an_absence():
    class Client:
        async def search_queries(self, queries, limit=5, timeout=None, *, filter_results=True):
            rows = {'건축법 제61조': [{'law_name': '건축법', 'law_type': '법률', 'article': '제61조', 'content': '일조 원문', 'hang_id': '건축법::제61조::①'},
                                     {'law_name': '건축법', 'law_type': '법률', 'article': '제62조', 'content': '옆 조문', 'hang_id': 'x'}]}
            return {'articles': [{'query': q, 'results': rows[q]} for q in queries if q in rows], 'errors': []}

    review = asyncio.run(build_review(analysis(), Client(), assessment_date='2026-10-09'))
    sunlight = next(item for item in review['items'] if item['id'] == 'sunlight')
    act, decree = sunlight['refs']
    assert (act['text'], act['text_status'], act['hang_ids']) == ('일조 원문', 'found', ['건축법::제61조::①'])
    assert decree['text'] is None and decree['text_status'] == 'needs_source' and decree['text_gap']
    assert review['search'] == {'connected': True, 'errors': []}
    assert any('건축법 시행령 제86조' in gap['what'] for gap in review['gaps'])
    offline = asyncio.run(build_review(analysis(), None))
    assert offline['search']['connected'] is False and offline['search']['errors'] == ['Law search is not configured']


def test_law_search_reads_a_numeric_string_similarity():
    from backend.app.adapters.law_search import LawSearchClient
    rows = LawSearchClient._articles({'results': [{'content': 'x', 'law_name': '건축법', 'law_type': '법률', 'article': '제61조', 'hang_id': 'h', 'similarity': '0.84'}]}, False, True)
    assert rows[0]['similarity'] == 0.84
