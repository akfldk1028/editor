"""The Systems Agent's say in routing — structure and building services: columns, slabs, shafts, ducts, pipes."""
from backend.app.modules.platform.routing.rules import Role

ROLE = Role(
    agent='systems',
    label='구조·설비 (Systems Agent)',
    default_skill=None,
    default_goal='systems',
    keywords=('구조', '기둥', '보 간격', '슬래브', '내력벽', '설비', '기계설비', '전기설비', '배관', '덕트', '샤프트', '공조', '환기',
              '소방 설비', '스프링클러', '승강기 설비'),
)
