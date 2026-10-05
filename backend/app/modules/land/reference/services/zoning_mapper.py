"""
Zoning Mapper - maps zoning zone names to BCR/FAR limits.

Loads static data from data/zoning_limits.json.

When a parcel spans more than one 용도지역, the limits come from 국토계획법 제84조
and depend on how much of the parcel is in each - see `resolve_limits`. The rule
this used to apply, the strictest limit over the whole parcel, is not in the
statute: it read 의정부 4115011300106840001, a 제2종일반주거지역 parcel merely
저촉된 by 자연녹지지역, as green throughout, at 20% and 100% where the dominant
zone allows 60% and 250%.
"""

from backend.app.modules.design.generation import paths as _design_paths

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DATA_PATH = _design_paths.package_root('land') / "data" / "zoning_limits.json"
_OVERLAP_PATH = _design_paths.package_root('land') / "data" / "zone_overlap_rules.json"
_ZONES: dict[str, dict] = {}
_OVERLAP: dict = {}


def _load():
    global _ZONES
    if _ZONES:
        return
    try:
        with open(_DATA_PATH, encoding="utf-8") as f:
            data = json.load(f)
        _ZONES = {z["zone_name"]: z for z in data["zones"]}
        logger.info(f"Loaded {len(_ZONES)} zoning zones from {_DATA_PATH}")
    except Exception as e:
        logger.error(f"Failed to load zoning data: {e}")
        _ZONES = {}


def _load_overlap() -> dict:
    """The 제84조 rules, as data. A statute amendment edits the file, not this."""

    global _OVERLAP
    if _OVERLAP:
        return _OVERLAP
    try:
        with open(_OVERLAP_PATH, encoding="utf-8") as f:
            _OVERLAP = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load zone overlap rules: {e}")
        _OVERLAP = {}
    return _OVERLAP


def is_green_zone(zone: dict) -> bool:
    """제84조제3항 turns on whether a 녹지지역 is involved.

    Decided by the zone's own `category`, not by a list of names written here.
    A new 녹지 용도지역 would carry the category and need no edit.
    """

    category = (_load_overlap().get("green_zone") or {}).get("category")
    return bool(category) and zone.get("category") == category


def get_all_zones() -> list[dict]:
    """Return all zoning zone definitions."""
    _load()
    return list(_ZONES.values())


def lookup(zone_name: str) -> dict | None:
    """
    Look up a single zone by exact name. Returns None if not found.

    Only exact matches are accepted to avoid ambiguity
    (e.g. "일반주거" could match 제1종/제2종/제3종 with different limits).
    """
    _load()
    return _ZONES.get(zone_name)


def resolve_limits(zone_names: list[str], zone_areas: dict[str, float] | None = None) -> dict:
    """
    Given a list of zone names, compute the effective BCR/FAR limits.

    One zone is one zone. More than one is 국토계획법 제84조, and every branch of
    it is a question about area: the parcel's capacity is each part's area times
    that part's own limit. Pass `zone_areas` (m2 per zone name, from
    `zone_geometry.parcel_zone_split`) and that is what is computed.

    Both branches of 제84조 give the same capacity and differ in what governs the
    *other* restrictions:

      제84조제1항  smallest part at or under the 시행령 size - 건폐율 and 용적률
                  are area-weighted, and 그 밖의 건축 제한 follows the largest
                  part's zone.
      제84조제3항  a 녹지지역 is involved - 각각의 용도지역 규정을 각각 적용, so
                  every part keeps its own other-restrictions too.

    Weighting and applying-each agree on capacity because applying each part its
    own limit and totalling is sum(area_i x limit_i), which over the parcel area
    is the weighted mean. The branch is still reported, because a caller asking
    about height or setback needs to know which zone answers.

    Without `zone_areas` the split is unknown, and an unknown split cannot be
    guessed - the previous guess, the strictest limit, understated this parcel by
    a factor of 2.5. The zones are returned with `bcr_limit`/`far_limit` as None
    and `needs_zone_areas` set, so a caller can see it has to go and measure.

    Returns:
        {
            "bcr_limit": float | None,
            "far_limit": float | None,
            "zones": [{...}],
            "matched": int,
            "unmatched": [str],
            "overlap": {...}   # only when more than one zone matched
        }
    """
    _load()
    matched_zones = []
    unmatched = []

    for name in zone_names:
        zone = lookup(name)
        if zone:
            matched_zones.append(zone)
        else:
            unmatched.append(name)

    if not matched_zones:
        return {
            "bcr_limit": None,
            "far_limit": None,
            "zones": [],
            "matched": 0,
            "unmatched": unmatched,
        }

    if len(matched_zones) == 1:
        only = matched_zones[0]
        return {
            "bcr_limit": only["bcr_default"],
            "far_limit": only["far_default"],
            "zones": matched_zones,
            "matched": 1,
            "unmatched": unmatched,
        }

    return combine_limits(matched_zones, zone_areas or {}, unmatched=unmatched)


def combine_limits(
    zones: list[dict],
    areas: dict[str, float] | None = None,
    *,
    unmatched: list[str] | None = None,
) -> dict:
    """국토계획법 제84조, once the areas are known.

    Public because it has to be the only implementation. There were two - this
    one and `regulation_calculator._resolve_bcr_far` - and both took the
    strictest limit, so correcting one left the other answering the old way to
    every caller that went through it, which was most of them. It takes resolved
    zone dicts rather than names so that a 시군구 조례 override already applied by
    the caller survives instead of being looked up again from the national
    defaults.
    """

    unmatched = list(unmatched or ())
    areas = areas or {}
    if not zones:
        return {"bcr_limit": None, "far_limit": None, "zones": [],
                "matched": 0, "unmatched": unmatched}
    # One zone needs no split. 제84조 is about a parcel that spans more than one,
    # and asking for areas when there is nothing to divide would make every
    # ordinary parcel depend on a network call it does not need.
    if len(zones) == 1:
        only = zones[0]
        return {"bcr_limit": only["bcr_default"], "far_limit": only["far_default"],
                "zones": zones, "matched": 1, "unmatched": unmatched}

    rules = _load_overlap()
    known = {z["zone_name"]: float(areas.get(z["zone_name"], 0.0)) for z in zones}
    total = sum(known.values())

    if total <= 0.0:
        return {
            "bcr_limit": None,
            "far_limit": None,
            "zones": zones,
            "matched": len(zones),
            "unmatched": unmatched,
            "overlap": {
                "article": (rules.get("capacity_rule") or {}).get("article"),
                "needs_zone_areas": True,
                "reason": (
                    "대지가 둘 이상의 용도지역에 걸쳐 있어 제84조가 적용되며, "
                    "용도지역별 면적 없이는 건폐율·용적률을 산정할 수 없다"
                ),
            },
        }

    bcr = sum(z["bcr_default"] * known[z["zone_name"]] for z in zones) / total
    far = sum(z["far_default"] * known[z["zone_name"]] for z in zones) / total

    smallest = min(zones, key=lambda z: known[z["zone_name"]])
    threshold = float((rules.get("small_part_threshold") or {}).get("default_m2") or 0.0)
    green = [z for z in zones if is_green_zone(z)]
    # 제84조제3항's own carve-out: a green part that is both the smallest and
    # under the size falls back to 제1항 rather than splitting the parcel.
    green_is_minor = (
        bool(green)
        and is_green_zone(smallest)
        and known[smallest["zone_name"]] <= threshold
    )
    per_part = bool(green) and not green_is_minor
    branch = "when_each" if per_part else "when_weighted"
    other = (rules.get("other_restrictions_rule") or {}).get(branch) or {}

    largest = max(zones, key=lambda z: known[z["zone_name"]])
    return {
        "bcr_limit": round(bcr, 4),
        "far_limit": round(far, 4),
        "zones": zones,
        "matched": len(zones),
        "unmatched": unmatched,
        "overlap": {
            "article": (rules.get("capacity_rule") or {}).get("article"),
            "capacity_method": (rules.get("capacity_rule") or {}).get("method"),
            "branch": "제84조제3항" if per_part else "제84조제1항",
            "other_restrictions": {
                "source_zone": None if per_part else largest["zone_name"],
                "rule": other.get("source_zone"),
                "article": other.get("article"),
            },
            "areas_m2": {name: round(value, 2) for name, value in known.items()},
            "total_area_m2": round(total, 2),
            "smallest_part": {
                "zone_name": smallest["zone_name"],
                "area_m2": round(known[smallest["zone_name"]], 2),
                "threshold_m2": threshold,
                "threshold_article": (rules.get("small_part_threshold") or {}).get("article"),
                # Said out loud on every response that leans on it: this number
                # is not in the law corpus we search, so it has not been checked
                # against the statute the way the rest of this has.
                "threshold_verified_in_corpus": bool(
                    (rules.get("small_part_threshold") or {}).get("verified_in_corpus")
                ),
            },
            "needs_zone_areas": False,
        },
    }
