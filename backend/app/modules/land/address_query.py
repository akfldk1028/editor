"""What a typed site search means, before any provider is asked: normalize, then classify.

Pure functions. The classes follow the address-matching pipeline the Korean map services use
(Kakao/Naver/VWorld: a parser that splits 지번·도로명·장소·지역 and a ranked candidate list):

- ``pnu``   19 digits once hyphens and spaces go, the 11th digit (산) 1 or 2.
- ``lot``   a 법정동·리·가 word (digits allowed: 을지로1가), optional 산, a 본번 or 본번-부번.
- ``road``  a 로·길·번길 word, then a 건물번호.
- ``area``  address words with no number (대구 수성구 범어동).
- ``place`` anything else (서울시청, 강남역).

Typos are never fixed here: ``세종대로 11O`` stays a road whose number is unreadable.
"""
import re
import unicodedata
from dataclasses import dataclass, field

# 시도: every form a person types, then its official name. Bare 광주 is left out of the rewrite on purpose: it is
# also 경기도 광주시.
SIDO = (
    ('서울특별시', ('서울', '서울시', '서울특별시')),
    ('부산광역시', ('부산', '부산시', '부산광역시')),
    ('대구광역시', ('대구', '대구시', '대구광역시')),
    ('인천광역시', ('인천', '인천시', '인천광역시')),
    ('광주광역시', ('광주', '광주광역시')),
    ('전라남도', ('전남', '전라남도')),
    ('전남광주통합특별시', ('전남광주', '전남광주통합특별시')),
    ('대전광역시', ('대전', '대전시', '대전광역시')),
    ('울산광역시', ('울산', '울산시', '울산광역시')),
    ('세종특별자치시', ('세종', '세종시', '세종특별자치시')),
    ('경기도', ('경기', '경기도')),
    ('강원특별자치도', ('강원', '강원도', '강원특별자치도')),
    ('충청북도', ('충북', '충청북도')),
    ('충청남도', ('충남', '충청남도')),
    ('전북특별자치도', ('전북', '전라북도', '전북특별자치도')),
    ('경상북도', ('경북', '경상북도')),
    ('경상남도', ('경남', '경상남도')),
    ('제주특별자치도', ('제주', '제주도', '제주특별자치도')),
)
SIDO_ALIASES = {alias: canonical for canonical, aliases in SIDO for alias in aliases}
_AMBIGUOUS_SIDO = {'광주', '제주'}  # also a 시: never rewritten, still matched both ways
# The provider's records now file 광주광역시 and 전라남도 under one 시도. The merge is explicit: a typed old 시도
# matches only its own former area — 광주 is the five 자치구, 전남 everything else in the merged 시도.
MERGED_SIDO = '전남광주통합특별시'
MERGED_FROM = {'광주광역시', '전라남도'}
GWANGJU_GU = {'동구', '서구', '남구', '북구', '광산구'}
DOTS = dict.fromkeys(map(ord, '·ㆍ・‧∙•'), '.')

DASHES = dict.fromkeys(map(ord, '‐‑‒–—―−﹘﹣－'), '-')
LOT_WORD = re.compile(r'^[가-힣][가-힣0-9.]*(?:동|리|가)$')
ROAD_WORD = re.compile(r'^(?=.*[가-힣])[가-힣0-9.]+(?:로|길)$')  # 3·15대로 is read as 3.15대로
NUMBER = re.compile(r'^(\d+)(?:-(\d+))?$')
REGION_WORD = re.compile(r'^[가-힣][가-힣0-9]*(?:시|군|구|읍|면|동|리|가|도)$')


def normalize(text: str) -> str:
    """NFKC, one space, 684번지 1 → 684-1, a space between Hangul and a number that ends the word, 산 split off."""
    value = unicodedata.normalize('NFKC', text or '').translate(DASHES).translate(DOTS)
    value = re.sub(r'[(),，、]', ' ', value)
    value = re.sub(r'\s+', ' ', value).strip().rstrip('.。')
    value = re.sub(r'(\d)\s*-\s*(\d)', r'\1-\2', value)
    value = re.sub(r'(\d+)\s*번지\s*(\d+)\s*(?:호)?', r'\1-\2', value)
    value = re.sub(r'(\d+(?:-\d+)?)\s*번지', r'\1', value)
    # 을지로 1가 → 을지로1가: a 가 number belongs to the word before it.
    value = re.sub(r'([가-힣])\s+(\d{1,2}가)(?=\s|\d|$)', r'\1\2', value)
    # 산곡동684-1 → 산곡동 684-1, 종로1가1 → 종로1가 1, but 을지로1가 stays one word (its number is followed by Hangul).
    value = re.sub(r'([가-힣])(\d+(?:-\d+)?)(?![\d가-힣-])', r'\1 \2', value)
    value = re.sub(r'(?:^|(?<=\s))산\s*(?=\d)', '산 ', value)
    return re.sub(r'\s+', ' ', value).strip()


def pnu_digits(text: str) -> str | None:
    """The 19 digits of a typed PNU (hyphens and spaces allowed), else None."""
    digits = re.sub(r'[\s-]', '', unicodedata.normalize('NFKC', text or '').translate(DASHES))
    return digits if re.fullmatch(r'\d{19}', digits) else None


def valid_pnu(pnu: str) -> bool:
    """19 digits whose 11th (the 산 digit) is 1 (대지) or 2 (임야)."""
    return bool(re.fullmatch(r'\d{19}', pnu or '')) and pnu[10] in '12'


@dataclass
class Query:
    kind: str                      # pnu | lot | road | area | place
    normalized: str
    pnu: str | None = None
    valid: bool = True             # False: a 19-digit PNU whose 산 digit is wrong
    name: str | None = None        # the 동·리·가 (lot) or the 로·길 (road)
    san: bool = False
    main: int | None = None
    sub: int | None = None         # None: no 부번 typed (a lot then means 부번 0)
    number_text: str | None = None # what stood where the number belongs (kept when unreadable)
    context: list[str] = field(default_factory=list)  # the other words: 시도·시군구·읍면, 용인·강남 …
    level: str | None = None       # area: the district level to search (L1 / L2 / L4)

    @property
    def regions(self) -> list[str]:
        """Every Hangul context word, suffix or not (용인, 강남, 수원): each one must be in a candidate's address,
        or that candidate contradicts the input."""
        return [word for word in self.context if re.fullmatch(r'[가-힣][가-힣0-9.]*', word)]

    def provider_text(self, *, with_context: bool = False, number: bool = True) -> str:
        """The words sent to the provider: the name and number alone (all regions), or with the typed regions first;
        without the number, the typed 동's own lots."""
        if self.kind in ('area', 'place'):
            return ' '.join(canonical_sido(word) for word in self.normalized.split())
        core = [self.name or '']
        if self.kind == 'lot' and self.san:
            core.append('산')
        if self.number_text and number:
            core.append(self.number_text)
        head = [canonical_sido(word) for word in self.regions] if with_context else []
        return ' '.join(part for part in (*head, *core) if part)


def canonical_sido(word: str) -> str:
    """The 시도 name the provider searches by (전라남도 → 전남광주통합특별시); other words unchanged."""
    if word in _AMBIGUOUS_SIDO:
        return word
    name = SIDO_ALIASES.get(word, word)
    return MERGED_SIDO if name in MERGED_FROM else name


def _number(word: str):
    found = NUMBER.match(word)
    return (int(found.group(1)), int(found.group(2)) if found.group(2) else None) if found else None


def classify(text: str) -> Query:
    normalized = normalize(text)
    digits = pnu_digits(text)
    if digits:
        return Query('pnu', digits, pnu=digits, valid=valid_pnu(digits))
    words = normalized.split()
    # 지번 first: 중앙로1가 1 is a lot even though 중앙로 alone would be a road.
    for index, word in enumerate(words):
        if not LOT_WORD.match(word):
            continue
        rest = words[index + 1:]
        san = bool(rest) and rest[0] == '산'
        if san:
            rest = rest[1:]
        if rest and _number(rest[0]):
            main, sub = _number(rest[0])
            context = words[:index] + rest[1:]
            return Query('lot', normalized, name=word, san=san, main=main, sub=sub, number_text=rest[0], context=context)
    for index, word in enumerate(words):
        if not ROAD_WORD.match(word) or index + 1 >= len(words):
            continue
        following = words[index + 1]
        number = _number(following)
        if number:
            return Query('road', normalized, name=word, main=number[0], sub=number[1], number_text=following,
                         context=words[:index] + words[index + 2:])
        if following[0].isdigit():
            # 세종대로 11O: a road with a number nobody can read; candidates, never a guess.
            return Query('road', normalized, name=word, number_text=None, context=words[:index] + words[index + 2:])
    if words and all(word in SIDO_ALIASES or REGION_WORD.match(word) for word in words):
        last = words[-1]
        level = 'L1' if last in SIDO_ALIASES and last not in _AMBIGUOUS_SIDO else (
            'L2' if last[-1] in '시군구' else 'L4')
        return Query('area', normalized, context=words[:-1], name=last, level=level)
    return Query('place', normalized)


def secondary_kind(kind: str) -> str | None:
    """The next most likely class, searched alongside the first and listed only when the first has no exact match."""
    return {'lot': 'place', 'road': 'place', 'area': 'place', 'place': 'area'}.get(kind)


# --- Reading a provider's address text -------------------------------------------------------------

def address_words(text: str) -> list[str]:
    return re.sub(r'[(),]', ' ', (text or '').translate(DOTS)).split()


def lot_parts(text: str):
    """``… 신촌동 산 1-3`` → ('신촌동', True, 1, 3); None when the text ends in no lot number."""
    words = address_words(text)
    if not words:
        return None
    number = _number(re.sub(r'[가-힣]+$', '', words[-1]))  # a place's lot may end in its 지목: 37대
    if not number or len(words) < 2:
        return None
    san = words[-2] == '산'
    name_at = -3 if san else -2
    if len(words) < -name_at:
        return None
    return words[name_at], san, number[0], number[1] or 0


def road_parts(text: str):
    """``서울특별시 중구 세종대로 110 (태평로1가)`` → ('세종대로', 110, None)."""
    found = re.search(r'(\S+(?:로|길))\s+(\d+)(?:-(\d+))?(?!\S)', (text or '').translate(DOTS))
    if not found:
        return None
    return found.group(1), int(found.group(2)), int(found.group(3)) if found.group(3) else None


def region_matches(word: str, label_words: list[str]) -> bool:
    """A typed region word is in the candidate's address: the same word, its 시·군·구 form (의정부 → 의정부시), or the same 시도."""
    if word in label_words or any(label == word + suffix for label in label_words for suffix in '시군구'):
        return True
    canonical = SIDO_ALIASES.get(word)
    if canonical is None:
        return False
    if canonical in MERGED_FROM:
        if canonical in label_words:
            return True
        if MERGED_SIDO not in label_words:
            return False
        at = label_words.index(MERGED_SIDO) + 1
        in_gwangju = at < len(label_words) and label_words[at] in GWANGJU_GU
        return in_gwangju == (canonical == '광주광역시')
    group = next(aliases for name, aliases in SIDO if name == canonical)
    return any(label in group or label == canonical for label in label_words)
