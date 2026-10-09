"""Article strings of the regulation calculators → structured references.

The calculators already name their grounds ("건축법 제61조제1항, 시행령 제86조제1항 (2023.9.12 개정)",
"국토계획법 §76, 시행령 §71", "건축법 제46-47조", "의정부시 도시계획 조례 제42조"). This reads them into
{instrument, kind, article, clause} so each ground can be looked up, shown and asked about; nothing is
added that the calculators did not say.
"""
from __future__ import annotations

import re

# Short names the calculators use → the instrument's full name (the statute graph and law.go.kr use these).
ALIASES = {
    '국토계획법': '국토의 계획 및 이용에 관한 법률',
    '군사기지법': '군사기지 및 군사시설 보호법',
    '가축분뇨법': '가축분뇨의 관리 및 이용에 관한 법률',
    '장애인등편의법': '장애인ㆍ노인ㆍ임산부 등의 편의증진 보장에 관한 법률',
    '녹색건축물법': '녹색건축물 조성 지원법',
    '소방시설법': '소방시설 설치 및 관리에 관한 법률',
    '문화재보호법': '문화재보호법',
}
_SUBORDINATE = ('시행령', '시행규칙')
_ARTICLE = re.compile(r'(?:제\s*(\d+)(?:\s*-\s*(\d+))?\s*조(?:\s*의\s*(\d+))?|§\s*(\d+)(?:\s*의\s*(\d+))?)((?:\s*제\s*\d+\s*[항호])*)')
_APPENDIX = re.compile(r'별표\s*(\d+)')


def _full(name: str) -> str:
    name = name.strip()
    if '조례' in name:  # "의정부시 주차장 설치 및 관리 조례 부설주차장 설치기준" → the ordinance itself
        name = name[:name.index('조례') + 2]
    return ALIASES.get(name, name)


def _kind(instrument: str) -> str:
    if '조례' in instrument or '규칙' in instrument and '시행규칙' not in instrument:
        return 'ordinance'
    if instrument.endswith('시행령'):
        return 'decree'
    if instrument.endswith('시행규칙'):
        return 'rule'
    return 'act'


def _article(number: str, sub: str | None) -> str:
    return f'제{int(number)}조' + (f'의{int(sub)}' if sub else '')


def parse(text: str | None) -> list[dict]:
    """Every instrument + article named in `text`, in order, each once. `시행령 …` after `건축법 …` means 건축법 시행령."""
    if not isinstance(text, str) or not text.strip():
        return []
    text = re.sub(r'\([^)]*\)', ' ', text)  # "(2023.9.12 개정)", "(경계로부터 0.5m)"
    refs: list[dict] = []
    act: str | None = None
    for part in re.split(r'[;,·、]', text):
        part = part.strip()
        if not part:
            continue
        head = re.split(r'제\s*\d|§|별표', part, maxsplit=1)[0].strip()
        if head:
            if head in _SUBORDINATE and act:
                instrument = f'{act} {head}'
            elif head.startswith(_SUBORDINATE) and act:
                instrument = f'{act} {head.split()[0]}'
            else:
                words = head.split()
                if words and words[-1] in _SUBORDINATE:
                    act = _full(' '.join(words[:-1]))
                    instrument = f'{act} {words[-1]}'
                else:
                    instrument = _full(head)
                    if _kind(instrument) == 'act':
                        act = instrument
        elif act:
            instrument = act
        else:
            continue
        found = False
        for match in _ARTICLE.finditer(part):
            number, sub = match.group(1) or match.group(4), match.group(3) or match.group(5)
            clause = re.sub(r'\s+', '', match.group(6) or '') or None
            numbers = [number]
            if match.group(2):
                numbers = [str(n) for n in range(int(number), int(match.group(2)) + 1)][:6]
            for value in numbers:
                refs.append({'instrument': instrument, 'kind': _kind(instrument), 'article': _article(value, sub if value == number else None), 'clause': clause})
            found = True
        for match in _APPENDIX.finditer(part):
            refs.append({'instrument': instrument, 'kind': _kind(instrument), 'article': f'별표 {match.group(1)}', 'clause': None})
            found = True
        if not found and _kind(instrument) == 'ordinance':
            refs.append({'instrument': instrument, 'kind': 'ordinance', 'article': None, 'clause': None})
    unique, seen = [], set()
    for ref in refs:
        key = (ref['instrument'], ref['article'], ref['clause'])
        if key not in seen:
            seen.add(key)
            unique.append(ref)
    return unique
