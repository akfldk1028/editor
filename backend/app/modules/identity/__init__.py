"""Who is using the editor: one local person by default, or people signed in with OAuth on a shared server.

    settings.py   EDITOR_AUTH_MODE and the provider credentials, read once
    tokens.py     signed, expiring tokens (session cookie, OAuth state)
    store.py      the users table; User.owner is the id data is stored under
    providers.py  the OAuth providers as data (Google, GitHub)
    service.py    Identity: the app's handle (app.state.identity) and who a request is
    deps.py       Owner: the dependency routes take instead of the literal 'local'
    router.py     /api/v1/auth: login, callback, me, logout, providers
"""
from .deps import Owner, current_owner
from .router import create_identity_router
from .service import Identity
from .settings import LOCAL_OWNER, IdentitySettings

__all__ = ['Identity', 'IdentitySettings', 'LOCAL_OWNER', 'Owner', 'create_identity_router', 'current_owner']
