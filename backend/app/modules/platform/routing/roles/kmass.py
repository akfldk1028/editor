"""The KMass Agent's say in routing — Korean housing masses from a brief: 판상·탑상, 동 배치, 세대 조합."""
from backend.app.modules.platform.routing.rules import Role

ROLE = Role(
    agent='kmass',
    label='한국형 주거 매스 (KMass Agent)',
    default_skill=None,
    default_goal='kmass',
    keywords=('한국형 매스', '아파트 매스', '공동주택 매스', '판상형', '탑상형', '판상', '탑상', '동 배치', '주동', '세대 조합', '단위세대 매스'),
)
