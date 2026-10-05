"""
PNU Resolver - validates/parses 19-digit PNU codes and resolves addresses via Vworld API.

PNU structure (19 digits):
  [시도2][시군구3][읍면동3][리2][토지구분1][본번4][부번4] 토지구분: 1=대, 2=임야

Vworld Geocoding:
  1) 주소 → 좌표 (api.vworld.kr/req/address)
  2) 좌표 → 지번주소 (api.vworld.kr/req/address reverse)
  Requires VWORLD_API_KEY env var (https://www.vworld.kr 에서 발급)
"""

import logging
import re

import httpx

from backend.app.modules.land.reference import config

logger = logging.getLogger(__name__)

_PNU_PATTERN = re.compile(r"^\d{19}$")


def validate_pnu(pnu: str) -> bool:
    """Check if a string is a valid 19-digit PNU code."""
    return bool(_PNU_PATTERN.match(pnu))


def parse_pnu(pnu: str) -> dict | None:
    """
    Parse a 19-digit PNU into components.

    Returns None if invalid, otherwise:
    {
        "pnu": str,
        "sido": str (2),
        "sigungu": str (3),
        "eupmyeondong": str (3),
        "ri": str (2),
        "land_type": str (1) - "1"=대, "2"=임야,
        "main_number": str (4),
        "sub_number": str (4)
    }
    """
    if not validate_pnu(pnu):
        return None

    return {
        "pnu": pnu,
        "sido": pnu[0:2],
        "sigungu": pnu[2:5],
        "eupmyeondong": pnu[5:8],
        "ri": pnu[8:10],
        "land_type": pnu[10:11],
        "main_number": pnu[11:15],
        "sub_number": pnu[15:19],
        "land_type_name": "대" if pnu[10] == "1" else "임야" if pnu[10] == "2" else "기타",
    }


def resolve_address(address: str) -> dict:
    """
    Resolve a Korean address to PNU via Vworld Geocoding API.

    Flow: 주소 → Vworld geocode → 좌표 + 법정동코드 + 지번

    Requires VWORLD_API_KEY env var.

    Returns:
        {
            "success": bool,
            "address": str,
            "pnu": str | None,
            "coordinates": {"x": float, "y": float} | None,
            "error": str (on failure)
        }
    """
    if not config.VWORLD_API_KEY:
        return {
            "success": False,
            "error": "VWORLD_API_KEY not configured. "
                     "Get a key at https://www.vworld.kr and set VWORLD_API_KEY env var.",
            "address": address,
            "pnu": None,
        }

    # Step 1: Geocode address (try PARCEL type for 지번, fallback to ROAD)
    for addr_type in ("PARCEL", "ROAD"):
        result = _vworld_geocode(address, addr_type)
        if result and result.get("response", {}).get("status") == "OK":
            return _parse_geocode_result(result, address)

    return {
        "success": False,
        "error": f"Vworld geocoding failed: no results for '{address}'",
        "address": address,
        "pnu": None,
    }


def _vworld_geocode(address: str, addr_type: str) -> dict | None:
    """Call Vworld geocoding API."""
    params = {
        "service": "address",
        "request": "getCoord",
        "key": config.VWORLD_API_KEY,
        "address": address,
        "type": addr_type,
        "format": "json",
        "crs": "EPSG:4326",
        "refine": "true",
    }

    try:
        resp = config.vworld_client.get(config.VWORLD_GEOCODE_URL, params=params)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError:
        logger.error("Vworld API unreachable")
        return None
    except Exception as e:
        logger.error(f"Vworld geocode failed: {e}")
        return None


def _parse_geocode_result(data: dict, original_address: str) -> dict:
    """Parse Vworld geocode response into our format."""
    try:
        response = data["response"]
        if response.get("status") != "OK":
            return {
                "success": False,
                "error": f"Vworld status: {response.get('status')}",
                "address": original_address,
                "pnu": None,
            }

        result = response["result"]
        point = result["point"]
        x = float(point["x"])
        y = float(point["y"])

        # Extract PNU from refined.structure.level4LC (19-digit code)
        pnu = None
        refined = response.get("refined", {})
        structure = refined.get("structure", {})
        level4lc = structure.get("level4LC", "")
        if validate_pnu(level4lc):
            pnu = level4lc

        geocoded_text = refined.get("text", "")

        return {
            "success": True,
            "address": original_address,
            "pnu": pnu,
            "coordinates": {"x": x, "y": y},
            "geocoded_address": geocoded_text,
        }

    except (KeyError, TypeError, ValueError) as e:
        return {
            "success": False,
            "error": f"Failed to parse Vworld response: {e}",
            "address": original_address,
            "pnu": None,
        }


# ---------------------------------------------------------------------------
# Reverse geocode: 좌표 → PNU + 필지 polygon (Vworld 2D Data API)
# ---------------------------------------------------------------------------

def reverse_geocode(x: float, y: float) -> dict:
    """
    Reverse-geocode a coordinate to PNU + full address + parcel polygon.

    Two API calls:
      1) Vworld 2D Data API (LP_PA_CBND_BUBUN) → PNU + geometry
      2) Vworld Address API (getAddress) → 전체 지번주소

    Args:
        x: longitude (EPSG:4326)
        y: latitude (EPSG:4326)

    Returns:
        {
            "success": bool,
            "pnu": str | None,
            "address": str | None (전체 주소: "서울특별시 강남구 역삼동 677"),
            "geometry": GeoJSON polygon | None,
            "coordinates": {"x": float, "y": float},
            "error": str (on failure)
        }
    """
    if not config.VWORLD_API_KEY:
        return {
            "success": False,
            "error": "VWORLD_API_KEY not configured",
            "pnu": None,
            "address": None,
            "geometry": None,
            "coordinates": {"x": x, "y": y},
        }

    # ── 1. Data API — PNU + 필지 geometry ──
    params = {
        "key": config.VWORLD_API_KEY,
        "service": "data",
        "request": "GetFeature",
        "data": "LP_PA_CBND_BUBUN",
        "geomFilter": f"POINT({x} {y})",
        "format": "json",
        "crs": "EPSG:4326",
        "size": "1",
    }

    try:
        resp = config.vworld_client.get(config.VWORLD_DATA_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
    except httpx.ConnectError:
        logger.error("Vworld Data API unreachable")
        return {
            "success": False,
            "error": "Vworld Data API unreachable",
            "pnu": None, "address": None, "geometry": None,
            "coordinates": {"x": x, "y": y},
        }
    except Exception as e:
        logger.error(f"Vworld Data API failed: {e}")
        return {
            "success": False,
            "error": f"Vworld Data API failed: {e}",
            "pnu": None, "address": None, "geometry": None,
            "coordinates": {"x": x, "y": y},
        }

    result = _parse_data_api_result(data, x, y)

    # ── 2. Address API — 전체 지번주소 보강 ──
    if result["success"]:
        full_addr = _vworld_reverse_address(x, y)
        if full_addr:
            result["address"] = full_addr

    return result


def fetch_parcel_geometry(pnu: str) -> dict:
    """
    Fetch parcel polygon by PNU from Vworld cadastral boundary layer.

    This is the address/PNU-search counterpart to reverse_geocode(). The map
    click flow already has geometry from POINT lookup, but direct PNU/address
    analysis needs to resolve the polygon before setback/datum lines can be
    drawn.
    """
    if not config.VWORLD_API_KEY:
        return {"success": False, "geometry": None, "error": "VWORLD_API_KEY not configured"}

    params = {
        "key": config.VWORLD_API_KEY,
        "service": "data",
        "request": "GetFeature",
        "data": "LP_PA_CBND_BUBUN",
        "attrFilter": f"pnu:=:{pnu}",
        "format": "json",
        "crs": "EPSG:4326",
        "size": "1",
    }

    try:
        resp = config.vworld_client.get(config.VWORLD_DATA_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("Vworld parcel geometry failed for PNU %s: %s", pnu, e)
        return {"success": False, "geometry": None, "error": f"ParcelGeometry: {e}"}

    try:
        features = (
            data.get("response", {})
            .get("result", {})
            .get("featureCollection", {})
            .get("features", [])
        )
        if not features:
            return {"success": False, "geometry": None, "error": "ParcelGeometry: no features"}

        geom = features[0].get("geometry")
        if not geom:
            return {"success": False, "geometry": None, "error": "ParcelGeometry: no geometry"}

        if geom.get("type") == "MultiPolygon":
            coords = geom.get("coordinates") or []
            if coords:
                largest = max(coords, key=lambda polygon: _ring_area(polygon[0]) if polygon else 0)
                geom = {"type": "Polygon", "coordinates": largest}

        return {"success": True, "geometry": geom}
    except (AttributeError, KeyError, TypeError, ValueError) as e:
        return {"success": False, "geometry": None, "error": f"ParcelGeometry parse: {e}"}


def _ring_area(ring: list[list[float]] | None) -> float:
    if not ring or len(ring) < 3:
        return 0.0
    total = 0.0
    for idx, point in enumerate(ring):
        nxt = ring[(idx + 1) % len(ring)]
        total += float(point[0]) * float(nxt[1]) - float(nxt[0]) * float(point[1])
    return abs(total) / 2.0


def _vworld_reverse_address(x: float, y: float) -> str | None:
    """
    Vworld Address API 역지오코딩 — 좌표 → 전체 지번주소.

    Returns: "서울특별시 강남구 역삼동 677" 형태, 실패 시 None.
    """
    params = {
        "service": "address",
        "request": "getAddress",
        "key": config.VWORLD_API_KEY,
        "point": f"{x},{y}",
        "type": "PARCEL",
        "format": "json",
        "crs": "EPSG:4326",
    }
    try:
        resp = config.vworld_client.get(config.VWORLD_GEOCODE_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
        response = data.get("response", {})
        if response.get("status") != "OK":
            return None
        results = response.get("result", [])
        if isinstance(results, list) and results:
            return results[0].get("text")
        if isinstance(results, dict):
            return results.get("text")
        return None
    except Exception as e:
        logger.debug(f"Reverse address failed: {e}")
        return None


def _parse_data_api_result(data: dict, x: float, y: float) -> dict:
    """Parse Vworld 2D Data API response."""
    try:
        resp = data.get("response", {})
        status = resp.get("status", "")
        if status != "OK":
            return {
                "success": False,
                "error": f"Vworld status: {status} - {resp.get('error', {}).get('text', 'No result')}",
                "pnu": None, "address": None, "geometry": None,
                "coordinates": {"x": x, "y": y},
            }

        result = resp.get("result", {})
        features = result.get("featureCollection", {}).get("features", [])
        if not features:
            return {
                "success": False,
                "error": "No parcel found at this location",
                "pnu": None, "address": None, "geometry": None,
                "coordinates": {"x": x, "y": y},
            }

        feat = features[0]
        props = feat.get("properties", {})
        geom = feat.get("geometry")

        pnu = props.get("pnu", "")
        addr = props.get("jibun", "") or props.get("addr", "")

        return {
            "success": True,
            "pnu": pnu or None,
            "address": addr,
            "geometry": geom,
            "coordinates": {"x": x, "y": y},
        }
    except (KeyError, TypeError, ValueError) as e:
        return {
            "success": False,
            "error": f"Failed to parse Data API response: {e}",
            "pnu": None, "address": None, "geometry": None,
            "coordinates": {"x": x, "y": y},
        }
