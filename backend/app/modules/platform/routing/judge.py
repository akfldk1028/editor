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
from typing import Awaitable, Callable

from pydantic import BaseModel

from backend.app.core.model_auth import model_auth_mode
from backend.app.modules.platform.routing import cards
from backend.app.modules.platform.routing.roles import DESCRIPTIONS, ROLES

ENV = 'EDITOR_ROUTING_JUDGE'          # llm | rules; unset = llm when the Claude CLI login is available
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


Judge = Callable[[str, str], Awaitable[Ledger | None]]

PROGRESS_LEDGER_PROMPT = """
You are the Orchestrator Agent of a Korean architectural design studio's agent network. Recall we are working on the following request from the user:

{task}

What we know right now (the situation; use it, never invent facts beyond it):

{situation}

And we have assembled the following team:

{team}

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


def participants() -> list[str]:
    return [role.agent for role in ROLES] + [ORCHESTRATOR]


def team_description(live: dict[str, dict | None] | None = None) -> str:
    """`name: description` per participant, whitespace collapsed — as Magentic-One builds `_team_description`.
    `live` = the agents' A2A cards (cards.roster); an agent without one is described by its role line."""
    live = live or {}
    lines = [cards.describe(role.agent, live.get(role.agent), DESCRIPTIONS.get(role.agent, role.label)) for role in ROLES]
    lines.append(re.sub(r'\s+', ' ', f'{ORCHESTRATOR}: {ORCHESTRATOR_DESCRIPTION}').strip())
    return '\n'.join(lines)


def progress_ledger_prompt(task: str, situation: str = '', live: dict[str, dict | None] | None = None) -> str:
    return PROGRESS_LEDGER_PROMPT.format(task=task, situation=situation.strip() or '(nothing beyond the team)', team=team_description(live),
                                         names=', '.join(participants()), orchestrator=ORCHESTRATOR)


def enabled(env=os.environ) -> bool:
    value = str(env.get(ENV) or '').strip().lower()
    if value in ('llm', 'rules'):
        return value == 'llm'
    return model_auth_mode(env) == 'oauth'


async def judge(text: str, situation: str = '', *, client=None, roster=cards.roster) -> Ledger | None:
    """The ledger for one question in a situation (site, goals, which agents are up: data, not prose written here),
    the team described by the agents' live A2A cards; None when the model is unavailable or never named a
    participant (rules then decide)."""
    try:
        from autogen_core.models import UserMessage

        from backend.app.adapters.cli_model_client import ClaudeCodeChatCompletionClient

        model = client or ClaudeCodeChatCompletionClient(timeout_s=TIMEOUT_S)
    except Exception:
        return None
    try:
        live = await roster([role.agent for role in ROLES])
    except Exception:
        live = None
    names = set(participants())
    for _ in range(MAX_JSON_RETRIES + 1):
        try:
            result = await model.create([UserMessage(content=progress_ledger_prompt(text, situation, live), source=ORCHESTRATOR)], json_output=Ledger)
            ledger = Ledger.model_validate_json(result.content if isinstance(result.content, str) else '{}')
        except Exception:
            return None
        if ledger.next_speaker.answer in names:
            return ledger
    return None
