import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.api.routes_land import create_land_router
from backend.app.modules.regulations.zoning_catalog import get_zones


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv('EDITOR_ARR_URL',raising=False)
    app=FastAPI();app.include_router(create_land_router())
    return TestClient(app)


def test_reference_limits_run_without_arr(client):
    zone=get_zones()['zones'][0]
    response=client.post('/api/v1/land/zoning-limits',json={'zones':[zone['zone_name']]})
    assert response.status_code==200
    value=response.json()
    assert value['limits']['bcr_limit']==zone['bcr_default']
    assert value['limits']['far_limit']==zone['far_default']
    assert value['scope']=='national_reference'
    assert value['permit_compliance_verified'] is False


def test_multiple_zones_without_areas_do_not_invent_limit(client):
    zones=[z['zone_name'] for z in get_zones()['zones'][:2]]
    value=client.post('/api/v1/land/zoning-limits',json={'zones':zones}).json()
    assert value['limits']['bcr_limit'] is None
    assert value['limits']['far_limit'] is None


@pytest.mark.parametrize('kind',['duplicate','blank','missing-area','negative','unknown-area','extra-area'])
def test_unsafe_area_inputs_rejected(client,kind):
    names=[z['zone_name'] for z in get_zones()['zones'][:2]]
    body={'zones':names,'zone_areas':dict.fromkeys(names,100.0)}
    if kind=='duplicate':body['zones']=[names[0],names[0]]
    elif kind=='blank':body['zones']=[' ']
    elif kind=='missing-area':body['zone_areas'].pop(names[1])
    elif kind=='negative':body['zone_areas'][names[0]]=-1
    elif kind=='unknown-area':body={'zones':['unknown'],'zone_areas':{'unknown':100.0}}
    else:body['zone_areas']['extra']=1
    assert client.post('/api/v1/land/zoning-limits',json=body).status_code==422


def test_cross_origin_rejected(client):
    response=client.post('/api/v1/land/zoning-limits',json={'zones':['unknown']},headers={'Origin':'https://other.example'})
    assert response.status_code==403
