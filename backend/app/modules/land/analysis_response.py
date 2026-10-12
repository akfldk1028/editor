"""
Response formatters for land regulation analysis.

Extracted from views.py — pure functions, no Django imports.
"""
from backend.app.modules.regulations import zoning_limits
from backend.app.modules.land.reference.services import designations


def format_regulations(reg: dict, reg_ext: dict | None = None) -> dict:
    """Format regulation_calculator output into API response structure."""
    result = {
        "bcr": {
            "limit_pct": reg.get("bcr_pct"),
            "article": reg.get("bcr_article", ""),
            "national_ceiling_pct": reg.get("national_bcr_ceiling_pct"),
            "status": (reg.get("municipal_coverage") or {}).get("status", "needs_evidence"),
            "coverage": reg.get("municipal_coverage"),
        },
        "far": {
            "limit_pct": reg.get("far_pct"),
            "article": reg.get("far_article", ""),
            "national_ceiling_pct": reg.get("national_far_ceiling_pct"),
            "status": (reg.get("municipal_coverage") or {}).get("status", "needs_evidence"),
            "coverage": reg.get("municipal_coverage"),
        },
        "height": {
            "limit_m": reg.get("height_limit_m"),
            "rule": "가로구역별 높이제한 적용",
            "article": reg.get("height_article", ""),
        },
        "sunlight_setback": {
            "applies": reg.get("sunlight_applies", False),
            "direction": "정북방향" if reg.get("sunlight_applies") else None,
            "rules": reg.get("sunlight_rules", []),
            "article": reg.get("sunlight_article", ""),
        },
        "corner_cutoff": {
            "required": reg.get("corner_cutoff_required", False),
            "rule": "8m 미만 도로 모퉁이 (교차각별 2~4m 후퇴)" if reg.get("corner_cutoff_required") else None,
            "article": reg.get("corner_cutoff_article", ""),
        },
        "road_diagonal": {
            "multiplier": reg.get("road_diagonal_multiplier"),
            "rule": reg.get("road_diagonal_rule", ""),
            "article": reg.get("road_diagonal_article", ""),
        },
        "building_line": {
            "setback_m": reg.get("building_line_setback_m"),
            "rule": "도로경계선 후퇴 (조례에 따름)",
            "article": reg.get("building_line_article", ""),
        },
        "adjacent_setback": {
            "min_m": reg.get("adjacent_setback_m"),
            "article": reg.get("adjacent_setback_article", ""),
        },
        "parking": {
            "rule": reg.get("parking_rule", ""),
            "article": reg.get("parking_article", ""),
            "ratio_m2_per_car": reg.get("parking_ratio_m2_per_car"),
            "ratio_uses": reg.get("parking_ratio_uses"),
            "ratio_rule": reg.get("parking_ratio_rule"),
            "required_cars": reg.get("parking_required"),
            "required_accessible_cars": reg.get("parking_required_accessible"),
            "accessible": reg.get("parking_accessible"),
            "calculated_intermediate": reg.get("parking_calculated_intermediate"),
            "calculation": reg.get("parking_calculation"),
            "status": reg.get("parking_status", "needs_evidence"),
            "program_uses": reg.get("parking_program_uses"),
            "missing_evidence": reg.get("parking_missing_evidence", []),
            "basis": reg.get("parking_basis"),
            "source": reg.get("parking_source"),
            "cap": reg.get("parking_cap"),
            "restricted_zone_candidate": reg.get("parking_restricted_candidate"),
            "ordinance_rows": reg.get("parking_ordinance_rows"),
            "national_rows": reg.get("parking_national_rows"),
            "needs_review": reg.get("parking_needs_review"),
        },
        "landscaping": {
            "threshold_m2": reg.get("landscaping_threshold_m2"),
            "min_pct": reg.get("landscaping_min_pct"),
            "tiers": reg.get("landscaping_tiers"),
            "article": reg.get("landscaping_article", ""),
        },
    }
    if reg_ext:
        result["extended"] = reg_ext
    return result


def build_restrictions(reg: dict, zone_names: list[str],
                       reg_ext: dict | None = None,
                       overlays: list[dict] | None = None,
                       overlay_all_matched: set[str] | None = None) -> list[str]:
    """Build a human-readable list of key restrictions."""
    restrictions = []

    bcr = reg.get("bcr_pct")
    far = reg.get("far_pct")

    if bcr is not None:
        restrictions.append(f"건폐율 상한: {bcr}%")
    if far is not None:
        restrictions.append(f"용적률 상한: {far}%")
    if (reg.get("municipal_coverage") or {}).get("status") == "needs_evidence":
        restrictions.append("건폐율·용적률: 적용 조례·판본·용도지역 증거 부족 — 상한 미확정")

    if reg.get("sunlight_applies"):
        note = designations.sunlight_exemption_note(zone_names, reg.get("north_neighbour_zone"))
        restrictions.append("일조사선: 정북방향 10m 이하 1.5m · 초과 부분 H/2 이격" + (f" — {note}" if note else ""))

    if reg.get("road_diagonal_multiplier") is not None:
        restrictions.append(
            f"높이제한: 전면도로폭 × {reg['road_diagonal_multiplier']} "
            f"(가로구역별 높이 미지정 시, 건축법 시행령 §82)"
        )

    if reg.get("corner_cutoff_required"):
        restrictions.append("가각전제: 8m 미만 도로 모퉁이 (시행령 §31)")

    if reg.get("adjacent_setback_m") is not None:
        restrictions.append(f"인접대지 이격: {reg['adjacent_setback_m']}m 이상")

    if reg.get("parking_ratio_m2_per_car"):
        line = f"주차: 시설면적 {reg['parking_ratio_m2_per_car']}㎡당 1대"
        if reg.get("parking_required") is not None:
            line += f" → {reg['parking_required']}대"
        cap = reg.get("parking_cap")
        if cap:
            line += f" (설치제한지역 후보: 최고 {cap['m2_per_car_max']}㎡당 1대"
            if cap.get("cars_max") is not None:
                line += f" → 최대 {cap['cars_max']}대"
            line += ")"
        restrictions.append(line)
    elif reg.get("parking_restricted_candidate"):
        restrictions.append(f"주차: 주차장설치제한지역 후보 ({reg['parking_restricted_candidate']['district']}) — 용도를 주면 상한 산정")
    if reg.get("landscaping_min_pct") is not None:
        restrictions.append(f"조경: 대지면적의 {reg['landscaping_min_pct']}% 이상")
    elif reg.get("landscaping_tiers"):
        parts = []
        for t in reg["landscaping_tiers"]:
            lo, hi = t.get("min_floor_area_m2", 0), t.get("max_floor_area_m2")
            span = f"연면적 {lo:,}㎡ 이상" if lo else f"연면적 {hi:,}㎡ 미만"
            parts.append(f"{span} {t['min_pct']}%")
        restrictions.append("조경: " + " / ".join(parts) + f" ({reg.get('landscaping_article', '')})")

    # Extended restrictions summary (Group A)
    if reg_ext:
        bur = reg_ext.get("building_use_restriction", {})
        if bur.get("prohibited_summary"):
            restrictions.append(f"건축물 용도 제한: {bur['prohibited_summary']}")

        sub = reg_ext.get("site_subdivision_limit", {})
        if sub.get("min_area_m2") and sub.get("basis") == "ordinance":
            restrictions.append(f"대지 분할 제한: 최소 {sub['min_area_m2']:g}m² ({sub.get('article')}, {sub.get('zone_category')})")
        elif sub.get("min_area_m2"):
            # 건축법 §57: the figure is the ordinance's, within the 시행령 §80 floor; the floor is what is known here.
            restrictions.append(f"대지 분할 제한: 시행령 하한 {sub['min_area_m2']}m² 이상 범위에서 조례로 정함 — 조례 면적 확인 필요")
        road = reg_ext.get("site_road_requirement", {})
        if road.get("basis") == "ordinance" and road.get("exempt_similar_buildings_below_m2") is not None:
            restrictions.append(f"접도의무: 연면적 2,000m²(공장 3,000m²) 이상이면 6m 도로에 4m 이상 접함 (시행령 §28②); "
                                f"축사·작물재배사 등 이와 비슷한 건축물은 연면적 {road['exempt_similar_buildings_below_m2']:,.0f}m² 미만이면 제외 ({road.get('exemption_article')})")

        dl = reg_ext.get("daylighting_spacing", {})
        if dl.get("applies"):
            restrictions.append("채광 인동간격: 공동주택 높이 기준 이격 (건축법 §61②)")

    # Only 용도지역 count: 지구·구역 (과밀억제권역, 지구단위계획구역 …) overlap a lot without splitting it.
    use_zones = [name for name in zone_names if zoning_limits.lookup(name) is not None]
    if len(use_zones) > 1:
        restrictions.append(
            f"복수 용도지역 ({len(use_zones)}개: {', '.join(use_zones)}) — 면적 분할과 규제별 적용 조문 확인 필요 (국토계획법 제84조·건축법 제54조)"
        )

    cat = reg.get("zone_category", "")
    if "녹지" in cat:
        restrictions.append("건축물 용도 제한 (녹지지역) — 시행령 별표 참조")
    elif "공업" in cat:
        restrictions.append("환경오염 관련 규제 주의 (공업지역)")
    elif "자연환경보전" in cat:
        restrictions.append("건축물 용도 극히 제한 (자연환경보전지역)")

    # Overlay zone restrictions
    overlay_matched_zones = set()
    if overlays:
        for ov in overlays:
            vals = ov.get("values", {})
            if vals.get("min_height_m") is not None and vals.get("max_height_m") is not None:
                restrictions.append(
                    f"높이제한: {ov['name']} {vals['min_height_m']}~{vals['max_height_m']}m "
                    f"({ov['article']})"
                )
            elif vals.get("max_height_m") is not None:
                restrictions.append(
                    f"높이제한: {ov['name']} 최고 {vals['max_height_m']}m ({ov['article']})"
                )
            else:
                restrictions.append(f"{ov['description']} ({ov['article']})")
            overlay_matched_zones.add(ov.get("raw_zone", ""))

    # Unmatched zones — exclude all overlay-recognized zones (regulations + info-only)
    all_recognized = overlay_matched_zones
    if overlay_all_matched:
        all_recognized = all_recognized | overlay_all_matched
    unmatched = [
        z for z in reg.get("unmatched_zones", [])
        if z not in all_recognized
    ]
    unknown_zones = [z for z in unmatched if designations.kind(z) == designations.USE_ZONE]
    unlisted = [z for z in unmatched if z not in unknown_zones]
    if unknown_zones:
        restrictions.append(
            f"미인식 용도지역: {', '.join(unknown_zones)} (수동 확인 필요)"
        )
    if unlisted:
        restrictions.append(
            f"규제표에 없는 지정: {', '.join(unlisted)} (용도지역이 아닌 지정 — 건폐율·용적률 상한에는 영향 없음, 근거 법령·고시 확인)"
        )

    return restrictions


def flatten_law_articles(law_articles: dict) -> dict:
    """Flatten nested {query, results} articles into flat list for frontend.

    Backend format: {"articles": [{"query": "...", "results": [item, ...]}]}
    Frontend format: {"articles": [item, ...], "total_count": int}
    """
    nested = law_articles.get("articles", [])
    seen_ids = set()
    flat = []
    for group in nested:
        if isinstance(group, dict) and "results" in group:
            for item in group["results"]:
                hang_id = item.get("hang_id", "")
                if hang_id and hang_id in seen_ids:
                    continue
                seen_ids.add(hang_id)
                flat.append(item)
        else:
            # Already flat item
            flat.append(group)
    return {
        "articles": flat,
        "total_count": len(flat),
        "errors": law_articles.get("errors", []),
    }
