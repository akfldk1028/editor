"""How much of a parcel lies in each 용도지역.

`getLandUseAttr` names the designations a parcel touches and says whether it is
포함 / 저촉 / 접함, but it never says how much. Every branch of 국토계획법 제84조
needs the how-much: the capacity of a parcel spanning two zones is the area of
each part times that part's own limit, and without the split there is nothing to
multiply. Lacking it, `zoning_mapper` had been taking the strictest limit over
the whole parcel, which is not a rule the statute contains - on 의정부
4115011300106840001 that read a 제2종일반주거지역 parcel merely 저촉된 by
자연녹지지역 as if all 2499 m2 of it were green, at 20% and 100% instead of 60%
and 250%.

So the split is measured, from the same Vworld WFS the parcel boundary already
comes from. `LT_C_UQ111` is the 용도지역 layer; each feature carries `uname` and
the year it was designated.

Nothing here decides anything legal. It returns areas. What the areas mean is
`zoning_mapper`'s job, and which article applies is written in
`land/data/zone_overlap_rules.json` rather than in either.
"""

from __future__ import annotations

from backend.app.modules.design.generation import paths as _design_paths

import datetime
import hashlib
import json
import logging
import os
import pathlib
from typing import Any, Iterable

import httpx
from shapely.geometry import Polygon, shape
from shapely.ops import unary_union

logger = logging.getLogger(__name__)


VWORLD_ZONE_LAYER = "LT_C_UQ111"
_VWORLD_DATA_URL = "https://api.vworld.kr/req/data"
# Vworld refuses requests from non-Korean addresses without one.
_REFERER = "http://localhost"
# The layer is queried by bounding box, so the box is grown a little to be sure
# a zone edge running along the parcel boundary is returned whole rather than
# clipped by the query itself.
_BBOX_PAD_DEGREES = 0.0008
_MAX_FEATURES = 300


def _api_key() -> str | None:
    return os.environ.get("VWORLD_API_KEY")


def fetch_zone_features(
    parcel_wgs84: Polygon, *, timeout: float = 20.0
) -> list[dict[str, Any]]:
    """Every 용도지역 polygon near the parcel, unfiltered.

    Near, not over: the layer is queried by bounding box, so neighbours across
    the street come back too. Discarding them is `zone_areas` job, and it does
    it by intersecting rather than by trusting the query.
    """

    key = _api_key()
    if not key:
        raise ZoneGeometryUnavailable("VWORLD_API_KEY is not set")

    min_x, min_y, max_x, max_y = parcel_wgs84.bounds
    pad = _BBOX_PAD_DEGREES
    params = {
        "key": key,
        "service": "data",
        "request": "GetFeature",
        "data": VWORLD_ZONE_LAYER,
        "geomFilter": f"BOX({min_x - pad},{min_y - pad},{max_x + pad},{max_y + pad})",
        "format": "json",
        "crs": "EPSG:4326",
        "size": _MAX_FEATURES,
        "domain": _REFERER,
    }
    try:
        response = httpx.get(
            _VWORLD_DATA_URL, params=params, headers={"Referer": _REFERER}, timeout=timeout
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        # The zone split of a fixed parcel is a constant, and this was the one
        # Vworld call with nothing behind it: a single read timeout raised
        # LegalSiteUnavailable and killed a whole massing run, because 제84조
        # needs the areas. Land use next door already keeps its last real
        # answer for exactly this; the split now does the same. Cached means
        # cached - it says so in the log, and it is never a substitute for a
        # first fetch, so a parcel never measured still fails loudly.
        cached = _load_feature_cache(parcel_wgs84)
        if cached is not None:
            return cached
        raise ZoneGeometryUnavailable(f"Vworld {VWORLD_ZONE_LAYER} failed: {error}") from error

    body = payload.get("response") or {}
    if body.get("status") != "OK":
        raise ZoneGeometryUnavailable(
            f"Vworld {VWORLD_ZONE_LAYER} returned {body.get('status')}"
        )
    collection = (body.get("result") or {}).get("featureCollection") or {}
    features = list(collection.get("features") or ())
    if features:
        _store_feature_cache(parcel_wgs84, features)
    return features


ZONE_FEATURE_CACHE_DIR = (
    _design_paths.backend_root() / "runtime" / "vworld_zone_features"
)


def _feature_cache_path(parcel_wgs84: Polygon) -> pathlib.Path:
    """Keyed by the queried box, which is what the answer actually depends on."""

    box = ",".join(f"{value:.6f}" for value in parcel_wgs84.bounds)
    stamp = hashlib.sha256(f"{VWORLD_ZONE_LAYER}|{box}".encode("utf-8")).hexdigest()[:16]
    return ZONE_FEATURE_CACHE_DIR / f"{stamp}.json"


def _store_feature_cache(parcel_wgs84: Polygon, features: list) -> None:
    try:
        ZONE_FEATURE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _feature_cache_path(parcel_wgs84).write_text(
            json.dumps({"fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        "bounds": list(parcel_wgs84.bounds),
                        "layer": VWORLD_ZONE_LAYER,
                        "features": features}, ensure_ascii=False),
            encoding="utf-8")
    except OSError as error:
        logger.warning("Could not cache zone features: %s", error)


def _load_feature_cache(parcel_wgs84: Polygon) -> list | None:
    path = _feature_cache_path(parcel_wgs84)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        logger.warning("Unreadable zone feature cache: %s", error)
        return None
    features = payload.get("features")
    if not isinstance(features, list) or not features:
        return None
    logger.warning("Vworld unavailable; using the cached real %s features fetched at %s",
                   VWORLD_ZONE_LAYER, payload.get("fetched_at"))
    return features


class ZoneGeometryUnavailable(RuntimeError):
    """The split could not be measured, so no capacity may be derived from it."""


def zone_areas(
    parcel_wgs84: Polygon,
    features: Iterable[dict[str, Any]],
    *,
    to_utm,
    minimum_share: float = 0.001,
) -> dict[str, float]:
    """Square metres of the parcel lying in each named 용도지역.

    Three things this does that a naive loop does not.

    It intersects. The layer is fetched by bounding box, so a zone that merely
    abuts the parcel arrives looking exactly like one that covers it, and only
    the intersection tells them apart - which is the same distinction
    `getLandUseAttr`'s 접함 makes, arrived at independently.

    It unions per name before measuring. The same 용도지역 comes back as several
    features, designated in different years; added up they would count the
    overlap twice and report more zone than there is parcel.

    It measures in metres. Areas in degrees are not areas, and they are wrong by
    a different factor at every latitude, which is exactly the kind of error that
    looks plausible on one parcel and is nonsense on the next.
    """

    parcel = to_utm(parcel_wgs84)
    total = float(parcel.area)
    if total <= 0.0:
        return {}

    grouped: dict[str, list[Polygon]] = {}
    for feature in features:
        name = ((feature.get("properties") or {}).get("uname") or "").strip()
        geometry = feature.get("geometry")
        if not name or not geometry:
            continue
        try:
            piece = to_utm(shape(geometry))
        except Exception:  # a malformed feature is not a reason to lose the rest
            logger.warning("zone_geometry: unreadable feature for %s", name)
            continue
        if piece.is_empty:
            continue
        overlap = piece.intersection(parcel)
        if overlap.is_empty or float(overlap.area) <= 0.0:
            continue
        grouped.setdefault(name, []).append(overlap)

    areas: dict[str, float] = {}
    for name, parts in grouped.items():
        merged = parts[0] if len(parts) == 1 else unary_union(parts)
        area = float(merged.area)
        # A hair of overlap is a boundary drawn at a different scale, not a part
        # of the parcel that carries its own building limits.
        if area / total >= minimum_share:
            areas[name] = area
    return areas


def parcel_zone_split(parcel_wgs84: Polygon, *, to_utm, timeout: float = 20.0) -> dict[str, float]:
    """The one call a caller needs: parcel in, 용도지역 areas in m2 out."""

    return zone_areas(
        parcel_wgs84, fetch_zone_features(parcel_wgs84, timeout=timeout), to_utm=to_utm
    )


__all__ = [
    "VWORLD_ZONE_LAYER",
    "ZoneGeometryUnavailable",
    "fetch_zone_features",
    "parcel_zone_split",
    "zone_areas",
]
