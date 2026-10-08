"""Which agent and skill answer a typed question — the editor's interim router.

The Orchestrator is the network's router (hub-and-spoke; see memory `agent-infra-design-research`);
until its editor door takes questions, the product routes here with the same shape it will send
there: a request → one `Route` (agent, skill, args, confidence, reason). The rules are a table, one
row per skill, read top to bottom; a row claims the request when its matcher says so. No row → the
default skill of the only agent that answers free text today (Law Agent `law_search`). Keeping the
decision explainable (`reason`) and the candidate set open follows TCAndon-Router / Uno-Orchestra:
route explainably, prefer the cheapest skill that can answer, never guess silently.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

ORDINANCE = re.compile(r'(?P<name>[가-힣]+(?:\s+[가-힣]+)*?\s*조례)\s*(?P<article>제?\s*\d+\s*조(?:\s*의\s*\d+)?)')
ARTICLE_ID = re.compile(r'^[^:]+::.+::제\d+조')
SEARCH_LIMIT = 8


@dataclass(frozen=True)
class Route:
    agent: str
    skill: str
    args: dict
    confidence: float
    reason: str

    def to_dict(self) -> dict:
        return {'agent': self.agent, 'skill': self.skill, 'confidence': self.confidence, 'reason': self.reason}


@dataclass(frozen=True)
class Rule:
    agent: str
    skill: str
    reason: str
    confidence: float
    build: Callable[[str, dict], dict | None] = field(repr=False)


def _ordinance(text: str, context: dict) -> dict | None:
    match = ORDINANCE.search(text)
    if not match:
        return None
    article = re.sub(r'\s+', '', match.group('article'))
    if not article.startswith('제'):
        article = '제' + article
    return {'name': re.sub(r'\s+', ' ', match.group('name')).strip(), 'article': article, 'limit': 3, **_dated(context)}


def _article(text: str, context: dict) -> dict | None:
    return {'full_id': text.strip(), **_dated(context)} if ARTICLE_ID.match(text.strip()) else None


def _search(text: str, context: dict) -> dict | None:
    return {'query': text.strip(), 'limit': SEARCH_LIMIT, **_dated(context)}


def _dated(context: dict) -> dict:
    return {'assessment_date': context['assessment_date']} if context.get('assessment_date') else {}


# Top to bottom: the first rule whose builder answers claims the request. The last row is the default.
RULES: tuple[Rule, ...] = (
    Rule('law', 'law_ordinance', '자치법규 이름과 조문 번호를 적었어요 → law.go.kr 조례 원문', 0.95, _ordinance),
    Rule('law', 'law_article', '법령 그래프의 조문 id를 적었어요', 0.9, _article),
    Rule('law', 'law_search', '법령 본문 검색 (기본)', 0.6, _search),
)


def route(text: str, *, assessment_date: str | None = None) -> Route:
    """The one route for a text; never None (the last rule is the default)."""
    context = {'assessment_date': assessment_date}
    for rule in RULES:
        args = rule.build(text, context)
        if args is not None:
            return Route(rule.agent, rule.skill, args, rule.confidence, rule.reason)
    raise RuntimeError('RULES must end with a default rule')
