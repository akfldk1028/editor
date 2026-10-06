"""Optimization job helpers: budgets, sunlight envelope, event GeoJSON enrichment, parking options, final result persistence.

Split out of views.py; views.py re-exports every name defined here.
"""

import logging
from backend.app.adapters.design_storage.persistence import save_results
from backend.app.modules.design.generation.services.mass_renderer import design_to_geojson

logger = logging.getLogger("backend.app.api.design_runtime.views")


def _all_mode_budget_options(options: dict | None) -> dict[str, int]:
    """Budget used for each algorithm when algorithm='all'."""
    options = options or {}
    return {
        "Number of generations": int(options.get("Number of generations", 80)),
        "num_islands": int(options.get("num_islands", 5)),
        "pop_per_island": int(options.get("pop_per_island", 20)),
    }


def _precompute_sunlight_envelope(job) -> dict | None:
    """
    Phase B (2026-05-08) — job_stream에서 NSGA-II 시작 전에 sunlight envelope 계산.

    Repair operator(`design.services.repair_operator.clip_to_sunlight_envelope`)가
    envelope corners polygon으로 footprint를 clip할 때 사용. PNU에서 zones 받아
    sunlight_applies 여부 판정 후 적용 zone(전용/일반주거)이면 envelope 생성.

    sunlight 미적용 zone(상업/공업 등)이면 None 반환 → Repair clip 단계 skip.

    실패시 None — Repair는 envelope 없이도 BCR/FAR/height 작동.
    """
    if not job.pnu and not job.site_polygon:
        return None
    try:
        from backend.app.modules.land.reference.services import land_api, regulation_calculator, road_frontage, zoning_mapper
        from backend.app.modules.land.reference.services.setback_geometry import compute_setback_lines
        from backend.app.modules.land.reference import config as land_config

        zones = []
        if job.pnu:
            try:
                land_info = land_api.get_land_use_info(job.pnu)
                zones = land_info.get("zones", []) or []
            except Exception as e:
                logger.warning(f"land_api zones lookup failed for {job.pnu}: {e}")

        if not zones:
            return None
        limits = zoning_mapper.resolve_limits(zones)
        zone_names = [z["zone_name"] for z in (limits or {}).get("zones", [])] or zones
        reg = regulation_calculator.calculate_all(
            zone_names,
            use_llm_extraction=False,
        )

        if not reg.get("sunlight_applies"):
            logger.info(f"[sunlight_clip] zone={zone_names} sunlight_applies=False → clip skip")
            return None
        road_frontages = []
        neighbor_parcels = []
        if job.site_polygon:
            try:
                roads_result = road_frontage.fetch_neighbor_roads(job.site_polygon)
                if roads_result.get("success"):
                    road_frontages = roads_result.get("roads") or []
            except Exception as e:
                logger.warning(f"[sunlight_clip] road frontage lookup failed: {e}")
            try:
                neighbors_result = road_frontage.fetch_neighbor_parcels(job.site_polygon)
                if neighbors_result.get("success"):
                    neighbor_parcels = neighbors_result.get("neighbors") or []
            except Exception as e:
                logger.warning(f"[sunlight_clip] neighbor parcel lookup failed: {e}")

        lines = compute_setback_lines(
            job.site_polygon, reg,
            compute_datum=land_config.ENABLE_DATUM_ELEVATION,
            road_frontages=road_frontages,
            neighbor_parcels=neighbor_parcels,
        )
        env = lines.get("sunlight_envelope")
        if env:
            corners = (env.get("slanted_polygons") or [{}])[0].get("corners") or []
            heights = [c[2] for c in corners] if corners else []
            logger.info(
                f"[sunlight_clip] zone={zone_names} envelope: "
                f"corners={len(corners)}, H={min(heights) if heights else 0:.1f}~"
                f"{max(heights) if heights else 0:.1f}m → Repair clip 활성"
            )
        else:
            logger.warning(f"[sunlight_clip] zone={zone_names} envelope=None")
        return env
    except Exception as e:
        logger.warning(f"_precompute_sunlight_envelope failed: {e}")
        return None


def _enrich_event_geojson(event, site_polygon, site_area_m2,
                          building_type="공동주택", algorithm="additive",
                          *,
                          outputs_def=None,
                          enable_repair: bool = False,
                          sunlight_envelope: dict | None = None):
    """Add best_geojson and pareto_geojson to SSE events for 3D visualization.

    When algorithm="per_design", each design dict must have an "algorithm" key.
    """
    def _algo_for(d: dict) -> str:
        if algorithm == "per_design":
            return d.get("algorithm", "additive")
        return algorithm

    best = event.get("best")
    if best and best.get("inputs"):
        try:
            a = _algo_for(best)
            feat = design_to_geojson(best["inputs"], site_polygon, site_area_m2,
                                     building_type, a,
                                     enable_repair=enable_repair,
                                     outputs_def=outputs_def,
                                     sunlight_envelope=sunlight_envelope)
            if feat:
                feat["properties"]["design_id"] = best.get("id")
                feat["properties"]["design_uid"] = best.get("uid")
                feat["properties"]["algorithm"] = a
                event["best_geojson"] = feat
        except Exception:
            pass

    pareto = event.get("pareto_front", [])
    if pareto:
        geojson_list = []
        for d in pareto:
            if not d.get("inputs"):
                continue
            try:
                a = _algo_for(d)
                feat = design_to_geojson(d["inputs"], site_polygon, site_area_m2,
                                         building_type, a,
                                         enable_repair=enable_repair,
                                         outputs_def=outputs_def,
                                         sunlight_envelope=sunlight_envelope)
                if feat:
                    feat["properties"]["design_id"] = d.get("id")
                    feat["properties"]["design_uid"] = d.get("uid")
                    feat["properties"]["objectives"] = d.get("objectives", [])
                    feat["properties"]["algorithm"] = a
                    geojson_list.append(feat)
            except Exception:
                pass
        if geojson_list:
            event["pareto_geojson"] = geojson_list


def _maas_design_from_feature(feature: dict, index: int, generation: int) -> dict:
    props = feature.get("properties", {}) or {}
    floor_area = float(props.get("floor_area") or 0.0)
    open_pct = float(props.get("open_pct") or max(0.0, 100.0 - float(props.get("bcr") or 0.0)))
    maas_score = float(props.get("maas_score") or 0.0)
    variant_id = props.get("variant_id") or f"maas_{index + 1:02d}"
    design_id = 900000 + index
    return {
        "id": design_id,
        "uid": f"maas:{variant_id}",
        "generation": generation,
        "parents": [None, None],
        "feasible": True,
        "inputs": [],
        "objectives": [floor_area, open_pct],
        "penalty": 0.0,
        "rank": maas_score,
        "elite": 1,
        "algorithm": "maas_legal_envelope",
    }


def _parking_options_from_job_options(job_options: dict | None, *, site_polygon_geojson: dict | None = None) -> dict:
    options = job_options or {}
    result = {}
    for key in ("parking_rule_id", "parking_metric", "parking_metric_value"):
        if options.get(key) is not None:
            result[key] = options.get(key)
    road_context = options.get("parking_road_context")
    if isinstance(road_context, dict):
        result["road_context"] = road_context
    elif isinstance(site_polygon_geojson, dict):
        inferred = _infer_parking_road_context(site_polygon_geojson)
        if inferred:
            result["road_context"] = inferred
    return result


def _infer_parking_road_context(site_polygon_geojson: dict) -> dict | None:
    try:
        from backend.app.modules.land.reference.services import road_frontage
        roads_result = road_frontage.fetch_neighbor_roads(site_polygon_geojson)
        road_frontages = roads_result.get("roads") if isinstance(roads_result, dict) else None
    except Exception:
        return None
    if not isinstance(road_frontages, list) or not road_frontages:
        return None
    widths = []
    for road in road_frontages:
        if not isinstance(road, dict):
            continue
        try:
            width = float(road.get("roadWidthM") or road.get("road_width_m") or 0.0)
        except (TypeError, ValueError):
            width = 0.0
        if width > 0:
            widths.append(width)
    return {
        "road_width_m": max(widths) if widths else None,
        "road_frontages": [
            {
                "geometry": road.get("geometry"),
                "roadWidthM": road.get("roadWidthM") or road.get("road_width_m"),
                "sharedEdge": road.get("sharedEdge") or road.get("shared_edge"),
                "roadCenterline": road.get("roadCenterline") or road.get("road_centerline"),
                "landCategory": road.get("landCategory") or road.get("land_category"),
            }
            for road in road_frontages
            if isinstance(road, dict)
        ][:5],
    }


def _save_final_results(job, event, site_polygon, site_area_m2,
                        building_type="공동주택", algorithm="additive",
                        *,
                        outputs_def=None,
                        enable_repair: bool = False,
                        sunlight_envelope: dict | None = None):
    """Save Pareto-optimal designs to database."""
    pareto = event.get("pareto_front", [])
    geojson_by_uid = {}
    geojson_by_id = {}
    for feature in event.get("pareto_geojson", []) or []:
        props = feature.get("properties", {}) or {}
        if props.get("design_uid") is not None:
            geojson_by_uid[str(props.get("design_uid"))] = feature
        if props.get("design_id") is not None:
            geojson_by_id[str(props.get("design_id"))] = feature
    designs_to_save = []
    for d in pareto:
        a = d.get("algorithm", algorithm) if algorithm == "per_design" else algorithm
        mass_geojson = (
            geojson_by_uid.get(str(d.get("uid")))
            or geojson_by_id.get(str(d.get("id")))
        )
        if mass_geojson is None and d.get("inputs"):
            mass_geojson = design_to_geojson(d.get("inputs", []), site_polygon, site_area_m2,
                                             building_type, a,
                                             enable_repair=enable_repair,
                                             outputs_def=outputs_def,
                                             sunlight_envelope=sunlight_envelope)
        if not isinstance(mass_geojson, dict) or not mass_geojson.get("geometry"):
            raise ValueError("Final design has no generated mass geometry")
        designs_to_save.append({
            "generation": d.get("generation", 0),
            "design_id": d.get("id", 0),
            "inputs": d.get("inputs", []),
            "outputs": {
                "objectives": d.get("objectives", []),
                "penalty": d.get("penalty", 0),
                "result_identity": {
                    "algorithm": a,
                    "uid": d.get("uid"),
                    "source_design_id": d.get("source_design_id", d.get("id", 0)),
                },
            },
            "ranking": 1.0,
            "crowding_distance": 0.0,
            "is_feasible": d.get("feasible", True),
            "is_pareto_optimal": True,
            "mass_geojson": mass_geojson,
        })
    save_results(job, designs_to_save)
