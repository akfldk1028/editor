"""The Mass Agent's say in routing — volumes, storeys stacked, the building's form."""
from backend.app.modules.platform.routing.rules import Role

ROLE = Role(
    agent='mass',
    label='매스 생성 (Mass Agent)',
    default_skill=None,
    default_goal='mass',
    keywords=('매스', '볼륨', '덩어리', '층 쌓', '쌓아', '형태', '외형', '몇 층까지', '층수 올', '테라스', '셋백 형태', '매싱'),
)
