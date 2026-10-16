"""Signed, expiring tokens for the session cookie and the OAuth `state`: `<payload>.<expiry>.<hmac>`, base64url.

HMAC-SHA256 over the payload and expiry with the server's secret: nothing in a token is secret, everything in it is
tamper-evident. A token past its expiry, with a wrong signature, or made for another purpose reads as None.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def _mac(secret: bytes, purpose: str, body: str) -> str:
    return _b64(hmac.new(secret, f'{purpose}:{body}'.encode(), hashlib.sha256).digest())


def sign(secret: bytes, purpose: str, payload: str, ttl_s: int, *, now: float | None = None) -> str:
    """`purpose` binds a token to its use: a state token is never accepted as a session, nor the reverse."""
    body = f'{_b64(payload.encode())}.{int((time.time() if now is None else now) + ttl_s)}'
    return f'{body}.{_mac(secret, purpose, body)}'


def verify(secret: bytes, purpose: str, token: str | None, *, now: float | None = None) -> str | None:
    if not token or token.count('.') != 2:
        return None
    encoded, expiry, mac = token.split('.')
    body = f'{encoded}.{expiry}'
    if not hmac.compare_digest(mac, _mac(secret, purpose, body)):
        return None
    try:
        if int(expiry) < (time.time() if now is None else now):
            return None
        return _unb64(encoded).decode()
    except (ValueError, UnicodeDecodeError):
        return None
