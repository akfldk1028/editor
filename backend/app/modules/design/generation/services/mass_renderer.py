"""
Mass geometry -> GeoJSON/3D mesh conversion for Cesium visualization.

Supports three algorithms: additive, subtractive, grid.
"""

import logging

from shapely.geometry import Polygon, mapping
from shapely.affinity import scale

from backend.app.modules.design.generation.services.site_geometry import utm_to_wgs84, wgs84_to_utm
from backend.app.modules.design.generation.services.mass_evaluator import BUILDERS, get_floor_height, _global_idx, _build_mass_polygon_freeform

logger = logging.getLogger(__name__)


def design_to_geojson(inputs: list, site_polygon: Polygon, site_area_m2: float,
                      building_type: str = "공동주택",
                      algorithm: str = "additive",
                      *,
                      enable_repair: bool = False,
                      outputs_def: list[dict] | None = None,
                      repair_limits=None,
                      sunlight_envelope: dict | None = None) -> dict | None:
    """
    Convert design inputs to GeoJSON Feature with 3D properties.

    Returns a GeoJSON Feature with:
    - geometry: building footprint polygon (WGS84)
    - properties: height, num_floors, area, building_type, mass_shape,
                  step-back info (step_floor, upper_scale, upper_geometry)
    """
    site_utm = wgs84_to_utm(site_polygon)
    builder = BUILDERS.get(algorithm, _build_mass_polygon_freeform)
    building_utm, _ = builder(inputs, site_utm)

    if building_utm is None or building_utm.is_empty:
        return None

    # Clip to site
    footprint_utm = building_utm.intersection(site_utm)
    if footprint_utm.is_empty:
        return None

    # Global gene indices depend on algorithm
    gb = _global_idx(algorithm, 0)
    num_floors = max(1, round(inputs[gb][0]))
    floor_height = get_floor_height(building_type)
    height = num_floors * floor_height

    # Keep visual/export geometry consistent with optimization evaluation.
    # Without this, a design can be scored after repair but rendered from the
    # unrepaired genome, which makes legal feasibility misleading in the UI.
    if enable_repair:
        from backend.app.modules.design.generation.services.mass_evaluator import _build_repair_limits_from_outputs
        from backend.app.modules.design.generation.services.repair_operator import repair_design

        if repair_limits is None:
            repair_limits = _build_repair_limits_from_outputs(outputs_def, building_type)
        repaired_fp, repaired_floors, _actions = repair_design(
            footprint_utm,
            site_utm,
            num_floors,
            repair_limits,
            sunlight_envelope=sunlight_envelope,
        )
        if repaired_fp is None or repaired_fp.is_empty:
            return None
        footprint_utm = repaired_fp
        num_floors = repaired_floors
        height = num_floors * floor_height

    # Step-back parameters
    idx_upper = gb + 2
    idx_step = gb + 3
    upper_scale_val = max(0.5, min(1.0, inputs[idx_upper][0])) if len(inputs) > idx_upper else 1.0
    step_frac = max(0.3, min(0.8, inputs[idx_step][0])) if len(inputs) > idx_step else 1.0

    has_stepback = upper_scale_val < 0.98 and step_frac < 0.95

    # Convert base footprint to WGS84
    footprint_wgs = utm_to_wgs84(footprint_utm)
    footprint_area = footprint_utm.area

    props = {
        "height": round(height, 2),
        "num_floors": num_floors,
        "floor_height": floor_height,
        "building_type": building_type,
        "mass_shape": algorithm,
        "footprint_area": round(footprint_area, 2),
        "bcr": round(footprint_area / site_area_m2 * 100, 2) if site_area_m2 > 0 else 0,
    }

    if has_stepback:
        step_floor = max(1, round(num_floors * step_frac))
        lower_floors = step_floor
        upper_floors = num_floors - step_floor
        upper_fp_utm = scale(footprint_utm, xfact=upper_scale_val,
                             yfact=upper_scale_val, origin='centroid')
        upper_fp_utm = upper_fp_utm.intersection(site_utm)
        upper_area = upper_fp_utm.area if not upper_fp_utm.is_empty else 0
        total_floor_area = footprint_area * lower_floors + upper_area * upper_floors

        props["step_floor"] = step_floor
        props["upper_scale"] = round(upper_scale_val, 3)
        props["lower_height"] = round(step_floor * floor_height, 2)
        if not upper_fp_utm.is_empty:
            props["upper_geometry"] = mapping(utm_to_wgs84(upper_fp_utm))
    else:
        total_floor_area = footprint_area * num_floors

    props["floor_area"] = round(total_floor_area, 2)
    props["far"] = round(total_floor_area / site_area_m2 * 100, 2) if site_area_m2 > 0 else 0

    return {
        "type": "Feature",
        "geometry": mapping(footprint_wgs),
        "properties": props,
    }


def pareto_to_feature_collection(pareto_designs: list, site_polygon: Polygon, site_area_m2: float,
                                  building_type: str = "공동주택",
                                  algorithm: str = "additive") -> dict:
    """
    Convert Pareto-optimal designs to a GeoJSON FeatureCollection.
    """
    features = []
    for d in pareto_designs:
        feat = design_to_geojson(d.get("inputs", []), site_polygon, site_area_m2, building_type, algorithm)
        if feat:
            feat["properties"]["design_id"] = d.get("id")
            feat["properties"]["generation"] = d.get("generation")
            feat["properties"]["objectives"] = d.get("objectives", [])
            features.append(feat)

    return {
        "type": "FeatureCollection",
        "features": features,
    }


# ───────────────────────────────────────────────────────────
# A7 — Constraint Visualizer (Phase 1, 2026-05-06)
# ───────────────────────────────────────────────────────────
# Cesium에 envelope + 매스 동시 표시용 GeoJSON 출력.
# 플렉시티 광고처럼 정북일조 사선·도로후퇴·이격선 시각화.

def constraint_envelope_geojson(
    site_polygon: Polygon,
    bcr_limit_pct: float = 60.0,
    far_limit_pct: float = 200.0,
    height_limit_m: float = 50.0,
    adjacent_setback_m: float = 1.0,
    north_setback_m: float = 1.5,
    road_setback_m: float = 3.0,
    sunlight_slope: float = 2.0,
    sunlight_base_height_m: float = 10.0,
) -> dict:
    """
    A7 — site polygon + 법규 한도 → envelope/setback GeoJSON.

    Frontend (Cesium SiteMapPanel)가 *envelope (녹색 반투명) + setback (빨간 점선)*
    을 매스 옆에 동시 표시.

    Returns:
        {
          "type": "FeatureCollection",
          "features": [
            { "geometry": <site polygon>, "properties": {"kind": "site", ...} },
            { "geometry": <adjacent setback inward>, "properties": {"kind": "adjacent_setback", "color": "#FF0000"} },
            { "geometry": <north sunlight base>, "properties": {"kind": "north_sunlight", "color": "#00C400"} },
            ...
          ]
        }
    """
    from shapely.geometry import box as shapely_box

    site_utm = wgs84_to_utm(site_polygon)
    minx, miny, maxx, maxy = site_utm.bounds

    features = [
        {
            "type": "Feature",
            "geometry": mapping(site_polygon),
            "properties": {
                "kind": "site",
                "label": "대지경계선",
                "color": "#000000",
                "stroke_width": 2,
            },
        },
    ]

    # 1. Adjacent setback (inward buffer) — 빨간 점선 "대지 안의 공지"
    if adjacent_setback_m > 0:
        try:
            inward = site_utm.buffer(-adjacent_setback_m)
            if not inward.is_empty and inward.area > 1.0:
                inward_wgs = utm_to_wgs84(inward)
                features.append({
                    "type": "Feature",
                    "geometry": mapping(inward_wgs),
                    "properties": {
                        "kind": "adjacent_setback",
                        "label": f"대지 안의 공지 ({adjacent_setback_m}m)",
                        "color": "#FF0000",
                        "stroke_dasharray": [4, 2],
                        "stroke_width": 1.5,
                    },
                })
        except Exception as e:
            logger.warning(f"adjacent_setback inward buffer failed: {e}")

    # 2. North sunlight base setback (§86①제1호) — 녹색 점선
    if north_setback_m > 0:
        try:
            north_clip_y = maxy - north_setback_m
            if north_clip_y > miny:
                # 북측 1.5m 가로 밴드
                north_band = shapely_box(minx, north_clip_y, maxx, maxy)
                north_band = north_band.intersection(site_utm)
                if not north_band.is_empty:
                    band_wgs = utm_to_wgs84(north_band)
                    features.append({
                        "type": "Feature",
                        "geometry": mapping(band_wgs),
                        "properties": {
                            "kind": "north_sunlight_base",
                            "label": f"정북 일조 base ({north_setback_m}m, §86①제1호)",
                            "color": "#00A000",
                            "stroke_dasharray": [6, 3],
                            "fill_opacity": 0.15,
                        },
                    })
        except Exception as e:
            logger.warning(f"north_setback band failed: {e}")

    # 3. Sunlight slope envelope (계단식 — 단순화 버전)
    # §86①제2호: H = 2x (slope=2:1), cap = max_depth × slope
    if sunlight_slope > 0:
        # slope envelope 정보는 properties로만 (실제 3D는 frontend가 그림)
        features.append({
            "type": "Feature",
            "geometry": mapping(site_polygon),
            "properties": {
                "kind": "sunlight_slope_info",
                "label": f"정북 일조 사선 (slope {sunlight_slope}:1)",
                "color": "#00C400",
                "fill_opacity": 0.0,
                "metadata": {
                    "base_height_m": sunlight_base_height_m,
                    "slope": sunlight_slope,
                    "max_height_m": min(50.0, sunlight_base_height_m + (maxy - miny) * sunlight_slope),
                },
            },
        })

    # 4. BCR/FAR/height envelope info (시각이 아닌 라벨)
    features.append({
        "type": "Feature",
        "geometry": mapping(site_polygon),
        "properties": {
            "kind": "regulation_summary",
            "label": "법규 한도",
            "fill_opacity": 0.0,
            "metadata": {
                "bcr_limit_pct": bcr_limit_pct,
                "far_limit_pct": far_limit_pct,
                "height_limit_m": height_limit_m,
                "adjacent_setback_m": adjacent_setback_m,
                "road_setback_m": road_setback_m,
            },
        },
    })

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "generator": "A7_constraint_visualizer",
            "version": "1.0",
        },
    }
