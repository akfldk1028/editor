"""The Interior Agent's say in routing — rooms as lived in: finishes, furniture, lighting, ceilings."""
from backend.app.modules.platform.routing.rules import Role

ROLE = Role(
    agent='interior',
    label='인테리어 (Interior Agent)',
    default_skill=None,
    default_goal='interior',
    keywords=('인테리어', '실내', '내부 마감', '바닥재', '벽지', '천장 마감', '가구', '조명 계획', '실내 조명', '인테리어 컨셉', '실내 디자인'),
)
