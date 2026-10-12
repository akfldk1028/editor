"""The jurisdiction's ordinance, read by the model — one generic path for every figure a 조례 decides.

건축법 leaves many numbers to the 건축조례 (the smallest lot a built parcel may be split into, the building size
above which a 6 m road is required, landscaping tiers, open-space distances, 공개공지 …) and the engine used to
state national defaults as if they were the parcel's rule. Writing an extractor per article would mean writing
one per law forever. Instead: the jurisdiction's 건축 조례 is found and fetched exactly as the Law Agent's
`law_ordinance` does (law.go.kr official text, the edition in force on the date), the model reads the whole
text against a list of QUESTIONS (data, one line per figure the product wants), and answers every question
with the figure, the article and a verbatim quote. The only code around the model is the check that each quote
really is in the text — a figure without a verifiable quote is dropped, never shown.

Nothing here names a city: the jurisdiction comes from the PNU, the ordinance from law.go.kr. A new figure is a
new line in QUESTIONS, not new code.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

from pydantic import BaseModel

from backend.app.modules.design.generation import paths as _design_paths

logger = logging.getLogger(__name__)

READING_VERSION = 'ordinance_reading.v1'
CACHE_TTL_DAYS = 1
ORDINANCE_KINDS = {'building': r'(시|군|구)\s*건축\s*조례$'}
MAX_TEXT_CHARS = 160_000

# What the product wants from the 건축 조례, keyed like the extended rule table. Data, not code: a new figure is a
# new line here. `scope_kind` says how the answer is broken down (the model fills `by_scope` accordingly).
QUESTIONS: dict[str, dict] = {
    'site_subdivision_limit': {'ask': '건축물이 있는 대지를 분할할 수 없는 최소 면적(건축법 제57조·시행령 제80조를 받는 조문)', 'unit': 'm2',
                               'scope_kind': '용도지역 종류(주거지역·상업지역·공업지역·녹지지역·그 밖의 지역)'},
    'site_road_requirement': {'ask': '너비 6m 이상 도로에 4m 이상 접해야 하는 건축물의 연면적 규모(시행령 제28조제2항을 받는 조문; '
                                     '"연면적 N제곱미터 미만으로 한다"면 N)', 'unit': 'm2', 'scope_kind': None},
    'landscaping': {'ask': '대지 안의 조경 면적 비율(연면적 구간별 %)과 조경 의무가 생기는 대지 면적', 'unit': '%', 'scope_kind': '연면적 구간'},
    'on_site_open_space': {'ask': '건축선·인접대지경계선에서 건축물까지 띄어야 하는 거리(대지 안의 공지)', 'unit': 'm',
                           'scope_kind': '용도·규모(별표면 별표 번호와 그 안의 구분)'},
    'public_open_space': {'ask': '공개공지를 확보해야 하는 건축물 규모와 대지면적 대비 비율', 'unit': '%', 'scope_kind': '시설·규모'},
    'sunlight_setback': {'ask': '일조 등의 확보를 위한 정북방향 이격 거리(높이 구간별)', 'unit': 'm', 'scope_kind': '높이 구간'},
}


class ScopedValue(BaseModel):
    scope: str
    value: float | None = None
    text: str | None = None       # when the figure is not one number (a formula, a table reference)


class ReadItem(BaseModel):
    key: str                      # a QUESTIONS key
    value: float | None = None    # the single figure, when there is one
    unit: str | None = None
    by_scope: list[ScopedValue] = []
    article: str | None = None    # "제41조" as written in the text
    quote: str | None = None      # verbatim from the article
    note: str | None = None


class OrdinanceReading(BaseModel):
    reason: str
    items: list[ReadItem] = []


PROMPT = """You are reading a Korean city's 건축 조례 (official text from law.go.kr, articles in order). Answer each
question with what THIS text says — the figure(s), the article number as written (e.g. 제41조), and a verbatim
quote of the sentence that carries the figure. Breakdowns go in by_scope with the scope named as the text names
it. If the ordinance does not decide a question, omit that key. Never invent or complete a figure; never cite an
article that is not in the text. Return JSON only.

Questions (key: what to find):
{questions}

Ordinance: {name} (edition {edition_id}, 시행 {effective_date})

{text}"""


def _normalize(value: str) -> str:
    return re.sub(r'[\s ]+', '', value or '')


def verify_quotes(reading: OrdinanceReading, articles: list[dict]) -> tuple[list[ReadItem], list[str]]:
    """Keep only items whose quote is in the text (whitespace ignored) and whose article, when named, exists;
    the second value lists what was dropped and why."""
    corpus = _normalize(' '.join(str(a.get('content') or '') for a in articles))
    numbers = {_normalize(str(a.get('article') or '')) for a in articles}
    kept, dropped = [], []
    for item in reading.items:
        if item.key not in QUESTIONS:
            dropped.append(f'{item.key}: 질문 목록에 없는 항목'); continue
        if not item.quote or len(_normalize(item.quote)) < 6 or _normalize(item.quote) not in corpus:
            dropped.append(f'{item.key}: 인용문이 조례 원문에 없음'); continue
        if item.article and _normalize(item.article) not in numbers:
            dropped.append(f'{item.key}: 인용 조문 {item.article}이 원문에 없음'); continue
        kept.append(item)
    return kept, dropped


async def read_with_model(name: str, edition_id: str, effective_date: str | None, articles: list[dict], client=None) -> OrdinanceReading | None:
    try:
        from autogen_core.models import UserMessage

        from backend.app.adapters.cli_model_client import ClaudeCodeChatCompletionClient

        model = client or ClaudeCodeChatCompletionClient(timeout_s=120.0)
        text = '\n\n'.join(f"{a.get('article') or ''}({a.get('title') or ''}) {a.get('content') or ''}" for a in articles)[:MAX_TEXT_CHARS]
        questions = '\n'.join(f"- {key}: {q['ask']} (unit {q['unit']}{'; by_scope by ' + q['scope_kind'] if q['scope_kind'] else ''})"
                              for key, q in QUESTIONS.items())
        prompt = PROMPT.format(questions=questions, name=name, edition_id=edition_id, effective_date=effective_date or '?', text=text)
        result = await model.create([UserMessage(content=prompt, source='editor')], json_output=OrdinanceReading)
        return OrdinanceReading.model_validate_json(result.content if isinstance(result.content, str) else '{}')
    except Exception as error:
        logger.warning('ordinance_reading: model reading failed (%s)', type(error).__name__)
        return None


def _cache_dir() -> Path:
    return _design_paths.backend_root() / 'runtime' / 'ordinance_reading'


def _read_cache(path: Path, assessment_date: str) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
        age = datetime.now(timezone.utc) - datetime.fromisoformat(payload['fetched_at'])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if payload.get('version') != READING_VERSION or payload.get('assessment_date') != assessment_date or age.days >= CACHE_TTL_DAYS:
        return None
    return payload


def pick_ordinance(discovery: dict, kind: str = 'building') -> dict | None:
    """The innermost jurisdiction's ordinance of this kind among what discovery found in force on the date
    (discovery lists outermost first, so the last match is the 시군구's own)."""
    pattern = ORDINANCE_KINDS[kind]
    rows = [row for row in discovery.get('ordinances') or [] if isinstance(row, dict) and re.search(pattern, str(row.get('name') or '').strip())]
    return rows[-1] if rows else None


async def ordinance_reading(pnu: str, sigungu_code: str, assessment_date: str | None, *, kind: str = 'building',
                            discover: Callable[..., Awaitable[dict]] | None = None, body: Callable[..., Awaitable[dict]] | None = None,
                            model_enabled: bool | None = None, client=None, cache_dir: Path | None = None) -> dict | None:
    """What the jurisdiction's ordinance decides for the parcel, as verified items, or None when it could not be read.

    {'ordinance': {name, edition_id, effective_date, url}, 'items': {key: {value, unit, by_scope, article, quote, note}},
     'dropped': [...], 'reason', 'fetched_at', 'assessment_date', 'version'}"""
    day = assessment_date or date.today().isoformat()
    path = (cache_dir or _cache_dir()) / f'{kind}-{sigungu_code}.json'
    if path.exists():
        cached = _read_cache(path, day)
        if cached is not None:
            return cached
    if model_enabled is None:
        from backend.app.modules.platform.routing import judge as judging
        model_enabled = judging.enabled()
    if not model_enabled:
        return None
    from backend.app.modules.law.ordinances import service as ordinances
    discover = discover or ordinances.discover
    body = body or ordinances.body
    try:
        row = pick_ordinance(await discover(pnu, day, topics=['건축']) or {}, kind)
        if row is None:
            return None
        text = await body(row['name'], row['edition_id'], day)
    except Exception as error:
        logger.warning('ordinance_reading: official text unavailable (%s)', type(error).__name__)
        return None
    if not isinstance(text, dict) or text.get('error') or not isinstance(text.get('articles'), list) or not text['articles']:
        return None
    reading = await read_with_model(row['name'], row['edition_id'], row.get('effective_date'), text['articles'], client)
    if reading is None:
        return None
    kept, dropped = verify_quotes(reading, text['articles'])
    result = {
        'version': READING_VERSION, 'assessment_date': day, 'fetched_at': datetime.now(timezone.utc).isoformat(),
        'ordinance': {'name': row['name'], 'edition_id': row['edition_id'], 'effective_date': row.get('effective_date'), 'url': row.get('detail_url')},
        'items': {item.key: {'value': item.value, 'unit': item.unit, 'by_scope': [s.model_dump() for s in item.by_scope],
                             'article': f"{row['name']} {item.article}" if item.article else row['name'], 'quote': item.quote, 'note': item.note}
                  for item in kept},
        'dropped': dropped, 'reason': reading.reason,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')
    except (OSError, TypeError, ValueError):
        pass
    return result


def zone_category(zone_name: str) -> str:
    """The 시행령 제80조 category a 용도지역 name falls in (주거·상업·공업·녹지), else 그 밖의 지역."""
    for category in ('주거지역', '상업지역', '공업지역', '녹지지역'):
        if category[:2] in (zone_name or ''):
            return category
    return '그 밖의 지역'


def _scoped(item: dict, scope_name: str) -> float | None:
    """The by_scope value whose scope names this category (or the catch-all), else the single value."""
    rows = item.get('by_scope') or []
    for row in rows:
        if row.get('value') is not None and scope_name[:2] in str(row.get('scope') or ''):
            return float(row['value'])
    for row in rows:
        if row.get('value') is not None and any(word in str(row.get('scope') or '') for word in ('그 밖', '기타', '해당하지')):
            return float(row['value'])
    return float(item['value']) if item.get('value') is not None else None


def apply_to_extended(reg_ext: dict, reading: dict | None, zone_names: list[str]) -> dict:
    """Every read item lands on the extended rule of the same key as `ordinance` (value, article, quote); the two
    figures the restrictions print as numbers are also set on their known fields."""
    if not reading or not isinstance(reg_ext, dict):
        return reg_ext
    items = reading.get('items') or {}
    for key, item in items.items():
        if key in reg_ext and isinstance(reg_ext[key], dict):
            reg_ext[key] = {**reg_ext[key], 'ordinance': {k: item.get(k) for k in ('value', 'unit', 'by_scope', 'article', 'quote', 'note')}, 'basis': 'ordinance'}
    main_zone = next((name for name in zone_names if name.endswith('지역')), '')
    sub = items.get('site_subdivision_limit')
    if sub and isinstance(reg_ext.get('site_subdivision_limit'), dict):
        category = zone_category(main_zone)
        area = _scoped(sub, category)
        if area is not None:
            reg_ext['site_subdivision_limit'].update({'min_area_m2': area, 'zone_category': category, 'article': sub.get('article')})
    road = items.get('site_road_requirement')
    if road and road.get('value') is not None and isinstance(reg_ext.get('site_road_requirement'), dict):
        size = float(road['value'])
        reg_ext['site_road_requirement'].update({
            'road_rule_size_m2': size, 'article': f"건축법 §44, 시행령 §28②; {road.get('article')}",
            'rule': f"건축물 대지는 2m 이상 도로에 접해야 함; 연면적 합계 {size:,.0f}㎡ 이상이면 너비 6m 이상 도로에 4m 이상 접해야 함 ({road.get('article')})"})
    return reg_ext


__all__ = ['OrdinanceReading', 'QUESTIONS', 'READING_VERSION', 'ReadItem', 'apply_to_extended', 'ordinance_reading', 'pick_ordinance',
           'read_with_model', 'verify_quotes', 'zone_category']
