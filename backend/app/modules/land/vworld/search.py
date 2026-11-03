"""Site search over VWorld search API 2.0 (https://www.vworld.kr/dev/v4dv_search2_s001.do).

``type=address&category=parcel|road`` answers with ``id`` = PNU, ``type=place`` with POIs, ``type=district``
(L1..L4) with district codes; ``size`` goes up to 1000. The provider matches by prefix and loosely (신촌동 1 also
brings 심곡동 1 and 신촌동 1-1), so every item is checked against what was typed (``address_rank``) instead of
trusting its order. ``getCoord`` stays only as the last fallback, and its answer is kept only when its refined
name (``level4L``: the 동·리 for PARCEL, the 로·길 for ROAD), number (``level5``) and regions equal the input — it
otherwise substitutes a neighbouring lot without saying so (청운동 산 1 → 산 1-1, 3.1대로 110 → 3·15대로 110).

One search has one deadline and a call budget: the optional steps (narrowing, the typed 동's own lots, a place's
lot, getCoord) are skipped when the budget is spent; the deadline ends the search as ``unavailable``.
"""
import asyncio
import logging

import httpx

from backend.app.modules.land.address_query import Query, address_words, classify, region_matches, secondary_kind
from backend.app.modules.land.address_rank import (
    LIMIT, address_candidates, district_candidates, place_candidates, place_relevant, rank_addresses,
)

logger = logging.getLogger(__name__)
SEARCH_URL = 'https://api.vworld.kr/req/search'
ADDRESS_URL = 'https://api.vworld.kr/req/address'
# Errors that are about the key or the daily quota: reported as `unavailable`, never as "not found".
KEY_ERRORS = {'INVALID_KEY', 'INCORRECT_KEY', 'UNAVAILABLE_KEY', 'OVER_REQUEST_LIMIT'}
# Everything that means "the provider could not answer" (HTTP: the call failed; MALFORMED: an unreadable body).
UNAVAILABLE = KEY_ERRORS | {'SYSTEM_ERROR', 'UNKNOWN_ERROR', 'HTTP', 'MALFORMED'}
PAGE = 1000
DEADLINE_S = 4.0
MAX_CALLS = 12

MESSAGES = {
    'none': '입력한 주소·지번·장소를 찾지 못했어요. 시군구나 동 이름을 함께 적어 보세요.',
    'pnu_invalid': 'PNU의 11번째 자리(산 구분)는 1 또는 2여야 해요.',
    'pnu_none': '이 PNU에 해당하는 필지가 없어요.',
    'not_configured': '주소 검색이 설정되지 않았어요 (VWORLD_API_KEY).',
    'OVER_REQUEST_LIMIT': '오늘 브이월드 검색 한도를 넘었어요. 내일 다시 시도해 주세요.',
    'key': '브이월드 인증키를 쓸 수 없어 주소를 찾지 못했어요 ({code}).',
    'slow': '브이월드 주소 검색이 너무 오래 걸려요. 잠시 후 다시 시도해 주세요.',
    'provider': '브이월드 주소 검색이 응답하지 않아요. 잠시 후 다시 시도해 주세요.',
}


class VworldUnavailable(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code

    @property
    def message(self) -> str:
        if self.code == 'OVER_REQUEST_LIMIT':
            return MESSAGES['OVER_REQUEST_LIMIT']
        if self.code in KEY_ERRORS:
            return MESSAGES['key'].format(code=self.code)
        if self.code in ('TIMEOUT', 'BUDGET'):
            return MESSAGES['slow']
        return MESSAGES['provider']


class OverBudget(VworldUnavailable):
    def __init__(self):
        super().__init__('BUDGET')


class _Session:
    """One search's provider calls: the client (key, transport), the HTTP connection, and the calls left."""
    def __init__(self, client, http, budget: int = MAX_CALLS):
        self.client, self.http, self.left = client, http, budget


async def _get(session: _Session, url: str, params: dict) -> dict:
    """One provider call; NOT_FOUND is an empty answer, a key/quota/system error raises (the key never leaves)."""
    if session.left <= 0:
        raise OverBudget()
    session.left -= 1
    try:
        response = await session.http.get(url, params={**params, 'key': session.client.api_key, 'format': 'json', 'crs': 'EPSG:4326'})
        response.raise_for_status()
        data = response.json()['response']
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
        logger.warning('VWorld %s failed (%s)', url.rsplit('/', 1)[-1], type(error).__name__)
        raise VworldUnavailable('HTTP') from None
    if not isinstance(data, dict):
        raise VworldUnavailable('MALFORMED')
    if data.get('status') == 'ERROR':
        error = data.get('error')
        code = str((error if isinstance(error, dict) else {}).get('code') or 'ERROR')
        logger.warning('VWorld %s refused: %s', url.rsplit('/', 1)[-1], code)
        if code in UNAVAILABLE:
            raise VworldUnavailable(code)
        return {}
    return data if data.get('status') == 'OK' else {}


async def _items(session: _Session, params: dict) -> tuple[list[dict], int]:
    """The items and the provider's total; any other shape is read as no items."""
    data = await _get(session, SEARCH_URL, {'service': 'search', 'request': 'search', 'version': '2.0', 'page': '1', **params})
    result = data.get('result')
    items = result.get('items') if isinstance(result, dict) else None
    items = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
    record = data.get('record')
    try:
        total = int(record.get('total') or 0) if isinstance(record, dict) else len(items)
    except (TypeError, ValueError):
        total = len(items)
    return items, max(total, len(items))


async def _optional(step, default):
    """A step the answer can do without: skipped when the call budget is spent."""
    try:
        return await step
    except OverBudget:
        return default


async def _addresses(session: _Session, query: Query, bbox):
    """(rows, truncated): every address the provider has for the typed name and number, nationwide (regions rank,
    they do not filter); ``truncated`` when more existed than one page brought and nothing narrowed them."""
    category = 'road' if query.kind == 'road' else 'parcel'
    items, total = await _items(session, {'type': 'address', 'category': category, 'query': query.provider_text(), 'size': str(PAGE)})
    truncated = total > len(items)
    if truncated and query.regions:
        # More than one page: the typed regions narrow it instead.
        narrowed = await _optional(_items(session, {'type': 'address', 'category': category, 'size': str(PAGE),
                                                    'query': query.provider_text(with_context=True)}), None)
        if narrowed is not None:
            items = narrowed[0] + items
            truncated = narrowed[1] > len(narrowed[0])
    rows = address_candidates(query, items, bbox)
    if query.kind == 'lot' and not any(row['_same_name'] for row in rows):
        # 을지로1가 1 brings 을지로2가 1-1: no lot 1 there, so the typed 동's own lots are the substitutes to offer.
        own = await _optional(_items(session, {'type': 'address', 'category': 'parcel', 'size': str(PAGE),
                                               'query': query.provider_text(with_context=True, number=False)}), ([], 0))
        rows = address_candidates(query, own[0] + items, bbox)
    return rows, truncated


def _bbox_param(bbox):
    return ','.join(f'{value:.6f}' for value in bbox) if bbox else None


async def _places(session: _Session, query: Query, bbox):
    """Places near the map first (as Kakao's keyword search does with ``rect``), nationwide when none near is named
    like the input (서울시청 with the map in 부산 still finds 서울특별시청)."""
    params = {'type': 'place', 'query': query.normalized, 'size': '100'}
    if bbox:
        items, _ = await _items(session, {**params, 'bbox': _bbox_param(bbox)})
        if place_relevant(query, items):
            return place_candidates(query, items, bbox)
    items, _ = await _items(session, params)
    return place_candidates(query, items, bbox)


async def _districts(session: _Session, query: Query, bbox):
    level = query.level or 'L4'
    items, _ = await _items(session, {'type': 'district', 'category': level, 'query': query.provider_text(), 'size': '20'})
    return district_candidates(query, items, level, bbox)


async def _run(kind: str, session: _Session, query: Query, bbox):
    """(rows, truncated) for one class of the input."""
    if kind in ('lot', 'road'):
        return await _addresses(session, query, bbox)
    if kind == 'place':
        return await _places(session, query, bbox), False
    area = classify(query.normalized)
    area.level = area.level or 'L4'
    return await _districts(session, area if area.kind == 'area' else query, bbox), False


async def _coordinate_fallback(session: _Session, query: Query):
    """``getCoord`` with ``refine``, kept only when its refined name, number and regions are the typed ones.
    ``level4L`` is the 동·리 for PARCEL and the 로·길 for ROAD (테헤란로 152 → level4L 테헤란로, level5 152)."""
    data = await _get(session, ADDRESS_URL, {'service': 'address', 'request': 'getCoord', 'address': query.normalized,
                                             'type': 'ROAD' if query.kind == 'road' else 'PARCEL', 'refine': 'true'})
    refined = data.get('refined') if isinstance(data.get('refined'), dict) else {}
    structure = refined.get('structure') if isinstance(refined.get('structure'), dict) else {}
    code = structure.get('level4LC') or ''
    san = len(code) == 19 and code[10] == '2'
    if structure.get('level4L') != query.name or structure.get('level5') != query.number_text:
        return None
    if query.kind == 'lot' and san != query.san:
        return None
    text = refined.get('text') if isinstance(refined.get('text'), str) else ''
    words = address_words(text) + [str(structure.get(level) or '') for level in ('level1', 'level2', 'level3')]
    if not text or not all(region_matches(word, words) for word in query.regions):
        return None
    try:
        point = [float(data['result']['point']['x']), float(data['result']['point']['y'])]
    except (KeyError, TypeError, ValueError):
        return None
    pnu = code if query.kind == 'lot' and len(code) == 19 and code.isdigit() else None
    return {'pnu': pnu, 'kind': query.kind, 'jibun': text if query.kind == 'lot' else None,
            'road': text if query.kind == 'road' else None, 'label': text, 'point': point, 'exact': True}


async def _place_parcels(session: _Session, rows: list[dict]):
    """A place's PNU: its lot text searched as a lot, kept only on an exact, single, complete match."""
    async def one(row):
        lot = classify(row.get('jibun') or '')
        if lot.kind != 'lot':
            return
        try:
            found, truncated = await _addresses(session, lot, None)
        except VworldUnavailable:
            return
        status, candidates = rank_addresses(lot, found)
        if status == 'unique' and not truncated:
            row['pnu'] = candidates[0]['pnu']
    await asyncio.gather(*(one(row) for row in rows[:3]))


def _bounds_point(geometry):
    try:
        rings = geometry['coordinates']
        while isinstance(rings[0][0], list):
            rings = [point for ring in rings for point in ring]
        xs, ys = [p[0] for p in rings], [p[1] for p in rings]
        return [(min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2], [min(xs), min(ys), max(xs), max(ys)]
    except (KeyError, TypeError, IndexError, ValueError):
        return None, None


async def _by_pnu(client, query: Query, reply: dict) -> dict:
    parcel = await client.fetch_parcel_geometry(query.pnu)
    if not parcel.get('success'):
        if parcel.get('unavailable'):
            return {**reply, 'status': 'unavailable', 'candidates': [], 'error': VworldUnavailable(parcel['unavailable']).message}
        return {**reply, 'status': 'none', 'candidates': [], 'error': MESSAGES['pnu_none']}
    point, box = _bounds_point(parcel.get('geometry'))
    label = parcel.get('address') or query.pnu
    return {**reply, 'status': 'unique', 'candidates': [
        {'pnu': query.pnu, 'kind': 'lot', 'jibun': label, 'road': None, 'label': label, 'point': point, 'bbox': box, 'exact': True}]}


async def _search(session: _Session, query: Query, bbox) -> tuple[str, list[dict]]:
    second = secondary_kind(query.kind)
    jobs = [_run(query.kind, session, query, bbox)] + ([_run(second, session, query, bbox)] if second else [])
    results = await asyncio.gather(*jobs, return_exceptions=True)
    if isinstance(results[0], BaseException):
        raise results[0]
    primary, truncated = results[0]
    if query.kind in ('lot', 'road'):
        status, candidates = rank_addresses(query, primary)
        if status == 'none':
            fallback = await _optional(_coordinate_fallback(session, query), None)
            if fallback:
                status, candidates = ('unique' if fallback['pnu'] else 'ambiguous'), [fallback]
        elif status == 'unique' and truncated:
            # One exact match on an incomplete page is not proof there is only one.
            status = 'ambiguous'
    else:
        candidates = primary
        status = 'ambiguous' if candidates else 'none'
    has_exact = any(row.get('exact') for row in candidates)
    if len(results) > 1 and isinstance(results[1], BaseException):
        if isinstance(results[1], VworldUnavailable) and not isinstance(results[1], OverBudget) and not has_exact:
            raise results[1]
        extra = []
    else:
        extra = results[1][0] if len(results) > 1 else []
    if status != 'unique' and not has_exact and extra:
        candidates = (candidates + extra)[:LIMIT]
        status = 'ambiguous'
    places = [row for row in candidates if row['kind'] == 'place' and not row.get('pnu')]
    if places:
        await _place_parcels(session, places)
    return status, candidates


async def search(client, text: str, bbox=None) -> dict:
    """``{status, normalized, kind, candidates, error?}``; status ``unique`` | ``ambiguous`` | ``none`` | ``unavailable``."""
    query = classify(text)
    reply = {'normalized': query.normalized, 'kind': query.kind}
    if not client.api_key:
        return {**reply, 'status': 'unavailable', 'candidates': [], 'error': MESSAGES['not_configured']}
    if query.kind == 'pnu' and not query.valid:
        return {**reply, 'status': 'none', 'candidates': [], 'error': MESSAGES['pnu_invalid']}
    try:
        async with asyncio.timeout(DEADLINE_S):
            if query.kind == 'pnu':
                return await _by_pnu(client, query, reply)
            async with httpx.AsyncClient(timeout=httpx.Timeout(DEADLINE_S, connect=2), transport=client.transport,
                                         follow_redirects=False) as http:
                status, candidates = await _search(_Session(client, http), query, bbox)
    except TimeoutError:
        logger.warning('VWorld search passed its %.0f s deadline', DEADLINE_S)
        return {**reply, 'status': 'unavailable', 'candidates': [], 'error': VworldUnavailable('TIMEOUT').message}
    except VworldUnavailable as error:
        return {**reply, 'status': 'unavailable', 'candidates': [], 'error': error.message}
    if status == 'none':
        return {**reply, 'status': 'none', 'candidates': [], 'error': MESSAGES['none']}
    return {**reply, 'status': status, 'candidates': candidates}
