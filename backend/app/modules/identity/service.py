"""The identity façade the app holds (`app.state.identity`): its settings, its user store, and who a request is."""
from __future__ import annotations

from fastapi import Request

from . import tokens
from .settings import LOCAL_OWNER, IdentitySettings
from .store import User, UserStore

SESSION = 'session'


class Identity:
    def __init__(self, settings: IdentitySettings, store: UserStore | None = None):
        self.settings = settings
        self.store = store or (UserStore(settings.data_dir / 'users.sqlite') if settings.oauth else None)

    @classmethod
    def from_env(cls) -> 'Identity':
        return cls(IdentitySettings.from_env())

    def session_token(self, user: User) -> str:
        return tokens.sign(self.settings.secret, SESSION, user.id, self.settings.session_days * 86400)

    def user_of(self, request: Request) -> User | None:
        """The signed-in person a request carries in its session cookie, or None."""
        if not self.settings.oauth or self.store is None:
            return None
        user_id = tokens.verify(self.settings.secret, SESSION, request.cookies.get(self.settings.cookie))
        return self.store.get(user_id) if user_id else None

    def owner_of(self, request: Request) -> str | None:
        """Whose data the request reads and writes: `local` on a one-person editor, the signed-in person on a shared
        server, None when nobody is signed in there."""
        if not self.settings.oauth:
            return LOCAL_OWNER
        user = self.user_of(request)
        return user.owner if user else None
