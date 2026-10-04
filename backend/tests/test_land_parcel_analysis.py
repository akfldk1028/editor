from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.routes_land import create_land_router
from backend.app.modules.land.repository import LandRepository

PNU = '1168011200101280003'
GEOMETRY = {'type': 'Polygon', 'coordinates': [[[127.0,37.0],[127.001,37.0],
            [127.001,37.001],[127.0,37.001],[127.0,37.0]]]}
ZONE = '제2종일반주거지역'


class Addresses:
    async def resolve_address(self, address):
        return {'success': True, 'pnu': PNU, 'address': address, 'coordinates': {'x':127, 'y':37}}
    async def fetch_parcel_geometry(self, pnu):
        return {'success': True, 'geometry': GEOMETRY}


class Attributes:
    async def fetch(self, pnu):
        return {'success': True, 'pnu': pnu, 'zones': [ZONE], 'land_area_m2': 900,
                'official_land_price': 1200, 'land_use_situation': '대',
                'source': 'vworld', 'zones_fetched': True}


class GeometryProvider:
    async def zone_features(self, parcel):
        return [{'type': 'Feature', 'properties': {'uname': ZONE}, 'geometry': GEOMETRY}]
    async def cadastral_features(self, parcel):
        return []


def client_for(tmp_path, monkeypatch, **kwargs):
    monkeypatch.delenv('EDITOR_ARR_URL', raising=False)
    monkeypatch.delenv('ENABLE_DATUM_ELEVATION', raising=False)
    app = FastAPI()
    app.include_router(create_land_router(address_client=kwargs.pop('address_client', Addresses()),
        attribute_client=Attributes(), geometry_client=GeometryProvider(),
        repository=LandRepository(tmp_path), **kwargs))
    return TestClient(app)


def test_pnu_and_address_analysis_have_real_geometry_branch(tmp_path, monkeypatch):
    client = client_for(tmp_path, monkeypatch)
    for kind, value in [('pnu', PNU), ('address', 'fixture address')]:
        response = client.post('/api/v1/land/analyze', json={'input_type':kind, 'input':value,
            'include_law':False, 'assessment_date':'2026-10-04'})
        assert response.status_code == 200
        result = response.json()
        assert result['pnu']['pnu'] == PNU
        assert result['land_info']['land_area_m2'] == 900
        assert result['setback_lines'] is not None
        assert result['assessment']['permit_compliance_verified'] is False
        assert result['storage']['saved'] is True
    assert client.get('/api/v1/land/stats?scope=editor').json()['total_queries'] == 2


def test_coordinate_only_address_does_not_crash_or_claim_parcel(tmp_path, monkeypatch):
    class CoordinateOnly(Addresses):
        async def resolve_address(self, address):
            return {'success':True, 'pnu':None, 'address':address, 'coordinates':{'x':127,'y':37}}
    client = client_for(tmp_path, monkeypatch, address_client=CoordinateOnly())
    response = client.post('/api/v1/land/analyze', json={'input_type':'address','input':'fixture','include_law':False})
    assert response.status_code == 200
    assert response.json()['pnu'] is None
    assert response.json()['regulations'] is None
    assert response.json()['warning']
    assert response.json()['errors']


def test_datum_opt_in_and_law_requests_still_require_owner(tmp_path, monkeypatch):
    client = client_for(tmp_path, monkeypatch)
    body = {'input_type':'pnu', 'input':PNU, 'include_law':True}
    assert client.post('/api/v1/land/analyze', json=body).status_code == 503
    monkeypatch.setenv('ENABLE_DATUM_ELEVATION', 'true')
    assert client.post('/api/v1/land/analyze', json=dict(body, include_law=False)).status_code == 503


def test_invalid_geometry_and_program_rejected_before_provider(tmp_path, monkeypatch):
    client = client_for(tmp_path, monkeypatch)
    body = {'input_type':'pnu','input':PNU,'include_law':False}
    for extra in [{'geometry':{'type':'Point','coordinates':[127,37]}},
                  {'floor_area_m2':-1}, {'assessment_date':'not-a-date'},
                  {'program_uses':[{'building_type':'office','floor_area_m2':False}]}]:
        assert client.post('/api/v1/land/analyze', json={**body,**extra}).status_code == 422
