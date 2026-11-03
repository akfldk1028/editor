import logging
import httpx
from backend.app.modules.land.pnu import normalize_pnu
from backend.app.modules.land.parcel_geometry import parcel_geometry
from backend.app.modules.land.vworld.search import UNAVAILABLE, VworldUnavailable, search

logger = logging.getLogger(__name__)


class VworldClient:
    def __init__(self, api_key: str, *, transport=None):
        self.api_key = api_key
        self.transport = transport

    async def _request(self, endpoint: str, params: dict):
        return (await self._request_coded(endpoint, params))[0]

    async def _request_coded(self, endpoint: str, params: dict):
        """(result, refusal): the refusal is the provider's error code (INVALID_KEY, OVER_REQUEST_LIMIT, …) or HTTP
        when the call itself failed — never "no parcel here", which is (None, None)."""
        if not self.api_key:
            return None, None
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=5), transport=self.transport,
                                         follow_redirects=False) as client:
                response = await client.get('https://api.vworld.kr/req/' + endpoint,
                    params={**params, 'key':self.api_key, 'format':'json', 'crs':'EPSG:4326'})
                response.raise_for_status()
                data = response.json()['response']
                if isinstance(data, dict) and data.get('status') == 'OK':
                    return data['result'], None
                if isinstance(data, dict) and data.get('status') == 'ERROR':
                    # A key or quota refusal is not "no parcel here": it is logged with its code (never the key).
                    code = str((data.get('error') or {}).get('code') or 'ERROR')
                    logger.warning('VWorld %s refused: %s', endpoint, code)
                    return None, code
                if not isinstance(data, dict):
                    return None, 'MALFORMED'
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
            logger.warning('VWorld %s failed (%s)', endpoint, type(error).__name__)
            return None, 'HTTP'
        return None, None

    async def _parcel(self, filters: dict, *, largest: bool):
        geometry, properties, _ = await self._parcel_coded(filters, largest=largest)
        return geometry, properties

    async def _parcel_coded(self, filters: dict, *, largest: bool):
        result, refusal = await self._request_coded('data', {'service':'data', 'request':'GetFeature',
            'data':'LP_PA_CBND_BUBUN', 'size':'1', **filters})
        try:
            feature = result['featureCollection']['features'][0]
            return parcel_geometry(feature['geometry'], largest=largest), feature.get('properties') or {}, None
        except (ValueError, KeyError, TypeError, IndexError, AttributeError):
            return None, {}, refusal

    async def fetch_parcel_geometry(self, pnu: str) -> dict:
        pnu = normalize_pnu(pnu)
        geometry, properties, refusal = await self._parcel_coded({'attrFilter':f'pnu:=:{pnu}'}, largest=True)
        if geometry is None:
            if refusal in UNAVAILABLE:
                # The key, the quota or the provider failed: say so, never "this PNU has no parcel".
                return {'success':False, 'geometry':None, 'error':VworldUnavailable(refusal).message, 'unavailable':refusal}
            return {'success':False, 'geometry':None, 'error':self._parcel_error()}
        address = properties.get('addr') if isinstance(properties, dict) else None
        # The parcel layer carries the full lot address, so a lookup by PNU needs no reverse geocode.
        return {'success':True, 'geometry':geometry, **({'address':address} if isinstance(address, str) and address else {})}

    def _parcel_error(self):
        return '필지 조회가 설정되지 않았어요 (VWORLD_API_KEY).' if not self.api_key else '필지 정보를 받지 못했어요.'

    async def reverse_geocode(self, x: float, y: float) -> dict:
        geometry, properties = await self._parcel({'geomFilter':f'POINT({x} {y})'}, largest=False)
        base = {'coordinates':{'x':x, 'y':y}, 'geometry':geometry}
        if geometry is None:
            return {**base, 'success':False, 'pnu':None, 'address':None, 'error':self._parcel_error()}
        if not isinstance(properties, dict): properties = {}
        try:
            pnu = normalize_pnu(properties.get('pnu', ''))
        except (ValueError, TypeError, AttributeError):
            pnu = None
        address = properties.get('jibun') or properties.get('addr') or ''
        if not isinstance(address, str): address = ''
        result = await self._request('address', {'service':'address', 'request':'getAddress',
            'point':f'{x},{y}', 'type':'PARCEL'})
        if isinstance(result, list): result = result[0] if result else None
        if isinstance(result, dict) and isinstance(result.get('text'), str) and result['text']:
            address = result['text']
        return {**base, 'success':True, 'pnu':pnu, 'address':address}

    async def search(self, query: str, bbox=None) -> dict:
        """Ranked candidates for a typed address, lot, road address, place or PNU (``vworld/search.py``)."""
        return await search(self, query, bbox)

    async def resolve_address(self, address: str) -> dict:
        """One parcel for a typed address: only a ``unique`` search answer gives a PNU; anything else fails with
        its reason (several parcels fit, nothing fits, the provider is unavailable)."""
        failure = {'success':False, 'address':address, 'pnu':None}
        found = await self.search(address)
        status = found.get('status')
        candidates = found.get('candidates') or []
        if status == 'unique' and candidates and candidates[0].get('pnu'):
            best = candidates[0]
            x, y = best['point']
            return {'success':True, 'address':address, 'pnu':best['pnu'], 'coordinates':{'x':x, 'y':y},
                    'geocoded_address':best.get('label') or address, 'status':status}
        if status == 'ambiguous' and found.get('kind') in ('area', 'place') and candidates:
            # A district or a place: its point (no PNU), so callers that only move the map keep working.
            best = candidates[0]
            x, y = best['point']
            return {'success':True, 'address':address, 'pnu':None, 'coordinates':{'x':x, 'y':y},
                    'geocoded_address':best.get('label') or address, 'status':status, 'candidates':candidates}
        if status == 'ambiguous':
            error = '해당하는 곳이 여러 곳이거나 입력한 그대로의 지번이 없어요. 지도 검색에서 골라 주세요.'
        else:
            error = found.get('error') or '주소에 해당하는 필지를 찾지 못했어요.'
        return {**failure, 'error':error, 'status':status, 'candidates':candidates}
