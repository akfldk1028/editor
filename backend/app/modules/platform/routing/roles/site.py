"""The Site Agent's say in routing — its facts (경계·접도·출입구·정북·지형·설비·재해·주변) come through the `limits` run."""
from backend.app.modules.platform.routing.rules import Role

ROLE = Role(
    agent='site_context',
    label='대지 사실 (Site Agent)',
    default_skill=None,
    default_goal='limits',
    keywords=('대지 경계', '경계', '접도', '도로 폭', '도로폭', '전면도로', '출입구', '진입', '정북', '진북', '표고', '지형', '경사', '옹벽',
              '설비 인입', '상수', '하수', '전기 인입', '재해', '침수', '주변 건물', '주변 맥락', '인접 건물', '필지', '지적', '면적이 얼마'),
)
