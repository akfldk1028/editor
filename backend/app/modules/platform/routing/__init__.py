"""Which agent answers a typed question — the editor's interim router, by role.

The Orchestrator is the network's router (hub-and-spoke); until its editor door takes questions the
product routes here, in the shape it will hand over (`Route`: kind, agent, skill|goal, confidence,
reason, choices). Decided in this order, after the research in memory `multi-agent-routing-research` (supervisor/triage
patterns: the model judges, rules are the fast path and the fallback):

1. A role's deterministic PATTERN claims the request (조례 제N조, a statute id) — confidence ≥ 0.9.
2. The Orchestrator's JUDGMENT (`judge.py`, the Magentic-One progress ledger over the team description,
   on the local Claude login): `next_speaker` is the agent (0.85, with the ledger's reason and the
   instruction the Orchestrator gives it), or the Orchestrator itself → `ask` with its question.
   `decide()` is this path; `route()` is the synchronous rule path it falls back to when the model is
   off (`EDITOR_ROUTING_JUDGE=rules`) or never named a participant.
3. Fallback — role KEYWORDS score the request; one role clearly ahead wins (0.7).
4. A tie or no keyword at all → `ask`: the user picks the role. Never a silent default.

A `role` the user already chose (the button) skips 2–4 and goes to that role's default.
"""
from __future__ import annotations

from dataclasses import replace

from backend.app.modules.platform.routing import cards
from backend.app.modules.platform.routing import judge as judging
from backend.app.modules.platform.routing.roles import ROLES
from backend.app.modules.platform.routing.roles.law import search
from backend.app.modules.platform.routing.rules import Choice, Route

KEYWORD_CONFIDENCE = 0.7
LEDGER_CONFIDENCE = 0.85   # the model named the speaker; the ledger's reason says why
ASK_CONFIDENCE = 0.3

_BY_AGENT = {role.agent: role for role in ROLES}
_CHOICES = tuple(Choice(role.agent, role.label) for role in ROLES)


def _score(text: str) -> list[tuple[int, int, str]]:
    """(hits, longest keyword, agent) per role with at least one hit, best first."""
    lowered = text.lower()
    matches = []
    for role in ROLES:
        for word in role.keywords:
            offset = 0
            while (position := lowered.find(word.lower(), offset)) >= 0:
                matches.append((position, position + len(word), role.agent, word))
                offset = position + 1
    # A domain phrase owns its span; its generic substring is not a second vote.
    specific = []
    covering_start, covering_end = -1, -1
    for match in sorted(matches, key=lambda m: (m[0], -m[1])):
        start, end = match[:2]
        if end < covering_end or (end == covering_end and start > covering_start):
            continue
        specific.append(match)
        covering_start, covering_end = start, end
    scored = []
    for role in ROLES:
        hits = {m[3] for m in specific if m[2] == role.agent}
        if hits:
            scored.append((len(hits), max(map(len, hits)), role.agent))
    scored.sort(key=lambda item: (-item[0], -item[1]))
    return scored


def _default_route(agent: str, text: str, context: dict, confidence: float, reason: str, decided_by: str = 'rules',
                   instruction: str | None = None) -> Route:
    """A free question to this role: its default skill (Law's search is the only one answered now) or its goal."""
    role = _BY_AGENT[agent]
    if role.default_skill:
        return Route('skill', agent, role.default_skill, None, search(text, context), confidence, reason, decided_by=decided_by, instruction=instruction)
    return Route('goal', agent, None, role.default_goal, {}, confidence, reason, decided_by=decided_by, instruction=instruction)


def _claimed(text: str, context: dict, roles=ROLES) -> Route | None:
    """The deterministic fast path: a role's pattern claims the request outright."""
    for candidate in roles:
        for pattern in candidate.patterns:
            args = pattern.build(text, context)
            if args is not None:
                return Route('skill', candidate.agent, pattern.skill, None, args, pattern.confidence, pattern.reason, decided_by='pattern')
    return None


def route(text: str, *, assessment_date: str | None = None, role: str | None = None) -> Route:
    """The rule path: one route for a text; `role` is the agent the user already picked (a choice button)."""
    context = {'assessment_date': assessment_date}
    if role and role in _BY_AGENT:
        chosen = _BY_AGENT[role]
        return _claimed(text, context, (chosen,)) or _default_route(role, text, context, 0.9, f'{chosen.label}로 직접 골랐어요', 'user')
    claimed = _claimed(text, context)
    if claimed:
        return claimed
    scored = _score(text)
    if scored and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        hits, _, agent = scored[0]
        return _default_route(agent, text, context, KEYWORD_CONFIDENCE, f'{_BY_AGENT[agent].label}의 말이 {hits}개 보여요')
    reason = '어느 에이전트의 일인지 분명하지 않아요' if not scored else f'{" · ".join(_BY_AGENT[a].label for _, _, a in scored[:2])} 둘 다 해당돼요'
    return Route('ask', None, None, None, {}, ASK_CONFIDENCE, reason, _CHOICES)


def _delegate(agent: str, text: str, confidence: float, reason: str, decided_by: str, instruction: str | None = None) -> Route:
    """A registered agent without a role module: the question is its, with the Orchestrator's instruction; no skill is
    chosen here (a skill needs its own arguments — the Orchestrator's conversation does that), so the door hands it over."""
    return Route('agent', agent, None, None, {'text': text}, confidence, reason, decided_by=decided_by, instruction=instruction)


async def decide(text: str, *, assessment_date: str | None = None, role: str | None = None, judge: judging.Judge | None = None,
                 enabled: bool | None = None, situation: judging.Situation = '', extras: list[str] | None = None,
                 policy: str | None = None) -> Route:
    """The product path: a picked role or a pattern decides at once; otherwise the Orchestrator's ledger (the
    model names the next speaker and what to tell it; naming itself means asking the user) — and the rule table
    only when the model is off (`EDITOR_ROUTING_JUDGE=rules`) or never named a participant. `extras` = registered
    agents without a role module (default: the registry's); the model may name them and the user may pick them."""
    context = {'assessment_date': assessment_date}
    extra = judging.extras() if extras is None else extras
    if role and role in _BY_AGENT:
        return route(text, assessment_date=assessment_date, role=role)
    if role and role in extra:
        return _delegate(role, text, 0.9, f'{role}로 직접 골랐어요', 'user')
    claimed = _claimed(text, context)
    if claimed:
        return claimed
    selected_policy = policy or judging.policy()
    if selected_policy not in ('auto', 'llm', 'rules'):
        raise ValueError('unsupported routing policy')
    if selected_policy == 'auto':
        scored = _score(text)
        if len(scored) == 1 and scored[0][0] >= 2:
            return route(text, assessment_date=assessment_date)
    if enabled is None:
        enabled = selected_policy != 'rules'
    if enabled and judge and callable(situation):
        situation = await situation()
    failures = []
    ledger = (await judge(text, situation) if judge else
              await judging.judge(text, situation, on_error=failures.append)) if enabled else None
    if ledger is None:
        result = route(text, assessment_date=assessment_date)
        return replace(result, fallback_reason=(failures[-1] if failures else 'model_unavailable')) if enabled else result
    speaker, instruction = ledger.next_speaker.answer, ledger.instruction_or_question.answer.strip() or None
    if ledger.is_request_satisfied.answer and instruction:
        # The Orchestrator answers the user itself (Magentic-One: request satisfied -> its final answer).
        return Route('answer', judging.ORCHESTRATOR, None, None, {}, LEDGER_CONFIDENCE, ledger.is_request_satisfied.reason,
                     decided_by='llm', instruction=instruction)
    if speaker in _BY_AGENT:
        return _default_route(speaker, text, context, LEDGER_CONFIDENCE, ledger.next_speaker.reason, 'llm', instruction)
    if speaker in extra:
        return _delegate(speaker, text, LEDGER_CONFIDENCE, ledger.next_speaker.reason, 'llm', instruction)
    # The Orchestrator asks: its question is the reason the user reads; no agent was told anything.
    choices = (*_CHOICES, *(Choice(agent, cards.display_name(agent)) for agent in extra))
    return Route('ask', None, None, None, {}, ASK_CONFIDENCE, instruction or '어느 에이전트의 일인지 분명하지 않아요', choices, decided_by='llm')
