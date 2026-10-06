def test_land_route_validates_input_and_origin_before_local_provider_call(monkeypatch):
    monkeypatch.setenv('ENABLE_DATUM_ELEVATION', 'true')
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.app.modules.land.routers.analysis import create_land_router
    provider_calls=[]
    class Attributes:
        async def fetch(self, pnu):
            provider_calls.append(('attributes', pnu))
            return {'success':True, 'pnu':pnu, 'zones':[], 'errors':[], 'source':'vworld'}
    class Addresses:
        async def fetch_parcel_geometry(self, pnu):
            provider_calls.append(('geometry', pnu))
            return {'success':False, 'error':'Fixture boundary unavailable'}
    app=FastAPI();app.include_router(create_land_router(
        attribute_client=Attributes(), address_client=Addresses()))
    client=TestClient(app)
    for body in [{'input':'','input_type':'address'}, {'input':'bad','input_type':'pnu'},
        {'input':'x','input_type':'address','url':'http://other'}]:
        assert client.post('/api/v1/land/analyze',json=body).status_code==422
    body={'input':'11680-11200-10128-0003','input_type':'pnu','include_law':True}
    assert client.post('/api/v1/land/analyze',json=body,headers={'Origin':'https://other.example'}).status_code==403
    assert provider_calls==[]
    response=client.post('/api/v1/land/analyze',json=body)
    assert response.status_code==200
    assert response.json()['execution_owner']=='editor'
    assert response.json()['pnu']['pnu']=='1168011200101280003'
    assert provider_calls==[('attributes','1168011200101280003'), ('geometry','1168011200101280003')]
