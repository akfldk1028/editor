"""The shapes a role module declares and the router returns.

A role module (`roles/<agent>.py`) is one agent's say in routing: `PATTERNS` (deterministic matchers
that claim a request outright with a skill and its args) and `KEYWORDS` (words that make the request
look like this agent's business, scored against every other role). The router (`__init__.py`) turns
them into one `Route`: a skill call, a goal handoff, or a question back to the user — never a silent guess.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

Builder = Callable[[str, dict], dict | None]


@dataclass(frozen=True)
class Pattern:
    """A deterministic claim: when `build` returns args for the text, this skill answers it."""
    skill: str
    reason: str
    confidence: float
    build: Builder = field(repr=False)


@dataclass(frozen=True)
class Role:
    agent: str
    # Korean label for the choice button when the router has to ask.
    label: str
    # What a free question to this role becomes: a Law skill (answered now) or a goal of the catalog (handed off).
    default_skill: str | None
    default_goal: str | None
    patterns: tuple[Pattern, ...] = ()
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class Choice:
    agent: str
    label: str


@dataclass(frozen=True)
class Route:
    """`kind`: 'skill' (call the agent's skill now), 'goal' (hand off to a catalog goal), 'ask' (the user picks a role)."""
    kind: str
    agent: str | None
    skill: str | None
    goal: str | None
    args: dict
    confidence: float
    reason: str
    choices: tuple[Choice, ...] = ()

    def to_dict(self) -> dict:
        return {'kind': self.kind, 'agent': self.agent, 'skill': self.skill, 'goal': self.goal, 'confidence': self.confidence,
                'reason': self.reason, 'choices': [{'agent': c.agent, 'label': c.label} for c in self.choices]}
