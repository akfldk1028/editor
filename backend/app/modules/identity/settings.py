"""Who may use this editor and how they sign in, read once from the environment.

`EDITOR_AUTH_MODE=local` (the default) is one person on their own machine: every request belongs to the owner
`local`, as before. `EDITOR_AUTH_MODE=oauth` is a shared server: a request belongs to the person signed in with one
of the configured OAuth providers, and a request without a valid session is refused.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

LOCAL_OWNER = 'local'
EDITOR_ROOT = Path(__file__).resolve().parents[4]  # backend/app/modules/identity/settings.py → editor
PROVIDER_ENV = (('google', 'EDITOR_OAUTH_GOOGLE'), ('github', 'EDITOR_OAUTH_GITHUB'))


@dataclass(frozen=True)
class ProviderCredentials:
    client_id: str
    client_secret: str


@dataclass(frozen=True)
class IdentitySettings:
    mode: str = 'local'
    secret: bytes = b''
    public_url: str = ''
    data_dir: Path = EDITOR_ROOT / 'runtime' / 'identity'
    providers: dict[str, ProviderCredentials] = field(default_factory=dict)
    session_days: int = 14
    cookie: str = 'editor_session'

    @property
    def oauth(self) -> bool:
        return self.mode == 'oauth'

    @property
    def secure_cookie(self) -> bool:
        return self.public_url.startswith('https://')

    @classmethod
    def from_env(cls, env=os.environ) -> 'IdentitySettings':
        mode = (env.get('EDITOR_AUTH_MODE') or 'local').strip().lower()
        if mode not in ('local', 'oauth'):
            raise ValueError('EDITOR_AUTH_MODE must be local or oauth')
        providers = {name: ProviderCredentials(env[f'{prefix}_CLIENT_ID'], env[f'{prefix}_CLIENT_SECRET'])
                     for name, prefix in PROVIDER_ENV
                     if env.get(f'{prefix}_CLIENT_ID') and env.get(f'{prefix}_CLIENT_SECRET')}
        secret = (env.get('EDITOR_AUTH_SECRET') or '').encode()
        public_url = (env.get('EDITOR_PUBLIC_URL') or '').rstrip('/')
        if mode == 'oauth':
            # A shared server without these would sign sessions anyone can forge, or send people nowhere.
            if len(secret) < 32:
                raise ValueError('EDITOR_AUTH_SECRET must be at least 32 bytes in oauth mode')
            if not public_url:
                raise ValueError('EDITOR_PUBLIC_URL is required in oauth mode (the OAuth redirect address)')
            if not providers:
                raise ValueError('oauth mode needs a provider: EDITOR_OAUTH_GOOGLE_* or EDITOR_OAUTH_GITHUB_*')
        if env.get('EDITOR_IDENTITY_DIR'):
            data_dir = Path(env['EDITOR_IDENTITY_DIR'])
        elif env.get('EDITOR_PLATFORM_DATA_DIR'):
            data_dir = Path(env['EDITOR_PLATFORM_DATA_DIR']) / 'identity'
        else:
            data_dir = EDITOR_ROOT / 'runtime' / 'identity'
        return cls(mode=mode, secret=secret, public_url=public_url, data_dir=data_dir, providers=providers,
                   session_days=int(env.get('EDITOR_SESSION_DAYS') or 14))
