"""ordinance_reading: the model reads the jurisdiction's ordinance against the question list; code only verifies quotes."""
import asyncio
import json
from types import SimpleNamespace

from backend.app.modules.land.reference.services import ordinance_reading as module

SUBDIVISION = ('제41조(건축물이 있는 대지의 분할제한) 법 제57조제1항 및 영 제80조에 따라 건축물이 있는 대지는 다음 각 호의 어느 하나에서 정하는 '
               '면적 미만으로 분할할 수 없다. 1. 주거지역 : 60제곱미터 2. 상업지역 : 150제곱미터 3. 공업지역 : 150제곱미터 '
               '4. 녹지지역 : 200제곱미터 5. 제1호부터 제4호까지의 규정에 해당하지 아니하는 지역 : 60제곱미터')
ROAD = '제31조(대지와 도로의 관계) 영 제28조제2항에 따라 건축조례로 정하는 건축물의 규모는 연면적 3,000 제곱미터 미만으로 한다.'
ARTICLES = [{'article': '제29조', 'title': '대지안의 조경', 'content': '면적 200제곱미터 이상인 대지에는 … 15퍼센트 이상'},
            {'article': '제31조', 'title': '대지와 도로의 관계', 'content': ROAD},
            {'article': '제41조', 'title': '건축물이 있는 대지의 분할제한', 'content': SUBDIVISION}]
DISCOVERY = {'ordinances': [{'name': '경기도 건축 조례', 'edition_id': '1', 'effective_date': '2025-01-01'},
                            {'name': '어느시 건축 조례', 'edition_id': '2163451', 'effective_date': '2026-08-19', 'detail_url': 'https://law.go.kr/x'}]}
ANSWER = {'reason': '조문에 적힌 대로', 'items': [
    {'key': 'site_subdivision_limit', 'unit': 'm2', 'article': '제41조', 'quote': '1. 주거지역 : 60제곱미터 2. 상업지역 : 150제곱미터',
     'by_scope': [{'scope': '주거지역', 'value': 60}, {'scope': '상업지역', 'value': 150}, {'scope': '녹지지역', 'value': 200}, {'scope': '그 밖의 지역', 'value': 60}]},
    {'key': 'site_road_requirement', 'value': 3000, 'unit': 'm2', 'article': '제31조', 'quote': '연면적 3,000 제곱미터 미만으로 한다'},
    {'key': 'landscaping', 'unit': '%', 'article': '제29조', 'quote': '이 문장은 조례에 없다', 'by_scope': [{'scope': '2,000㎡ 이상', 'value': 15}]},
    {'key': 'public_open_space', 'value': 10, 'unit': '%', 'article': '제44조', 'quote': '면적 200제곱미터 이상인 대지에는'},
    {'key': 'invented_rule', 'value': 1, 'quote': '연면적 3,000 제곱미터 미만으로 한다'}]}


class Model:
    def __init__(self, answer=ANSWER):
        self.answer = answer
        self.prompts = []

    async def create(self, messages, **kwargs):
        self.prompts.append(messages[0].content)
        if isinstance(self.answer, Exception):
            raise self.answer
        return SimpleNamespace(content=json.dumps(self.answer, ensure_ascii=False))


def test_quotes_are_verified_against_the_text_and_everything_else_is_dropped():
    reading = module.OrdinanceReading.model_validate(ANSWER)
    kept, dropped = module.verify_quotes(reading, ARTICLES)
    assert [item.key for item in kept] == ['site_subdivision_limit', 'site_road_requirement']
    assert dropped == ['landscaping: 인용문이 제29조 원문에 없음', 'public_open_space: 인용 조문 제44조이 원문에 없음', 'invented_rule: 질문 목록에 없는 항목']
    # A quote attributed to the wrong article is dropped even though the sentence exists elsewhere in the text.
    misattributed = module.OrdinanceReading.model_validate({'reason': 'x', 'items': [{'key': 'site_road_requirement', 'value': 3000, 'article': '제41조', 'quote': '연면적 3,000 제곱미터 미만으로 한다'}]})
    assert module.verify_quotes(misattributed, ARTICLES) == ([], ['site_road_requirement: 인용문이 제41조 원문에 없음'])


def test_pick_ordinance_takes_the_innermost_ordinance_of_each_kind():
    assert module.pick_ordinance(DISCOVERY)['name'] == '어느시 건축 조례'
    assert module.pick_ordinance({'ordinances': [{'name': '어느시 도시계획 조례'}]}) is None
    rows = {'ordinances': [{'name': '경기도 도시계획 조례', 'edition_id': '1'}, {'name': '어느시 도시계획 조례', 'edition_id': '2'},
                           {'name': '어느시 주차장 설치 및 관리 조례', 'edition_id': '3'}, {'name': '어느군 도시·군계획 조례', 'edition_id': '4'}]}
    assert module.pick_ordinance(rows, 'planning')['edition_id'] == '4'
    assert module.pick_ordinance(rows, 'parking')['edition_id'] == '3'
    assert set(module.questions_for('planning')) == {'bcr_by_zone', 'far_by_zone', 'use_tables'} and module.questions_for('building') is module.QUESTIONS


def test_read_all_kinds_reads_each_ordinance_side_by_side_and_skips_what_it_cannot(tmp_path, monkeypatch):
    async def reading(pnu, sigungu, day, *, kind):
        if kind == 'parking':
            raise RuntimeError('no parking ordinance')
        return None if kind == 'planning' else {'kind': kind, 'items': {}}
    monkeypatch.setattr(module, 'ordinance_reading', reading)
    assert asyncio.run(module.read_all_kinds('p', '41150', '2026-10-12')) == {'building': {'kind': 'building', 'items': {}}}


def test_the_model_reads_the_whole_ordinance_once_per_day_and_the_figures_reach_the_rules(tmp_path):
    calls = []
    async def discover(pnu, day, topics=()):
        calls.append('discover'); return DISCOVERY
    async def body(name, edition_id, day):
        calls.append(('body', name, edition_id)); return {'articles': ARTICLES}
    model = Model()
    reading = asyncio.run(module.ordinance_reading('4115011300106840001', '41150', '2026-10-12', discover=discover, body=body, model_enabled=True, client=model, cache_dir=tmp_path))
    assert '제41조' in model.prompts[0] and 'site_subdivision_limit' in model.prompts[0] and '어느시 건축 조례' in model.prompts[0]
    assert reading['ordinance'] == {'name': '어느시 건축 조례', 'edition_id': '2163451', 'effective_date': '2026-08-19', 'url': 'https://law.go.kr/x'}
    assert set(reading['items']) == {'site_subdivision_limit', 'site_road_requirement'}
    assert reading['items']['site_road_requirement']['article'] == '어느시 건축 조례 제31조' and reading['items']['site_road_requirement']['value'] == 3000
    assert len(reading['dropped']) == 3
    again = asyncio.run(module.ordinance_reading('4115011300106840001', '41150', '2026-10-12', discover=discover, body=body, model_enabled=True, client=model, cache_dir=tmp_path))
    assert again == reading and calls.count('discover') == 1

    ext = {'site_subdivision_limit': {'name': '대지 분할 제한', 'min_area_m2': 60, 'article': '건축법 §57, 시행령 §80'},
           'site_road_requirement': {'name': '접도의무', 'min_frontage_m': 2, 'rule': '2m', 'article': '건축법 §44'},
           'landscaping_x': {}}
    applied = module.apply_to_extended(ext, reading, ['지구단위계획구역', '제2종일반주거지역'])
    assert applied['site_subdivision_limit']['min_area_m2'] == 60 and applied['site_subdivision_limit']['zone_category'] == '주거지역'
    assert applied['site_subdivision_limit']['article'] == '어느시 건축 조례 제41조' and applied['site_subdivision_limit']['basis'] == 'ordinance'
    # 시행령 §28②: the ordinance figure is the size of 축사·작물재배사-type buildings exempt from the 6 m road, not the 2,000 m² rule.
    assert applied['site_road_requirement']['exempt_similar_buildings_below_m2'] == 3000 and applied['site_road_requirement']['rule'] == '2m'
    assert applied['site_road_requirement']['exemption_article'] == '어느시 건축 조례 제31조'
    green = module.apply_to_extended({'site_subdivision_limit': {'min_area_m2': 60}}, reading, ['자연녹지지역'])
    assert green['site_subdivision_limit']['min_area_m2'] == 200
    # Two zones left after the split: the one with more ground governs the category, whatever the list order.
    two = module.apply_to_extended({'site_subdivision_limit': {'min_area_m2': 60}}, reading, ['자연녹지지역', '일반상업지역'], {'자연녹지지역': 100.0, '일반상업지역': 900.0})
    assert two['site_subdivision_limit']['min_area_m2'] == 150 and two['site_subdivision_limit']['zone_category'] == '상업지역'
    other = module.apply_to_extended({'site_subdivision_limit': {'min_area_m2': 60}}, reading, ['계획관리지역'])
    assert other['site_subdivision_limit']['min_area_m2'] == 60 and other['site_subdivision_limit']['zone_category'] == '그 밖의 지역'
    unknown = module.apply_to_extended({'site_subdivision_limit': {'min_area_m2': 60}}, reading, ['도시지역'])
    assert 'basis' not in unknown['site_subdivision_limit'] or unknown['site_subdivision_limit']['zone_category'] == '그 밖의 지역'
    assert module.apply_to_extended(ext, None, ['제2종일반주거지역']) is ext


def test_no_model_no_ordinance_or_a_failed_model_means_no_reading(tmp_path):
    async def discover(pnu, day, topics=()):
        return DISCOVERY
    async def body(name, edition_id, day):
        return {'articles': ARTICLES}
    assert asyncio.run(module.ordinance_reading('p', '41150', '2026-10-12', discover=discover, body=body, model_enabled=False, cache_dir=tmp_path)) is None
    assert asyncio.run(module.ordinance_reading('p', '41150', '2026-10-12', discover=discover, body=body, model_enabled=True, client=Model(RuntimeError('cli down')), cache_dir=tmp_path)) is None
    async def nothing(pnu, day, topics=()):
        return {'ordinances': [{'name': '어느시 도시계획 조례', 'edition_id': '9'}]}
    assert asyncio.run(module.ordinance_reading('p', '41150', '2026-10-12', discover=nothing, body=body, model_enabled=True, client=Model(), cache_dir=tmp_path)) is None
