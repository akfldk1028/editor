"""
Overlay zone resolver — matches Vworld zone names to overlay regulations.

Standard 21 용도지역 are handled by zoning_mapper. This module handles
all other zones (지구, 구역, 보호구역 등) via substring matching
against overlay_zones.json definitions.
"""

from backend.app.modules.design.generation import paths as _design_paths

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_DATA_PATH = _design_paths.package_root('land') / "data" / "overlay_zones.json"
_OVERLAY_DATA: dict | None = None


def _load_data() -> dict:
    global _OVERLAY_DATA
    if _OVERLAY_DATA is None:
        with open(_DATA_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        # Skip JSON comment keys
        _OVERLAY_DATA = {k: v for k, v in raw.items() if not k.startswith("__")}
    return _OVERLAY_DATA


# Standard 21 용도지역 keywords — skip these (zoning_mapper handles them)
_STANDARD_ZONE_KEYWORDS = (
    "주거지역", "상업지역", "공업지역", "녹지지역",
    "관리지역", "농림지역", "자연환경보전지역",
)


def _is_standard_zone(zone_name: str) -> bool:
    """Check if zone_name is a standard 21 용도지역."""
    return any(kw in zone_name for kw in _STANDARD_ZONE_KEYWORDS)


def resolve_overlays(zone_names: list[str]) -> list[dict]:
    """
    Match zone names against overlay zone definitions.

    Returns only zones with actual regulations (constraint != "none").
    Info-only matches (도로, 광장 등) are excluded from results
    but still count as "recognized" for unmatched filtering.

    Args:
        zone_names: raw zone names from Vworld getLandUseAttr

    Returns:
        list of overlay regulation dicts:
        [{name, raw_zone, category, constraint, values, article, description}]
    """
    data = _load_data()
    results = []

    for raw_zone in zone_names:
        if _is_standard_zone(raw_zone):
            continue

        # Longest key first to avoid short keys stealing long key matches
        for key, defn in sorted(data.items(), key=lambda x: -len(x[0])):
            if key not in raw_zone:
                continue

            # Skip info-only entries from regulation results
            if defn.get("constraint") == "none":
                break

            entry = {
                "name": key,
                "raw_zone": raw_zone,
                "category": defn.get("category", ""),
                "constraint": defn.get("constraint", ""),
                "article": defn.get("article", ""),
                "description": defn.get("description", ""),
                "values": {},
            }

            pattern = defn.get("pattern")
            extract_keys = defn.get("extract", [])
            if pattern and extract_keys:
                m = re.search(pattern, raw_zone)
                if m:
                    for i, ek in enumerate(extract_keys):
                        try:
                            entry["values"][ek] = int(m.group(i + 1))
                        except (IndexError, ValueError):
                            pass

            results.append(entry)
            break

    return results


def get_all_matched_zones(zone_names: list[str]) -> set[str]:
    """
    Return raw_zone names that matched ANY overlay definition (including info-only).
    Used to filter out recognized zones from the "미인식" list.
    """
    data = _load_data()
    matched = set()

    for raw_zone in zone_names:
        if _is_standard_zone(raw_zone):
            continue
        for key in sorted(data.keys(), key=lambda x: -len(x)):
            if key in raw_zone:
                matched.add(raw_zone)
                break

    return matched
