"""The team as the agents describe themselves: their live A2A agent cards (A2A 1.0, `/.well-known/agent-card.json`).

Google ADK's rule — delegation quality is the agents' own descriptions — and Magentic-One's team roster both want the
agents' words, not a copy kept here. Each role's registry entry (`infra/config/services.json`, one owner of ports
and card URLs) says where its card is; an agent that is down or has no card falls back to the one-line role
description written from its card (`roles/<agent>.py`). Cards are cached for a minute.
"""
from __future__ import annotations

import os
import re
import time

import httpx

from backend.app.modules.platform.status.registry import Registry, base_url

CARD_TIMEOUT_S = 2.0
CACHE_S = 60.0
MAX_SKILLS = 12
_registry = Registry()
_cache: dict[str, tuple[float, dict | None]] = {}


def host_id(agent: str) -> str:
    return agent.replace('_', '-')


def card_url(agent: str, *, registry: Registry = _registry, env=os.environ) -> str | None:
    entry = next((e for e in registry.entries() if e.get('id') == host_id(agent)), None)
    if not entry or not entry.get('card_url'):
        return None
    base = base_url(entry, env)
    return entry['card_url'].replace('{base}', base) if base else None


def _card(data: dict) -> dict | None:
    name, description = data.get('name'), data.get('description')
    if not isinstance(name, str) or not isinstance(description, str):
        return None
    skills = [{'id': s['id'], 'name': s.get('name') or s['id'], 'description': s.get('description') or s.get('name') or ''}
              for s in data.get('skills') or [] if isinstance(s, dict) and isinstance(s.get('id'), str)]
    return {'name': name, 'description': description, 'skills': skills}


def registered(*, registry: Registry = _registry) -> list[str]:
    """Every agent the registry lists with a card, as the network names it (underscored id)."""
    return [str(e['id']).replace('-', '_') for e in registry.entries() if e.get('kind') == 'agent' and e.get('card_url')]


async def fetch_card(url: str) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=CARD_TIMEOUT_S) as client:
            response = await client.get(url, headers={'accept': 'application/json'})
            response.raise_for_status()
            return _card(response.json())
    except Exception:
        return None


async def roster(agents: list[str], *, fetch=fetch_card, now=time.monotonic, cache=_cache, registry: Registry = _registry) -> dict[str, dict | None]:
    """{agent: card | None} for every agent, each card at most CACHE_S old."""
    result = {}
    for agent in agents:
        cached = cache.get(agent)
        if cached and now() - cached[0] < CACHE_S:
            result[agent] = cached[1]
            continue
        url = card_url(agent, registry=registry)
        card = await fetch(url) if url else None
        cache[agent] = (now(), card)
        result[agent] = card
    return result


def describe(agent: str, card: dict | None, fallback: str) -> str:
    """One `name: description` line (whitespace collapsed) — the card's own words with its skill ids, else the fallback."""
    if not card:
        return re.sub(r'\s+', ' ', f'{agent}: {fallback}').strip()
    skills = card['skills'][:MAX_SKILLS]
    more = len(card['skills']) - len(skills)
    said = '; '.join(f"{s['id']}: {s['description']}" if s['description'] else s['id'] for s in skills)
    line = f"{agent}: {card['description']}" + (f' Skills: {said}' if said else '') + (f' (+{more} more)' if more > 0 else '')
    return re.sub(r'\s+', ' ', line).strip()
