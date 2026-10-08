"""The Design Intent Agent's say in routing — parti, ordering principles, non-negotiables (card: intent_declare, intent_check)."""
from backend.app.modules.platform.routing.rules import Role

ROLE = Role(
    agent='design_intent',
    label='설계 의도 (Design Intent Agent)',
    default_skill=None,
    default_goal='intent',
    keywords=('설계 의도', '설계의도', '컨셉', '콘셉트', '파르티', '디자인 원칙', '디자인 방향', '꼭 지킬', '양보 못', '비협상', '의도를 지켰',
              '의도 선언', '거부한 대안'),
)
