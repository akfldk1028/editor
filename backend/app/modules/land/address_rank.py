"""Ranking a provider's candidates against what was typed. Pure; the provider calls live in ``vworld/search.py``.

Order: an exact 본번·부번·산 (or 건물번호) on the typed 동·리·가 (or 로·길) first, then how many typed region
words (시도·시군구·읍면) the address carries, then distance to the map's centre. A lot is ``unique`` only when
exactly one exact match exists and nothing was substituted; every other outcome lists candidates and lets the
person choose.
"""
import math
import re

from backend.app.modules.land.address_query import Query, address_words, lot_parts, region_matches, road_parts

LIMIT = 8
# How far a district reaches on the map, by level, in degrees either side of its point (the provider sends a point only).
DISTRICT_SPAN = {'L1': 0.45, 'L2': 0.08, 'L3': 0.05, 'L4': 0.012}
# Place hits that name a facility at a lot, not the lot's building: they still count toward their lot.
MINOR_PLACE = ('도로시설', '전기차충전소', '진출입시설', '면형구조시설', '주차장')


def _point(item):
    try:
        x, y = float(item['point']['x']), float(item['point']['y'])
    except (KeyError, TypeError, ValueError):
        return None
    return [x, y] if math.isfinite(x) and math.isfinite(y) and -180 <= x <= 180 and -90 <= y <= 90 else None


def _distance(point, bbox):
    if not bbox or not point:
        return 0.0
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    return math.hypot((point[0] - cx) * math.cos(math.radians(cy)), point[1] - cy)


def _regions(query: Query, words: list[str]):
    """(matched, contradicted): typed region words found in the address, and typed ones it lacks."""
    typed = query.regions
    matched = sum(region_matches(word, words) for word in typed)
    return matched, len(typed) - matched


def _pnu(item):
    value = item.get('id')
    return value if isinstance(value, str) and re.fullmatch(r'\d{19}', value) else None


def address_candidates(query: Query, items: list[dict], bbox=None) -> list[dict]:
    """Provider address items (``type=address``) as scored candidates, one per parcel and address."""
    seen, rows = set(), []
    for order, item in enumerate(items):
        address = item.get('address') or {}
        parcel, road = address.get('parcel') or '', address.get('road') or ''
        pnu, point = _pnu(item), _point(item)
        if not point or (pnu, road if query.kind == 'road' else '') in seen:
            continue
        seen.add((pnu, road if query.kind == 'road' else ''))
        words = address_words(road) + address_words(parcel)
        if query.kind == 'road':
            parts = road_parts(road)
            same_name = bool(parts) and parts[0] == query.name
            number_match = same_name and query.main is not None and parts[1] == query.main and parts[2] == query.sub
            san_differs = False
            san_same = True
            closeness = (abs(parts[1] - query.main) if same_name and query.main is not None else 10 ** 6) if parts else 10 ** 6
            label = road
            jibun = parcel
        else:
            parts = lot_parts(parcel)
            same_name = bool(parts) and parts[0] == query.name
            main = int(pnu[11:15]) if pnu else (parts[2] if parts else None)
            sub = int(pnu[15:19]) if pnu else (parts[3] if parts else None)
            san = (pnu[10] == '2') if pnu else bool(parts and parts[1])
            numbers_equal = main == query.main and sub == (query.sub or 0)
            number_match = same_name and numbers_equal and san == query.san
            san_differs = same_name and numbers_equal and san != query.san
            san_same = san == query.san
            closeness = (abs((main or 0) - (query.main or 0)) * 10000 + abs((sub or 0) - (query.sub or 0))) if same_name else 10 ** 9
            label = parcel
            jibun = parcel
        matched, contradicted = _regions(query, words)
        rows.append({
            'pnu': pnu, 'kind': query.kind, 'jibun': jibun, 'road': road or None, 'label': label or parcel or road,
            'point': point, 'exact': bool(number_match and not contradicted),
            '_number': number_match, '_san_differs': san_differs, '_san_same': san_same, '_same_name': same_name, '_matched': matched,
            '_contradicted': contradicted, '_closeness': closeness, '_distance': _distance(point, bbox), '_order': order,
        })
    return rows


def _key(row):
    return (not row['exact'], not row['_number'], row['_contradicted'] > 0, not row['_same_name'], -row['_matched'],
            not row['_san_same'], row['_closeness'], row['_distance'], row['_order'])


def _public(rows, *, substituted: bool):
    out = []
    for row in rows[:LIMIT]:
        clean = {key: value for key, value in row.items() if not key.startswith('_')}
        if substituted and not clean['exact']:
            clean['substituted'] = True
        out.append(clean)
    return out


def rank_addresses(query: Query, rows: list[dict]) -> tuple[str, list[dict]]:
    """(status, candidates) for a lot or road search."""
    if not rows:
        return 'none', []
    rows = sorted(rows, key=_key)
    exact = [row for row in rows if row['exact']]
    distinct = {row['pnu'] or row['label'] for row in exact}
    if exact:
        # 산 left out (산곡동 100 when 의정부 has only 산 100): a near match in a 시군구 with no exact one.
        exact_areas = {(row['pnu'] or '')[:5] for row in exact}
        near = [row for row in rows if row['_san_differs'] and not row['_contradicted']
                and (row['pnu'] or '')[:5] not in exact_areas]
        if len(distinct) == 1 and not near:
            return 'unique', _public(exact[:1], substituted=False)
        return 'ambiguous', _public(exact + near, substituted=True)
    # Nothing exact: the closest addresses, each marked as a substitute for what was typed.
    return 'ambiguous', _public(rows, substituted=True)


def _place_lot(parcel: str) -> str:
    """The lot a place stands on, its 지목 suffix dropped: ``… 태평로1가 31대`` / ``… 31 대`` → ``… 태평로1가 31``."""
    return re.sub(r'(\d)\s*[가-힣]$', r'\1', (parcel or '').strip())


def _compact(text: str) -> str:
    return re.sub(r'\s+', '', text or '')


def place_relevant(query: Query, items: list[dict]) -> bool:
    """Some hit is named like the input (score above 0), not only something that happens to be near the map."""
    typed = _compact(query.normalized)
    return bool(typed) and any(typed in _compact(item.get('title') or '') for item in items)


def place_candidates(query: Query, items: list[dict], bbox=None) -> list[dict]:
    """Place hits grouped by the lot they stand on: a lot with an exactly named place, then the most hits, first.
    서울시청 → 태평로1가 31 (the 시청 lot, even though its first hit is a charger there)."""
    typed = _compact(query.normalized)
    groups: dict[str, dict] = {}
    for order, item in enumerate(items):
        title = item.get('title') or ''
        address = item.get('address') or {}
        lot = _place_lot(address.get('parcel') or '')
        point = _point(item)
        if not point or not (lot or address.get('road')):
            continue
        name = _compact(title)
        score = 3 if name == typed else 2 if name.startswith(typed) else 1 if typed in name else 0
        minor = any(word in (item.get('category') or '') for word in MINOR_PLACE)
        group = groups.setdefault(lot or address.get('road'), {
            'title': title, 'score': -1, 'minor': True, 'hits': 0, 'point': point, 'road': address.get('road') or None,
            'lot': lot, 'order': order})
        group['hits'] += score > 0
        if (score, not minor) > (group['score'], not group['minor']):
            group.update(title=title, score=score, minor=minor, point=point, road=address.get('road') or group['road'])
    rows = []
    for group in groups.values():
        matched, contradicted = _regions(query, address_words(group['lot']) + address_words(group['road'] or ''))
        rows.append({'pnu': None, 'kind': 'place', 'jibun': group['lot'] or None, 'road': group['road'],
                     'label': group['title'], 'point': group['point'], 'exact': group['score'] == 3,
                     '_key': (-group['score'], contradicted, group['minor'], -group['hits'],
                              _distance(group['point'], bbox), group['order'])})
    rows.sort(key=lambda row: row['_key'])
    return [{key: value for key, value in row.items() if key != '_key'} for row in rows[:LIMIT]]


def district_candidates(query: Query, items: list[dict], level: str, bbox=None) -> list[dict]:
    rows = []
    for order, item in enumerate(items):
        point, title = _point(item), item.get('title') or ''
        if not point or not title:
            continue
        span = DISTRICT_SPAN.get(level, 0.02)
        words = address_words(title)
        matched, contradicted = _regions(query, words)
        rows.append({'kind': 'area', 'jibun': None, 'road': None, 'label': title, 'point': point,
                     'bbox': [point[0] - span, point[1] - span * 0.8, point[0] + span, point[1] + span * 0.8],
                     'exact': bool(words) and words[-1] == query.name and not contradicted, 'code': str(item.get('id') or ''),
                     '_key': (contradicted, -matched, _distance(point, bbox), order)})
    rows.sort(key=lambda row: row['_key'])
    return [{key: value for key, value in row.items() if key != '_key'} for row in rows[:LIMIT]]
