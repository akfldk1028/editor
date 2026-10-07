import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.app.modules.land import selection_facts
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


@pytest.fixture(autouse=True)
def empty_facts_cache():
    selection_facts.facts_cache.clear()
    yield
    selection_facts.facts_cache.clear()


class Addresses:
    def __init__(self):
        self.calls = 0
        self.outlines = []

    async def reverse_geocode(self, x, y):
        self.calls += 1
        for pnu, (geometry, address, _, _) in PARCELS.items():
            west, south = geometry['coordinates'][0][0]
            if west <= x <= west + 0.0002 and south <= y <= south + 0.0002:
                return {'success': True, 'pnu': pnu, 'address': address, 'geometry': geometry,
                        'coordinates': {'x': x, 'y': y}}
        return {'success': False, 'pnu': None, 'address': None, 'geometry': None}

    async def fetch_parcel_geometry(self, pnu):
        self.outlines.append(pnu)
        if pnu not in PARCELS:
            return {'success': False, 'geometry': None}
        return {'success': True, 'geometry': PARCELS[pnu][0], 'address': PARCELS[pnu][1]}


class Attributes:
    def __init__(self):
        self.fetched = []

    async def fetch(self, pnu):
        self.fetched.append(pnu)
        _, _, area, zones = PARCELS[pnu]
        return {'success': True, 'pnu': pnu, 'zones': zones, 'land_area_m2': area, 'official_land_price': None,
                'land_use_situation': '대', 'source': 'vworld', 'zones_fetched': True}


def client(tmp_path, addresses=None, attributes=None):
    app = FastAPI()
    app.include_router(create_land_router(public_origin=ORIGIN, repository=LandRepository(tmp_path),
                                          address_client=addresses or Addresses(),
                                          attribute_client=attributes or Attributes()))
    return TestClient(app)


def body(*pnus, **extra):
    return {'parcels': [pick(pnu) for pnu in pnus], **extra}


A, B, FAR = PARCELS


def test_v3_database_migrates_to_v5_and_keeps_existing_rows(tmp_path):
    repo = LandRepository(tmp_path)
    repo.save({'input_type': 'pnu'}, {}, 1.0)
    with sqlite3.connect(repo.path) as db:
        db.execute('DROP TABLE site_selections')
        db.execute('PRAGMA user_version=3')
    assert repo.stats()['total_queries'] == 1
    with sqlite3.connect(repo.path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 5
        columns = [row[1] for row in db.execute('PRAGMA table_info(site_selections)')]
    assert columns == ['selection_id', 'created_at', 'label', 'parcel_count', 'total_area_m2', 'contiguous',
                       'parcels_json', 'source_json', 'scope']


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


def test_same_bundle_again_makes_no_upstream_calls_and_never_reverse_geocodes(tmp_path):
    addresses, attributes = Addresses(), Attributes()
    api = client(tmp_path, addresses, attributes)
    first = api.post('/api/v1/land/selections/preview', json=body(A, B)).json()
    assert sorted(addresses.outlines) == sorted([A, B]) and sorted(attributes.fetched) == sorted([A, B])
    second = api.post('/api/v1/land/selections/preview', json=body(A, B)).json()
    assert len(addresses.outlines) == 2 and len(attributes.fetched) == 2
    assert second == first
    assert first['parcels'][0]['address'] == '경기도 의정부시 산곡동 684-1'
    assert addresses.calls == 0


def test_adding_a_parcel_fetches_only_the_new_one(tmp_path):
    addresses, attributes = Addresses(), Attributes()
    api = client(tmp_path, addresses, attributes)
    api.post('/api/v1/land/selections/preview', json=body(A))
    grown = api.post('/api/v1/land/selections/preview', json=body(A, B)).json()
    assert addresses.outlines == [A, B] and attributes.fetched == [A, B]
    assert grown['contiguous'] is True and grown['total_area_m2'] == 1500.5
    saved = api.post('/api/v1/land/selections', json=body(A, B)).json()
    assert saved['parcel_count'] == 2 and addresses.outlines == [A, B]
    assert addresses.calls == 0


def test_cache_expires_and_evicts_the_least_recently_used():
    now = [0.0]
    cache = selection_facts.FactsCache(ttl_s=10, max_entries=2, clock=lambda: now[0])
    cache.put('a', 1)
    cache.put('b', 2)
    assert cache.get('a') == 1
    cache.put('c', 3)
    assert cache.get('b') is None and cache.get('a') == 1 and cache.get('c') == 3
    now[0] = 10.0
    assert cache.get('a') is None and len(cache) == 1


def test_failed_lookups_are_not_remembered(tmp_path):
    class Down(Attributes):
        async def fetch(self, pnu):
            self.fetched.append(pnu)
            return {'success': False, 'pnu': pnu, 'zones': [], 'land_area_m2': None, 'official_land_price': None,
                    'land_use_situation': '', 'source': 'unavailable', 'zones_fetched': False}

    attributes = Down()
    api = client(tmp_path, attributes=attributes)
    api.post('/api/v1/land/selections/preview', json=body(A))
    api.post('/api/v1/land/selections/preview', json=body(A))
    assert attributes.fetched == [A, A]


def test_too_many_new_parcels_in_one_request_is_400(tmp_path, monkeypatch):
    monkeypatch.setattr(selection_facts, 'MAX_UPSTREAM_PER_REQUEST', 1)
    addresses = Addresses()
    api = client(tmp_path, addresses)
    response = api.post('/api/v1/land/selections/preview', json=body(A, B))
    assert response.status_code == 400 and 'new parcels' in response.json()['detail']
    assert addresses.outlines == []
    assert api.post('/api/v1/land/selections/preview', json=body(A)).status_code == 200
    assert api.post('/api/v1/land/selections/preview', json=body(A, B)).status_code == 200


def test_v4_database_upgrades_with_existing_rows_in_default_scope(tmp_path):
    repo = LandRepository(tmp_path)
    repo.save({'input_type': 'pnu'}, {}, 1.0)
    with sqlite3.connect(repo.path) as db:
        db.execute('DROP TABLE site_selections')
        db.execute('''CREATE TABLE site_selections (
            selection_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, label TEXT NOT NULL,
            parcel_count INTEGER NOT NULL, total_area_m2 REAL, contiguous INTEGER,
            parcels_json TEXT NOT NULL, source_json TEXT NOT NULL)''')
        db.execute("INSERT INTO site_selections VALUES ('old', '2026-10-01T00:00:00+00:00', '옛 대지', 1, 10.0, 1, "
                   "'[{\"pnu\": \"4115011300106840001\", \"summary\": {\"zones\": []}}]', '{}')")
        db.execute('PRAGMA user_version=4')
    api = client(tmp_path)
    latest = api.get('/api/v1/land/selections/latest').json()
    assert latest['selection_id'] == 'old' and latest['scope'] == 'default' and latest['label'] == '옛 대지'
    assert api.get('/api/v1/land/selections/latest?scope=default').json()['selection_id'] == 'old'
    assert api.get('/api/v1/land/selections/latest?scope=p1').status_code == 404
    with sqlite3.connect(repo.path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 5


def test_latest_is_per_scope(tmp_path):
    api = client(tmp_path)
    in_a = api.post('/api/v1/land/selections', json=body(A, scope='project-A')).json()
    in_b = api.post('/api/v1/land/selections', json=body(FAR, scope='project.B_2')).json()
    plain = api.post('/api/v1/land/selections', json=body(B)).json()
    assert in_a['scope'] == 'project-A' and in_b['scope'] == 'project.B_2' and plain['scope'] == 'default'
    assert api.get('/api/v1/land/selections/latest?scope=project-A').json()['selection_id'] == in_a['selection_id']
    assert api.get('/api/v1/land/selections/latest?scope=project.B_2').json()['selection_id'] == in_b['selection_id']
    assert api.get('/api/v1/land/selections/latest').json()['selection_id'] == plain['selection_id']
    assert api.get('/api/v1/land/selections/latest?scope=nobody').status_code == 404
    assert len(api.get('/api/v1/land/selections').json()['selections']) == 3


@pytest.mark.parametrize('scope', ['', 'has space', 'a/b', 'x' * 65, '한글'])
def test_bad_scope_is_422(tmp_path, scope):
    api = client(tmp_path)
    assert api.post('/api/v1/land/selections', json=body(A, scope=scope)).status_code == 422
    assert api.get('/api/v1/land/selections/latest', params={'scope': scope}).status_code == 422
    assert api.get('/api/v1/land/selections').json() == {'selections': []}
