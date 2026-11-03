"""The Site Agent's say in routing — its facts (경계·접도·출입구·정북·지형·설비·재해·주변) come through the `limits` run."""
import re

from backend.app.modules.land.address_query import normalize, pnu_digits, valid_pnu
from backend.app.modules.platform.routing.rules import Pattern, Role

PNU = re.compile(r'^\d{19}$')
# A whole message that is one address, nothing else — the way a first message names the site. 지번: words, the last
# one a 법정동·리 (…동/리/가/읍/면), then 산 684-1 / 737 / 12번지. 도로명: words, a 로·길 name, its number. No place
# names are listed here: any jurisdiction fits, and the geocoder (the map's own search) decides whether it exists.
# Matched on the search's own normalized text (address_query.normalize): 산곡동684-1, 테헤란로152 and 684번지 1 read
# as 산곡동 684-1, 테헤란로 152 and 684-1, and a 동 word may hold digits (을지로1가, 효자동2가).
# A 동·리 word, a 가 word with its number (을지로1가 — a bare …가 is a particle: 아이가), or a 읍·면 word.
LOT = r'(?P<lot>[가-힣][가-힣0-9.]*(?:동|리)|[가-힣][가-힣0-9.]*\d가|[가-힣]+(?:읍|면))'
# Everyday words that end like a 동·리 and are followed by a count ("우리 2명", "운동 3번"): never a site.
NOT_A_PLACE = {'우리', '거리', '자리', '소리', '머리', '다리', '요리', '관리', '처리', '정리', '수리', '무리', '원리', '진리',
               '이동', '활동', '운동', '행동', '자동', '공동', '감동', '변동', '출동', '작동', '가동', '노동'}
JIBUN = re.compile(r'^(?:[가-힣0-9.]+\s+)*' + LOT + r'\s+(?:산\s*)?\d+(?:-\d+)?$')
ROAD = re.compile(r'^(?:[가-힣0-9.]+\s+)*[가-힣0-9.]{2,}(?:로|길)\s+\d+(?:-\d+)?$')


def _is_pnu(value: str) -> bool:
    digits = pnu_digits(value)
    return bool(digits) and valid_pnu(digits) and re.fullmatch(r'[\d\s-]+', value) is not None


def locate(text: str, context: dict) -> dict | None:
    value = re.sub(r'\s+', ' ', text).strip().rstrip('.。')
    shape = normalize(value)
    jibun = JIBUN.match(shape)
    if jibun and jibun.group('lot') in NOT_A_PLACE:
        jibun = None
    return {'query': value} if PNU.match(value) or _is_pnu(value) or jibun or ROAD.match(shape) else None


# The same shapes inside a sentence ("산곡동 684-1에 어린이집을 지으려고 해요"): the message still belongs to whoever answers it,
# but the site it names is the map's. A 지번 ends at its number (a following 번지 is taken, a following 에/의 is not).
# Each ends at a word end: "아이가 2명" is a count, not 지번 2.
JIBUN_IN = re.compile(r'(?:[가-힣]+\s+)*' + LOT + r'\s+(?:산\s*)?\d+(?:-\d+)?(?![\d가-힣.-])')
ROAD_IN = re.compile(r'(?:[가-힣]+\s+)*[가-힣0-9.]{2,}(?:로|길)\s+\d+(?:-\d+)?(?![\d가-힣.-])')
PNU_IN = re.compile(r'(?<!\d)\d{19}(?!\d)')
# A number and then a particle (684-1에, 684-1번지에서 once 번지 is read): the particle is split off.
PARTICLE = re.compile(r'(\d+(?:-\d+)?)(에서|에|의|은|는|을|를|과|와|으로|이|도|까지|부터)(?![가-힣])')


def find(text: str) -> str | None:
    """The first address or PNU named inside a message, or None — the whole-message form is `locate`'s."""
    value = normalize(PARTICLE.sub(r'\1 \2', normalize(text)))
    found = PNU_IN.search(value)
    if found:
        return found.group(0)
    for found in JIBUN_IN.finditer(value):
        if found.group('lot') not in NOT_A_PLACE:
            return found.group(0).strip()
    found = ROAD_IN.search(value)
    return found.group(0).strip() if found else None


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
