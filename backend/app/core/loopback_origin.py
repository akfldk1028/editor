"""The editor's own page reached through another loopback name is the same page.

Every write route compares the request Origin with the public origin (EDITOR_PUBLIC_URL, e.g.
http://127.0.0.1:3003). Opening the editor as http://localhost:3003 sent Origin localhost and every
check answered 403 (the site card's "필지 경계 조회 실패: 403", 2026-11-03). Loopback names of the
same scheme and port are one machine and one page, so the Origin is restated as the public origin
before any route sees it. Any other origin is passed through unchanged and still refused.
"""
from __future__ import annotations

from urllib.parse import urlsplit

LOOPBACK = {'localhost', '127.0.0.1', '::1', '[::1]'}


def alias_of(origin: str, public: str) -> bool:
    try:
        a, b = urlsplit(origin), urlsplit(public)
    except ValueError:
        return False
    return (a.scheme == b.scheme and a.port == b.port and a.port is not None
            and (a.hostname or '') in LOOPBACK and (b.hostname or '') in LOOPBACK)


class LoopbackOrigin:
    def __init__(self, app, public: str):
        self.app, self.public = app, public

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http':
            headers = scope.get('headers') or []
            origins = [v.decode('latin-1') for k, v in headers if k == b'origin']
            origin = origins[0] if len(origins) == 1 else None   # several Origin headers are left for the routes to refuse
            if origin and origin != self.public and alias_of(origin, self.public):
                scope = {**scope, 'headers': [(k, self.public.encode('latin-1') if k == b'origin' else v)
                                              for k, v in headers]}
        await self.app(scope, receive, send)
