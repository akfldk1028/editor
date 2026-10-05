"""Geometry mutations for direct MAAS operations."""

from __future__ import annotations

import math
from typing import Any

from shapely.affinity import scale as shapely_scale
from shapely.geometry import Polygon, mapping
from shapely.geometry.polygon import orient

from backend.app.modules.design.generation.maas.interactive.schemas import MassOperation
from backend.app.modules.design.generation.services.site_geometry import geojson_to_polygon, utm_to_wgs84, wgs84_to_utm


def _feature_with_geometry(feature: dict[str, Any], geometry_utm) -> dict[str, Any]:
    out = dict(feature)
    out["geometry"] = mapping(utm_to_wgs84(geometry_utm))
    out["properties"] = dict(feature.get("properties") or {})
    return out


def _sync_maas_model(props: dict[str, Any]) -> None:
    """Keep the canonical maas_model aligned with compatibility fields."""
    model = dict(props.get("maas_model") or {})
    if not model:
        return
    if "floor_plates" in props:
        model["floor_plates"] = props.get("floor_plates") or []
    if "mass_volumes" in props:
        model["volumes"] = props.get("mass_volumes") or []
    metrics = dict(model.get("legal_metrics") or {})
    for key in ("far", "bcr", "height", "num_floors", "footprint_area", "floor_area", "min_setback", "open_pct"):
        if key in props:
            metrics[key] = props.get(key)
    model["legal_metrics"] = metrics
    props["maas_model"] = model


def scale_footprint(feature: dict[str, Any], factor: float) -> tuple[dict[str, Any], list[str]]:
    geom = wgs84_to_utm(geojson_to_polygon(feature.get("geometry")))
    factor = max(0.5, min(1.8, factor))
    scaled = shapely_scale(geom, xfact=factor, yfact=factor, origin="centroid")
    return _feature_with_geometry(feature, scaled), [f"geometry_agent: footprint scaled by factor={factor:.3f}"]


def push_pull_seed(feature: dict[str, Any], operation: MassOperation) -> tuple[dict[str, Any], list[str]]:
    props = dict(feature.get("properties") or {})
    floor_height = float(props.get("floor_height") or 2.8)
    if operation.delta_floors is not None:
        delta_floors = operation.delta_floors
    elif operation.delta_m is not None:
        delta_floors = int(round(operation.delta_m / max(floor_height, 0.1)))
    else:
        delta_floors = 0
    floors = max(1, int(round(float(props.get("num_floors") or 1))) + delta_floors)
    props["num_floors"] = floors
    props["height"] = round(floors * floor_height, 2)
    _sync_maas_model(props)
    out = dict(feature)
    out["properties"] = props
    return out, [f"geometry_agent: push/pull target={operation.target.kind} delta_floors={delta_floors}"]


def trim_floor_plates(feature: dict[str, Any], operation: MassOperation, site_area_m2: float) -> tuple[dict[str, Any], list[str]] | None:
    props = dict(feature.get("properties") or {})
    model = props.get("maas_model") if isinstance(props.get("maas_model"), dict) else {}
    plates = list((model or {}).get("floor_plates") or props.get("floor_plates") or [])
    if not plates:
        return None
    delta = operation.delta_floors
    if delta is None and operation.delta_m is not None:
        floor_height = float(props.get("floor_height") or 2.8)
        delta = int(round(operation.delta_m / max(floor_height, 0.1)))
    if delta is None or delta >= 0:
        return None
    keep_count = max(1, len(plates) + delta)
    kept = plates[:keep_count]
    floor_area = sum(float(p.get("area") or 0.0) for p in kept)
    footprint_area = float(props.get("footprint_area") or 0.0)
    props["floor_plates"] = kept
    if props.get("mass_volumes"):
        kept_top = float(kept[-1].get("top_height") or 0.0)
        volumes = []
        for volume in props.get("mass_volumes") or []:
            next_volume = dict(volume)
            top = float(next_volume.get("top_height") or 0.0)
            bottom = float(next_volume.get("bottom_height") or 0.0)
            if bottom >= kept_top:
                continue
            if top > kept_top:
                next_volume["top_height"] = round(kept_top, 2)
            volumes.append(next_volume)
        props["mass_volumes"] = volumes
    props["num_floors"] = keep_count
    props["height"] = kept[-1].get("top_height")
    props["floor_area"] = round(floor_area, 2)
    if site_area_m2 > 0:
        props["far"] = round(floor_area / site_area_m2 * 100.0, 2)
        props["bcr"] = round(footprint_area / site_area_m2 * 100.0, 2)
    _sync_maas_model(props)
    out = dict(feature)
    out["properties"] = props
    return out, [f"geometry_agent: legal floor plate stack trimmed by {delta} floors"]


def offset_edge(feature: dict[str, Any], operation: MassOperation) -> tuple[dict[str, Any], list[str]]:
    edge_index = operation.target.edge_index
    if edge_index is None:
        raise ValueError("offset_edge requires target.edge_index")
    delta_m = float(operation.delta_m or 0.0)
    if abs(delta_m) < 0.01:
        raise ValueError("offset_edge requires a non-zero delta_m")

    poly = orient(wgs84_to_utm(geojson_to_polygon(feature.get("geometry"))), sign=1.0)
    coords = list(poly.exterior.coords)[:-1]
    if len(coords) < 3:
        raise ValueError("mass geometry must have at least 3 vertices")
    i = edge_index % len(coords)
    j = (i + 1) % len(coords)
    ax, ay = coords[i]
    bx, by = coords[j]
    dx = bx - ax
    dy = by - ay
    length = math.hypot(dx, dy)
    if length < 0.01:
        raise ValueError("selected edge is too short")

    # With a CCW polygon the interior is on the left side of each edge, so the
    # outward normal is the right-hand normal.
    nx, ny = dy / length, -dx / length
    shifted = list(coords)
    shifted[i] = (ax + nx * delta_m, ay + ny * delta_m)
    shifted[j] = (bx + nx * delta_m, by + ny * delta_m)
    candidate = Polygon(shifted)
    if not candidate.is_valid:
        candidate = candidate.buffer(0)
    if candidate.is_empty or candidate.area < 1.0:
        raise ValueError("offset_edge produced an invalid footprint")
    return _feature_with_geometry(feature, candidate), [
        f"geometry_agent: edge {i} offset by {delta_m:.2f}m before legal repair"
    ]


def mutate_seed(feature: dict[str, Any], operation: MassOperation) -> tuple[dict[str, Any], list[str]]:
    if operation.type == "scale_footprint":
        return scale_footprint(feature, operation.factor or 1.0)
    if operation.type == "push_pull_face":
        return push_pull_seed(feature, operation)
    if operation.type == "offset_edge":
        return offset_edge(feature, operation)
    if operation.type == "reshape_floor_plate":
        return scale_footprint(feature, operation.factor or 1.0)
    raise ValueError(f"unsupported operation {operation.type}")


__all__ = ["mutate_seed", "offset_edge", "push_pull_seed", "scale_footprint", "trim_floor_plates"]
