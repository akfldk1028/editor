import asyncio
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.api.routes_land import create_land_router


def test_pnu_resolution_works_without_legacy_url(monkeypatch):
    monkeypatch.delenv('EDITOR_ARR_URL', raising=False)
    app = FastAPI(); app.include_router(create_land_router())
    client = TestClient(app)
    result = client.post('/api/v1/land/resolve', json={'input':'11680-11200-10128-0003','input_type':'pnu'})
    assert result.status_code == 200
    assert result.json() == {'valid':True,'parsed':{
        'pnu':'1168011200101280003','sido':'11','sigungu':'680','eupmyeondong':'112',
        'ri':'00','land_type':'1','main_number':'0128','sub_number':'0003','land_type_name':'대'}}
    assert client.post('/api/v1/land/resolve',json={'input':'１２３４５６７８９０１２３４５６７８９','input_type':'pnu'}).status_code == 422
    assert client.post('/api/v1/land/resolve',json={'input':'x','input_type':'address'},headers={'Origin':'https://other.example'}).status_code == 403


def test_address_fallback_preserves_coordinate_only_result():
    from backend.app.adapters.vworld import VworldClient
    sent=[]
    def handle(request):
        sent.append(request.url.params['type'])
        if len(sent)==1:return httpx.Response(200,json={'response':{'status':'NOT_FOUND'}})
        return httpx.Response(200,json={'response':{'status':'OK','result':{'point':{'x':'127','y':'37'}},'refined':{'text':'resolved','structure':{'level4LC':'short'}}}})
    result=asyncio.run(VworldClient('test-key',transport=httpx.MockTransport(handle)).resolve_address('input'))
    assert sent==['PARCEL','ROAD']
    assert result=={'success':True,'address':'input','pnu':None,'coordinates':{'x':127.0,'y':37.0},'geocoded_address':'resolved'}


def test_address_route_uses_provider_directly_and_preserves_pnu():
    from backend.app.adapters.vworld import VworldClient
    def handle(request):
        assert request.url.host=='api.vworld.kr'
        assert request.url.params['type']=='PARCEL'
        return httpx.Response(200,json={'response':{'status':'OK','result':{'point':{'x':'127','y':'37'}},'refined':{'structure':{'level4LC':'1168011200101280003'}}}})
    app=FastAPI();app.include_router(create_land_router(address_client=VworldClient('test-key',transport=httpx.MockTransport(handle))))
    result=TestClient(app).post('/api/v1/land/resolve',json={'input':'address','input_type':'address'})
    assert result.status_code==200
    assert result.json()['pnu']=='1168011200101280003'
    assert result.json()['success'] is True


@pytest.mark.parametrize('kind',['missing-key','http-error','malformed','invalid-point'])
def test_provider_failures_never_expose_key_or_become_success(kind):
    from backend.app.adapters.vworld import VworldClient
    def handle(request):
        if kind=='missing-key':raise AssertionError('No request without credentials')
        if kind=='http-error':return httpx.Response(503)
        if kind=='malformed':return httpx.Response(200,json={'response':[]})
        return httpx.Response(200,json={'response':{'status':'OK','result':{'point':{'x':'NaN','y':'37'}}}})
    result=asyncio.run(VworldClient('' if kind=='missing-key' else 'private-key',transport=httpx.MockTransport(handle)).resolve_address('input'))
    assert result['success'] is False
    assert result['pnu'] is None
    assert 'private-key' not in str(result)
