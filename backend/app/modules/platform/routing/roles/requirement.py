"""The Requirement Agent's say in routing — what the person said, structured into requirements (card: requirement_structure)."""
from backend.app.modules.platform.routing.rules import Role

ROLE = Role(
    agent='requirement',
    label='요구사항 정리 (Requirement Agent)',
    default_skill=None,
    default_goal='program',
    keywords=('요구사항', '요구 사항', '브리프', '의뢰', '건축주', '발주', '원하는 것', '조건 정리', '조건을 정리', '열린 질문', '모순',
              '가정과', '사용자 요청 정리'),
)
