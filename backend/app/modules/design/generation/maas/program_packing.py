"""Program packing summaries for legal MAAS floor groups.

Legal envelope generation decides where mass is allowed. This module applies
the existing room-packing algorithm inside each accepted floor group, so agents
can reason about cores, units, and usable program without weakening legal
constraints.
"""

from __future__ import annotations

from typing import Any

from shapely.geometry import mapping, shape

from backend.app.modules.design.generation.services.floor_packing import packing_floor_plan
from backend.app.modules.design.generation.services.site_geometry import geojson_to_polygon, utm_to_wgs84, wgs84_to_utm
from backend.app.modules.design.generation.maas.program_massing.profiles import resolve_program_profile


def _program_template(building_type: str, typical_area: float) -> list[dict[str, Any]]:
    """Return a compact room program scaled to one typical floor."""
    label = building_type or ""
    usable = max(typical_area * 0.82, 1.0)
    profile_id = resolve_program_profile(label)["id"]

    if profile_id == "gymnasium":
        return _fit_program([
            {"name": "sports_hall", "area": max(48.0, usable * 0.62), "adjacency": ["entry", "storage"]},
            {"name": "entry", "area": max(12.0, usable * 0.12), "adjacency": ["sports_hall", "changing"]},
            {"name": "changing", "area": max(12.0, usable * 0.12), "adjacency": ["entry", "sports_hall"]},
            {"name": "storage", "area": max(8.0, usable * 0.08), "adjacency": ["sports_hall"]},
        ], usable)

    if profile_id == "cafe":
        return _fit_program([
            {"name": "public_seating", "area": max(20.0, usable * 0.46), "adjacency": ["counter", "terrace"]},
            {"name": "counter", "area": max(8.0, usable * 0.16), "adjacency": ["public_seating", "kitchen"]},
            {"name": "kitchen", "area": max(8.0, usable * 0.16), "adjacency": ["counter", "service"]},
            {"name": "terrace", "area": max(10.0, usable * 0.14), "adjacency": ["public_seating"]},
            {"name": "service", "area": max(4.0, usable * 0.06), "adjacency": ["kitchen"]},
        ], usable)

    if "업무" in label or "오피스" in label:
        return _fit_program([
            {"name": "core", "area": max(18.0, usable * 0.18), "adjacency": ["lobby", "workspace"]},
            {"name": "lobby", "area": max(10.0, usable * 0.10), "adjacency": ["core", "workspace"]},
            {"name": "workspace", "area": max(24.0, usable * 0.46), "adjacency": ["core", "meeting"]},
            {"name": "meeting", "area": max(10.0, usable * 0.12), "adjacency": ["workspace"]},
            {"name": "service", "area": max(8.0, usable * 0.08), "adjacency": ["core"]},
        ], usable)

    if "주택" in label or "생활" in label or "공동" in label:
        return _fit_program([
            {"name": "core", "area": max(16.0, usable * 0.16), "adjacency": ["corridor"]},
            {"name": "corridor", "area": max(12.0, usable * 0.13), "adjacency": ["core", "unit_a", "unit_b"]},
            {"name": "unit_a", "area": max(24.0, usable * 0.28), "adjacency": ["corridor"]},
            {"name": "unit_b", "area": max(24.0, usable * 0.28), "adjacency": ["corridor"]},
            {"name": "service", "area": max(7.0, usable * 0.06), "adjacency": ["core"]},
        ], usable)

    return _fit_program([
        {"name": "core", "area": max(16.0, usable * 0.18), "adjacency": ["public"]},
        {"name": "public", "area": max(18.0, usable * 0.22), "adjacency": ["core", "program"]},
        {"name": "program", "area": max(28.0, usable * 0.38), "adjacency": ["public", "service"]},
        {"name": "service", "area": max(8.0, usable * 0.10), "adjacency": ["core", "program"]},
    ], usable)


def _fit_program(rooms: list[dict[str, Any]], target_area: float) -> list[dict[str, Any]]:
    """Scale template room areas so packing is not asked to exceed the plate."""
    total = sum(float(room.get("area") or 0.0) for room in rooms)
    if total <= 0 or total <= target_area:
        return rooms
    scale = target_area / total
    return [
        {
            **room,
            "area": round(max(1.0, float(room.get("area") or 0.0) * scale), 2),
        }
        for room in rooms
    ]


def attach_program_packing(
    floor_groups: list[dict[str, Any]],
    *,
    building_type: str,
    cell_size_m: float = 3.0,
) -> list[dict[str, Any]]:
    """Attach deterministic packing summaries to each legal floor group."""
    packed: list[dict[str, Any]] = []
    for group in floor_groups:
        enriched = dict(group)
        floor_count = max(int(group.get("floor_count") or 1), 1)
        typical_area = float(group.get("area") or 0.0) / floor_count
        rooms = _program_template(building_type, typical_area)
        packing = {
            "stage": "post_legal_floor_group_packing",
            "algorithm": "circle_grid_packing",
            "constraint_source": "maas_legal_envelope",
            "typical_floor_area": round(typical_area, 2),
            "cell_size": cell_size_m,
            "rooms": rooms,
            "status": "pending",
        }
        try:
            if typical_area < 24.0:
                packing["status"] = "skipped_small_program"
                enriched["program_packing"] = packing
                packed.append(enriched)
                continue
            footprint = wgs84_to_utm(geojson_to_polygon(group.get("geometry")))
            if footprint.is_empty or footprint.area < cell_size_m * cell_size_m:
                packing["status"] = "skipped_small_footprint"
            else:
                result = packing_floor_plan(
                    footprint,
                    rooms,
                    cell_size=cell_size_m,
                    options={
                        "num_runs": 2,
                        "max_iterations": 80,
                        "seed": 4100 + int(group.get("group") or 0),
                    },
                )
                best = (result.get("results") or [{}])[0]
                best_floor_plan = _floor_plan_to_wgs84(best.get("floor_plan"))
                metrics = best.get("metrics", {})
                packing.update({
                    "status": "ok",
                    "grid": result.get("grid_info"),
                    "best_metrics": metrics,
                    "best_floor_plan": best_floor_plan,
                    "preview_summary": _preview_summary(best_floor_plan, metrics),
                    "result_count": result.get("num_results", 0),
                })
        except Exception as exc:
            packing.update({"status": "failed", "error": str(exc)[:160]})
        enriched["program_packing"] = packing
        packed.append(enriched)
    return packed


def _floor_plan_to_wgs84(floor_plan: dict[str, Any] | None) -> dict[str, Any] | None:
    """Convert UTM room polygons back to WGS84 for frontend/agent use."""
    if not isinstance(floor_plan, dict):
        return None
    features = []
    for feature in floor_plan.get("features") or []:
        try:
            geom = utm_to_wgs84(shape(feature.get("geometry")))
            features.append({
                "type": "Feature",
                "properties": dict(feature.get("properties") or {}),
                "geometry": mapping(geom),
            })
        except Exception:
            continue
    return {"type": "FeatureCollection", "features": features}


def _preview_summary(
    floor_plan: dict[str, Any] | None,
    metrics: dict[str, Any],
) -> dict[str, Any]:
    features = floor_plan.get("features") if isinstance(floor_plan, dict) else []
    room_names = [
        str((feature.get("properties") or {}).get("room_name"))
        for feature in features
        if (feature.get("properties") or {}).get("room_name")
    ]
    return {
        "room_count": len(room_names),
        "room_names": room_names,
        "adjacency_score": round(float(metrics.get("adjacency_score") or 0.0), 3),
        "area_error": round(float(metrics.get("area_error") or 0.0), 3),
        "compactness": round(float(metrics.get("compactness") or 0.0), 3),
    }


__all__ = ["attach_program_packing"]
