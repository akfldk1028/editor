import math
import httpx
from backend.app.modules.land.pnu import normalize_pnu
from backend.app.modules.land.parcel_geometry import parcel_geometry


class VworldClient:
    def __init__(self, api_key: str, *, transport=None):
        self.api_key = api_key
        self.transport = transport

    async def _request(self, endpoint: str, params: dict):
        if not self.api_key:
            return None
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=5), transport=self.transport,
                                         follow_redirects=False) as client:
                response = await client.get('https://api.vworld.kr/req/' + endpoint,
                    params={**params, 'key':self.api_key, 'format':'json', 'crs':'EPSG:4326'})
                response.raise_for_status()
                data = response.json()['response']
                if isinstance(data, dict) and data.get('status') == 'OK':
                    return data['result']
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            pass
        return None

    async def _parcel(self, filters: dict, *, largest: bool):
        result = await self._request('data', {'service':'data', 'request':'GetFeature',
            'data':'LP_PA_CBND_BUBUN', 'size':'1', **filters})
        try:
            feature = result['featureCollection']['features'][0]
            return parcel_geometry(feature['geometry'], largest=largest), feature.get('properties') or {}
        except (ValueError, KeyError, TypeError, IndexError, AttributeError):
            return None, {}

    async def fetch_parcel_geometry(self, pnu: str) -> dict:
        pnu = normalize_pnu(pnu)
        geometry, properties = await self._parcel({'attrFilter':f'pnu:=:{pnu}'}, largest=True)
        if geometry is None:
            return {'success':False, 'geometry':None, 'error':self._parcel_error()}
        address = properties.get('addr') if isinstance(properties, dict) else None
        # The parcel layer carries the full lot address, so a lookup by PNU needs no reverse geocode.
        return {'success':True, 'geometry':geometry, **({'address':address} if isinstance(address, str) and address else {})}

    def _parcel_error(self):
        return 'Parcel lookup is not configured' if not self.api_key else 'Parcel lookup returned no usable result'

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

    async def resolve_address(self, address: str) -> dict:
        failure = {'success':False, 'address':address, 'pnu':None}
        if not self.api_key:
            return {**failure, 'error':'Address lookup is not configured'}
        async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=5), transport=self.transport,
                                     follow_redirects=False) as client:
            for kind in ('PARCEL', 'ROAD'):
                try:
                    response = await client.get('https://api.vworld.kr/req/address', params={
                        'service':'address', 'request':'getCoord', 'key':self.api_key,
                        'address':address, 'type':kind, 'format':'json', 'crs':'EPSG:4326', 'refine':'true'})
                    response.raise_for_status()
                    data = response.json()['response']
                    if not isinstance(data, dict) or data.get('status') != 'OK':
                        continue
                    point = data['result']['point']
                    x, y = float(point['x']), float(point['y'])
                    if not math.isfinite(x) or not math.isfinite(y) or not (-180 <= x <= 180 and -90 <= y <= 90):
                        raise ValueError('Invalid coordinates')
                    refined = data.get('refined') or {}
                    candidate = (refined.get('structure') or {}).get('level4LC', '')
                    try:
                        pnu = normalize_pnu(candidate) if isinstance(candidate, str) else None
                    except ValueError:
                        pnu = None
                    text = refined.get('text', '')
                    if not isinstance(text, str):
                        raise ValueError('Invalid address')
                    return {'success':True, 'address':address, 'pnu':pnu,
                            'coordinates':{'x':x, 'y':y}, 'geocoded_address':text}
                except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
                    continue
        return {**failure, 'error':'Address lookup returned no usable result'}
