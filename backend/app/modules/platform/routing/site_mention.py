"""Does a message name a site? The model's judgment (the editor's local Claude login, as `judge.py`), rules as the fallback.

A whole-message address is the Site role's deterministic claim (`roles/site.locate`). Inside a sentence
("산곡동 684-1에 어린이집을 지으려고 해요") the judgment is the model's: it reads the message and returns the
address or PNU the user named, exactly as written, or nothing. When the model is off (`EDITOR_ROUTING_JUDGE=rules`,
no login) or fails, `roles/site.find` (the same address shapes, searched) decides instead — never silence.
"""
from __future__ import annotations

from pydantic import BaseModel

from backend.app.modules.platform.routing import judge as judging
from backend.app.modules.platform.routing.roles import site

TIMEOUT_S = 20.0

PROMPT = """You read one message a user typed to a Korean architectural design studio's agent network.

Message:

{text}
{current}
Does this message name a specific site — a Korean address (지번: 동/리 + 번지, e.g. 산곡동 684-1; 도로명: 로/길 + 번호,
e.g. 테헤란로 152), or a 19-digit PNU? Answer in JSON:

    - reason: one short sentence, in Korean.
    - names_site: true only when a concrete address or PNU is written in the message. A district, city or
      place name alone (의정부, 강남역 근처), or talk about "the site" without naming it, is false.
    - address: the address or PNU exactly as the user wrote it (keep the 시·군·구 words if they wrote them,
      drop particles like 에/의/쪽), or null when names_site is false. Never invent or complete an address.
"""

CURRENT = """
The conversation is already about one site: {address} (PNU {pnu}). "이 대지", "여기", "우리 땅", or a lot number alone
that is this site's ("684-1", "이 대지(684-1)") refer to it — then names_site is false. names_site is true only when
the message names a different site completely (its own 동/리 or 로/길 name with the number, or a PNU).
"""


class SiteMention(BaseModel):
    reason: str
    names_site: bool
    address: str | None = None


async def site_named(text: str, *, current: dict | None = None, client=None, enabled: bool | None = None) -> str | None:
    """The address or PNU the message names, or None. Model first, rules when the model is off or answers nothing usable.

    `current` = {pnu, address} of the site the conversation is already about: a message that refers back to it
    ("이 대지(684-1)") names no new site, so the map is not sent to the first 684-1 the geocoder finds nationwide."""
    if enabled is None:
        enabled = judging.enabled()
    found = None
    if enabled:
        found = await _ask_model(text, client, current=current)
    if found is None:
        found = site.find(text) or ''
    return None if same_site(found, current) else (found or None)


def same_site(named: str | None, current: dict | None) -> bool:
    """The named text is a part of the current site's own address or PNU ("684-1" of "의정부시 산곡동 684-1"): the same site."""
    if not named or not current:
        return False
    key = named.replace(' ', '')
    return any(key and key in str(value).replace(' ', '') for value in (current.get('address'), current.get('pnu')) if value)


async def _ask_model(text: str, client, *, current: dict | None = None) -> str | None:
    """The model's answer: '' for "no site", the address for a named one, None when the model was unavailable."""
    try:
        from autogen_core.models import UserMessage

        from backend.app.adapters.cli_model_client import ClaudeCodeChatCompletionClient

        model = client or ClaudeCodeChatCompletionClient(timeout_s=TIMEOUT_S)
        known = CURRENT.format(address=current.get('address') or '-', pnu=current.get('pnu') or '-') if current and (current.get('address') or current.get('pnu')) else ''
        result = await model.create([UserMessage(content=PROMPT.format(text=text.strip(), current=known), source='editor')], json_output=SiteMention)
        mention = SiteMention.model_validate_json(result.content if isinstance(result.content, str) else '{}')
    except Exception:
        return None
    address = (mention.address or '').strip()
    return address if mention.names_site and address else ''
