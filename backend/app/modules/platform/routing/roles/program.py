"""The Program Agent's say in routing — uses, rooms, area schedules (card: program_from_brief, program_generate)."""
from backend.app.modules.platform.routing.rules import Role

ROLE = Role(
    agent='program',
    label='프로그램·면적표 (Program Agent)',
    default_skill=None,
    default_goal='program',
    keywords=('프로그램', '면적표', '실 구성', '실별', '방 개수', '세대수', '세대 구성', '용도 구성', '연면적 배분', '공간 구성', '필요 면적', '소요 면적'),
)
