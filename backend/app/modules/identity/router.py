"""`/api/v1/auth`: sign in with a provider, sign out, and who is signed in.

The flow is OAuth 2.0's authorization code: `/login/{provider}` sends the person to the provider with a signed
`state` and drops a one-time nonce cookie; the provider sends them back to `/callback/{provider}`, which checks the
state against that cookie (so a callback someone else started is refused), trades the code for their profile, and
sets the session cookie. Every address is under EDITOR_PUBLIC_URL, which the providers must list as the redirect.
"""
from __future__ import annotations

import json
import secrets

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from . import tokens
from .providers import PROVIDERS, ProviderError
from .service import Identity

STATE = 'oauth_state'
NONCE_COOKIE = 'editor_oauth_nonce'
STATE_TTL_S = 600


def safe_next(value: str | None) -> str:
    """Where to land after signing in: a path on this site only (never `//host` or a full URL)."""
    return value if value and value.startswith('/') and not value.startswith('//') else '/'


def create_identity_router(identity: Identity, *, transport=None) -> APIRouter:
    router = APIRouter(prefix='/api/v1/auth', tags=['auth'])
    settings = identity.settings

    def redirect_uri(provider: str) -> str:
        return f'{settings.public_url}/api/v1/auth/callback/{provider}'

    def configured(provider: str):
        if not settings.oauth or provider not in settings.providers or provider not in PROVIDERS:
            raise HTTPException(404, 'unknown sign-in provider')
        return PROVIDERS[provider], settings.providers[provider]

    @router.get('/providers')
    def providers():
        return {'mode': settings.mode,
                'providers': [{'name': name, 'label': PROVIDERS[name].label} for name in settings.providers if name in PROVIDERS]}

    @router.get('/me')
    def me(request: Request):
        if not settings.oauth:
            return {'mode': settings.mode, 'user': None}
        user = identity.user_of(request)
        if user is None:
            raise HTTPException(401, 'sign in required')
        return {'mode': settings.mode, 'user': {'name': user.name, 'email': user.email, 'provider': user.provider}}

    @router.get('/login/{provider}')
    def login(provider: str, next: str | None = None):
        spec, credentials = configured(provider)
        nonce = secrets.token_urlsafe(16)
        state = tokens.sign(settings.secret, STATE, json.dumps({'provider': provider, 'nonce': nonce, 'next': safe_next(next)}), STATE_TTL_S)
        response = RedirectResponse(spec.authorize(credentials.client_id, redirect_uri(provider), state), status_code=302)
        response.set_cookie(NONCE_COOKIE, nonce, max_age=STATE_TTL_S, httponly=True, samesite='lax', secure=settings.secure_cookie,
                            path='/api/v1/auth')
        return response

    @router.get('/callback/{provider}')
    async def callback(request: Request, provider: str, code: str | None = None, state: str | None = None):
        spec, credentials = configured(provider)
        payload = tokens.verify(settings.secret, STATE, state)
        claimed = json.loads(payload) if payload else None
        nonce = request.cookies.get(NONCE_COOKIE)
        if not code or not claimed or claimed.get('provider') != provider or not nonce or not secrets.compare_digest(nonce, str(claimed.get('nonce'))):
            raise HTTPException(400, 'sign-in expired or started elsewhere; start again')
        try:
            subject, email, name = await spec.identify(credentials.client_id, credentials.client_secret, redirect_uri(provider), code,
                                                       transport=transport)
        except ProviderError:
            raise HTTPException(502, 'the provider did not confirm who you are; start again') from None
        user = identity.store.sign_in(provider, subject, email, name)
        response = RedirectResponse(safe_next(claimed.get('next')), status_code=302)
        response.set_cookie(settings.cookie, identity.session_token(user), max_age=settings.session_days * 86400, httponly=True,
                            samesite='lax', secure=settings.secure_cookie, path='/')
        response.delete_cookie(NONCE_COOKIE, path='/api/v1/auth')
        return response

    @router.post('/logout', status_code=204)
    def logout():
        response = Response(status_code=204)
        response.delete_cookie(settings.cookie, path='/')
        return response

    return router
