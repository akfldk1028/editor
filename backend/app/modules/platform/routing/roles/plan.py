"""The Plan Agent's say in routing — floor-plan geometry: rooms, core, circulation, egress (card: plan_generate, plan_stage)."""
from backend.app.modules.platform.routing.rules import Role

ROLE = Role(
    agent='plan',
    label='평면 생성 (Plan Agent)',
    default_skill=None,
    default_goal='plan',
    keywords=('평면', '평면도', '실 배치', '방 배치', '방을 나눠', '층별 평면', '복도', '피난 동선', '피난 거리', '출입문', '문 위치', '개구부 위치',
              '코어 평면', '계단실', '엘리베이터 위치'),
)
