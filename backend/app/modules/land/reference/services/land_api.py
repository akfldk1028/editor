"""
Land API - fetches land info from Vworld public data APIs.

Phase 3: Live API using 3 Vworld Data APIs (same key as pnu_resolver).
Falls back to stub if VWORLD_API_KEY is not configured.

APIs:
- getLandUseAttr: 토지이용계획 → 용도지역 names
- ladfrlList: 토지임야대장 → 면적(m2), 지목
- getIndvdLandPriceAttr: 개별공시지가 → 원/m2
"""

from backend.app.modules.design.generation import paths as _design_paths

import datetime
import json
import logging
import pathlib

import httpx

from backend.app.modules.land.reference import config

logger = logging.getLogger(__name__)


def get_land_use_info(pnu: str) -> dict:
    """
    Fetch land use info from Vworld Data APIs.

    Calls 3 APIs independently; partial failure is OK (min 1 success).
    Falls back to stub if VWORLD_API_KEY not configured.

    Args:
        pnu: 19-digit PNU code

    Returns:
        {
            "success": bool,
            "pnu": str,
            "zones": [str],
            "land_area_m2": float | None,
            "official_land_price": int | None,
            "land_use_situation": str,
            "source": "stub" | "vworld"
        }
    """
    if not config.VWORLD_API_KEY:
        logger.info(f"land_api.get_land_use_info(pnu={pnu}) - stub mode (no API key)")
        return _stub_result(pnu)

    logger.info(f"land_api.get_land_use_info(pnu={pnu}) - calling Vworld APIs")

    zones = []
    land_area_m2 = None
    land_use_situation = ""
    official_land_price = None
    errors = []

    # 1. 토지이용계획 → 용도지역
    land_use = _fetch_land_use_attr(pnu)
    if land_use["success"]:
        zones = land_use["zones"]
    else:
        errors.append(land_use["error"])

    # 2. 토지임야대장 → 면적, 지목
    ladfrl = _fetch_ladfrl(pnu)
    if ladfrl["success"]:
        land_area_m2 = ladfrl["land_area_m2"]
        land_use_situation = ladfrl["land_use_situation"]
    else:
        errors.append(ladfrl["error"])

    # 3. 개별공시지가
    price = _fetch_land_price(pnu)
    if price["success"]:
        official_land_price = price["official_land_price"]
    else:
        errors.append(price["error"])

    any_success = land_use["success"] or ladfrl["success"] or price["success"]

    result = {
        "success": any_success,
        "pnu": pnu,
        "zones": zones,
        "land_area_m2": land_area_m2,
        "official_land_price": official_land_price,
        "land_use_situation": land_use_situation,
        "source": "vworld" if any_success else "stub",
    }
    if errors:
        result["errors"] = errors
    if not any_success:
        # A parcel's zoning does not change, but Vworld goes down for hours at
        # a time. The cache holds a previous *real* response, never a
        # synthesized one, and is read only when every live call has failed -
        # so live data stays authoritative and the substitution is logged.
        cached = _load_land_use_cache(pnu)
        if cached is not None:
            return cached
        result["message"] = "All Vworld API calls failed. " + "; ".join(errors)
    elif land_use["success"]:
        _store_land_use_cache(pnu, result)

    return result


LAND_USE_CACHE_DIR = (
    _design_paths.backend_root()
    / "runtime"
    / "vworld_land_use"
)


def _land_use_cache_path(pnu: str) -> pathlib.Path:
    return LAND_USE_CACHE_DIR / f"{pnu}.json"


def _store_land_use_cache(pnu: str, result: dict) -> None:
    try:
        LAND_USE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _land_use_cache_path(pnu).write_text(
            json.dumps(
                {
                    "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "result": result,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError as error:
        logger.warning("Could not cache land use for PNU %s: %s", pnu, error)


def _load_land_use_cache(pnu: str) -> dict | None:
    path = _land_use_cache_path(pnu)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        logger.warning("Unreadable land use cache for PNU %s: %s", pnu, error)
        return None
    cached = payload.get("result")
    if not isinstance(cached, dict) or not cached.get("zones"):
        return None
    logger.warning(
        "Vworld unavailable; using the cached real land use for PNU %s "
        "fetched at %s",
        pnu,
        payload.get("fetched_at"),
    )
    return dict(cached)


def _fetch_land_use_attr(pnu: str) -> dict:
    """토지이용계획 API → 용도지역명 목록.

    Response: landUses.field[].prposAreaDstrcCodeNm
    Filters to cnflcAtNm in ("포함","저촉") — parcel is IN or OVERLAPS the zone.
    Excludes "접함" (merely adjacent, zone does not apply to this parcel).
    Returns all zone/district names; downstream zoning_mapper filters to known 21 types.
    """
    params = {
        "key": config.VWORLD_API_KEY,
        "pnu": pnu,
        "format": "json",
        "numOfRows": "50",
        "pageNo": "1",
    }
    try:
        resp = config.vworld_client.get(f"{config.VWORLD_DATA_BASE}/getLandUseAttr", params=params)
        resp.raise_for_status()
        data = resp.json()

        # Success: data["landUses"]["field"][...]
        # No data: data["response"]["totalCount"] == "0"
        land_uses = data.get("landUses", {})
        items = land_uses.get("field", [])
        if isinstance(items, dict):
            items = [items]

        if not items:
            return {"success": False, "error": "getLandUseAttr: no data for this PNU", "zones": []}

        zones = []
        seen = set()
        for item in items:
            # Include zones the parcel is IN or OVERLAPS.
            # 포함(1)=fully inside, 저촉(2)=partially overlapping → both applicable.
            # 접함(3)=adjacent only → skip (zone does not apply to this parcel).
            # None = field missing → include as defensive default.
            if item.get("cnflcAtNm") not in ("포함", "저촉", None):
                continue
            name = item.get("prposAreaDstrcCodeNm", "").strip()
            if not name:
                continue
            normalized = _normalize_zone_name(name)
            if normalized not in seen:
                zones.append(normalized)
                seen.add(normalized)

        return {"success": True, "zones": zones}

    except httpx.ConnectError:
        logger.error("Vworld getLandUseAttr API unreachable")
        return {"success": False, "error": "getLandUseAttr: connection failed", "zones": []}
    except Exception as e:
        logger.error(f"getLandUseAttr failed: {e}")
        return {"success": False, "error": f"getLandUseAttr: {e}", "zones": []}


def _fetch_ladfrl(pnu: str) -> dict:
    """토지임야대장 API → 면적(m2), 지목.

    Response: ladfrlVOList.ladfrlVOList[].lndpclAr / lndcgrCodeNm
    """
    params = {
        "key": config.VWORLD_API_KEY,
        "pnu": pnu,
        "format": "json",
        "numOfRows": "1",
        "pageNo": "1",
    }
    try:
        resp = config.vworld_client.get(f"{config.VWORLD_DATA_BASE}/ladfrlList", params=params)
        resp.raise_for_status()
        data = resp.json()

        wrapper = data.get("ladfrlVOList", {})
        items = wrapper.get("ladfrlVOList", [])
        if isinstance(items, dict):
            items = [items]

        if not items:
            return {
                "success": False,
                "error": "ladfrlList: no data for this PNU",
                "land_area_m2": None,
                "land_use_situation": "",
            }

        item = items[0]
        area_str = item.get("lndpclAr", "")
        area = float(area_str) if area_str else None
        jimok = item.get("lndcgrCodeNm", "").strip()

        return {"success": True, "land_area_m2": area, "land_use_situation": jimok}

    except httpx.ConnectError:
        logger.error("Vworld ladfrlList API unreachable")
        return {
            "success": False,
            "error": "ladfrlList: connection failed",
            "land_area_m2": None,
            "land_use_situation": "",
        }
    except Exception as e:
        logger.error(f"ladfrlList failed: {e}")
        return {
            "success": False,
            "error": f"ladfrlList: {e}",
            "land_area_m2": None,
            "land_use_situation": "",
        }


def _fetch_land_price(pnu: str) -> dict:
    """개별공시지가 API → 원/m2 (latest year).

    Response: indvdLandPrices.field[].pblntfPclnd
    Uses stdrYear=current year, falls back to previous years.
    """
    current_year = datetime.date.today().year
    years_to_try = [str(current_year), str(current_year - 1)]

    for year in years_to_try:
        result = _fetch_land_price_for_year(pnu, year)
        if result["success"]:
            return result

    return {"success": False, "error": "getIndvdLandPriceAttr: no data", "official_land_price": None}


def _fetch_land_price_for_year(pnu: str, stdr_year: str) -> dict:
    """Fetch price for a specific year."""
    params = {
        "key": config.VWORLD_API_KEY,
        "pnu": pnu,
        "format": "json",
        "numOfRows": "1",
        "pageNo": "1",
        "stdrYear": stdr_year,
    }
    try:
        resp = config.vworld_client.get(f"{config.VWORLD_DATA_BASE}/getIndvdLandPriceAttr", params=params)
        resp.raise_for_status()
        data = resp.json()

        prices = data.get("indvdLandPrices", {})
        items = prices.get("field", [])
        if isinstance(items, dict):
            items = [items]

        if not items:
            return {"success": False, "error": f"no price data for {stdr_year}", "official_land_price": None}

        price_str = items[0].get("pblntfPclnd", "")
        price = int(float(price_str)) if price_str else None

        return {"success": True, "official_land_price": price}

    except httpx.ConnectError:
        logger.error("Vworld getIndvdLandPriceAttr API unreachable")
        return {"success": False, "error": "getIndvdLandPriceAttr: connection failed", "official_land_price": None}
    except Exception as e:
        logger.error(f"getIndvdLandPriceAttr failed: {e}")
        return {"success": False, "error": f"getIndvdLandPriceAttr: {e}", "official_land_price": None}


def _normalize_zone_name(name: str) -> str:
    """Normalize zone name to match zoning_limits.json format.

    Vworld may return short names (e.g. '일반상업') without '지역' suffix.
    Our data uses full names like '일반상업지역'.
    """
    if name.endswith("지역") or name.endswith("지구") or name.endswith("구역") or name.endswith("권역"):
        return name
    # Try appending '지역'
    from backend.app.modules.land.reference.services import zoning_mapper  # lazy: avoid import cycle if mapper ever imports land_api
    candidate = name + "지역"
    if zoning_mapper.lookup(candidate) is not None:
        return candidate
    return name


def _stub_result(pnu: str) -> dict:
    """Return stub result when API key is not configured."""
    return {
        "success": True,
        "pnu": pnu,
        "zones": [],
        "land_area_m2": None,
        "official_land_price": None,
        "land_use_situation": "",
        "source": "stub",
        "message": "VWORLD_API_KEY not configured. "
                   "Provide zones manually via 'zones' field in request body.",
    }
