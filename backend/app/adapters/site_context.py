"""The one module that knows where the Site Context Agent is and how to ask it for ground heights.

SiteContextAgent (agents/SiteContextAgent) holds the NGII-derived DEM mosaic and builds a tile
on demand for any parcel in Korea. It runs on its own server, so the datum engines here never
open its raster; they POST points to /site/ground-heights and get every height from the NGII
mosaic, or a refusal - never a partial list and never another provider's value.
"""
from __future__ import annotations

import math
import os

import httpx

from backend.app.core.agent_network import network_headers

SITE_CONTEXT_AGENT_URL_ENV = 'SITE_CONTEXT_AGENT_URL'
DEFAULT_URL = 'http://127.0.0.1:8304'
PROVIDER = 'sitecontext_ngii'


class SiteHeightsError(RuntimeError):
    pass


def ground_heights(points, *, base_url=None, transport=None, timeout=120.0):
    """Heights for (lat, lng) points, in order, and the dataset receipt Site returned."""
    base = (base_url or os.environ.get(SITE_CONTEXT_AGENT_URL_ENV) or DEFAULT_URL).rstrip('/')
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=5), transport=transport,
                          headers=network_headers(), follow_redirects=False) as client:
            response = client.post(base + '/site/ground-heights',
                                   json={'points': [[float(lat), float(lng)] for lat, lng in points]})
        payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise SiteHeightsError(f'Site Context Agent unreachable at {base}: {error}') from None
    if not isinstance(payload, dict) or payload.get('status') != 'ok':
        reason = payload.get('reason') or payload.get('error') if isinstance(payload, dict) else None
        raise SiteHeightsError(f'Site Context Agent gave no ground heights: {reason or response.status_code}')
    heights = payload.get('heights')
    if (payload.get('source') != PROVIDER or not isinstance(heights, list) or len(heights) != len(points)
            or not all(type(h) in (int, float) and math.isfinite(h) and -500 <= h <= 9000 for h in heights)):
        raise SiteHeightsError('Site Context Agent returned missing or invalid heights')
    return [float(h) for h in heights], payload.get('dataset')
