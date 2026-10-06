from fastapi.testclient import TestClient

from backend.app.main import create_app


def test_native_law_provider_preserves_source_bound_criteria():
    with TestClient(create_app()) as client:
        response = client.post('/api/v1/law/agent/facility-criteria', json={})
    assert response.status_code == 200
    result = response.json()
    assert result['rules'] and result['facility_types']
    assert result['permit_ready'] is False


def test_law_provider_serves_the_binding_parking_count_verbatim():
    """Lawagent's golden set reaches the single numeric owner here, never by importing it."""
    from backend.app.modules.land.reference.services import regulation_calculator
    body = {'zone_names': ['제3종일반주거지역'], 'sigungu_code': '41150',
            'building_type': '업무시설', 'floor_area_m2': 2000, 'assessment_date': '2026-10-06'}
    with TestClient(create_app()) as client:
        response = client.post('/api/v1/law/agent/parking-count', json=body)
        assert client.post('/api/v1/law/agent/parking-count', json={}).status_code == 400
        assert client.post('/api/v1/law/agent/parking-count', json={'zone_names': 'x'}).status_code == 400
    assert response.status_code == 200
    owner = regulation_calculator.calculate_all(body['zone_names'], use_llm_extraction=False,
        sigungu_code='41150', building_type='업무시설', floor_area_m2=2000, assessment_date='2026-10-06')
    served = response.json()
    assert served['parking_required'] == owner['parking_required']
    assert served['parking_calculation']['rounding_policy'] == owner['parking_calculation']['rounding_policy']


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


def test_agent_doors_require_the_network_token_when_one_is_set(monkeypatch):
    """Agents on other servers carry A2A_TOKEN; without it the agent-only doors refuse."""
    monkeypatch.setenv('A2A_TOKEN', 'mesh-secret')
    ops = {'operation': 'ramp_overhead', 'arguments': {}}
    with TestClient(create_app()) as client:
        assert client.post('/api/v1/law/agent/facility-criteria', json={}).status_code == 401
        assert client.post('/api/v1/law/agent/facility-criteria', json={},
                           headers={'Authorization': 'Bearer wrong'}).status_code == 401
        assert client.post('/api/v1/law/agent/facility-criteria', json={},
                           headers={'Authorization': 'Bearer mesh-secret'}).status_code == 200
        assert client.post('/api/v1/design/masterplan/operations/', json=ops).status_code == 401
        assert client.post('/api/v1/design/masterplan/operations/', json=ops,
                           headers={'Authorization': 'Bearer mesh-secret'}).status_code != 401
