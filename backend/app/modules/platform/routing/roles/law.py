"""The Law Agent's say in routing — from its A2A card skills (law_ordinance, law_article, law_search, …)."""
import re

from backend.app.modules.platform.routing.rules import Pattern, Role

ORDINANCE = re.compile(r'(?P<name>[가-힣]+(?:\s+[가-힣]+)*?\s*조례)\s*(?P<article>제?\s*\d+\s*조(?:\s*의\s*\d+)?)')
ARTICLE_ID = re.compile(r'^[^:]+::.+::제\d+조')
SEARCH_LIMIT = 8


def _dated(context: dict) -> dict:
    return {'assessment_date': context['assessment_date']} if context.get('assessment_date') else {}


def ordinance(text: str, context: dict) -> dict | None:
    match = ORDINANCE.search(text)
    if not match:
        return None
    article = re.sub(r'\s+', '', match.group('article'))
    if not article.startswith('제'):
        article = '제' + article
    return {'name': re.sub(r'\s+', ' ', match.group('name')).strip(), 'article': article, 'limit': 3, **_dated(context)}


def article(text: str, context: dict) -> dict | None:
    return {'full_id': text.strip(), **_dated(context)} if ARTICLE_ID.match(text.strip()) else None


def search(text: str, context: dict) -> dict:
    return {'query': text.strip(), 'limit': SEARCH_LIMIT, **_dated(context)}


ROLE = Role(
    agent='law',
    label='법령·조례 검색 (Law Agent)',
    default_skill='law_search',
    default_goal=None,
    patterns=(
        Pattern('law_ordinance', '자치법규 이름과 조문 번호를 적었어요 → law.go.kr 조례 원문', 0.95, ordinance),
        Pattern('law_article', '법령 그래프의 조문 id를 적었어요', 0.9, article),
    ),
    keywords=('법', '법령', '법규', '조례', '조문', '조항', '시행령', '시행규칙', '건폐율', '용적률', '건폐', '용적', '높이제한', '높이 제한',
              '일조', '사선', '이격', '조경', '건축선', '가각', '용도지역', '지구단위', '지역지구', '허가', '규제', '기준', '상한', '지하층', '지표면'),
)
