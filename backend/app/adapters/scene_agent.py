"""The one module that knows where SceneAgent is and how to ask it for the context.

SceneAgent (agents/SceneAgent) owns the 3D context: it asks SiteContext for the building footprints around a
point and gives each one a height (measured, estimated from storeys, or unknown). The world view draws them as
white masses, so it works with or without the VWorld 3D SDK. SceneAgent runs on its own server.
"""
from __future__ import annotations

import os

import httpx

from backend.app.core.agent_network import network_headers

SCENE_AGENT_URL_ENV = 'SCENE_AGENT_URL'
DEFAULT_URL = 'http://127.0.0.1:8310'


class SceneAgentError(RuntimeError):
    pass


def context_buildings(lat, lon, radius_m, **kw):
    """White masses: {status: ok, features, counts, record} or needs_evidence."""
    return _ask('/scene/context-buildings', lat, lon, radius_m, **kw)


def context_ground(lat, lon, radius_m, **kw):
    """Ground: parcels by 지목 class (road, paved, green, water, ...) and carriageways."""
    return _ask('/scene/context-ground', lat, lon, radius_m, **kw)


def _ask(path, lat, lon, radius_m, *, base_url=None, transport=None, timeout=180.0):
    base = (base_url or os.environ.get(SCENE_AGENT_URL_ENV) or DEFAULT_URL).rstrip('/')
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=5), transport=transport,
                          headers=network_headers(), follow_redirects=False) as client:
            response = client.post(base + path,
                                   json={'lat': float(lat), 'lon': float(lon), 'radius_m': float(radius_m)})
        payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise SceneAgentError(f'SceneAgent unreachable at {base}: {error}') from None
    if not isinstance(payload, dict) or payload.get('status') not in ('ok', 'needs_evidence'):
        reason = payload.get('error') if isinstance(payload, dict) else None
        raise SceneAgentError(f'SceneAgent gave no answer for {path}: {reason or response.status_code}')
    return payload
