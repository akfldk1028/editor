"""The ordinances that can bind one parcel on one date — discovered, jurisdiction-verified, edition-dated.

Three passes over law.go.kr (`search.search_all`, every page walked):
  1. the editions in force now (nw=1) for each jurisdiction level × topic — the authoritative list of what
     exists today; a record is kept only when its issuing government (`지자체기관명`) is exactly one of
     the parcel's jurisdictions, and similarly named governments are listed as excluded, never dropped silently;
  2. for a kept ordinance whose edition starts after the assessment date, its own history (nw=2, exact name)
     to find the edition in force on the date — the latest `시행일자` on or before it;
  3. only when the date lies in the past, the topic history too: ordinances that exist only there were in
     force at some time but their repeal date is not in the list, so they are returned apart (`historical`,
     in_force unknown) and never as current.

Topics: the ordinance names the review already cites (the calculators' grounds) with their government prefix
removed, plus the delegations every building review rests on (국토계획법 → 도시계획 조례, 건축법 → 건축 조례,
주차장법 → 주차장 조례) — statutes, not a list of towns. Relevance is `exact` when a review reference names
the ordinance, `topic` when a topic word is in its name. `coverage_complete` stays false: the search's
completeness (`search.complete`) is not legal coverage, and no body has been read here.
"""
from __future__ import annotations

import asyncio
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

from backend.app.modules.law.ordinances import jurisdiction, search

ORDINANCE_URL = 'https://www.law.go.kr/LSW/ordinInfoP.do?ordinSeq='
DEFAULT_TOPICS = ('도시계획', '건축', '주차장')
_SUFFIX = re.compile(r'(시행규칙|조례|규칙)$')
_WORKERS = 6
EXCLUDED_CAP = 60
COVERAGE_NOTE = '검색 완료는 법적 적용 범위의 완결이 아니에요. 찾은 조례는 읽을 원문이지 판정이 아니며, 본문은 아직 조회하지 않았어요.'


def _norm(value) -> str:
    return re.sub(r'\s+', '', str(value or ''))


def _iso(value) -> str | None:
    raw = _norm(value).replace('-', '').replace('.', '')
    if not re.fullmatch(r'\d{8}', raw):
        return None
    try:
        return date(int(raw[:4]), int(raw[4:6]), int(raw[6:])).isoformat()
    except ValueError:
        return None


def topics_from_refs(refs: list[dict], levels: list[dict], extra: list[str] = ()) -> list[dict]:
    """[{topic, from: [instrument…]}] — a cited ordinance name minus its government words, minus 조례/규칙."""
    names = {_norm(level[key]) for level in levels for key in ('name', 'issuer')}
    found: dict[str, list] = {}
    for ref in refs:
        instrument = str(ref.get('instrument') or '').strip()
        tokens = instrument.split()
        while tokens and _norm(tokens[0]) in names:
            tokens.pop(0)
        if tokens:
            tokens[-1] = _SUFFIX.sub('', tokens[-1])
        topic = ' '.join(token for token in tokens if token)
        if _norm(topic) and _norm(topic) not in {'조례', '규칙'}:
            found.setdefault(_norm(topic), [topic, []])[1].append(instrument)
    out = [{'topic': value[0], 'from': value[1]} for value in found.values()]
    for topic in [*DEFAULT_TOPICS, *extra]:
        if _norm(topic) and _norm(topic) not in found:
            found[_norm(topic)] = [topic, []]
            out.append({'topic': topic, 'from': ['statutory delegation' if topic in DEFAULT_TOPICS else 'caller']})
    return out


def _record(row: dict) -> dict | None:
    mst = _norm(row.get('자치법규일련번호'))
    if not mst:
        return None
    return {'name': str(row.get('자치법규명') or '').strip(), 'kind': str(row.get('자치법규종류') or '').strip() or None,
            'ordinance_id': _norm(row.get('자치법규ID')) or None, 'edition_id': mst,
            'effective_date': _iso(row.get('시행일자')), 'promulgated': _iso(row.get('공포일자')),
            'promulgation_no': str(row.get('공포번호') or '').strip() or None, 'revision': str(row.get('제개정구분명') or '').strip() or None,
            'issuer': str(row.get('지자체기관명') or '').strip(), 'detail_url': row.get('자치법규상세링크') if isinstance(row.get('자치법규상세링크'), str) else None}


def _generic_target(instrument: str, listed: list[tuple[str, str]], innermost: str) -> str | None:
    """The one listed ordinance a generic name ('건축조례') can mean: the only one ending in it, or — when several
    levels have one — the innermost government's only one. Two at the same level leave it unresolved."""
    ending = [(name, level) for name, level in listed if _norm(name).endswith(instrument) and _norm(name) != instrument]
    if len(ending) == 1:
        return ending[0][0]
    inner = [name for name, level in ending if level == innermost]
    return inner[0] if len(inner) == 1 else None


def _attach_refs(name: str, refs: list[dict], listed: list[tuple[str, str]], innermost: str) -> list[dict]:
    """Review references naming this ordinance: by its exact name, or a generic name that can mean only it."""
    out = []
    for ref in refs:
        instrument = _norm(ref.get('instrument'))
        if not instrument:
            continue
        exact = instrument == _norm(name)
        generic = not exact and _generic_target(instrument, listed, innermost) == name
        if exact or generic:
            out.append({'item_id': ref.get('item_id'), 'title': ref.get('title'), 'article': ref.get('article'),
                        'status': ref.get('status'), 'match': 'exact' if exact else 'generic_name'})
    return out


class _Discovery:
    def __init__(self, levels, topics, when, fetch_json, page_limit):
        self.levels, self.topics, self.when, self.fetch_json, self.page_limit = levels, topics, when, fetch_json, page_limit
        self.issuers = {_norm(level['issuer']): level for level in levels}
        self.queries: list[dict] = []
        self.seen: set[str] = set()
        self.editions: dict[str, list[dict]] = {}
        self.level_of: dict[str, str] = {}
        self.excluded: dict[str, dict] = {}
        self.other = 0

    def run(self, specs: list[dict]) -> list[dict]:
        """Searches in parallel; each spec gets its page count, total, completeness and error."""
        with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
            results = list(pool.map(lambda q: search.search_all(q['query'], q['edition_set'], fetch_json=self.fetch_json, page_limit=self.page_limit), specs))
        for spec, result in zip(specs, results):
            spec.update({'pages': result['pages'], 'total': result['total'], 'complete': result['complete'], 'error': result['error']})
            self.queries.append(spec)
        return [result['rows'] for result in results]

    def topic_specs(self, edition_set: str) -> list[dict]:
        return [{'level': level['level'], 'issuer': level['issuer'], 'query': f"{level['name']} {topic['topic']} 조례", 'edition_set': edition_set}
                for level in self.levels for topic in self.topics]

    def take(self, rows: list[dict], *, only_id: str | None = None) -> list[str]:
        """Keeps jurisdiction-verified, topic-matched records; returns the ordinance keys touched."""
        keys = []
        for row in rows:
            record = _record(row)
            if record is None or record['edition_id'] in self.seen:
                continue
            level = self.issuers.get(_norm(record['issuer']))
            key = record['ordinance_id'] or record['edition_id']
            if only_id is not None and key != only_id:
                continue
            self.seen.add(record['edition_id'])
            if level is None:
                self.excluded.setdefault(f"{record['issuer']}|{record['name']}", {'name': record['name'], 'issuer': record['issuer'], 'reason': 'jurisdiction_mismatch'})
                continue
            if not any(_norm(topic['topic']) in _norm(record['name']) for topic in self.topics):
                self.other += 1
                continue
            self.editions.setdefault(key, []).append(record)
            self.level_of.setdefault(key, level['level'])
            keys.append(key)
        return keys

    def dated(self, key: str) -> tuple[dict | None, list[dict]]:
        editions = self.editions[key]
        on_date = [e for e in editions if e['effective_date'] and e['effective_date'] <= self.when]
        future = sorted((e for e in editions if e['effective_date'] and e['effective_date'] > self.when), key=lambda e: e['effective_date'])
        pick = max(on_date, key=lambda e: (e['effective_date'], e['promulgated'] or '', e['edition_id'])) if on_date else None
        return pick, future

    def entry(self, key: str, *, in_force: str) -> dict | None:
        pick, future = self.dated(key)
        if pick is None:
            return None
        return {**pick, 'level': self.level_of[key], 'url': ORDINANCE_URL + pick['edition_id'], 'editions_seen': len(self.editions[key]),
                'future_editions': [{'edition_id': e['edition_id'], 'effective_date': e['effective_date']} for e in future],
                'status': {'jurisdiction': 'verified', 'edition': 'dated' if in_force == 'current' else 'history_only',
                           'body': 'not_fetched', 'in_force': in_force}}


def discover_for_parcel(pnu: str, assessment_date: str, *, address: str | None, refs: list[dict] = (), topics: list[str] = (),
                        fetch_json, page_limit: int = 20, now=None, today: date | None = None) -> dict:
    when = date.fromisoformat(assessment_date)
    clock = now or (lambda: datetime.now(timezone.utc))
    today = today or clock().date()
    place = jurisdiction.resolve(pnu, address)
    base = {'pnu': pnu, 'assessment_date': assessment_date, 'retrieved_at': clock().isoformat(),
            'source': f'{search.SOURCE} (nw=1 현행, nw=2 연혁)', 'jurisdiction': place, 'topics': [],
            'search': {'queries': [], 'complete': False, 'other_results': 0, 'errors': []}, 'ordinances': [], 'historical': [],
            'excluded': [], 'excluded_total': 0, 'coverage_complete': False, 'coverage_note': COVERAGE_NOTE}
    if place['status'] != 'resolved':
        return base
    levels = place['levels']
    topic_rows = topics_from_refs(list(refs), levels, list(topics))
    run = _Discovery(levels, topic_rows, when.isoformat(), fetch_json, page_limit)
    # 1. What is in force now, for every level × topic.
    current: list[str] = []
    for rows in run.run(run.topic_specs('current')):
        current.extend(run.take(rows))
    current = list(dict.fromkeys(current))
    # 2. An edition starting after the date: the ordinance's own history, by exact name, for the edition in force then.
    pending = [key for key in current if run.dated(key)[0] is None]
    if pending:
        specs = [{'level': run.level_of[key], 'issuer': run.editions[key][0]['issuer'], 'query': run.editions[key][0]['name'], 'edition_set': 'history', 'for': key} for key in pending]
        for key, rows in zip(pending, run.run(specs)):
            run.take(rows, only_id=key)
    ordinances = []
    for key in current:
        entry = run.entry(key, in_force='current')
        if entry is None:
            first = run.editions[key][0]
            future = run.dated(key)[1]
            run.excluded.setdefault(f'future|{key}', {'name': first['name'], 'issuer': first['issuer'], 'reason': 'not_yet_effective',
                                                     'first_effective_date': future[0]['effective_date'] if future else first['effective_date']})
            continue
        ordinances.append(entry)
    # 3. A past date: the topic history as well — what existed then and is gone from the current list.
    historical = []
    if when < today:
        for rows in run.run(run.topic_specs('history')):
            for key in dict.fromkeys(run.take(rows)):
                if key in current:
                    continue
                entry = run.entry(key, in_force='unknown')
                if entry is not None:
                    historical.append(entry)
    innermost = levels[-1]['level']
    listed = [(o['name'], o['level']) for o in ordinances]
    for ordinance in [*ordinances, *historical]:
        ordinance['review_refs'] = _attach_refs(ordinance['name'], list(refs), listed, innermost)
        ordinance['topics'] = [topic['topic'] for topic in topic_rows if _norm(topic['topic']) in _norm(ordinance['name'])]
        ordinance['status']['relevance'] = 'exact' if any(r['match'] == 'exact' for r in ordinance['review_refs']) else 'topic'
    order = {level['level']: index for index, level in enumerate(levels)}
    for bucket in (ordinances, historical):
        bucket.sort(key=lambda o: (-order[o['level']], o['status']['relevance'] != 'exact', o['kind'] != '조례', o['name']))
    rows = list(run.excluded.values())
    return {**base, 'topics': topic_rows,
            'search': {'queries': run.queries, 'complete': bool(run.queries) and all(q['complete'] for q in run.queries), 'other_results': run.other,
                       'errors': [f"{q['query']} ({q['edition_set']}): {q['error']}" for q in run.queries if q['error']]},
            'ordinances': ordinances, 'historical': historical, 'excluded': rows[:EXCLUDED_CAP], 'excluded_total': len(rows)}


async def body(name: str, edition_id: str, assessment_date: str, *, fetch_service=None) -> dict:
    """The door's whole-text composition: the official record for one edition, verified, off the event loop."""
    from backend.app.modules.law.ordinances import body as whole
    if fetch_service is None:
        oc = search.law_oc()
        if not oc:
            return {'error': 'law_oc_not_configured', 'reason': 'LAW_OC is not set', 'edition_id': edition_id}
        fetch_service = lambda mst: whole.fetch_service(mst, oc=oc)  # noqa: E731
    return await asyncio.to_thread(whole.ordinance_body, name, edition_id, assessment_date, fetch_service=fetch_service)


async def resolve_address(pnu: str) -> str | None:
    """The parcel's registry address from Vworld by PNU (None when the lookup fails)."""
    from backend.app.modules.land.vworld import VworldClient
    result = await VworldClient(os.environ.get('VWORLD_API_KEY', '')).fetch_parcel_geometry(pnu)
    address = result.get('address') if isinstance(result, dict) else None
    return address if isinstance(address, str) and address.strip() else None


async def discover(pnu: str, assessment_date: str, *, refs: list[dict] = (), topics: list[str] = (), resolver=None,
                   fetch_json=None, page_limit: int = 20) -> dict:
    """The door's composition: registry address, then the blocking searches off the event loop."""
    resolver = resolver or resolve_address
    if fetch_json is None:
        oc = search.law_oc()
        if not oc:
            return {'pnu': pnu, 'assessment_date': assessment_date, 'error': 'law_oc_not_configured',
                    'jurisdiction': {'status': 'unresolved', 'reason': 'law_oc_not_configured', 'levels': [], 'notes': [], 'address': None},
                    'ordinances': [], 'historical': [], 'excluded': [], 'excluded_total': 0, 'topics': [],
                    'search': {'queries': [], 'complete': False, 'other_results': 0, 'errors': []}, 'coverage_complete': False}
        fetch_json = lambda params: search.fetch_page(params, oc=oc)  # noqa: E731
    address = await resolver(pnu)
    return await asyncio.to_thread(discover_for_parcel, pnu, assessment_date, address=address, refs=list(refs), topics=list(topics),
                                   fetch_json=fetch_json, page_limit=page_limit)
