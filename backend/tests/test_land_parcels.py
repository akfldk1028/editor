import asyncio
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.adapters.vworld import VworldClient
from backend.app.api.routes_land import create_land_router

PNU = '1168011200101280003'
SMALL = [[[127,37],[127.1,37],[127.1,37.1],[127,37.1],[127,37]]]
COMPETITOR = [[[126,37],[126.9,37],[126.9,37.9],[126,37.9],[126,37]]]
LARGE = [[[128,37],[129,37],[129,38],[128,38],[128,37]],
         [[128.2,37.2],[128.2,37.8],[128.8,37.8],[128.8,37.2],[128.2,37.2]]]
GEOMETRY = {'type':'MultiPolygon','coordinates':[SMALL,COMPETITOR,LARGE]}

def payload(geometry=GEOMETRY):
    return {'response':{'status':'OK','result':{'featureCollection':{'features':[
        {'geometry':geometry,'properties':{'pnu':PNU,'jibun':'fallback'}}]}}}}

def test_parcel_selects_largest_exterior_and_preserves_holes():
    def handle(request):
        assert request.url.params['attrFilter'] == f'pnu:=:{PNU}'
        assert request.url.params['crs'] == 'EPSG:4326'
        return httpx.Response(200,json=payload())
    result=asyncio.run(VworldClient('key',transport=httpx.MockTransport(handle)).fetch_parcel_geometry(PNU))
    assert result == {'success':True,'geometry':{'type':'Polygon','coordinates':LARGE}}

@pytest.mark.parametrize('address_result',[None,{'text':'full'},[{'text':'full'}]])
def test_reverse_preserves_all_polygons_and_address_fallback(address_result):
    def handle(request):
        if request.url.path.endswith('/data'):
            assert request.url.params['geomFilter']=='POINT(127.0 37.0)'
            return httpx.Response(200,json=payload())
        assert request.url.params['request']=='getAddress'
        if address_result is None:return httpx.Response(503)
        return httpx.Response(200,json={'response':{'status':'OK','result':address_result}})
    result=asyncio.run(VworldClient('key',transport=httpx.MockTransport(handle)).reverse_geocode(127.0,37.0))
    assert result=={'success':True,'pnu':PNU,'address':'fallback' if address_result is None else 'full',
                    'geometry':GEOMETRY,'coordinates':{'x':127.0,'y':37.0}}

@pytest.mark.parametrize('kind',['missing-key','http','empty','malformed','geometry'])
@pytest.mark.parametrize('operation',['parcel','reverse'])
def test_failures_are_safe(kind,operation):
    def handle(request):
        if kind=='missing-key':raise AssertionError('unexpected network')
        if kind=='http':return httpx.Response(503)
        if kind=='empty':return httpx.Response(200,json={'response':{'status':'OK','result':{'featureCollection':{'features':[]}}}})
        if kind=='malformed':return httpx.Response(200,json={'response':[]})
        return httpx.Response(200,json=payload({'type':'Polygon','coordinates':[[[True,37]]]}))
    provider=VworldClient('' if kind=='missing-key' else 'private-key',transport=httpx.MockTransport(handle))
    result=asyncio.run(provider.fetch_parcel_geometry(PNU) if operation=='parcel' else provider.reverse_geocode(127,37))
    assert result['success'] is False and result['geometry'] is None
    assert 'private-key' not in str(result)

def test_routes_validate_before_provider_and_require_same_origin():
    def handle(request):raise AssertionError('unexpected network')
    app=FastAPI();app.include_router(create_land_router(address_client=VworldClient('',transport=httpx.MockTransport(handle))))
    client=TestClient(app)
    for body in ({'x':123,'y':37},{'x':127,'y':45},{'x':'127','y':37},{'x':True,'y':37}):
        assert client.post('/api/v1/land/reverse',json=body).status_code==422
    assert client.post('/api/v1/land/parcel-geometry',json={'pnu':'invalid'}).status_code==422
    for endpoint,body in [('reverse',{'x':127,'y':37}),('parcel-geometry',{'pnu':PNU})]:
        assert client.post('/api/v1/land/'+endpoint,json=body,headers={'Origin':'https://other.example'}).status_code==403
        result=client.post('/api/v1/land/'+endpoint,json=body)
        assert result.status_code==200 and result.json()['success'] is False

def test_successful_routes_use_provider_without_legacy_service(monkeypatch):
    monkeypatch.delenv('EDITOR_ARR_URL',raising=False)
    def handle(request):
        if request.url.path.endswith('/data'):return httpx.Response(200,json=payload())
        return httpx.Response(503)
    app=FastAPI();app.include_router(create_land_router(address_client=VworldClient('key',transport=httpx.MockTransport(handle))))
    client=TestClient(app)
    result=client.post('/api/v1/land/parcel-geometry',json={'pnu':'11680-11200-10128-0003'})
    assert result.status_code==200 and result.json()['geometry']['coordinates']==LARGE
    result=client.post('/api/v1/land/reverse',json={'x':127,'y':37})
    assert result.status_code==200 and result.json()['geometry']==GEOMETRY

@pytest.mark.parametrize('geometry',[
    {'type':'Polygon','coordinates':[]},
    {'type':'Polygon','coordinates':[[[127,37],[128,37],[128,38],[127,38]]]},
    {'type':'Polygon','coordinates':[[[127,37],[128,38],[128,37],[127,38],[127,37]]]},
    {'type':'Polygon','coordinates':[[[181,37],[182,37],[182,38],[181,37]]]},
    {'type':'Polygon','coordinates':[[[127,37],[128,float('nan')],[128,38],[127,37]]]},
])
def test_invalid_geometry_is_rejected(geometry):
    from backend.app.modules.land.parcel_geometry import parcel_geometry
    with pytest.raises(ValueError):parcel_geometry(geometry)
