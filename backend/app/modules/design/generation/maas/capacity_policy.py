"""Program- and brief-aware FAR capacity policy for MAAS review masses."""

from __future__ import annotations

from typing import Any


# Policy aliases only. Architectural geometry and coordinates must never be
# authored in this module. Keeping Korean and English aliases prevents a
# Korean brief from silently falling through to the generic FAR objective.
DESIGN_LED_PROGRAM_TOKENS = (
    "미술관", "박물관", "갤러리", "문화", "체육", "운동", "공공",
    "파빌리온", "전시", "공연", "도서관", "학교", "교육", "종교",
    "museum", "gallery", "cultural", "gymnasium", "sports", "civic",
    "pavilion", "exhibition", "performance", "library", "school",
)
CAPACITY_FIRST_PROGRAM_TOKENS = (
    "공동주택", "다가구", "다세대", "아파트", "주거", "오피스텔",
    "업무", "근린생활", "판매", "상가",
    "housing", "apartment", "residential", "officetel", "office",
    "neighborhoodliving", "neighbourhoodliving", "retail", "commercial",
)


def resolve_massing_capacity_policy(
    *,
    building_type: str,
    site_area_m2: float,
    parking_options: dict[str, Any] | None,
) -> dict[str, Any]:
    """Resolve FAR intent from program, site size, and an optional brief."""
    options = parking_options or {}
    brief = options.get("massing_brief") if isinstance(options.get("massing_brief"), dict) else {}
    mode = str(brief.get("mode") or options.get("massing_mode") or "").strip().lower().replace("_", "-")
    explicit_min = brief.get("min_far_utilization", options.get("min_far_utilization"))
    explicit_target = brief.get("target_far_utilization", options.get("target_far_utilization"))
    if explicit_min is not None:
        minimum = max(0.0, min(1.0, float(explicit_min)))
        resolved_mode, source = mode or "explicit", "explicit_brief"
    elif mode in {"design-led", "design", "civic", "competition"}:
        minimum, resolved_mode, source = 0.20, "design-led", "explicit_mode"
    elif mode in {"balanced", "mixed"}:
        minimum, resolved_mode, source = 0.45, "balanced", "explicit_mode"
    elif mode in {"capacity-first", "capacity", "feasibility"}:
        minimum, resolved_mode, source = 0.60, "capacity-first", "explicit_mode"
    else:
        label = _normalise_label(building_type)
        if any(_normalise_label(token) in label for token in DESIGN_LED_PROGRAM_TOKENS):
            minimum, resolved_mode = 0.20, "design-led"
        elif any(_normalise_label(token) in label for token in CAPACITY_FIRST_PROGRAM_TOKENS) and site_area_m2 <= 1000.0:
            minimum, resolved_mode = 0.60, "capacity-first"
        elif any(_normalise_label(token) in label for token in CAPACITY_FIRST_PROGRAM_TOKENS):
            minimum, resolved_mode = 0.55, "balanced"
        else:
            minimum, resolved_mode = 0.35, "balanced"
        source = "program_and_site_default"
    if explicit_target is not None:
        target = max(minimum, min(1.0, float(explicit_target)))
    else:
        target = {
            "capacity-first": 0.70,
            "balanced": 0.75,
            "design-led": 0.55,
        }.get(resolved_mode, minimum)
        target = max(minimum, target)
    return {
        "schema_version": "arr.maas.capacity_policy.v1",
        "mode": resolved_mode,
        "min_far_utilization": round(minimum, 4),
        "target_far_utilization": round(target, 4),
        "source": source,
        "building_type": building_type,
        "site_area_m2": round(float(site_area_m2), 2),
    }


def _normalise_label(value: Any) -> str:
    return str(value or "").casefold().replace(" ", "").replace("-", "").replace("_", "")


__all__ = ["resolve_massing_capacity_policy"]
