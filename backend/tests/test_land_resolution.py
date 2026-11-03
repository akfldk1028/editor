import asyncio
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.modules.land.routers.analysis import create_land_router


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


def _search_items(handle_items):
    def handle(request):
        params=request.url.params
        if request.url.path.endswith('/search') and params.get('type')=='address':
            items=handle_items(params)
            return httpx.Response(200,json={'response':{'status':'OK','record':{'total':str(len(items))},'result':{'items':items}}})
        return httpx.Response(200,json={'response':{'status':'NOT_FOUND'}})
    return handle


def test_address_resolution_gives_a_pnu_only_for_one_exact_parcel():
    from backend.app.modules.land.vworld import VworldClient
    one=lambda params:[{'id':'1168011200101280003','address':{'parcel':'서울특별시 강남구 대치동 128-3','road':''},'point':{'x':'127','y':'37'}}]
    result=asyncio.run(VworldClient('test-key',transport=httpx.MockTransport(_search_items(one))).resolve_address('대치동 128-3'))
    assert result['success'] is True and result['pnu']=='1168011200101280003'
    assert result['coordinates']=={'x':127.0,'y':37.0} and result['geocoded_address']=='서울특별시 강남구 대치동 128-3'
    # The provider's nearest lot (128-4 for 128-3) is never taken as the answer.
    near=lambda params:[{'id':'1168011200101280004','address':{'parcel':'서울특별시 강남구 대치동 128-4','road':''},'point':{'x':'127','y':'37'}}]
    missed=asyncio.run(VworldClient('test-key',transport=httpx.MockTransport(_search_items(near))).resolve_address('대치동 128-3'))
    assert missed['success'] is False and missed['pnu'] is None and missed['status']=='ambiguous'
    assert missed['candidates'][0]['substituted'] is True


def test_address_route_uses_provider_directly_and_preserves_pnu():
    from backend.app.modules.land.vworld import VworldClient
    def items(params):
        assert params['category']=='parcel'
        return [{'id':'1168011200101280003','address':{'parcel':'서울특별시 강남구 대치동 128-3'},'point':{'x':'127','y':'37'}}]
    app=FastAPI();app.include_router(create_land_router(address_client=VworldClient('test-key',transport=httpx.MockTransport(_search_items(items)))))
    client=TestClient(app)
    result=client.post('/api/v1/land/resolve',json={'input':'대치동 128-3','input_type':'address'})
    assert result.status_code==200
    assert result.json()['pnu']=='1168011200101280003'
    assert result.json()['success'] is True
    searched=client.post('/api/v1/land/search',json={'query':'대치동 128-3','bbox':[126.9,37.4,127.1,37.6]})
    assert searched.status_code==200 and searched.json()['status']=='unique'
    assert searched.json()['candidates'][0]['pnu']=='1168011200101280003'
    assert client.post('/api/v1/land/search',json={'query':'x','bbox':[127,37,126,38]}).status_code==422
    assert client.post('/api/v1/land/search',json={'query':'x'},headers={'Origin':'https://other.example'}).status_code==403


@pytest.mark.parametrize('kind',['missing-key','http-error','malformed','invalid-point'])
def test_provider_failures_never_expose_key_or_become_success(kind):
    from backend.app.modules.land.vworld import VworldClient
    def handle(request):
        if kind=='missing-key':raise AssertionError('No request without credentials')
        if kind=='http-error':return httpx.Response(503)
        if kind=='malformed':return httpx.Response(200,json={'response':[]})
        return httpx.Response(200,json={'response':{'status':'OK','result':{'point':{'x':'NaN','y':'37'}}}})
    result=asyncio.run(VworldClient('' if kind=='missing-key' else 'private-key',transport=httpx.MockTransport(handle)).resolve_address('input'))
    assert result['success'] is False
    assert result['pnu'] is None
    assert 'private-key' not in str(result)
