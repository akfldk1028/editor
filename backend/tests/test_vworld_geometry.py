import asyncio
import json

import httpx
import pytest

from backend.app.modules.land.vworld.geometry import VworldGeometryClient, GeometryProviderUnavailable


PARCEL = {'type': 'Polygon', 'coordinates': [[[127, 37], [127.001, 37], [127.001, 37.001], [127, 37.001], [127, 37]]]}


def client(handler, key='fixture-secret'):
    return VworldGeometryClient(key, transport=httpx.MockTransport(handler))


@pytest.mark.parametrize('kind,padding,layer,size', [
    ('zone_features', 0.0008, 'LT_C_UQ111', '300'),
    ('cadastral_features', 0.0002, 'LP_PA_CBND_BUBUN', '100'),
])
def test_layer_bbox_and_request_contract(kind, padding, layer, size):
    def handler(request):
        assert request.url.params['data'] == layer
        assert request.url.params['size'] == size
        assert request.url.params['geomFilter'] == f'BOX({127-padding},{37-padding},{127.001+padding},{37.001+padding})'
        if kind == 'zone_features':
            assert request.headers['Referer'] == 'http://localhost'
            assert request.url.params['domain'] == 'http://localhost'
        return httpx.Response(200, json={'response': {'status': 'OK', 'result': {'featureCollection': {'features': []}}}})
    assert asyncio.run(getattr(client(handler), kind)(PARCEL)) == []


@pytest.mark.parametrize('mode,cache_allowed', [('network', True), ('http', True), ('json', True),
                                              ('status', False), ('schema', False)])
def test_failures_are_safe_and_cache_policy_is_explicit(mode, cache_allowed):
    def handler(request):
        if mode == 'network':
            raise httpx.ConnectError('secret URL ' + str(request.url), request=request)
        if mode == 'http':
            return httpx.Response(503)
        if mode == 'json':
            return httpx.Response(200, content=b'not json')
        if mode == 'status':
            return httpx.Response(200, json={'response': {'status': 'ERROR', 'message': 'fixture-secret'}})
        return httpx.Response(200, json={'response': {'status': 'OK', 'result': {'featureCollection': {'features': [None]}}}})
    with pytest.raises(GeometryProviderUnavailable) as error:
        asyncio.run(client(handler).zone_features(PARCEL))
    assert error.value.cache_allowed is cache_allowed
    assert 'fixture-secret' not in str(error.value) and 'https://' not in str(error.value)


def test_missing_key_and_invalid_geometry_never_fetch_or_allow_cache():
    def fail(request):
        pytest.fail('must not call provider')
    with pytest.raises(GeometryProviderUnavailable) as error:
        asyncio.run(client(fail, key='').zone_features(PARCEL))
    assert error.value.cache_allowed is False
    with pytest.raises(ValueError):
        asyncio.run(client(fail).zone_features({'type': 'Point', 'coordinates': [127, 37]}))


def test_provider_features_are_returned_without_hidden_cache_io():
    feature = {'type': 'Feature', 'properties': {'uname': 'zone'}, 'geometry': PARCEL}
    response = {'response': {'status': 'OK', 'result': {'featureCollection': {'features': [feature]}}}}
    result = asyncio.run(client(lambda r: httpx.Response(200, json=response)).cadastral_features(PARCEL))
    assert result == [feature]
    assert 'fixture-secret' not in json.dumps(result)


def test_multipolygon_query_bounds_keep_source_branch_selection():
    second = [[[128,38],[128.01,38],[128.01,38.01],[128,38.01],[128,38]]]
    parcel = {'type':'MultiPolygon','coordinates':[PARCEL['coordinates'],second]}
    seen = []
    def handler(request):
        seen.append(request.url.params['geomFilter'])
        return httpx.Response(200,json={'response':{'status':'OK','result':{'featureCollection':{'features':[]}}}})
    provider = client(handler)
    asyncio.run(provider.zone_features(parcel))
    asyncio.run(provider.cadastral_features(parcel))
    assert seen == [f'BOX({128-.0008},{38-.0008},{128.01+.0008},{38.01+.0008})',
                    f'BOX({127-.0002},{37-.0002},{127.001+.0002},{37.001+.0002})']
