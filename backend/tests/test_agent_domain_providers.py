from fastapi.testclient import TestClient

from backend.app.main import create_app


def test_native_law_provider_preserves_source_bound_criteria():
    with TestClient(create_app()) as client:
        response = client.post('/api/v1/law/agent/facility-criteria', json={})
    assert response.status_code == 200
    result = response.json()
    assert result['rules'] and result['facility_types']
    assert result['permit_ready'] is False


def test_native_land_provider_uses_actual_basement_calculator():
    with TestClient(create_app()) as client:
        response = client.post('/api/v1/land/agent/basement-storey', json={
            'datum_m': 10, 'floor_level_m': 8, 'storey_height_m': 3,
        })
    assert response.status_code == 200
    assert response.json()['is_basement'] is True


def test_provider_rejects_unknown_operations_cross_origin_and_nonfinite():
    with TestClient(create_app()) as client:
        assert client.post('/api/v1/law/agent/delete', json={}).status_code == 404
        assert client.post('/api/v1/law/agent/facility-criteria', json={},
                           headers={'Origin': 'https://other.test'}).status_code == 403
        assert client.post('/api/v1/land/agent/basement-storey',
                           content='{"datum_m": NaN}').status_code == 400
