"""Constraint endpoints: auto constraints, job validation, planm floor plan, constraint visualization.

Split out of views.py; views.py re-exports every name defined here.
"""

import json
import logging
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from backend.app.adapters.design_storage.models import OptimizationJob
from backend.app.modules.design.generation.services.constraint_bridge import regulations_to_constraints, compute_setback_geometry
from backend.app.modules.design.generation.services.regulation_validator import validate_best_designs, auto_correct_constraints
from backend.app.modules.design.generation.services.site_geometry import geojson_to_polygon

logger = logging.getLogger("backend.app.api.design_runtime.views")


def _daylight_diagonal_multiplier(zone_names: list[str], building_type: str) -> float | None:
    """건축법 §61②/시행령 §86③ 채광사선 적용 배수."""
    residential_types = ("공동주택", "아파트", "다세대", "연립", "다가구")
    if not any(t in (building_type or "") for t in residential_types):
        return None
    # 법 §61②: 일반상업지역ㆍ중심상업지역에 건축하는 공동주택은 제외.
    if any(z in ("일반상업지역", "중심상업지역") for z in zone_names):
        return None
    if any(z in ("근린상업지역", "준주거지역") for z in zone_names):
        return 4.0
    return 2.0


@csrf_exempt
@require_http_methods(["POST"])
def auto_constraints(request):
    """POST /design/auto-constraints/ — Generate constraints from land regulations."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    pnu = body.get("pnu", "")
    zones = body.get("zones", [])
    address = body.get("address", "")
    building_type = body.get("building_type", "")
    include_law_articles = bool(body.get("include_law_articles", True))

    if not pnu and not zones and not address:
        return JsonResponse({"error": "pnu, zones, or address required"}, status=400)

    # Call land/analyze internally
    try:
        from backend.app.modules.land.reference.services import regulation_calculator
        from backend.app.modules.land.reference.services import zoning_mapper, land_api, road_frontage

        # If PNU given but no zones, look up zones via Vworld Data API
        if not zones and pnu:
            land_info = land_api.get_land_use_info(pnu)
            zones = land_info.get("zones", [])

        # resolve_limits handles exact matching + strictest-zone logic
        limits = zoning_mapper.resolve_limits(zones) if zones else {}
        zone_names = [z["zone_name"] for z in limits.get("zones", [])] if limits else zones

        reg = regulation_calculator.calculate_all(
            zone_names,
            use_llm_extraction=include_law_articles,
        )

        daylight_multiplier = _daylight_diagonal_multiplier(zone_names, building_type)
        if daylight_multiplier is not None:
            reg["daylight_diagonal_multiplier"] = daylight_multiplier

        constraints = regulations_to_constraints(reg)

        # Query law articles for building-type-specific regulations
        law_articles = {}
        if include_law_articles and building_type and zone_names:
            try:
                from backend.app.modules.land.reference.services.law_enricher import search_for_building_type
                law_result = search_for_building_type(building_type, zone_names)
                law_articles = law_result
            except Exception as e:
                logger.warning(f"Law search for building type failed: {e}")
                law_articles = {"articles": [], "total_count": 0,
                                "errors": [str(e)]}

        # Compute setback geometry for map visualization
        setback_geometries = {}
        site_geojson = body.get("site_polygon")
        if site_geojson:
            try:
                from backend.app.modules.land.reference.services.setback_geometry import compute_setback_lines
                from backend.app.modules.land.reference import config as land_config
                road_frontages = []
                neighbor_parcels = []
                try:
                    roads_result = road_frontage.fetch_neighbor_roads(site_geojson)
                    if roads_result.get("success"):
                        road_frontages = roads_result.get("roads") or []
                except Exception as e:
                    logger.warning(f"road frontage lookup failed: {e}")
                try:
                    neighbors_result = road_frontage.fetch_neighbor_parcels(site_geojson)
                    if neighbors_result.get("success"):
                        neighbor_parcels = neighbors_result.get("neighbors") or []
                except Exception as e:
                    logger.warning(f"neighbor parcel lookup failed: {e}")

                lines = compute_setback_lines(
                    site_geojson, reg,
                    compute_datum=land_config.ENABLE_DATUM_ELEVATION,
                    road_frontages=road_frontages,
                    neighbor_parcels=neighbor_parcels,
                )
                adj_m = reg.get("adjacent_setback_m") or 0.5
                sunlight_m = 1.5
                if lines.get("buildable_area"):
                    setback_geometries["buildable_area"] = {
                        "geometry": lines["buildable_area"],
                        "distance_m": float(adj_m),
                        "label": f"건축가능영역 (이격 {adj_m}m)",
                    }
                if lines.get("north_setback"):
                    setback_geometries["north_setback"] = {
                        "geometry": lines["north_setback"],
                        "distance_m": sunlight_m,
                        "label": f"정북 일조사선 {sunlight_m}m",
                    }
                if lines.get("adjacent_setback"):
                    setback_geometries["adjacent_setback"] = {
                        "geometry": lines["adjacent_setback"],
                        "distance_m": float(adj_m),
                        "label": f"인접대지 이격 {adj_m}m",
                    }
                road_m = 0.0
                if lines.get("road_setback"):
                    road_setback_meta = lines.get("road_setback") or {}
                    road_m = road_setback_meta.get("setback_m")
                    if road_m is None:
                        road_m = reg.get("building_line_setback_m") or 1.0
                if lines.get("road_setback"):
                    setback_geometries["road_setback"] = {
                        "geometry": lines["road_setback"],
                        "distance_m": float(road_m),
                        "label": f"건축선 후퇴 {road_m}m",
                    }
                cutoff_val = reg.get("corner_cutoff_m") or 3.0
                if lines.get("corner_cutoff"):
                    setback_geometries["corner_cutoff"] = {
                        "geometry": lines["corner_cutoff"],
                        "distance_m": float(cutoff_val),
                        "label": f"가각전제 {cutoff_val}m",
                    }
                desig_m = reg.get("building_designation_setback_m")
                if lines.get("building_designation_line"):
                    setback_geometries["building_designation_line"] = {
                        "geometry": lines["building_designation_line"],
                        "distance_m": float(desig_m) if desig_m else 2.0,
                        "label": f"건축지정선 {desig_m or 2.0}m",
                    }
                if lines.get("sunlight_envelope"):
                    setback_geometries["sunlight_envelope"] = lines["sunlight_envelope"]
                if lines.get("daylight_diagonal_envelope"):
                    setback_geometries["daylight_diagonal_envelope"] = lines["daylight_diagonal_envelope"]
                # Phase 2D: datum_result는 envelope과 독립적으로 노출
                # (정북일조 미적용 zone(상업 등)에서도 datum 표시 가능)
                if lines.get("datum_result"):
                    setback_geometries["datum_result"] = lines["datum_result"]
                    datum = lines["datum_result"]
                    road_widths = [
                        float(r.get("roadWidthM") or r.get("road_width_m") or 0.0)
                        for r in road_frontages
                        if float(r.get("roadWidthM") or r.get("road_width_m") or 0.0) > 0
                    ]
                    if road_widths:
                        road_width = max(road_widths)
                        road_diag_mult = reg.get("road_diagonal_multiplier")
                        setback_geometries["front_road_diagonal_profile"] = {
                            "road_width_m": road_width,
                            "slope": float(road_diag_mult or 1.5),
                            "applies": road_diag_mult is not None,
                            "law_basis": reg.get("road_diagonal_article") or "건축법 시행령 §82 도로사선 기준 참고",
                            "note": reg.get("road_diagonal_rule") or "현행 도로사선은 삭제/가로구역별 높이제한으로 대체. 1:1.5는 참고 단면.",
                            "road_datum_m": datum.get("road_datum_m"),
                            "parcel_datum_m": datum.get("parcel_datum_m"),
                        }
                    setback_geometries["road_frontages"] = [
                        {
                            "geometry": r.get("geometry"),
                            "roadWidthM": float(r.get("roadWidthM") or r.get("road_width_m") or 0.0),
                            "sharedEdge": r.get("sharedEdge") or r.get("shared_edge"),
                            "roadCenterline": r.get("roadCenterline") or r.get("road_centerline"),
                            "landCategory": r.get("landCategory") or r.get("land_category"),
                        }
                        for r in road_frontages
                    ][:5]
                    setback_geometries["neighbor_parcels"] = [
                        {
                            "geometry": n.get("geometry"),
                            "sharedEdge": n.get("sharedEdge") or n.get("shared_edge"),
                            "landCategory": n.get("landCategory") or n.get("land_category"),
                            "pnu": n.get("pnu"),
                        }
                        for n in neighbor_parcels
                    ][:10]
            except Exception as e:
                logger.warning(f"setback_geometry failed, falling back: {e}")
                # Fallback: simple buffer
                setback_m = reg.get("adjacent_setback_m")
                if setback_m:
                    geom = compute_setback_geometry(site_geojson, float(setback_m))
                    if geom:
                        setback_geometries["adjacent_setback"] = {
                            "geometry": geom,
                            "distance_m": float(setback_m),
                            "label": f"인접대지 이격 {setback_m}m",
                        }

        return JsonResponse({
            "zones": zone_names,
            "regulations": {
                "bcr_pct": reg.get("bcr_pct"),
                "far_pct": reg.get("far_pct"),
                "height_limit_m": reg.get("height_limit_m"),
                "adjacent_setback_m": reg.get("adjacent_setback_m"),
                "sunlight_applies": reg.get("sunlight_applies"),
                "sunlight_rules": reg.get("sunlight_rules"),
                "corner_cutoff_required": reg.get("corner_cutoff_required"),
                "road_diagonal_multiplier": reg.get("road_diagonal_multiplier"),
                "road_diagonal_rule": reg.get("road_diagonal_rule"),
                "road_diagonal_article": reg.get("road_diagonal_article"),
                "daylight_diagonal_multiplier": reg.get("daylight_diagonal_multiplier"),
                "zone_category": reg.get("zone_category"),
            },
            "constraints": constraints,
            "setback_geometries": setback_geometries,
            "law_articles": law_articles,
            "building_type": building_type,
        })

    except ImportError:
        logger.warning("land app not available for constraint generation")
        return JsonResponse({
            "zones": zones,
            "regulations": {},
            "constraints": [],
            "warning": "land app not available",
        })
    except Exception as e:
        logger.error(f"Auto-constraints failed: {e}")
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def validate_job(request, job_id):
    """
    POST /design/jobs/<id>/validate/ — Validate designs against building regulations.

    Body: {
        "regulation_result": {bcr_pct, far_pct, height_limit_m, adjacent_setback_m, ...}
    }

    Returns validation results + tightened constraints if violations found.
    """
    try:
        job = OptimizationJob.objects.get(id=job_id)
    except OptimizationJob.DoesNotExist:
        return JsonResponse({"error": "Job not found"}, status=404)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    regulation_result = body.get("regulation_result", {})
    if not regulation_result:
        return JsonResponse({"error": "regulation_result is required"}, status=400)

    # Get top pareto designs
    pareto_designs = job.results.filter(is_pareto_optimal=True)
    if not pareto_designs.exists():
        return JsonResponse({"error": "No pareto designs found. Run optimization first."}, status=400)

    # Extract metrics from stored design outputs
    designs_metrics = []
    for d in pareto_designs[:5]:
        outputs = d.outputs or {}
        objectives = outputs.get("objectives", [])
        # Map from job_spec output order to named metrics
        output_defs = job.job_spec.get("outputs", [])
        metrics = {}
        for i, obj_def in enumerate(output_defs):
            if i < len(objectives):
                metrics[obj_def["name"]] = objectives[i]
        designs_metrics.append(metrics)

    # Validate
    result = validate_best_designs(designs_metrics, regulation_result)

    # If violations exist, suggest tightened constraints
    tightened = None
    if not result["all_valid"] and result["worst_violations"]:
        current_constraints = list(job.constraints or [])
        tightened = auto_correct_constraints(result["worst_violations"], current_constraints)

    return JsonResponse({
        "job_id": str(job_id),
        "all_valid": result["all_valid"],
        "violations": result["violations"],
        "worst_violations": result["worst_violations"],
        "tightened_constraints": tightened,
    })


from backend.app.adapters.planm_agent import PlanmClient


@csrf_exempt
@require_http_methods(["POST"])
def create_floor_plan(request):
    """
    POST /design/floor-plan/

    Proxy to the Plan Agent (agents/planm): the floor-plan algorithms (ga, subdivision,
    mcts, packing, graph2plan) live there. The body is forwarded unchanged; the reply
    carries the agent's receipt of exactly that body and design_acceptance: not_verified.
    """
    try:
        body = json.loads(request.body)
        if not isinstance(body, dict):
            raise ValueError("Expected a JSON object")
    except (json.JSONDecodeError, ValueError, TypeError):
        return JsonResponse({"error": "Expected a finite JSON object"}, status=400)
    if not body.get("footprint_geojson"):
        return JsonResponse({"error": "footprint_geojson is required"}, status=400)
    if not body.get("rooms"):
        return JsonResponse({"error": "rooms list is required"}, status=400)
    try:
        result = PlanmClient().generate(body)
    except TimeoutError as exc:
        return JsonResponse({"error": str(exc)}, status=504)
    except (RuntimeError, ValueError) as exc:
        logger.warning("Plan Agent unavailable for floor-plan: %s", exc)
        return JsonResponse({"error": f"Plan Agent unavailable: {exc}"}, status=502)
    if "error" in result:
        return JsonResponse(result, status=422)
    return JsonResponse(result)


@csrf_exempt
@require_http_methods(["POST"])
def constraints_visualize(request):
    """POST /design/constraints/visualize/ — site polygon + 법규 한도 → envelope/setback GeoJSON.

    Flexity 광고 스타일: 대지경계선 + 대지 안의 공지(빨간 점선) + 정북 일조 base(녹색 점선) +
    sunlight slope metadata + 법규 한도 라벨.
    """
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    site_polygon_geojson = body.get("site_polygon")
    if not site_polygon_geojson:
        return JsonResponse({"error": "site_polygon is required"}, status=400)

    try:
        site_polygon = geojson_to_polygon(site_polygon_geojson)
    except Exception as e:
        return JsonResponse({"error": f"Invalid site_polygon: {e}"}, status=400)

    from backend.app.modules.design.generation.services.mass_renderer import constraint_envelope_geojson

    kwargs = {
        k: body[k] for k in (
            "bcr_limit_pct", "far_limit_pct", "height_limit_m",
            "adjacent_setback_m", "north_setback_m", "road_setback_m",
            "sunlight_slope", "sunlight_base_height_m",
        ) if k in body
    }

    try:
        result = constraint_envelope_geojson(site_polygon, **kwargs)
    except Exception as e:
        logger.exception("constraint_envelope_geojson failed")
        return JsonResponse({"error": str(e)}, status=500)

    return JsonResponse(result)
