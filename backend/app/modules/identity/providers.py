"""The OAuth 2.0 authorization-code flow for each sign-in provider, as data: where to send the person, where to trade
the code for a token, where to read who they are, and how that profile maps to (subject, email, name).

Adding a provider is adding a row here and its two environment variables in settings.PROVIDER_ENV.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlencode

import httpx


class ProviderError(Exception):
    """The provider refused the code or its answer did not name a person."""


Profile = tuple[str, str | None, str | None]  # subject, email, name


@dataclass(frozen=True)
class Provider:
    name: str
    label: str
    authorize_url: str
    token_url: str
    userinfo_url: str
    scope: str
    profile: Callable[[dict], Profile]

    def authorize(self, client_id: str, redirect_uri: str, state: str) -> str:
        return self.authorize_url + '?' + urlencode({'client_id': client_id, 'redirect_uri': redirect_uri, 'response_type': 'code',
                                                     'scope': self.scope, 'state': state})

    async def identify(self, client_id: str, client_secret: str, redirect_uri: str, code: str, *, transport=None) -> Profile:
        """Trades the code for an access token and reads the person behind it."""
        async with httpx.AsyncClient(timeout=15, transport=transport, headers={'Accept': 'application/json'}) as http:
            try:
                token = await http.post(self.token_url, data={'grant_type': 'authorization_code', 'code': code, 'redirect_uri': redirect_uri,
                                                              'client_id': client_id, 'client_secret': client_secret})
                access = token.json().get('access_token') if token.status_code == 200 else None
                if not access:
                    raise ProviderError('code refused')
                info = await http.get(self.userinfo_url, headers={'Authorization': f'Bearer {access}'})
                if info.status_code != 200:
                    raise ProviderError('profile unavailable')
                subject, email, name = self.profile(info.json())
            except (httpx.HTTPError, ValueError) as error:
                raise ProviderError(type(error).__name__) from None
        if not subject:
            raise ProviderError('profile names no account')
        return subject, email, name


def _google(body: dict) -> Profile:
    return str(body.get('sub') or ''), body.get('email'), body.get('name')


def _github(body: dict) -> Profile:
    return str(body.get('id') or ''), body.get('email'), body.get('name') or body.get('login')


PROVIDERS: dict[str, Provider] = {
    'google': Provider('google', 'Google', 'https://accounts.google.com/o/oauth2/v2/auth', 'https://oauth2.googleapis.com/token',
                       'https://openidconnect.googleapis.com/v1/userinfo', 'openid email profile', _google),
    'github': Provider('github', 'GitHub', 'https://github.com/login/oauth/authorize', 'https://github.com/login/oauth/access_token',
                       'https://api.github.com/user', 'read:user user:email', _github),
}
