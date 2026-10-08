"""`GET /api/v1/platform/capabilities`: the goal catalog the conversation derives its choices from."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.modules.platform.goals import DOOR_GOALS, GOALS, capabilities, goal
from backend.app.modules.platform.routers.status import create_status_router
from backend.app.schemas.site_run import SITE_GOALS


def test_catalog_marks_what_the_door_takes_and_what_the_conversation_offers():
    body = capabilities()
    by_id = {g['id']: g for g in body['goals']}
    assert set(by_id) == {g['id'] for g in GOALS} and len(by_id) == len(GOALS)
    assert by_id['limits'] == {'id': 'limits', 'label': '법규·한계 검토', 'owners': ['site_context', 'law', 'revision'],
                               'inputs': ['pnu', 'assessment_date'], 'optional': ['building_type', 'parcels'], 'offer': True, 'available': True}
    assert by_id['health']['available'] is True and by_id['health']['offer'] is False
    assert by_id['mass']['available'] is False and by_id['mass']['offer'] is True
    assert [g['id'] for g in body['goals'] if g['available'] and g['offer']] == ['limits']
    assert SITE_GOALS <= DOOR_GOALS
    assert body['conversation'] == {'ask': True, 'law_analysis': True}
    assert goal('mass')['owners'] == ['program', 'masterplan', 'mass', 'revision'] and goal('nope') is None


def test_every_goal_names_owners_the_agent_folders_know():
    known = {'site_context', 'law', 'revision', 'domain_expert', 'requirement', 'program', 'masterplan', 'mass', 'elevation'}
    for g in GOALS:
        assert set(g['owners']) <= known, g['id']


def test_capabilities_route_serves_the_catalog():
    app = FastAPI()
    app.include_router(create_status_router(owner=None, service=object()), prefix='/api/v1/platform')  # status never called
    response = TestClient(app).get('/api/v1/platform/capabilities')
    assert response.status_code == 200 and response.json()['goals'][0]['id'] == 'limits'
