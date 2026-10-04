import math
import httpx
from backend.app.modules.land.pnu import normalize_pnu


class VworldClient:
    def __init__(self, api_key: str, *, transport=None):
        self.api_key = api_key
        self.transport = transport

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
