import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.modules.land.repository import LandRepository
from backend.app.modules.land.routers.analysis import create_land_router

ORIGIN = 'http://editor.test'


def square(west, south, size=0.0002):
    return {'type': 'Polygon', 'coordinates': [[[west, south], [west + size, south], [west + size, south + size],
                                                [west, south + size], [west, south]]]}


# Two parcels sharing an edge and one a few hundred metres away; each pick point sits inside its parcel.
PARCELS = {
    '4115011300106840001': (square(127.1000, 37.7300), '경기도 의정부시 산곡동 684-1', 1000.0, ['제2종일반주거지역', '가축사육제한구역']),
    '4115011300106850000': (square(127.1002, 37.7300), '경기도 의정부시 산곡동 685', 500.5, ['자연녹지지역']),
    '4115011300107000000': (square(127.1100, 37.7400), '경기도 의정부시 산곡동 700', 250.0, ['제2종일반주거지역']),
}


def pick(pnu):
    ring = PARCELS[pnu][0]['coordinates'][0]
    return {'pnu': pnu, 'lng': ring[0][0] + 0.0001, 'lat': ring[0][1] + 0.0001}


class Addresses:
    def __init__(self):
        self.calls = 0

    async def reverse_geocode(self, x, y):
        self.calls += 1
        for pnu, (geometry, address, _, _) in PARCELS.items():
            west, south = geometry['coordinates'][0][0]
            if west <= x <= west + 0.0002 and south <= y <= south + 0.0002:
                return {'success': True, 'pnu': pnu, 'address': address, 'geometry': geometry,
                        'coordinates': {'x': x, 'y': y}}
        return {'success': False, 'pnu': None, 'address': None, 'geometry': None}

    async def fetch_parcel_geometry(self, pnu):
        return {'success': pnu in PARCELS, 'geometry': PARCELS[pnu][0] if pnu in PARCELS else None}


class Attributes:
    async def fetch(self, pnu):
        _, _, area, zones = PARCELS[pnu]
        return {'success': True, 'pnu': pnu, 'zones': zones, 'land_area_m2': area, 'official_land_price': None,
                'land_use_situation': '대', 'source': 'vworld', 'zones_fetched': True}


def client(tmp_path):
    app = FastAPI()
    app.include_router(create_land_router(public_origin=ORIGIN, repository=LandRepository(tmp_path),
                                          address_client=Addresses(), attribute_client=Attributes()))
    return TestClient(app)


def body(*pnus, **extra):
    return {'parcels': [pick(pnu) for pnu in pnus], **extra}


A, B, FAR = PARCELS


def test_v3_database_migrates_to_v4_and_keeps_existing_rows(tmp_path):
    repo = LandRepository(tmp_path)
    repo.save({'input_type': 'pnu'}, {}, 1.0)
    with sqlite3.connect(repo.path) as db:
        db.execute('DROP TABLE site_selections')
        db.execute('PRAGMA user_version=3')
    assert repo.stats()['total_queries'] == 1
    with sqlite3.connect(repo.path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 4
        columns = [row[1] for row in db.execute('PRAGMA table_info(site_selections)')]
    assert columns == ['selection_id', 'created_at', 'label', 'parcel_count', 'total_area_m2', 'contiguous',
                       'parcels_json', 'source_json']


def test_one_parcel_is_filled_by_the_server_and_round_trips(tmp_path):
    api = client(tmp_path)
    assert api.get('/api/v1/land/selections/latest').status_code == 404
    response = api.post('/api/v1/land/selections', json=body(A), headers={'Origin': ORIGIN})
    assert response.status_code == 200
    saved = response.json()
    assert saved['label'] == '경기도 의정부시 산곡동 684-1'
    assert saved['parcel_count'] == 1 and saved['contiguous'] is True and saved['total_area_m2'] == 1000.0
    assert saved['parcels'][0]['summary'] == {'address': '경기도 의정부시 산곡동 684-1', 'land_category': '대',
                                              'area_m2': 1000.0, 'zones': ['제2종일반주거지역']}
    assert saved['zones'] == ['제2종일반주거지역']
    assert saved['source'][A]['land']['provider'] == 'vworld'
    assert 'geometries' not in saved and 'outline' not in saved
    assert api.get('/api/v1/land/selections/latest').json() == saved
    with sqlite3.connect(LandRepository(tmp_path).path) as db:
        stored = ' '.join(map(str, db.execute('SELECT * FROM site_selections').fetchone()))
    assert 'coordinates' not in stored and 'Polygon' not in stored


def test_two_touching_parcels_are_contiguous_and_keep_the_users_order(tmp_path):
    api = client(tmp_path)
    preview = api.post('/api/v1/land/selections/preview', json=body(B, A)).json()
    assert preview['contiguous'] is True
    assert preview['outline']['type'] == 'Polygon'
    assert set(preview['geometries']) == {A, B}
    saved = api.post('/api/v1/land/selections', json=body(B, A, label='고산 합필')).json()
    assert [parcel['pnu'] for parcel in saved['parcels']] == [B, A]
    assert saved['label'] == '고산 합필' and saved['parcel_count'] == 2 and saved['total_area_m2'] == 1500.5
    assert saved['zones'] == ['자연녹지지역', '제2종일반주거지역']
    assert api.get('/api/v1/land/selections?limit=5').json()['selections'][0]['selection_id'] == saved['selection_id']


def test_two_apart_parcels_save_but_are_not_contiguous(tmp_path):
    api = client(tmp_path)
    saved = api.post('/api/v1/land/selections', json=body(A, FAR)).json()
    assert saved['contiguous'] is False
    assert saved['label'] == '경기도 의정부시 산곡동 684-1 외 1필지'
    assert api.get('/api/v1/land/selections/latest').json()['contiguous'] is False


def test_bad_repeated_or_too_many_parcels_are_400(tmp_path):
    api = client(tmp_path)
    assert api.post('/api/v1/land/selections', json={'parcels': [{**pick(A), 'pnu': '12345'}]}).status_code == 400
    assert api.post('/api/v1/land/selections', json={'parcels': [pick(A), {**pick(A), 'pnu': '41150-11300-10684-0001'}]}).status_code == 400
    many = [{'pnu': f'41150113001{index:04d}0000', 'lng': 127.1, 'lat': 37.73} for index in range(51)]
    assert api.post('/api/v1/land/selections', json={'parcels': many}).status_code == 400
    assert api.post('/api/v1/land/selections', json={'parcels': []}).status_code == 422
    assert api.post('/api/v1/land/selections', json={**body(A), 'geometry': {}}).status_code == 422
    assert api.get('/api/v1/land/selections').json() == {'selections': []}


def test_cross_origin_selection_is_403(tmp_path):
    api = client(tmp_path)
    assert api.post('/api/v1/land/selections', json=body(A), headers={'Origin': 'https://other.example'}).status_code == 403
    assert api.post('/api/v1/land/selections/preview', json=body(A), headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
    assert api.get('/api/v1/land/selections').json() == {'selections': []}


def test_selection_without_storage_is_503(monkeypatch):
    monkeypatch.delenv('EDITOR_LAND_DATA_DIR', raising=False)
    app = FastAPI()
    app.include_router(create_land_router(public_origin=ORIGIN, address_client=Addresses(), attribute_client=Attributes()))
    api = TestClient(app)
    assert api.post('/api/v1/land/selections', json=body(A)).status_code == 503
    assert api.get('/api/v1/land/selections/latest').status_code == 503
