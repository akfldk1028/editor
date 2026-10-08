"""The Elevation Agent's say in routing — facades and elevations."""
from backend.app.modules.platform.routing.rules import Role

ROLE = Role(
    agent='elevation',
    label='입면 설계 (Elevation Agent)',
    default_skill=None,
    default_goal='elevation',
    keywords=('입면', '파사드', '외벽', '창 배치', '개구부', '커튼월', '마감재', '외장'),
)
