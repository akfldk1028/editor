"""Vworld land attributes; caching belongs to the land application service.

Unlike the legacy stub, missing credentials never report a successful lookup.
Malformed shapes and negative/nonfinite numbers fail their individual endpoint;
error messages omit provider exceptions because their URLs contain API keys.
"""
import asyncio
from datetime import date
import math

import httpx

from backend.app.modules.land.pnu import normalize_pnu
from backend.app.modules.regulations.zoning_catalog import get_zones


BASE_URL = 'https://api.vworld.kr/ned/data'


def _number(value):
    if value is None or value == '':
        return None
    if type(value) not in (str, int, float):
        raise ValueError('Invalid number')
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError('Invalid number')
    return number


def _zones(items):
    catalog = {zone['zone_name'] for zone in get_zones()['zones']}
    zones, seen = [], set()
    for item in items:
        if item.get('cnflcAtNm') not in ('포함', '저촉', None):
            continue
        name = item.get('prposAreaDstrcCodeNm', '')
        if not isinstance(name, str):
            raise ValueError('Invalid zone name')
        name = name.strip()
        if not name:
            continue
        if not name.endswith(('지역', '지구', '구역', '권역')) and name + '지역' in catalog:
            name += '지역'
        if name not in seen:
            zones.append(name)
            seen.add(name)
    return {'zones': zones}


def _parcel(items):
    item = items[0]
    area = _number(item.get('lndpclAr'))
    use = item.get('lndcgrCodeNm', '')
    if not isinstance(use, str):
        raise ValueError('Invalid land use')
    return {'land_area_m2': area, 'land_use_situation': use.strip()}


def _price(items):
    value = _number(items[0].get('pblntfPclnd'))
    return {'official_land_price': int(value) if value is not None else None}


class VworldLandClient:
    def __init__(self, api_key: str, *, transport=None, year=None):
        if year is not None and (type(year) is not int or not 2 <= year <= 9999):
            raise ValueError('Invalid price assessment year')
        self.api_key = api_key
        self.transport = transport
        self.year = year

    async def _part(self, client, pnu, endpoint, wrapper, field, parse, *, year=None):
        params = {'key': self.api_key, 'pnu': pnu, 'format': 'json', 'pageNo': '1',
                  'numOfRows': '50' if endpoint == 'getLandUseAttr' else '1'}
        if year is not None:
            params['stdrYear'] = str(year)
        try:
            response = await client.get(f'{BASE_URL}/{endpoint}', params=params)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get(wrapper, {}), dict):
                raise ValueError('Invalid response wrapper')
            items = data.get(wrapper, {}).get(field, [])
            if isinstance(items, dict):
                items = [items]
            if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
                raise ValueError('Invalid response entries')
            if not items:
                return False, {}, f'{endpoint}: no data for this PNU'
            return True, parse(items), None
        except httpx.ConnectError:
            return False, {}, f'{endpoint}: connection failed'
        except httpx.HTTPError:
            return False, {}, f'{endpoint}: provider unavailable'
        except (ValueError, TypeError, OverflowError):
            return False, {}, f'{endpoint}: invalid provider data'

    async def _land_price(self, client, pnu):
        year = self.year if self.year is not None else date.today().year
        for candidate in (year, year - 1):
            result = await self._part(client, pnu, 'getIndvdLandPriceAttr',
                'indvdLandPrices', 'field', _price, year=candidate)
            if result[0]:
                return result
        return False, {}, 'getIndvdLandPriceAttr: no usable data'

    async def fetch(self, pnu: str) -> dict:
        pnu = normalize_pnu(pnu)
        result = {'success': False, 'pnu': pnu, 'zones': [], 'land_area_m2': None,
                  'official_land_price': None, 'land_use_situation': '',
                  'source': 'unavailable', 'zones_fetched': False}
        if not self.api_key:
            return {**result, 'message': 'Vworld land lookup is not configured',
                    'errors': ['Vworld land lookup is not configured']}
        async with httpx.AsyncClient(transport=self.transport, timeout=httpx.Timeout(15, connect=5),
                                     follow_redirects=False) as client:
            parts = await asyncio.gather(
                self._part(client, pnu, 'getLandUseAttr', 'landUses', 'field', _zones),
                self._part(client, pnu, 'ladfrlList', 'ladfrlVOList', 'ladfrlVOList', _parcel),
                self._land_price(client, pnu),
            )
        errors = []
        for success, fields, error in parts:
            if success:
                result.update(fields)
                result['success'] = True
            else:
                errors.append(error)
        result['zones_fetched'] = parts[0][0]
        if errors:
            result['errors'] = errors
        if result['success']:
            result['source'] = 'vworld'
        else:
            result['message'] = 'All Vworld API calls failed.'
        return result
