"""Complete, bounded provider reads for map-only cadastral and land-cover display."""
import asyncio
import hashlib
import json
import math

import httpx

URLS = {'cadastre': 'https://api.vworld.kr/req/wfs', 'cover': 'https://api.mcee.go.kr/geoserver/wfs'}
LAYERS = {'cadastre': 'lp_pa_cbnd_bubun', 'cover': 'EGIS:lv3_2025y'}
CADASTRE_PAGE = 1000
COVER_PAGE = 5000
MAX_FEATURES = 20000


class SourceUnavailable(RuntimeError):
    pass


def bbox(lat, lon, radius):
    dy = radius / 110500
    dx = dy / math.cos(math.radians(lat))
    return lon - dx, lat - dy, lon + dx, lat + dy


async def fetch(kind, bounds, api_key, *, transport=None):
    if kind == 'cadastre' and not api_key:
        raise SourceUnavailable('cadastre: server key is not configured')
    requests, total_bytes = 0, 0
    async with httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(20, connect=5),
                                 headers={'Referer': 'http://localhost'}, follow_redirects=False) as client:
        async def page(params):
            nonlocal requests, total_bytes
            requests += 1
            if requests > 32:
                raise SourceUnavailable(f'{kind}: request budget exceeded; use a smaller viewport')
            try:
                chunks, size = [], 0
                async with client.stream('GET', URLS[kind], params=params) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        total_bytes += len(chunk)
                        # EGIS returns whole regional polygons: a measured Seoul
                        # viewport is 11.27 MB before display clipping.
                        page_limit = 16_000_000 if kind == 'cover' else 8_000_000
                        if size > page_limit or total_bytes > 24_000_000:
                            raise SourceUnavailable(f'{kind}: response exceeds viewport byte budget')
                        chunks.append(chunk)
                body = await asyncio.to_thread(json.loads, b''.join(chunks))
                if not isinstance(body, dict) or not isinstance(body.get('features'), list):
                    raise ValueError('not a feature collection')
                rows = body['features']
                if any(not isinstance(r, dict) or r.get('type') != 'Feature' or
                       not isinstance(r.get('geometry'), dict) or
                       r['geometry'].get('type') not in ('Polygon', 'MultiPolygon') or
                       not isinstance(r.get('properties'), dict) for r in rows):
                    raise ValueError('invalid polygon feature')
                matched = body.get('numberMatched', body.get('totalFeatures'))
                matched = int(matched) if str(matched).isdigit() else None
                return rows, matched
            except SourceUnavailable:
                raise
            except (httpx.HTTPError, ValueError, TypeError):
                # Exception URLs can contain the private provider key.
                raise SourceUnavailable(f'{kind}: provider unavailable or invalid response') from None

        async def cadastre(cell, depth=0):
            w, s, e, n = cell
            rows, matched = await page({'SERVICE': 'WFS', 'REQUEST': 'GetFeature', 'VERSION': '1.1.0',
                'TYPENAME': LAYERS[kind], 'BBOX': f'{s},{w},{n},{e},EPSG:4326',
                'SRSNAME': 'EPSG:4326', 'OUTPUT': 'application/json', 'MAXFEATURES': str(CADASTRE_PAGE),
                'KEY': api_key, 'DOMAIN': 'http://localhost'})
            if (matched is not None and len(rows) == matched) or (matched is None and len(rows) < CADASTRE_PAGE):
                return rows
            if depth >= 4:
                raise SourceUnavailable('cadastre: incomplete viewport at maximum subdivision')
            mx, my = (w + e) / 2, (s + n) / 2
            collected = {}
            for child in ((w, s, mx, my), (mx, s, e, my), (w, my, mx, n), (mx, my, e, n)):
                for row in await cadastre(child, depth + 1):
                    identity = row.get('id') or row['properties'].get('pnu') or json.dumps(row, sort_keys=True)
                    collected[str(identity)] = row
                    if len(collected) > MAX_FEATURES:
                        raise SourceUnavailable('cadastre: feature budget exceeded')
            if matched is not None and len(collected) < matched:
                raise SourceUnavailable('cadastre: incomplete subdivided response')
            return list(collected.values())

        if kind == 'cadastre':
            rows = await cadastre(bounds)
        else:
            rows, seen_pages, expected = [], set(), None
            w, s, e, n = bounds
            for _ in range(20):
                batch, matched = await page({'service': 'WFS', 'version': '2.0.0', 'request': 'GetFeature',
                    'typeNames': LAYERS[kind], 'srsName': 'EPSG:4326', 'outputFormat': 'application/json',
                    'count': str(COVER_PAGE), 'startIndex': str(len(rows)),
                    'bbox': f'{s},{w},{n},{e},urn:ogc:def:crs:EPSG::4326'})
                if expected is not None and matched is not None and expected != matched:
                    raise SourceUnavailable('cover: source changed during pagination')
                if matched is not None:
                    expected = matched
                digest = await asyncio.to_thread(
                    lambda: hashlib.sha256(json.dumps(batch, sort_keys=True).encode()).hexdigest())
                if batch and digest in seen_pages:
                    raise SourceUnavailable('cover: provider repeated a page')
                seen_pages.add(digest)
                rows.extend(batch)
                if len(rows) > MAX_FEATURES:
                    raise SourceUnavailable('cover: feature budget exceeded')
                if expected is not None and len(rows) >= expected:
                    break
                if not batch or (expected is None and len(batch) < COVER_PAGE):
                    if expected is not None and len(rows) < expected:
                        raise SourceUnavailable('cover: incomplete paged response')
                    break
            else:
                raise SourceUnavailable('cover: pagination budget exceeded')
        if len(rows) > MAX_FEATURES:
            raise SourceUnavailable(f'{kind}: feature budget exceeded')
        return {'rows': rows, 'record': {'source': kind, 'url': URLS[kind], 'layer': LAYERS[kind],
                                         'received': len(rows), 'requests': requests, 'complete_bbox': list(bounds)}}
