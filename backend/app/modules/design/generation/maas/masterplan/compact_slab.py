"""Explicit compact excavation alternatives from already drawn level geometry.

This does not edit a plan or establish structural/permit feasibility. The caller
must retain the original alternative and independently validate any selection.
"""
from __future__ import annotations

import math

from shapely.geometry import shape
from shapely.ops import unary_union
from backend.app.modules.design.generation.maas.masterplan.geometry import EPS


REQUIRED_LAYERS = frozenset({
    "parking_stall", "parking_aisle", "vehicular_access", "ramp",
    "building_core", "column", "basement_plant_zone", "basement_room",
})


def compact_slab_candidate(features, *, level, envelope, wall_clearance_m=None):
    """Return a contained convex slab proposal, never a clipped/shrunken plan.

    `envelope` is the authorized excavation envelope as a Shapely polygon.
    Optional wall clearance is a caller-declared geometric allowance, not a
    structural wall design. Missing clearances remain explicit review items.
    Level-specific core, column, plant and access reservations must be drawn by
    the caller; missing programme cannot be inferred from parking geometry.
    """
    if not isinstance(level, int) or isinstance(level, bool) or level >= 0:
        raise ValueError("compact slab requires a negative integer basement level")
    if wall_clearance_m is not None:
        if isinstance(wall_clearance_m, bool):
            raise ValueError("wall clearance must be a finite nonnegative distance")
        wall_clearance_m = float(wall_clearance_m)
        if not math.isfinite(wall_clearance_m) or wall_clearance_m < 0:
            raise ValueError("wall clearance must be a finite nonnegative distance")
    if envelope.is_empty or not envelope.is_valid or envelope.geom_type not in {"Polygon", "MultiPolygon"}:
        raise ValueError("excavation envelope must be a valid polygon")
    required, old_slabs, layers = [], [], set()
    for feat in features:
        props = feat.get("properties") or {}
        if props.get("level", 0) != level:
            continue
        layer = props.get("layer")
        if layer not in REQUIRED_LAYERS and layer != "basement_boundary":
            continue
        geom = shape(feat["geometry"])
        if geom.is_empty or not geom.is_valid or geom.geom_type not in {"Polygon", "MultiPolygon"}:
            raise ValueError(f"{layer} must have valid nonempty polygon geometry")
        if layer == "basement_boundary":
            old_slabs.append(geom)
        else:
            required.append(geom)
            layers.add(layer)
    base = {"level": level, "polygon": None, "status": "no_candidate"}
    if not required:
        return {**base, "reason": "no declared geometry on this basement level"}
    occupied = unary_union(required)
    slab = occupied.convex_hull
    mandatory = occupied
    if wall_clearance_m:
        slab = slab.buffer(wall_clearance_m, join_style=2)
        mandatory = occupied.buffer(wall_clearance_m, join_style=2)
    if not envelope.buffer(EPS).covers(slab):
        clipped=slab.intersection(envelope)
        # Only unused envelope corners may be removed. Retain every required
        # object and authored wall allowance, and a single connected slab.
        if (clipped.geom_type!='Polygon' or not clipped.is_valid
                or not clipped.buffer(EPS).covers(mandatory)):
            return {**base, "reason": "convex slab exceeds excavation envelope"}
        slab=clipped
    old_area = unary_union(old_slabs).area if old_slabs else None
    pending = ["structural_foundation_and_excavation_review", "programme_completeness_review",
               "pedestrian_egress_and_services_review"]
    if wall_clearance_m is None:
        pending.append("wall_clearance_not_declared")
    return {"status": "concept_candidate", "level": level, "polygon": slab,
            "area_m2": slab.area, "original_area_m2": old_area,
            "saved_area_m2": old_area - slab.area if old_area is not None else None,
            "wall_clearance_m": wall_clearance_m, "preserved_layers": sorted(layers),
            "pending_reviews": pending,
            "method": "programme hull within excavation envelope, preserving every object and authored allowance"}
