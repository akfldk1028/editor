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

Does this message name a specific site — a Korean address (지번: 동/리 + 번지, e.g. 산곡동 684-1; 도로명: 로/길 + 번호,
e.g. 테헤란로 152), or a 19-digit PNU? Answer in JSON:

    - reason: one short sentence, in Korean.
    - names_site: true only when a concrete address or PNU is written in the message. A district, city or
      place name alone (의정부, 강남역 근처), or talk about "the site" without naming it, is false.
    - address: the address or PNU exactly as the user wrote it (keep the 시·군·구 words if they wrote them,
      drop particles like 에/의/쪽), or null when names_site is false. Never invent or complete an address.
"""


class SiteMention(BaseModel):
    reason: str
    names_site: bool
    address: str | None = None


async def site_named(text: str, *, client=None, enabled: bool | None = None) -> str | None:
    """The address or PNU the message names, or None. Model first, rules when the model is off or answers nothing usable."""
    if enabled is None:
        enabled = judging.enabled()
    if enabled:
        found = await _ask_model(text, client)
        if found is not None:
            return found or None
    return site.find(text)


async def _ask_model(text: str, client) -> str | None:
    """The model's answer: '' for "no site", the address for a named one, None when the model was unavailable."""
    try:
        from autogen_core.models import UserMessage

        from backend.app.adapters.cli_model_client import ClaudeCodeChatCompletionClient

        model = client or ClaudeCodeChatCompletionClient(timeout_s=TIMEOUT_S)
        result = await model.create([UserMessage(content=PROMPT.format(text=text.strip()), source='editor')], json_output=SiteMention)
        mention = SiteMention.model_validate_json(result.content if isinstance(result.content, str) else '{}')
    except Exception:
        return None
    address = (mention.address or '').strip()
    return address if mention.names_site and address else ''
