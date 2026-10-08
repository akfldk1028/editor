"""The MasterPlan Agent's say in routing — layout, parking layout, ramps, cores (card: masterplan_layout_*)."""
from backend.app.modules.platform.routing.rules import Role

ROLE = Role(
    agent='masterplan',
    label='배치·주차 설계 (MasterPlan Agent)',
    default_skill=None,
    default_goal='masterplan',
    keywords=('배치', '배치도', '주차 배치', '주차장 배치', '램프', '코어', '동선', '차량 동선', '진출입', '건물 위치', '어디에 놓', '어디에 두',
              '지하 주차', '필로티', '대안', '레이아웃'),
)
