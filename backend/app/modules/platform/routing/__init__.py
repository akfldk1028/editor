"""Which agent answers a typed question — the editor's interim router, by role.

The Orchestrator is the network's router (hub-and-spoke); until its editor door takes questions the
product routes here, in the shape it will hand over (`Route`: kind, agent, skill|goal, confidence,
reason, choices). Decided in this order, after the research in memory `multi-agent-routing-research`:

1. A role's deterministic PATTERN claims the request (조례 제N조, a statute id) — confidence ≥ 0.9.
2. Role KEYWORDS score the request; one role clearly ahead wins (0.7) — a Law skill is called now,
   another agent's role becomes a goal handoff of the catalog.
3. A tie or no keyword at all → `ask`: the user picks the role. Never a silent default.

A `role` the user already chose (the button) skips 2–3 and goes to that role's default.
"""
from __future__ import annotations

from backend.app.modules.platform.routing.roles import ROLES
from backend.app.modules.platform.routing.roles.law import search
from backend.app.modules.platform.routing.rules import Choice, Route

KEYWORD_CONFIDENCE = 0.7
ASK_CONFIDENCE = 0.3

_BY_AGENT = {role.agent: role for role in ROLES}
_CHOICES = tuple(Choice(role.agent, role.label) for role in ROLES)


def _score(text: str) -> list[tuple[int, int, str]]:
    """(hits, longest keyword, agent) per role with at least one hit, best first."""
    lowered = text.lower()
    scored = []
    for role in ROLES:
        hits = [word for word in role.keywords if word.lower() in lowered]
        if hits:
            scored.append((len(hits), max(len(word) for word in hits), role.agent))
    scored.sort(key=lambda item: (-item[0], -item[1]))
    return scored


def _default_route(agent: str, text: str, context: dict, confidence: float, reason: str) -> Route:
    """A free question to this role: its default skill (Law's search is the only one answered now) or its goal."""
    role = _BY_AGENT[agent]
    if role.default_skill:
        return Route('skill', agent, role.default_skill, None, search(text, context), confidence, reason)
    return Route('goal', agent, None, role.default_goal, {}, confidence, reason)


def route(text: str, *, assessment_date: str | None = None, role: str | None = None) -> Route:
    """One route for a text; `role` is the agent the user already picked (a choice button)."""
    context = {'assessment_date': assessment_date}
    if role and role in _BY_AGENT:
        chosen = _BY_AGENT[role]
        for pattern in chosen.patterns:
            args = pattern.build(text, context)
            if args is not None:
                return Route('skill', role, pattern.skill, None, args, pattern.confidence, pattern.reason)
        return _default_route(role, text, context, 0.9, f'{chosen.label}로 직접 골랐어요')
    for candidate in ROLES:
        for pattern in candidate.patterns:
            args = pattern.build(text, context)
            if args is not None:
                return Route('skill', candidate.agent, pattern.skill, None, args, pattern.confidence, pattern.reason)
    scored = _score(text)
    if scored and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        hits, _, agent = scored[0]
        return _default_route(agent, text, context, KEYWORD_CONFIDENCE, f'{_BY_AGENT[agent].label}의 말이 {hits}개 보여요')
    reason = '어느 에이전트의 일인지 분명하지 않아요' if not scored else f'{" · ".join(_BY_AGENT[a].label for _, _, a in scored[:2])} 둘 다 해당돼요'
    return Route('ask', None, None, None, {}, ASK_CONFIDENCE, reason, _CHOICES)
