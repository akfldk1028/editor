"""The goals the product can ask the Orchestrator for — one catalog, served as `GET /platform/capabilities`.

A goal names the Orchestrator flow that answers it, the owners that flow walks (in order, as the
conversation will draw them), the inputs the editor must collect, and whether the Orchestrator's editor
door accepts it today. The door accepts `health`, `limits` and `specialist_review`
(agents/OrchestratorAgent/orchestrator/editor_runs.py); the other flows exist in the Orchestrator
(`*_flow.py`) but are not open to the editor yet, so they are listed as unavailable — the conversation
offers only available goals, and a goal that opens later becomes a button by flipping one row here.
The Orchestrator does not publish this list yet (memory `this-session-owns-the-orchestrator` §11); when
it does, this module reads it instead of restating it.
"""
from backend.app.schemas.site_run import SITE_GOALS

GOALS = (
    {'id': 'limits', 'label': '대지·법규 검토', 'owners': ['site_context', 'law', 'revision'],
     'inputs': ['pnu', 'assessment_date'], 'optional': ['building_type', 'parcels'], 'offer': True},
    {'id': 'health', 'label': '에이전트 상태 확인', 'owners': [], 'inputs': [], 'optional': [], 'offer': False},
    {'id': 'specialist_review', 'label': '전문 검토', 'owners': ['domain_expert'], 'inputs': ['review'], 'optional': [], 'offer': False},
    # Flows the Orchestrator has but does not open to the editor door yet.
    {'id': 'program', 'label': '프로그램 번역', 'owners': ['requirement', 'program'], 'inputs': ['brief'], 'optional': [], 'offer': True},
    {'id': 'masterplan', 'label': '배치 설계', 'owners': ['program', 'masterplan', 'revision'], 'inputs': ['pnu', 'program'], 'optional': [], 'offer': True},
    {'id': 'mass', 'label': '매스 생성', 'owners': ['program', 'masterplan', 'mass', 'revision'], 'inputs': ['pnu', 'program'], 'optional': [], 'offer': True},
    {'id': 'elevation', 'label': '입면 설계', 'owners': ['elevation'], 'inputs': ['mass'], 'optional': [], 'offer': True},
    {'id': 'kmass', 'label': '한국형 주거 매스', 'owners': ['program', 'kmass', 'revision'], 'inputs': ['pnu', 'brief'], 'optional': [], 'offer': True},
    {'id': 'plan', 'label': '평면 생성', 'owners': ['program', 'plan', 'revision'], 'inputs': ['mass', 'program'], 'optional': [], 'offer': True},
    {'id': 'intent', 'label': '설계 의도 선언', 'owners': ['design_intent'], 'inputs': ['brief'], 'optional': [], 'offer': True},
    {'id': 'scene', 'label': '3D 장면', 'owners': ['scene'], 'inputs': ['pnu'], 'optional': ['mass'], 'offer': True},
    # Agents with a folder and a role but no Orchestrator flow yet: the handoff names them, the door refuses them.
    {'id': 'systems', 'label': '구조·설비 검토', 'owners': ['systems'], 'inputs': ['mass'], 'optional': [], 'offer': True},
    {'id': 'interior', 'label': '인테리어', 'owners': ['interior'], 'inputs': ['plan'], 'optional': [], 'offer': True},
    {'id': 'cost', 'label': '공사비 산정', 'owners': ['cost'], 'inputs': ['mass'], 'optional': ['program'], 'offer': True},
)

# What the editor door accepts today, besides the site goals: restated from editor_runs.py.
DOOR_GOALS = frozenset(SITE_GOALS) | {'health', 'specialist_review'}


def capabilities() -> dict:
    """Every goal with `available` (the door takes it) and `offer` (the conversation shows it as a choice)."""
    goals = [{**goal, 'available': goal['id'] in DOOR_GOALS} for goal in GOALS]
    return {
        'goals': goals,
        'conversation': {'ask': True, 'law_analysis': True},
        'source': 'editor mirror of orchestrator editor_runs.py (the Orchestrator publishes no list yet)',
    }


def goal(goal_id: str) -> dict | None:
    return next((g for g in capabilities()['goals'] if g['id'] == goal_id), None)
