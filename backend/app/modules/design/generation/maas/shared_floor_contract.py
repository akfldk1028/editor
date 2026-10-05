"""One authoritative floor-plate contract for MASS downstream evidence."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from typing import Any, Sequence

from shapely import intersection
from shapely.errors import GEOSException
from shapely.geometry import MultiPolygon, Polygon, mapping
from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.source_geometry.ir import SourceMass
from backend.app.modules.design.generation.maas.source_geometry.polygon_quality import repair_source_polygon
from backend.app.modules.design.generation.maas.floor_viability import evaluate_floor_section_viability, minimum_usable_floor_area_m2


SCHEMA_VERSION = "arr.maas.shared_floor_contract.v1"


def _seal_contract(payload: dict[str, Any]) -> dict[str, Any]:
    """Hash the contract without recursively hashing its previous seal."""

    sealed = deepcopy(payload)
    sealed.pop("floor_contract_hash", None)
    for plate in sealed.get("plates") or ():
        if isinstance(plate, dict):
            plate.pop("floor_contract_hash", None)
    contract_hash = sha256(
        json.dumps(
            sealed,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    sealed["floor_contract_hash"] = contract_hash
    for plate in sealed.get("plates") or ():
        if isinstance(plate, dict):
            plate["floor_contract_hash"] = contract_hash
    return sealed


def bind_shared_floor_contract_capacity(
    contract: dict[str, Any],
    capacity_alternative: dict[str, Any] | None,
) -> dict[str, Any]:
    """Attach the measured requested/realized capacity band and reseal."""

    if contract.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("shared-floor capacity binding requires the v1 contract")
    payload = deepcopy(contract)
    payload["capacity_alternative"] = deepcopy(capacity_alternative or {})
    return _seal_contract(payload)


def _repair_polygonal(
    geometry: Any,
    *,
    minimum_area: float,
) -> Polygon | MultiPolygon | None:
    """Repair every polygonal component without filling holes or dropping wings."""

    if geometry is None or geometry.is_empty:
        return None
    candidate = geometry if geometry.is_valid else geometry.buffer(0)
    if candidate.is_empty:
        return None
    parts: list[Polygon] = []

    def collect(value: Any) -> None:
        if isinstance(value, Polygon):
            repaired = repair_source_polygon(
                value,
                minimum_area=minimum_area,
            )
            if repaired is not None:
                parts.append(repaired.normalize())
            return
        for part in getattr(value, "geoms", ()):
            collect(part)

    collect(candidate)
    if not parts:
        return None
    merged = unary_union(parts)
    merged_parts = [
        part.normalize()
        for part in (
            (merged,)
            if isinstance(merged, Polygon)
            else getattr(merged, "geoms", ())
        )
        if isinstance(part, Polygon)
        and not part.is_empty
        and float(part.area) >= minimum_area
    ]
    if not merged_parts:
        return None
    ordered = sorted(merged_parts, key=lambda part: part.wkb_hex)
    return ordered[0] if len(ordered) == 1 else MultiPolygon(ordered)


def materialize_shared_floor_contract(
    source: SourceMass,
    *,
    site_local_utm: Any,
    legal_sections: Sequence[Any | None],
    height_m: float,
    floors: int,
    pnu: str = "",
    program_hash: str = "",
    geometry_hash: str = "",
    floor_capacity_plan_hash: str = "",
    feasible_capacity_m2: float | None = None,
    minimum_clear_depth_m: float = 2.4,
    minimum_support_ratio: float = 0.20,
) -> dict[str, Any]:
    """Intersect one source mass with exact legal sections at every floor."""

    floor_count = max(1, int(floors))
    floor_height = max(0.1, float(height_m) / floor_count)
    site_area = max(float(site_local_utm.area), 1e-9)
    minimum_area = minimum_usable_floor_area_m2(site_area)
    stack = (
        source.metadata.get("floorwise_legal_matrix_stack")
        if isinstance(source.metadata.get("floorwise_legal_matrix_stack"), dict)
        else {}
    )
    target_floor_areas = [
        round(max(0.0, float(value)), 4)
        for value in (stack.get("target_floor_areas_m2") or ())[:floor_count]
    ]
    capacity_alternative = deepcopy(
        source.metadata.get("capacity_alternative_projection")
        if isinstance(
            source.metadata.get("capacity_alternative_projection"),
            dict,
        )
        else {}
    )
    plates: list[dict[str, Any]] = []
    contract_failures: list[str] = []
    previous_occupied = None

    for floor_index in range(floor_count):
        floor_number = floor_index + 1
        bottom_height = floor_index * floor_height
        top_height = floor_number * floor_height
        fraction = (floor_index + 0.5) / floor_count
        active = [
            repaired
            for volume in source.volumes
            for repaired in (
                _repair_polygonal(volume.footprint, minimum_area=0.01),
            )
            if repaired is not None
            if float(volume.bottom_fraction) <= fraction < float(volume.top_fraction)
        ]
        raw_legal = (
            legal_sections[floor_index]
            if floor_index < len(legal_sections)
            else None
        )
        legal = (
            _repair_polygonal(raw_legal, minimum_area=0.01)
            if raw_legal is not None
            else None
        )
        source_union = (
            _repair_polygonal(unary_union(active), minimum_area=0.01)
            if active
            else None
        )
        topology_failed = False
        try:
            raw_occupied = (
                intersection(source_union, legal, grid_size=1e-6)
                if source_union is not None and legal is not None
                else None
            )
            occupied = (
                _repair_polygonal(raw_occupied, minimum_area=0.01)
                if raw_occupied is not None
                else None
            )
            topology_failed = bool(
                raw_occupied is not None
                and not raw_occupied.is_empty
                and occupied is None
            )
        except GEOSException:
            occupied = None
            topology_failed = True
        gross_area = (
            float(occupied.area)
            if occupied is not None and not occupied.is_empty
            else 0.0
        )
        floor_viability = evaluate_floor_section_viability(
            occupied,
            parcel_area_m2=site_area,
            minimum_clear_depth_m=minimum_clear_depth_m,
        )
        clear_core_area = float(
            floor_viability["clear_depth_core_area_m2"]
        )
        source_area = float(source_union.area) if source_union is not None else 0.0
        legal_retention = gross_area / source_area if source_area > 0.0 else 0.0
        try:
            support_ratio = (
                1.0
                if floor_index == 0
                else (
                    float(
                        intersection(
                            occupied,
                            previous_occupied,
                            grid_size=1e-6,
                        ).area
                    ) / max(gross_area, 1e-9)
                    if (
                        occupied is not None
                        and not occupied.is_empty
                        and previous_occupied is not None
                        and not previous_occupied.is_empty
                    )
                    else 0.0
                )
            )
        except GEOSException:
            support_ratio = 0.0
            topology_failed = True
        failures: list[str] = []
        if topology_failed:
            failures.append("invalid_floor_topology")
        if legal is None or legal.is_empty:
            failures.append("missing_legal_floor_plate")
        if "insufficient_floor_area" in floor_viability["failure_reasons"]:
            failures.append("insufficient_floor_area")
        if (
            "insufficient_clear_floor_depth"
            in floor_viability["failure_reasons"]
        ):
            failures.append("insufficient_clear_floor_depth")
        if legal_retention + 1e-9 < 0.80:
            failures.append("floor_outside_legal_envelope")
        if floor_index > 0 and support_ratio + 1e-9 < minimum_support_ratio:
            failures.append("insufficient_vertical_support")
        contract_failures.extend(failures)
        plates.append({
            "floor": floor_number,
            "bottom_height_m": round(bottom_height, 3),
            "top_height_m": round(top_height, 3),
            "legal_geometry_utm": (
                mapping(legal) if legal is not None and not legal.is_empty else None
            ),
            "occupied_geometry_utm": (
                mapping(occupied)
                if occupied is not None and not occupied.is_empty
                else None
            ),
            "gross_area_m2": round(gross_area, 3),
            "target_area_m2": (
                target_floor_areas[floor_index]
                if floor_index < len(target_floor_areas)
                else None
            ),
            "usable_area_m2": round(gross_area if clear_core_area > 1e-6 else 0.0, 3),
            "clear_depth_core_area_m2": round(clear_core_area, 3),
            "minimum_clear_depth_m": round(float(minimum_clear_depth_m), 3),
            "legal_retention_ratio": round(legal_retention, 4),
            "support_ratio": round(support_ratio, 4),
            "hard_pass": not failures,
            "failure_reasons": failures,
        })
        previous_occupied = occupied

    total_floor_area = sum(float(plate["gross_area_m2"]) for plate in plates)
    capacity = max(0.0, float(feasible_capacity_m2 or 0.0))
    identity = {
        "pnu": str(pnu or "PNU_UNRESOLVED"),
        "program_hash": str(program_hash or "PROGRAM_HASH_UNRESOLVED"),
        "geometry_hash": str(geometry_hash or "GEOMETRY_HASH_UNRESOLVED"),
        "floor_capacity_plan_hash": str(floor_capacity_plan_hash or ""),
    }
    unique_failures = list(dict.fromkeys(contract_failures))
    payload = {
        "schema_version": SCHEMA_VERSION,
        "identity": identity,
        "floor_capacity_plan_hash": str(floor_capacity_plan_hash or ""),
        "target_floor_areas_m2": target_floor_areas,
        "capacity_alternative": capacity_alternative,
        "floor_height_m": round(floor_height, 3),
        "minimum_clear_depth_m": round(float(minimum_clear_depth_m), 3),
        "minimum_support_ratio": round(float(minimum_support_ratio), 4),
        "plates": plates,
        "totals": {
            "num_floors": len([plate for plate in plates if plate["hard_pass"]]),
            "requested_floors": floor_count,
            "total_floor_area_m2": round(total_floor_area, 3),
            "far_pct": round(total_floor_area / site_area * 100.0, 3),
            "feasible_capacity_m2": round(capacity, 3),
            "capacity_utilization": (
                round(total_floor_area / capacity, 4) if capacity > 0.0 else None
            ),
        },
        "hard_pass": bool(len(plates) == floor_count and not unique_failures),
        "failure_reasons": unique_failures,
    }
    return _seal_contract(payload)


__all__ = [
    "SCHEMA_VERSION",
    "bind_shared_floor_contract_capacity",
    "materialize_shared_floor_contract",
]
