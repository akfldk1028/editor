"""The Domain Expert Agent's say in routing — a specialist's review of a positive revision (door goal: specialist_review)."""
from backend.app.modules.platform.routing.rules import Role

ROLE = Role(
    agent='domain_expert',
    label='전문 검토 (Domain Expert Agent)',
    default_skill=None,
    default_goal='specialist_review',
    keywords=('전문가 검토', '전문 검토', '전문가 의견', '자문', '세컨드 오피니언', '실무자가 보면', '실무 검토', '심의', '전문가에게'),
)
