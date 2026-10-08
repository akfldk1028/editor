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
    known = {'site_context', 'law', 'revision', 'domain_expert', 'requirement', 'program', 'masterplan', 'mass', 'elevation',
             'kmass', 'plan', 'design_intent', 'scene', 'systems', 'interior', 'cost'}
    for g in GOALS:
        assert set(g['owners']) <= known, g['id']


def test_capabilities_route_serves_the_catalog():
    app = FastAPI()
    app.include_router(create_status_router(owner=None, service=object()), prefix='/api/v1/platform')  # status never called
    response = TestClient(app).get('/api/v1/platform/capabilities')
    assert response.status_code == 200 and response.json()['goals'][0]['id'] == 'limits'


def test_situation_reads_site_goals_and_the_catalogs_agent_states_as_data():
    from backend.app.modules.platform.situation import describe
    from backend.app.schemas.platform import AgentSummary

    def agent(agent_id, status):
        return AgentSummary(agent_id=agent_id, label=agent_id, capabilities=[], implementation_status='x', connection_status=status,
                            checked_at=None, evidence_ref=None)

    text = describe(pnu='4115011300106840001', address='산곡동 684-1', assessment_date='2026-10-08',
                    agents=[agent('law', 'available'), agent('mass', 'unavailable'), agent('orchestrator', 'local'), agent('construction', 'not_declared')])
    assert text.startswith('- selected site: 산곡동 684-1 PNU 4115011300106840001\n- assessment date: 2026-10-08\n')
    assert '- goal limits (법규·한계 검토): available now; owners site_context -> law -> revision; needs pnu, assessment_date' in text
    assert '- goal mass (매스 생성): not open to the editor yet' in text
    assert text.endswith('- agents up: law, orchestrator\n- agents down: mass') and 'construction' not in text
    assert describe(pnu=None).startswith('- selected site: none yet') and describe(pnu=None).endswith('(the Orchestrator catalog did not answer)')
