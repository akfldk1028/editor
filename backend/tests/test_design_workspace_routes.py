from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.routes_design_workspace import create_design_workspace_router


class Addresses:
    async def resolve_address(self, value):
        return {'success': True, 'pnu': '1168010100106770000'}

    async def fetch_parcel_geometry(self, pnu):
        return {'success': True, 'geometry': {'type': 'Polygon', 'coordinates': [[
            [127.0, 37.5], [127.001, 37.5], [127.001, 37.501], [127.0, 37.501], [127.0, 37.5],
        ]]}}


def client():
    app = FastAPI()
    app.include_router(create_design_workspace_router(address_client=Addresses(), public_origin='http://editor.test'))
    return TestClient(app)


def test_original_boundary_contract_and_projected_area():
    response = client().post('/api/v1/design/site-boundary', json={'pnu': '서울시 역삼동'})
    assert response.status_code == 200
    value = response.json()
    assert value['pnu'] == '1168010100106770000'
    assert value['geometry']['type'] == 'Polygon'
    assert 9000 < value['area_m2'] < 11000
    assert value['execution_owner'] == 'editor'


def test_boundary_rejects_cross_origin_and_empty_request():
    api = client()
    assert api.post('/api/v1/design/site-boundary', json={'pnu': 'test'}, headers={'Origin': 'http://other.test'}).status_code == 403
    assert api.post('/api/v1/design/site-boundary', json={'pnu': ''}).status_code == 422


def test_language_catalog_keeps_graph_references_and_snapshot_provenance():
    response = client().get('/api/v1/design/maas/language-system')
    assert response.status_code == 200
    value = response.json()
    nodes = {node['id'] for node in value['exploration_graph']['nodes']}
    assert len(nodes) > 100
    assert all(edge['source'] in nodes and edge['target'] in nodes for edge in value['exploration_graph']['edges'])
    assert value['editor_provenance']['execution_verified'] is False
