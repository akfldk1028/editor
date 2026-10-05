import json
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.app.api.routes_law import create_law_router


class Provider:
    async def search(self, query, limit, domain=None):
        return {'results': [{'hang_id': 'law::1', 'content': query}], 'domain_id': domain}


def client():
    app = FastAPI()
    app.include_router(create_law_router(provider=Provider(), public_origin='http://editor'))
    return TestClient(app)


def test_search_preserves_domain_and_rejects_cross_origin():
    api = client()
    result = api.post('/api/v1/law/domain/building/search', json={'q': 'height', 'limit': 3})
    assert result.status_code == 200
    assert result.json()['domain_id'] == 'building'
    assert result.json()['total_count'] == 1
    assert api.post('/api/v1/law/search', json={'q': 'height'}, headers={'Origin': 'http://other'}).status_code == 403
    assert api.post('/api/v1/law/search', json={'q': ' ', 'limit': 2000}).status_code == 422


def test_stream_reports_observed_events_only():
    response = client().get('/api/v1/law/search/stream', params={'query': 'height'})
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    assert [event['status'] for event in events] == ['started', 'complete']
    assert events[-1]['results'][0]['content'] == 'height'
    assert not any('stage' in event for event in events)
