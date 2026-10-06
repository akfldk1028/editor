from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.modules.land.routers.analysis import create_land_router
from backend.app.modules.land.repository import LandRepository
from backend.app.modules.land.datum import DatumService
from backend.app.adapters.elevation import ElevationFetchError

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
    monkeypatch.setenv('ENABLE_DATUM_ELEVATION', 'true' if kwargs.pop('datum_enabled', False) else 'false')
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


def test_datum_opt_in_computes_locally_with_per_request_service(tmp_path, monkeypatch):
    instances = []
    class Provider:
        provenance = {'actual_provider': 'fixture_dem'}
        def fetch(self, points): return [25.0] * len(points)
    def factory():
        instance = DatumService(Provider())
        instances.append(instance)
        return instance
    client = client_for(tmp_path, monkeypatch, datum_enabled=True, datum_service_factory=factory)
    body = {'input_type':'pnu', 'input':PNU, 'include_law':False}
    for _ in range(2):
        response = client.post('/api/v1/land/analyze', json=body)
        assert response.status_code == 200
        value = response.json()
        assert value['execution_owner'] == 'editor'
        assert value['setback_lines']['datum_result']['elevation_m'] == 25
        assert value['setback_lines']['datum_result']['elevation_source'] == 'fixture_dem'
    assert len(instances) == 2 and instances[0] is not instances[1]


def test_failed_datum_keeps_relative_geometry_and_records_error(tmp_path, monkeypatch):
    class FailedProvider:
        provenance = {'actual_provider':None, 'providers':[], 'fallback_used':False}
        def fetch(self, points): raise ElevationFetchError('unavailable')
    baseline = client_for(tmp_path, monkeypatch)
    body = {'input_type':'pnu', 'input':PNU, 'include_law':False}
    relative = baseline.post('/api/v1/land/analyze', json=body).json()['setback_lines']
    client = client_for(tmp_path, monkeypatch, datum_enabled=True,
                        datum_service_factory=lambda: DatumService(FailedProvider()))
    response = client.post('/api/v1/land/analyze', json=body)
    assert response.status_code == 200
    result = response.json()
    assert result['setback_lines']['datum_result']['elevation_source'] == 'failed'
    assert result['setback_lines']['datum_result']['elevation_m'] is None
    assert result['errors'] == ['Datum elevation unavailable']
    for key in ('walls', 'slanted_polygons'):
        assert result['setback_lines']['sunlight_envelope'][key] == relative['sunlight_envelope'][key]


def test_disabled_datum_never_constructs_provider(tmp_path, monkeypatch):
    def factory(): raise AssertionError('disabled datum was constructed')
    client = client_for(tmp_path, monkeypatch, datum_service_factory=factory)
    response = client.post('/api/v1/land/analyze', json={
        'input_type':'pnu', 'input':PNU, 'include_law':False})
    assert response.status_code == 200
    assert response.json()['setback_lines']['datum_result'] is None


def test_default_datum_factory_uses_explicit_environment_settings(tmp_path, monkeypatch):
    from backend.app.modules.land import services
    captured = []
    class Provider:
        provenance = {'actual_provider': 'fixture_dem'}
        def __init__(self, provider, **kwargs): captured.append((provider, kwargs))
        def fetch(self, points): return [25.0] * len(points)
    monkeypatch.setattr(services, 'ElevationClient', Provider)
    monkeypatch.setenv('ELEVATION_PROVIDER', 'ngii_local_dem')
    monkeypatch.setenv('NGII_DEM_LOCAL_PATH', 'fixture.tif')
    monkeypatch.setenv('DATUM_EDGE_SUBSAMPLE', 'false')
    monkeypatch.setenv('DATUM_MEDIAN_FILTER', 'false')
    client = client_for(tmp_path, monkeypatch, datum_enabled=True)
    response = client.post('/api/v1/land/analyze', json={
        'input_type':'pnu', 'input':PNU, 'include_law':False})
    assert response.status_code == 200
    assert captured == [('ngii_local_dem', {'opentopodata_url':'http://localhost:5000',
                                          'local_dem_path':'fixture.tif', 'timeout':5})]


def test_invalid_datum_configuration_returns_safe_503(tmp_path, monkeypatch):
    monkeypatch.setenv('DATUM_EDGE_SUBSAMPLE_STEP_M', 'secret invalid setting')
    client = client_for(tmp_path, monkeypatch, datum_enabled=True)
    response = client.post('/api/v1/land/analyze', json={
        'input_type':'pnu', 'input':PNU, 'include_law':False})
    assert response.status_code == 503
    assert response.json()['detail'] == 'Datum configuration unavailable'


def test_invalid_geometry_and_program_rejected_before_provider(tmp_path, monkeypatch):
    client = client_for(tmp_path, monkeypatch)
    body = {'input_type':'pnu','input':PNU,'include_law':False}
    for extra in [{'geometry':{'type':'Point','coordinates':[127,37]}},
                  {'floor_area_m2':-1}, {'assessment_date':'not-a-date'},
                  {'program_uses':[{'building_type':'office','floor_area_m2':False}]}]:
        assert client.post('/api/v1/land/analyze', json={**body,**extra}).status_code == 422
