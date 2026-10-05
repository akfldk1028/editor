"""Minimal OpenAI transport for massv2.

Deliberately small and local rather than reaching into `llm_proposals`, whose
caller is a private function inside a 1793-line module belonging to the other
pipeline. Sixty lines of transport is cheaper to own than that coupling, and
keeping it here is what stops this package from growing into another one of
those files.

Structured output is required, not requested: the schema is enforced by the API
so a malformed authoring response fails here instead of three stages later.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

DEFAULT_MODEL = "gpt-5.4-mini"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
_ENDPOINT = "https://api.openai.com/v1/responses"
_GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"


class LlmUnavailable(RuntimeError):
    """No key, no network, or the model refused to answer in schema."""


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    # settings.py loads .env; import lazily so this module stays importable in
    # contexts that never call out.
    from django.conf import settings

    return str(getattr(settings, name, "") or "").strip()


def _api_key() -> str:
    key = _env("OPENAI_API_KEY")
    if not key:
        raise LlmUnavailable("OPENAI_API_KEY is not set")
    return key


def _gemini_schema(node: Any) -> Any:
    """Gemini takes an OpenAPI subset, which has no `additionalProperties`."""

    if isinstance(node, dict):
        return {
            key: _gemini_schema(value)
            for key, value in node.items()
            if key not in {"additionalProperties", "strict"}
        }
    if isinstance(node, list):
        return [_gemini_schema(item) for item in node]
    return node


def _gemini_call(
    *, system: str, user: str, schema: dict[str, Any], model: str | None, timeout: float
) -> dict[str, Any]:
    # Pick by shape, not by name. This environment has a GEMINI_API_KEY holding
    # an `AQ.`-prefixed OAuth token, which this endpoint rejects, alongside a
    # GOOGLE_API_KEY holding a real `AIza`-prefixed API key. Preferring the
    # matching shape is more reliable than guessing which variable was meant.
    candidates = [_env("GEMINI_API_KEY"), _env("GOOGLE_API_KEY")]
    key = next(
        (item for item in candidates if item.startswith("AIza")),
        next((item for item in candidates if item), ""),
    )
    if not key:
        raise LlmUnavailable("no Gemini API key (GEMINI_API_KEY / GOOGLE_API_KEY)")
    name = model or _env("MASSV2_GEMINI_MODEL") or DEFAULT_GEMINI_MODEL
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _gemini_schema(schema),
        },
    }
    request = urllib.request.Request(
        f"{_GEMINI_ENDPOINT}/{name}:generateContent?key={key}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:400]
        raise LlmUnavailable(f"gemini HTTP {error.code}: {detail}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise LlmUnavailable(f"gemini {error}") from error

    for candidate in body.get("candidates") or ():
        for part in (candidate.get("content") or {}).get("parts") or ():
            text = part.get("text")
            if text:
                return json.loads(text)
    raise LlmUnavailable(f"gemini returned no content: {str(body)[:300]}")


def structured_call(
    *,
    system: str,
    user: str,
    schema: dict[str, Any],
    schema_name: str,
    model: str | None = None,
    timeout: float = 180.0,
    max_output_tokens: int = 16000,
    provider: str | None = None,
) -> dict[str, Any]:
    """One structured-output request; returns the parsed object.

    Two providers, because a project that must always use an LLM cannot be one
    exhausted billing account away from having no LLM. `provider` pins one
    explicitly; left unset, OpenAI is tried first and Gemini answers if OpenAI
    has no key or no credit. Anything else - a bad schema, a refusal - raises
    rather than silently falling through, so a real failure stays visible.
    """

    choice = (provider or _env("MASSV2_LLM_PROVIDER") or "auto").lower()
    if choice == "gemini":
        return _gemini_call(system=system, user=user, schema=schema, model=model, timeout=timeout)

    payload = {
        "model": model or os.environ.get("MASSV2_LLM_MODEL") or DEFAULT_MODEL,
        "input": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "strict": True,
                "schema": schema,
            }
        },
        "max_output_tokens": int(max_output_tokens),
    }
    def _fallback(reason: str) -> dict[str, Any]:
        if choice != "auto":
            raise LlmUnavailable(reason)
        return _gemini_call(
            system=system, user=user, schema=schema, model=None, timeout=timeout
        )

    try:
        key = _api_key()
    except LlmUnavailable as error:
        return _fallback(str(error))

    request = urllib.request.Request(
        _ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:400]
        # No credit or no access is an account fact, not a bad request; the
        # other provider can still answer it.
        if error.code in (401, 402, 403, 429):
            return _fallback(f"HTTP {error.code}: {detail}")
        raise LlmUnavailable(f"HTTP {error.code}: {detail}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        return _fallback(str(error))

    for item in body.get("output") or ():
        for part in item.get("content") or ():
            text = part.get("text")
            if text:
                return json.loads(text)
    raise LlmUnavailable(f"no structured content in response: {str(body)[:300]}")
