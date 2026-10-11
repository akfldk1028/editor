"""The Site Agent's say in routing — its facts (경계·접도·출입구·정북·지형·설비·재해·주변) come through the `limits` run."""
import re

from backend.app.modules.platform.routing.rules import Pattern, Role

PNU = re.compile(r'^\d{19}$')
# A whole message that is one address, nothing else — the way a first message names the site. 지번: words, the last
# one a 법정동·리 (…동/리/가/읍/면), then 산 684-1 / 737 / 12번지. 도로명: words, a 로·길 name, its number. No place
# names are listed here: any jurisdiction fits, and the geocoder (the map's own search) decides whether it exists.
JIBUN = re.compile(r'^(?:[가-힣]+\s+)*[가-힣]+(?:동|리|가|읍|면)\s+(?:산\s*)?\d+(?:-\d+)?(?:\s*번지)?$')
ROAD = re.compile(r'^(?:[가-힣]+\s+)*[가-힣0-9]{2,}(?:로|길)\s+\d+(?:-\d+)?$')


def locate(text: str, context: dict) -> dict | None:
    value = re.sub(r'\s+', ' ', text).strip().rstrip('.。')
    return {'query': value} if PNU.match(value) or JIBUN.match(value) or ROAD.match(value) else None


ROLE = Role(
    agent='site_context',
    label='대지 사실 (Site Agent)',
    default_skill=None,
    default_goal='limits',
    patterns=(
        Pattern('site_locate', '주소(또는 PNU)를 적었어요 → 지도에서 그 필지를 찾아요', 0.95, locate),
    ),
    keywords=('대지 경계', '경계', '접도', '도로 폭', '도로폭', '전면도로', '출입구', '진입', '정북', '진북', '표고', '지형', '경사', '옹벽',
              '설비 인입', '상수', '하수', '전기 인입', '재해', '침수', '주변 건물', '주변 맥락', '인접 건물', '필지', '지적', '면적이 얼마'),
)
