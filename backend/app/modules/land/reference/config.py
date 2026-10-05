"""
Centralized configuration for the land app.

All env vars, URLs, timeouts, and shared httpx clients live here.
Services import from this module instead of reading env vars independently.
"""

import atexit
import os

import httpx

# ── Env vars ──────────────────────────────────────────
VWORLD_API_KEY: str = os.getenv("VWORLD_API_KEY", "")
LAW_BACKEND_URL: str = os.getenv("LAW_BACKEND_URL", "").strip()
AG_LIGHT_URL: str = os.getenv("AG_LIGHT_URL", "").strip()

# ── LLM Extraction (법조문 → 규제 수치 동적 추출) ────
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
LLM_EXTRACTION_ENABLED: bool = os.getenv("LLM_EXTRACTION_ENABLED", "true").lower() == "true"
LLM_EXTRACTION_MODEL: str = os.getenv("LLM_EXTRACTION_MODEL", "gpt-4o-mini")
LLM_EXTRACTION_TIMEOUT: float = 15.0

# ── Ordinance Override ────────────────────────────────
ORDINANCE_DIR: str = os.path.join(os.path.dirname(__file__), "data", "ordinance_overrides")

# ── Vworld URLs ───────────────────────────────────────
VWORLD_GEOCODE_URL = "https://api.vworld.kr/req/address"
VWORLD_DATA_URL = "https://api.vworld.kr/req/data"
VWORLD_DATA_BASE = "https://api.vworld.kr/ned/data"

# ── Datum Elevation (§119, §86) ───────────────────────
# Vworld 표고 API 없음 (2019 3D Open API 폐쇄, 2026-05-04 직접 호출 재검증 확정).
# Provider:
#   - "open_meteo" (default): Copernicus GLO-90 90m DEM, 무료 외부 REST, 도시 ~11m 오차
#   - "ngii_lidar_1m" (Phase 3-α): NGII 1m LiDAR DEM self-host (opentopodata Docker),
#     도시 ±10cm, 미커버시 Open-Meteo 자동 폴백
OPEN_METEO_URL = "https://api.open-meteo.com/v1/elevation"
NGII_LIDAR_URL: str = os.getenv("NGII_LIDAR_URL", "http://localhost:5000")
# Step 4 — NGII 연속수치지형도(SHP) → 자체 DEM raster (.tif).
# tools/ngii_contour_to_dem.py로 생성. provider=ngii_local_dem 일 때 사용.
NGII_DEM_LOCAL_PATH: str = os.getenv("NGII_DEM_LOCAL_PATH", "")
ELEVATION_PROVIDER: str = os.getenv("ELEVATION_PROVIDER", "open_meteo")

# Datum 알고리즘 정확도 (Step 1 — 90m DEM 노이즈 흡수, edge sub-sample).
# 둘 다 default true. 기존 회귀 테스트는 flag false로 monkey patch (단일 중점 동작 유지).
DATUM_EDGE_SUBSAMPLE: bool = (
    os.getenv("DATUM_EDGE_SUBSAMPLE", "true").lower() == "true"
)
DATUM_EDGE_SUBSAMPLE_THRESHOLD_M: float = float(
    os.getenv("DATUM_EDGE_SUBSAMPLE_THRESHOLD_M", "10.0")
)
DATUM_EDGE_SUBSAMPLE_STEP_M: float = float(
    os.getenv("DATUM_EDGE_SUBSAMPLE_STEP_M", "5.0")
)
DATUM_MEDIAN_FILTER: bool = (
    os.getenv("DATUM_MEDIAN_FILTER", "true").lower() == "true"
)
DATUM_MEDIAN_FILTER_WINDOW: int = int(
    os.getenv("DATUM_MEDIAN_FILTER_WINDOW", "3")
)

# Phase 2B opt-in flag — production 배포는 false로 시작.
# True면 setback_geometry → envelope에 §119 datum 평면을 절대 표고로 주입.
# False면 LOCKED SPEC 시각 결과 유지 (frontend는 terrain.getHeight() fallback).
ENABLE_DATUM_ELEVATION: bool = (
    os.getenv("ENABLE_DATUM_ELEVATION", "false").lower() == "true"
)

# ── Timeouts ──────────────────────────────────────────
VWORLD_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
LAW_TIMEOUT = httpx.Timeout(30.0, connect=5.0)
PROXY_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
ELEVATION_TIMEOUT = httpx.Timeout(5.0, connect=3.0)

# ── Shared httpx clients (singletons) ────────────────
vworld_client = httpx.Client(timeout=VWORLD_TIMEOUT)
proxy_client = httpx.Client(timeout=PROXY_TIMEOUT)
open_meteo_client = httpx.Client(timeout=ELEVATION_TIMEOUT)
ngii_client = httpx.Client(timeout=ELEVATION_TIMEOUT)


def _cleanup_clients():
    """Close httpx clients on process shutdown."""
    for c in (vworld_client, proxy_client, open_meteo_client, ngii_client):
        try:
            c.close()
        except Exception:
            pass


atexit.register(_cleanup_clients)
