"""The Orchestrator Agent's judgment: who speaks next for a question — the Magentic-One orchestrator's ledger step.

Modelled on `autogen_agentchat.teams._group_chat._magentic_one._magentic_one_orchestrator` (AutoGen,
the most-used orchestrator-workers implementation): the team is described as one `name: description`
line per participant, the model answers a progress ledger in JSON — `next_speaker {reason, answer}` and
`instruction_or_question {reason, answer}` — the speaker must be one of the participant names (an
unknown name is retried, never accepted), and the instruction is what the Orchestrator says to that
agent. The Orchestrator itself is a participant: choosing it means the question is unclear or spans
several agents, and it asks the user. The model is the workspace's local Claude login
(`adapters/cli_model_client`, OAuth, no key). The Orchestrator's own door should run this same
ledger over its live A2A cards; `Ledger` is the contract it should return.
"""
from __future__ import annotations

import os
import re
import time
from threading import Lock
from typing import Awaitable, Callable

from pydantic import BaseModel, ValidationError

from backend.app.core.model_auth import model_auth_mode
from backend.app.modules.platform.routing import cards
from backend.app.modules.platform.routing.roles import DESCRIPTIONS, ROLES

ENV = 'EDITOR_ROUTING_JUDGE'          # auto | llm | rules
TIMEOUT_S = 45.0
MAX_JSON_RETRIES = 2                  # Magentic-One retries an invalid ledger / unknown speaker
ORCHESTRATOR = 'orchestrator'
ORCHESTRATOR_DESCRIPTION = ('The Orchestrator Agent itself: speaks next only when the question is unclear, spans several '
                            'agents, or belongs to none — it then asks the user which agent to involve.')


class LedgerEntryBooleanAnswer(BaseModel):
    reason: str
    answer: bool


class LedgerEntryStringAnswer(BaseModel):
    reason: str
    answer: str


class Ledger(BaseModel):
    """Magentic-One's progress ledger for a first turn (the loop/progress booleans are meaningless before any step):
    satisfied -> the Orchestrator answers the user itself (`instruction_or_question.answer` is that reply);
    otherwise `next_speaker` is the agent to involve and the instruction is what the Orchestrator tells it."""
    is_request_satisfied: LedgerEntryBooleanAnswer
    next_speaker: LedgerEntryStringAnswer
    instruction_or_question: LedgerEntryStringAnswer


Situation = str | Callable[[], Awaitable[str]]
Judge = Callable[[str, str], Awaitable[Ledger | None]]

PROGRESS_LEDGER_PROMPT = """
You are the Orchestrator Agent of a Korean architectural design studio's agent network. Recall we are working on the following request from the user:

{task}

What we know right now (the situation; use it, never invent facts beyond it):

{situation}

And we have assembled the following team:

{team}

Choose the owner of the requested operation even when its execution needs a missing parcel,
project, geometry, budget or other parameter. The selected specialist can ask for that evidence;
missing execution parameters alone do not make the routing intent unclear. Distinguish obtaining
existing site facts from proposing a new design or checking a legal limit. Route the operation the
user asks for, not every domain mentioned as context. Ask as Orchestrator only when the responsible
owner itself is genuinely ambiguous or the user requests several distinct owners' operations.

To make progress on the request, please answer the following questions, including necessary reasoning:

    - Is the request fully satisfied by what the Orchestrator itself can say from the situation above: a greeting,
      a question about what this network can do or which agents are on, a clarification, small talk? (True if you
      can answer the user completely yourself without any specialist's data or computation; False if a specialist
      must look something up, compute, or design.)
    - Who should speak next? (select from: {names}) Judge by what each team member does, not by surface words.
      Choose `{orchestrator}` when the request is satisfied above, or when it is unclear, spans several members, or
      belongs to none.
    - What instruction or question would you give this team member? (Phrase as if speaking directly to them, in
      plain Korean, and include any specific information they may need. If the request is satisfied, this is the
      Orchestrator's reply to the user, in plain Korean, complete and specific to the situation. If `{orchestrator}`
      speaks next without the request being satisfied, write the one plain Korean question it asks the user.)

Please output an answer in pure JSON format according to the following schema. The JSON object must be parsable as-is. DO NOT OUTPUT ANYTHING OTHER THAN JSON, AND DO NOT DEVIATE FROM THIS SCHEMA:

    {{
        "is_request_satisfied": {{
            "reason": string,
            "answer": boolean
        }},
        "next_speaker": {{
            "reason": string,
            "answer": string (select from: {names})
        }},
        "instruction_or_question": {{
            "reason": string,
            "answer": string
        }}
    }}
"""


_ROLE_AGENTS = tuple(role.agent for role in ROLES)
EXTRA_FALLBACK = 'registered in the network with an A2A card; described by that card when it answers'


def extras(registered=cards.registered) -> list[str]:
    """Agents the registry lists (with a card) that have no role module — the team grows with the registry, not with code here."""
    return [agent for agent in registered() if agent not in _ROLE_AGENTS]


def participants(extra: list[str] | None = None) -> list[str]:
    return [*_ROLE_AGENTS, *(extras() if extra is None else extra), ORCHESTRATOR]


def team_description(live: dict[str, dict | None] | None = None, extra: list[str] | None = None) -> str:
    """`name: description` per participant, whitespace collapsed — as Magentic-One builds `_team_description`.
    `live` = the agents' A2A cards (cards.roster); a role agent without one is described by its role line, a
    registered agent without a role by its card alone."""
    live = live or {}
    lines = [cards.describe(role.agent, live.get(role.agent), DESCRIPTIONS.get(role.agent, role.label)) for role in ROLES]
    lines += [cards.describe(agent, live.get(agent), EXTRA_FALLBACK) for agent in (extras() if extra is None else extra)]
    lines.append(re.sub(r'\s+', ' ', f'{ORCHESTRATOR}: {ORCHESTRATOR_DESCRIPTION}').strip())
    return '\n'.join(lines)


def progress_ledger_prompt(task: str, situation: str = '', live: dict[str, dict | None] | None = None, extra: list[str] | None = None) -> str:
    return PROGRESS_LEDGER_PROMPT.format(task=task, situation=situation.strip() or '(nothing beyond the team)', team=team_description(live, extra),
                                         names=', '.join(participants(extra)), orchestrator=ORCHESTRATOR)


def policy(env=os.environ) -> str:
    value = str(env.get(ENV) or '').strip().lower()
    if value in ('auto', 'llm', 'rules'):
        return value
    return 'llm' if model_auth_mode(env) == 'oauth' else 'rules'


def enabled(env=os.environ) -> bool:
    return policy(env) != 'rules'


def error_code(error: Exception) -> str:
    text = str(error).lower()
    if 'limit' in text and ('weekly' in text or 'usage' in text or 'hit your' in text):
        return 'model_usage_limit'
    if 'rate limit' in text or 'rate_limit' in text:
        return 'model_rate_limit'
    if 'oauth' in text or 'unauthorized' in text or 'authentication' in text or 'not logged in' in text:
        return 'model_authentication'
    if isinstance(error, TimeoutError) or 'timed out' in text or 'timeout' in text:
        return 'model_timeout'
    return 'model_unavailable'


class FailureBackoff:
    def __init__(self, now=time.monotonic):
        self.now = now
        self.until = 0.0
        self.lock = Lock()

    def blocked(self):
        with self.lock:
            return self.now() < self.until

    def failed(self, code):
        cooldown = 60 if code in ('model_usage_limit', 'model_authentication') else 15
        with self.lock:
            self.until = max(self.until, self.now() + cooldown)


_backoff = FailureBackoff()


async def judge(text: str, situation: Situation = '', *, client=None, roster=cards.roster, on_error=None,
                on_prompt: Callable[[str], None] | None = None, backoff=_backoff) -> Ledger | None:
    """The ledger for one question in a situation (site, goals, which agents are up: data, not prose written here),
    the team described by the agents' live A2A cards; None when the model is unavailable or never named a
    participant (rules then decide)."""
    shared_client = client is None
    if shared_client and backoff.blocked():
        if on_error:
            on_error('model_circuit_open')
        return None
    try:
        from autogen_core.models import UserMessage

        from backend.app.adapters.cli_model_client import ClaudeCodeChatCompletionClient

        model = client or ClaudeCodeChatCompletionClient(timeout_s=TIMEOUT_S)
    except Exception as error:
        if on_error:
            on_error(error_code(error))
        return None
    if callable(situation):
        situation = await situation()
    extra = extras()
    try:
        live = await roster([*_ROLE_AGENTS, *extra])
    except Exception:
        live = None
    names = set(participants(extra))
    prompt = progress_ledger_prompt(text, situation, live, extra)
    if on_prompt:
        on_prompt(prompt)
    for _ in range(MAX_JSON_RETRIES + 1):
        try:
            result = await model.create([UserMessage(content=prompt, source=ORCHESTRATOR)], json_output=Ledger)
        except Exception as error:
            code = error_code(error)
            if shared_client:
                backoff.failed(code)
            if on_error:
                on_error(code)
            return None
        try:
            ledger = Ledger.model_validate_json(result.content if isinstance(result.content, str) else '{}')
        except ValidationError:
            # A malformed ledger is the model's answer, not an outage: ask again, never open the circuit.
            continue
        if ledger.next_speaker.answer in names:
            return ledger
    if on_error:
        on_error('model_invalid_speaker')
    return None
