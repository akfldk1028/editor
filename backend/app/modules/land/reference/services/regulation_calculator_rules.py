"""Zone-rule resolvers of `regulation_calculator.calculate_all` (split out of
regulation_calculator.py).

BCR/FAR, height, sunlight, corner cutoff, road diagonal, building line,
adjacent setback, landscaping and building designation.
"""

import logging

from backend.app.modules.land.reference import config
from backend.app.modules.land.reference.services import zoning_mapper

# Same logger name as before the split, so log routing does not change.
logger = logging.getLogger(__name__.rpartition(".")[0] + ".regulation_calculator")


def _empty_result() -> dict:
    return {
        "bcr_pct": None, "bcr_article": "",
        "far_pct": None, "far_article": "",
        "national_bcr_ceiling_pct": None, "national_far_ceiling_pct": None,
        "municipal_bcr_snapshot_pct": None, "municipal_far_snapshot_pct": None,
        "municipal_coverage": {"status": "needs_evidence", "sources": [],
                               "missing_evidence": ["recognized_zoning_and_jurisdiction"]},
        "sunlight_status": "needs_evidence",
        "parking_status": "needs_evidence",
        "height_limit_m": None, "height_article": "",
        "sunlight_applies": False, "sunlight_rules": [], "sunlight_article": "",
        "corner_cutoff_required": False, "corner_cutoff_m": None, "corner_cutoff_article": "",
        "road_diagonal_multiplier": None, "road_diagonal_rule": "",
        "road_diagonal_article": "",
        "building_line_setback_m": None, "building_line_article": "",
        "adjacent_setback_m": None, "adjacent_setback_article": "",
        "parking_rule": "", "parking_article": "",
        "landscaping_threshold_m2": None, "landscaping_min_pct": None,
        "landscaping_article": "",
        "sunlight_source": "",
        "adjacent_setback_source": "",
        "building_designation_applies": False,
        "building_designation_setback_m": None,
        "building_designation_article": "",
        "building_designation_source": "",
        "zone_category": "",
        "matched_zones": [],
        "unmatched_zones": [],
    }


def _resolve_bcr_far(zones_data: list[dict], zone_areas: dict[str, float] | None = None) -> dict:
    """BCR/FAR per 국토계획법 제84조. One implementation, in zoning_mapper.

    This used to take the strictest limit across zones independently of
    `zoning_mapper`, so the same wrong rule existed twice and fixing either one
    alone changed nothing for callers of the other.
    """

    combined = zoning_mapper.combine_limits(zones_data, zone_areas)
    bcr = combined["bcr_limit"]
    far = combined["far_limit"]

    bcr_articles = list(dict.fromkeys(z["bcr_article"] for z in zones_data))
    far_articles = list(dict.fromkeys(z["far_article"] for z in zones_data))

    overlap = combined.get("overlap")
    if overlap:
        # The article that actually decided the number, not only the ones that
        # set each zone's own default.
        bcr_articles.append(overlap["article"])
        far_articles.append(overlap["article"])

    return {
        "bcr_pct": bcr,
        "bcr_article": "; ".join(dict.fromkeys(bcr_articles)),
        "far_pct": far,
        "far_article": "; ".join(dict.fromkeys(far_articles)),
        "zone_overlap": overlap,
    }


def _resolve_height(zones_data: list[dict]) -> dict:
    """Height limit: use strictest (lowest non-null)."""
    heights = [z["height_limit_m"] for z in zones_data if z.get("height_limit_m") is not None]
    articles = list(dict.fromkeys(z.get("height_limit_article", "") for z in zones_data if z.get("height_limit_article")))

    return {
        "height_limit_m": min(heights) if heights else None,
        "height_article": "; ".join(articles) if articles else "",
    }


def _use_llm_extraction(override: bool | None) -> bool:
    return config.LLM_EXTRACTION_ENABLED if override is None else bool(override)


def _resolve_sunlight(zones_data: list[dict], use_llm_extraction: bool | None = None) -> dict:
    """Resolve static rules and keep any unverified extraction advisory."""
    # Base: static JSON
    base = _resolve_sunlight_from_json(zones_data)
    base["sunlight_source"] = "static_json"

    # Advisory extraction only; source identity/applicability are not verified.
    if _use_llm_extraction(use_llm_extraction):
        try:
            from backend.app.modules.land.reference.services import law_enricher
            zone_names = [z["zone_name"] for z in zones_data]
            extracted = law_enricher.extract_regulation_values(zone_names, "sunlight")
            if extracted:
                base['sunlight_proposal'] = {'status': 'unverified_proposal', 'values': extracted}
        except Exception as e:
            logger.warning(f"LLM sunlight extraction failed, using JSON fallback: {e}")

    return base


def _resolve_sunlight_from_json(zones_data: list[dict]) -> dict:
    """Sunlight from static JSON (fallback)."""
    applies = any(
        z.get("sunlight_setback", {}).get("applies", False)
        for z in zones_data
    )

    if not applies:
        articles = list(dict.fromkeys(
            z.get("sunlight_setback", {}).get("article", "")
            for z in zones_data
            if z.get("sunlight_setback", {}).get("article")
        ))
        return {
            "sunlight_applies": False,
            "sunlight_rules": [],
            "sunlight_article": "; ".join(articles) if articles else "",
        }

    for z in zones_data:
        ss = z.get("sunlight_setback", {})
        if ss.get("applies"):
            return {
                "sunlight_applies": True,
                "sunlight_rules": ss.get("rules", []),
                "sunlight_article": ss.get("article", ""),
            }

    return {"sunlight_applies": False, "sunlight_rules": [], "sunlight_article": ""}


def _resolve_corner_cutoff(zones_data: list[dict]) -> dict:
    """Corner cutoff: required if ANY zone requires it. Cutoff distance from zone or ordinance."""
    required = any(
        z.get("corner_cutoff", {}).get("required", False)
        for z in zones_data
    )
    articles = list(dict.fromkeys(
        z.get("corner_cutoff", {}).get("article", "")
        for z in zones_data
        if z.get("corner_cutoff", {}).get("article")
    ))
    # Cutoff distance: ordinance/zone override or None (→ setback_geometry calculates dynamically)
    cutoff_values = [
        z.get("corner_cutoff", {}).get("default_cutoff_m")
        for z in zones_data
        if z.get("corner_cutoff", {}).get("default_cutoff_m") is not None
    ]

    return {
        "corner_cutoff_required": required,
        "corner_cutoff_m": max(cutoff_values) if cutoff_values else None,
        "corner_cutoff_article": "; ".join(articles) if articles else "",
    }


def _resolve_road_diagonal(zones_data: list[dict]) -> dict:
    """Road diagonal: use strictest (lowest multiplier)."""
    multipliers = [
        z.get("road_diagonal", {}).get("multiplier")
        for z in zones_data
        if z.get("road_diagonal", {}).get("multiplier") is not None
    ]
    notes = [
        z.get("road_diagonal", {}).get("note", "")
        for z in zones_data
        if z.get("road_diagonal", {}).get("note")
    ]
    articles = list(dict.fromkeys(
        z.get("road_diagonal", {}).get("article", "")
        for z in zones_data
        if z.get("road_diagonal", {}).get("article")
    ))

    return {
        "road_diagonal_multiplier": min(multipliers) if multipliers else None,
        "road_diagonal_rule": notes[0] if notes else "",
        "road_diagonal_article": "; ".join(articles) if articles else "",
    }


def _resolve_building_line(zones_data: list[dict]) -> dict:
    """Building line: rule text only (site-specific calculation in Phase 3+)."""
    articles = list(dict.fromkeys(
        z.get("building_line_article", "")
        for z in zones_data
        if z.get("building_line_article")
    ))

    return {
        "building_line_setback_m": None,
        "building_line_article": "; ".join(articles) if articles else "",
    }


def _resolve_adjacent_setback(zones_data: list[dict], use_llm_extraction: bool | None = None) -> dict:
    """Use the largest sourced setback; extractions never replace numeric rules."""
    # Base: static JSON
    setbacks = [
        z.get("adjacent_setback_m")
        for z in zones_data
        if z.get("adjacent_setback_m") is not None
    ]
    articles = list(dict.fromkeys(
        z.get("adjacent_setback_article", "")
        for z in zones_data
        if z.get("adjacent_setback_article")
    ))
    base = {
        "adjacent_setback_m": max(setbacks) if setbacks else None,
        "adjacent_setback_article": "; ".join(articles) if articles else "",
        "adjacent_setback_source": "static_json",
    }

    # Advisory extraction only; source identity/applicability are not verified.
    if _use_llm_extraction(use_llm_extraction):
        try:
            from backend.app.modules.land.reference.services import law_enricher
            zone_names = [z["zone_name"] for z in zones_data]
            extracted = law_enricher.extract_regulation_values(zone_names, "adjacent_setback")
            if extracted:
                base['adjacent_setback_proposal'] = {'status': 'unverified_proposal', 'values': extracted}
        except Exception as e:
            logger.warning(f"LLM adjacent_setback extraction failed: {e}")

    return base


def _resolve_landscaping(zones_data: list[dict], land_info: dict | None = None,
                         common: dict | None = None) -> dict:
    """Landscaping (건축법 §42 -> 건축조례). Every 건축 조례 seen so far tiers the
    minimum by the building's 연면적 (2,000 m2+ 15 %, 1,000-2,000 10 %, under
    1,000 5 %), not by zone, so when the city's ordinance is on file the tiers are
    returned and min_pct is left to the caller who knows the floor area. The
    zone-keyed static value is only the fallback for cities without a file."""
    ls_common = (common or {}).get("landscaping") if common else None
    if isinstance(ls_common, dict) and ls_common.get("tiers"):
        return {
            "landscaping_threshold_m2": ls_common.get("threshold_m2", 200),
            "landscaping_min_pct": None,
            "landscaping_tiers": ls_common["tiers"],
            "landscaping_article": ls_common.get("article", ""),
        }
    thresholds = []
    pcts = []
    articles_set = set()

    for z in zones_data:
        ls = z.get("landscaping", {})
        if ls.get("threshold_m2") is not None:
            thresholds.append(ls["threshold_m2"])
        if ls.get("min_pct") is not None:
            pcts.append(ls["min_pct"])
        if ls.get("article"):
            articles_set.add(ls["article"])

    return {
        "landscaping_threshold_m2": min(thresholds) if thresholds else None,
        "landscaping_min_pct": max(pcts) if pcts else None,
        "landscaping_article": "; ".join(articles_set) if articles_set else "",
    }


def _resolve_building_designation(
    all_zone_names: list[str], use_llm_extraction: bool | None = None,
) -> dict:
    """A district-plan designation requires the parcel's actual plan evidence."""
    is_district_plan = any("지구단위계획" in z for z in all_zone_names)

    base = {
        "building_designation_applies": is_district_plan,
        "building_designation_setback_m": None,
        "building_designation_article": (
            "국토계획법 §49-52, 건축법 §46-47" if is_district_plan else ""
        ),
        "building_designation_source": "needs_district_plan_evidence" if is_district_plan else "",
    }

    if not is_district_plan:
        return base

    # Advisory extraction only; source identity/applicability are not verified.
    if _use_llm_extraction(use_llm_extraction):
        try:
            from backend.app.modules.land.reference.services import law_enricher
            standard_zones = [
                z for z in all_zone_names
                if zoning_mapper.lookup(z) is not None
            ]
            if standard_zones:
                extracted = law_enricher.extract_regulation_values(
                    standard_zones, "building_designation",
                )
                if extracted:
                    base['building_designation_proposal'] = {'status': 'unverified_proposal', 'values': extracted}
        except Exception as e:
            logger.warning(f"LLM building_designation extraction failed: {e}")

    return base
