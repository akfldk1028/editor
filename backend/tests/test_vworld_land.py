import asyncio
import json

import httpx
import pytest

from backend.app.adapters.vworld.land import VworldLandClient


PNU = '1168011200101280003'


def fetch(handler, *, key='fixture-secret'):
    return asyncio.run(VworldLandClient(key, transport=httpx.MockTransport(handler), year=2026).fetch(PNU))


def test_three_endpoints_normalize_filter_deduplicate_and_retry_previous_year():
    seen = []
    def handler(request):
        seen.append((request.url.path, dict(request.url.params)))
        assert request.url.params['pnu'] == PNU and request.url.params['key'] == 'fixture-secret'
        endpoint = request.url.path.rsplit('/', 1)[1]
        if endpoint == 'getLandUseAttr':
            return httpx.Response(200, json={'landUses': {'field': [
                {'prposAreaDstrcCodeNm': ' 일반상업 ', 'cnflcAtNm': '포함'},
                {'prposAreaDstrcCodeNm': '일반상업지역', 'cnflcAtNm': '저촉'},
                {'prposAreaDstrcCodeNm': '자연녹지지역', 'cnflcAtNm': '접함'},
                {'prposAreaDstrcCodeNm': '지구단위계획구역'},
            ]}})
        if endpoint == 'ladfrlList':
            return httpx.Response(200, json={'ladfrlVOList': {'ladfrlVOList': {'lndpclAr': '123.5', 'lndcgrCodeNm': ' 대 '}}})
        if request.url.params['stdrYear'] == '2026':
            return httpx.Response(200, json={'indvdLandPrices': {'field': []}})
        return httpx.Response(200, json={'indvdLandPrices': {'field': [{'pblntfPclnd': '345.9'}]}})
    result = fetch(handler)
    assert result == {'success': True, 'pnu': PNU, 'zones': ['일반상업지역', '지구단위계획구역'],
        'land_area_m2': 123.5, 'official_land_price': 345, 'land_use_situation': '대',
        'source': 'vworld', 'zones_fetched': True}
    assert [params['stdrYear'] for path, params in seen if path.endswith('getIndvdLandPriceAttr')] == ['2026', '2025']


def test_no_key_is_explicitly_unavailable_and_never_calls_provider():
    result = fetch(lambda request: pytest.fail('no key must not call network'), key='')
    assert result['success'] is False and result['source'] == 'unavailable'
    assert result['zones_fetched'] is False
    assert 'not configured' in result['message']


def test_partial_area_success_keeps_zone_failure_and_disables_zone_cache_eligibility():
    def handler(request):
        if request.url.path.endswith('ladfrlList'):
            return httpx.Response(200, json={'ladfrlVOList': {'ladfrlVOList': [{'lndpclAr': 0, 'lndcgrCodeNm': ''}]}})
        return httpx.Response(503)
    result = fetch(handler)
    assert result['success'] is True and result['source'] == 'vworld'
    assert result['land_area_m2'] == 0 and result['official_land_price'] is None
    assert result['zones'] == [] and result['zones_fetched'] is False
    assert len(result['errors']) == 2
    assert 'fixture-secret' not in json.dumps(result) and 'https://' not in json.dumps(result)


@pytest.mark.parametrize('payload', [[], {'landUses': []}, {'landUses': {'field': [None]}},
    {'landUses': {'field': [{'prposAreaDstrcCodeNm': 123}]}}])
def test_malformed_provider_shape_fails_closed_without_exception_text(payload):
    result = fetch(lambda request: httpx.Response(200, json=payload))
    assert result['success'] is False
    assert result['zones_fetched'] is False and len(result['errors']) == 3
    assert 'fixture-secret' not in json.dumps(result)


@pytest.mark.parametrize('number', ['NaN', 'Infinity', '-1', True, {}, []])
def test_invalid_numeric_values_do_not_become_success(number):
    def handler(request):
        if request.url.path.endswith('ladfrlList'):
            return httpx.Response(200, json={'ladfrlVOList': {'ladfrlVOList': [{'lndpclAr': number}]}})
        if request.url.path.endswith('getIndvdLandPriceAttr'):
            return httpx.Response(200, json={'indvdLandPrices': {'field': [{'pblntfPclnd': number}]}})
        return httpx.Response(200, json={})
    result = fetch(handler)
    assert result['success'] is False
    assert result['land_area_m2'] is None and result['official_land_price'] is None


def test_filtered_zone_response_remains_a_successful_fetch_without_inventing_zone():
    def handler(request):
        if request.url.path.endswith('getLandUseAttr'):
            return httpx.Response(200, json={'landUses': {'field': {'prposAreaDstrcCodeNm': '일반상업지역', 'cnflcAtNm': '접함'}}})
        return httpx.Response(200, json={})
    result = fetch(handler)
    assert result['success'] is True and result['zones_fetched'] is True and result['zones'] == []


def test_invalid_pnu_is_rejected_before_network():
    with pytest.raises(ValueError):
        asyncio.run(VworldLandClient('key', transport=httpx.MockTransport(lambda r: pytest.fail('network'))).fetch('../invalid'))
