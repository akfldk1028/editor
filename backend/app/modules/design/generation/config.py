"""
Centralized configuration for the design app.

All env vars, timeouts, and shared clients live here.
"""

import atexit
import os

import httpx

# ── Env vars ─────────────────────────────────────────
VWORLD_API_KEY: str = os.getenv("VWORLD_API_KEY", "")
MASS_BRAIN_URL: str = os.getenv("MASS_BRAIN_URL", "http://127.0.0.1:8210")

# ── Timeouts ─────────────────────────────────────────
VWORLD_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
MASS_BRAIN_TIMEOUT = httpx.Timeout(3.0, connect=0.5)

# ── Shared httpx clients ─────────────────────────────
# Note: land/ services are imported directly (same Django process).
# Only external APIs need httpx clients.
vworld_client = httpx.Client(timeout=VWORLD_TIMEOUT)
mass_brain_client = httpx.Client(base_url=MASS_BRAIN_URL, timeout=MASS_BRAIN_TIMEOUT)


def _cleanup_clients():
    try:
        vworld_client.close()
    except Exception:
        pass
    try:
        mass_brain_client.close()
    except Exception:
        pass


atexit.register(_cleanup_clients)
