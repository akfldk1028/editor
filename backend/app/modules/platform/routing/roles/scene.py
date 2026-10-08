"""The Scene Agent's say in routing — the site and its surroundings in 3D, and the report cameras (card: scene_views)."""
from backend.app.modules.platform.routing.rules import Role

ROLE = Role(
    agent='scene',
    label='3D 장면 (Scene Agent)',
    default_skill=None,
    default_goal='scene',
    keywords=('3d', '3D', '장면', '주변 3D', '주변 매스 3D', '카메라', '조감도', '뷰 잡아', '보고서 뷰', '렌더', '투시도', '지형 위에'),
)
