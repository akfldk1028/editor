"""Conservative identity for raw MOLIT GIS buildings, before tiling or simplification."""
from __future__ import annotations

import hashlib
import json
import math

import shapely
from shapely.geometry import MultiPolygon


def polygon_identity(geometry):
    if geometry is None or geometry.is_empty:
        return None, {"reason": "empty-source"}
    repaired = shapely.make_valid(shapely.force_2d(geometry), method="structure", keep_collapsed=False)
    polygons = []

    def collect(item):
        if item.geom_type == "Polygon" and item.area > 0:
            polygons.append(item)
        elif hasattr(item, "geoms"):
            for part in item.geoms:
                collect(part)

    collect(repaired)
    if not polygons:
        return None, {"reason": "no-positive-area-after-repair"}
    result = polygons[0] if len(polygons) == 1 else MultiPolygon(polygons)
    if not result.is_valid:
        return None, {"reason": "invalid-polygon-after-repair"}
    result = shapely.normalize(result)
    digest = hashlib.sha256(shapely.to_wkb(result, byte_order=1, output_dimension=2)).hexdigest()
    return result, {"geometrySHA256": digest, "areaM2": result.area,
                    "repaired": not geometry.is_valid, "parts": len(polygons)}


def _number(value):
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if math.isfinite(number) else None


def canonical_identity(properties: dict, geometry, *, edition: str, provenance: dict):
    normalized, audit = polygon_identity(geometry)
    if normalized is None:
        return {"rejected": audit, "provenance": [provenance]}
    gis_id = str(properties.get("A1") or "").strip()
    attributes = {"pnu": str(properties.get("A2") or "").strip(),
                  "use": str(properties.get("A8") or "").strip(),
                  "sourceHeight": _number(properties.get("A16")),
                  "storeys": _number(properties.get("A26")),
                  "basementStoreys": _number(properties.get("A27"))}
    key = "gis:" + hashlib.sha256(json.dumps([gis_id, audit["geometrySHA256"]], separators=(",", ":")).encode()).hexdigest()
    return {"key": key, "gisID": gis_id, "edition": edition, "attributes": attributes,
            "geometry": normalized, "audit": audit, "provenance": [provenance]}


def merge_identical(left: dict, right: dict):
    if "rejected" in left or "rejected" in right or left["key"] != right["key"]:
        return None
    if left["edition"] != right["edition"]:
        raise ValueError("Different source editions require explicit snapshot selection")
    if left["attributes"] != right["attributes"]:
        raise ValueError("Identical geometry has conflicting physical attributes; explicit reconciliation required")
    # Administrative name/code corrections do not create another physical building.
    unique = {json.dumps(p, sort_keys=True, ensure_ascii=False): p for p in left["provenance"] + right["provenance"]}
    return {**left, "provenance": [unique[k] for k in sorted(unique)]}
