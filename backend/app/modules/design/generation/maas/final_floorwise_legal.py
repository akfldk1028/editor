"""Fail-closed floorwise legality for MAAS review candidates."""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Any

from shapely.geometry import Polygon, mapping
from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.floor_groups import build_floor_groups
from backend.app.modules.design.generation.maas.legal_envelope import LegalEnvelope, allowed_footprint_at_height, failed_constraint_metrics
from backend.app.modules.design.generation.maas.geometry_language.source_bridge import materialize_floorwise_legal_source
from backend.app.modules.design.generation.maas.source_geometry import SourceMass, SourceVolume, evaluate_source_volume_coherence
from backend.app.modules.design.generation.services.site_geometry import geojson_to_polygon, utm_to_wgs84, wgs84_to_utm


_AREA_TOLERANCE_M2 = 0.05
_MIN_OCCUPIED_AREA_M2 = 1.0
_HEIGHT_ALIGNMENT_TOLERANCE_M = 0.11


def _largest_areal_polygon(geometry):
    if isinstance(geometry, Polygon):
        return geometry
    polygons = [
        polygon
        for item in getattr(geometry, "geoms", ())
        for polygon in (
            [item]
            if isinstance(item, Polygon)
            else list(getattr(item, "geoms", ()))
        )
        if isinstance(polygon, Polygon) and not polygon.is_empty
    ]
    return max(polygons, key=lambda polygon: polygon.area) if polygons else None


@dataclass(frozen=True)
class FloorwiseLegalResult:
    feature: dict[str, Any] | None
    evidence: dict[str, Any]
    authored_source: SourceMass | None = None


def _polygon(value: Any):
    if not isinstance(value, dict):
        return None
    try:
        polygon = wgs84_to_utm(geojson_to_polygon(value))
    except Exception:
        return None
    if polygon.is_empty:
        return None
    if not isinstance(polygon, Polygon):
        polygon = _largest_areal_polygon(polygon)
    if polygon is None:
        return None
    return polygon if polygon.area >= _MIN_OCCUPIED_AREA_M2 else None


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _canonical_volumes(feature: dict[str, Any]) -> list[dict[str, Any]]:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    model = props.get("maas_model") if isinstance(props.get("maas_model"), dict) else {}
    volumes = props.get("mass_volumes")
    if not isinstance(volumes, list):
        volumes = model.get("volumes")
    return [item for item in volumes or [] if isinstance(item, dict)]


def _explicit_plates(feature: dict[str, Any]) -> list[dict[str, Any]]:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    model = props.get("maas_model") if isinstance(props.get("maas_model"), dict) else {}
    plates = props.get("floor_plates")
    if not isinstance(plates, list):
        plates = model.get("floor_plates")
    return [item for item in plates or [] if isinstance(item, dict)]


def _occupied_sections_from_volumes(
    volumes: list[dict[str, Any]],
    *,
    floor_height: float,
) -> tuple[list[tuple[int, float, Any, list[str]]], list[str]]:
    parsed: list[tuple[float, float, Any, str]] = []
    failed_checks: list[str] = []
    for index, volume in enumerate(volumes):
        bottom = _float(volume.get("bottom_height"))
        top = _float(volume.get("top_height"))
        polygon = _polygon(volume.get("geometry"))
        if bottom is None or top is None or top <= bottom or polygon is None:
            failed_checks.append(f"invalid_mass_volume:{index}")
            continue
        bottom_grid = round(bottom / floor_height) * floor_height
        top_grid = round(top / floor_height) * floor_height
        if (
            abs(bottom - bottom_grid) > _HEIGHT_ALIGNMENT_TOLERANCE_M
            or abs(top - top_grid) > _HEIGHT_ALIGNMENT_TOLERANCE_M
        ):
            failed_checks.append(f"non_floor_aligned_mass_volume:{index}")
            continue
        parsed.append((bottom, top, polygon, str(volume.get("role") or "morphology_volume")))
    if failed_checks or not parsed:
        return [], failed_checks or ["missing_mass_volume_sections"]

    maximum_height = max(top for _, top, _, _ in parsed)
    floor_count = max(1, int(math.ceil(maximum_height / floor_height - 1e-9)))
    sections: list[tuple[int, float, Any, list[str]]] = []
    for floor in range(1, floor_count + 1):
        top_height = floor * floor_height
        sample_height = top_height - min(0.001, floor_height * 0.0001)
        active = [
            (polygon, role)
            for bottom, top, polygon, role in parsed
            if bottom <= sample_height + 1e-7 and top >= sample_height - 1e-7
        ]
        if not active:
            has_higher_occupancy = any(
                top > top_height + _HEIGHT_ALIGNMENT_TOLERANCE_M
                for _, top, _, _ in parsed
            )
            if has_higher_occupancy:
                return [], [f"vertical_occupancy_gap_before_floor:{floor}"]
            if sections:
                break
            return [], [f"no_occupied_section_at_floor:{floor}"]
        occupied = unary_union([polygon for polygon, _ in active])
        if not isinstance(occupied, Polygon):
            occupied = _largest_areal_polygon(occupied)
        if occupied is None:
            return [], [f"non_polygon_occupied_section_at_floor:{floor}"]
        sections.append((floor, top_height, occupied, sorted({role for _, role in active})))
    return sections, []


def _occupied_sections_from_plates(
    plates: list[dict[str, Any]],
) -> tuple[list[tuple[int, float, Any, list[str]]], list[str]]:
    sections: list[tuple[int, float, Any, list[str]]] = []
    failed_checks: list[str] = []
    for index, plate in enumerate(plates):
        floor = int(plate.get("floor") or index + 1)
        top_height = _float(plate.get("top_height"))
        polygon = _polygon(plate.get("geometry"))
        if top_height is None or top_height <= 0 or polygon is None:
            failed_checks.append(f"invalid_floor_plate:{index}")
            continue
        sections.append((floor, top_height, polygon, ["floor_plate"]))
    if failed_checks or not sections:
        return [], failed_checks or ["missing_floor_plates"]
    sections.sort(key=lambda item: (item[1], item[0]))
    return sections, []


def _plates_cover_claimed_occupancy(
    plates: list[dict[str, Any]],
    volumes: list[dict[str, Any]],
    *,
    claimed_height: float,
    floor_height: float,
) -> bool:
    if not plates:
        return False
    floors: list[int] = []
    tops: list[float] = []
    for index, plate in enumerate(plates):
        try:
            floors.append(int(plate.get("floor") or index + 1))
        except (TypeError, ValueError):
            return False
        top = _float(plate.get("top_height"))
        if top is None:
            return False
        expected_top = (index + 1) * floor_height
        if abs(top - expected_top) > _HEIGHT_ALIGNMENT_TOLERANCE_M:
            return False
        tops.append(top)
    if floors != list(range(1, len(plates) + 1)):
        return False
    if any(current <= previous for previous, current in zip(tops, tops[1:])):
        return False
    volume_tops = [
        top
        for volume in volumes
        for top in [_float(volume.get("top_height"))]
        if top is not None
    ]
    occupied_height = max([claimed_height, *volume_tops], default=claimed_height)
    expected_floor_count = max(1, int(math.ceil(occupied_height / floor_height - 1e-9)))
    return (
        len(plates) == expected_floor_count
        and abs(tops[-1] - expected_floor_count * floor_height)
        <= _HEIGHT_ALIGNMENT_TOLERANCE_M
        and tops[-1] + _HEIGHT_ALIGNMENT_TOLERANCE_M >= occupied_height
    )


def _reject(
    *,
    source: str,
    failed_checks: list[str],
    checked_floor_count: int,
    original_height_m: float,
) -> FloorwiseLegalResult:
    return FloorwiseLegalResult(
        feature=None,
        evidence={
            "schema_version": "arr.maas.floorwise_legal.v1",
            "status": "fail",
            "source": source,
            "failed_checks": failed_checks,
            "checked_floor_count": checked_floor_count,
            "checked_mass_volume_count": 0,
            "original_height_m": round(original_height_m, 2),
        },
    )


def _has_authored_profiled_visual(
    feature: dict[str, Any],
    authored_source: SourceMass | None,
) -> bool:
    if authored_source is not None and any(
        surface.surface_type.startswith("profiled_")
        for surface in authored_source.surfaces
    ):
        return True
    props = feature.get("properties")
    props = props if isinstance(props, dict) else {}
    model = props.get("maas_model")
    model = model if isinstance(model, dict) else {}
    surfaces = props.get("source_surfaces")
    if not isinstance(surfaces, list):
        surfaces = model.get("source_surfaces")
    return any(
        isinstance(surface, dict)
        and str(surface.get("surface_type") or "").startswith("profiled_")
        for surface in surfaces or ()
    )


def _canonical_stack_from_materialized_source(
    source: SourceMass,
    *,
    floor_count: int,
    floor_height: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    total_height = floor_count * floor_height
    plates: list[dict[str, Any]] = []
    volumes: list[dict[str, Any]] = []
    for floor_index in range(floor_count):
        fraction = (floor_index + 0.5) / floor_count
        active = [
            volume.footprint
            for volume in source.volumes
            if (
                float(volume.bottom_fraction) <= fraction
                < float(volume.top_fraction)
            )
        ]
        occupied = unary_union(active) if active else None
        occupied = _largest_areal_polygon(occupied)
        if occupied is None or occupied.area < _MIN_OCCUPIED_AREA_M2:
            return None
        top_height = (floor_index + 1) * floor_height
        geometry = mapping(utm_to_wgs84(occupied))
        plates.append({
            "floor": floor_index + 1,
            "top_height": round(top_height, 2),
            "area": round(float(occupied.area), 2),
            "geometry": geometry,
        })
        volumes.append({
            "band": floor_index,
            "bottom_height": round(floor_index * floor_height, 2),
            "top_height": round(top_height, 2),
            "geometry": geometry,
            "role": "floorwise_legal_mass",
            "source_roles": sorted({
                volume.role
                for volume in source.volumes
                if (
                    float(volume.bottom_fraction) <= fraction
                    < float(volume.top_fraction)
                )
            }),
            "floorwise_legal": True,
        })
    if abs(total_height - float(plates[-1]["top_height"])) > 1e-7:
        return None
    return plates, volumes


def _projected_surface_records(
    source: SourceMass,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for surface in source.surfaces:
        record = surface.signature()
        # The Task-1 certificate hashes eight-decimal projected coordinates.
        # SourceSurface.signature() is a compact three-decimal summary, so it
        # cannot be the renderer/VLM authority for a certified binding.
        record["vertices_m"] = [
            [float(x), float(y), float(z)]
            for x, y, z in surface.vertices_m
        ]
        records.append(record)
    return records


def revalidate_final_floorwise_feature(
    feature: dict[str, Any],
    *,
    envelope: LegalEnvelope,
    sunlight_envelope: dict[str, Any] | None,
    building_type: str,
    authored_source: SourceMass | None = None,
) -> FloorwiseLegalResult:
    """Return a feature whose canonical occupied geometry is legal per floor.

    Existing explicit floor plates are measured directly. Candidates without
    plates are sectioned from their canonical mass-volume bands. Every occupied
    section is clipped to the height-dependent legal footprint and rebound as
    both the explicit plates and canonical mass volumes used downstream.
    """
    candidate = copy.deepcopy(feature)
    props = candidate.get("properties") if isinstance(candidate.get("properties"), dict) else {}
    model = props.get("maas_model") if isinstance(props.get("maas_model"), dict) else {}
    floor_height = _float(props.get("floor_height")) or float(envelope.floor_height)
    if floor_height <= 0:
        return _reject(
            source="unknown",
            failed_checks=["invalid_floor_height"],
            checked_floor_count=0,
            original_height_m=_float(props.get("height")) or 0.0,
        )

    original_height = _float(props.get("height")) or 0.0
    original_plates = _explicit_plates(candidate)
    original_volumes = _canonical_volumes(candidate)
    plates_are_complete = _plates_cover_claimed_occupancy(
        original_plates,
        original_volumes,
        claimed_height=original_height,
        floor_height=floor_height,
    )
    if original_plates and plates_are_complete:
        source = "exact_floor_plates"
        sections, failed_checks = _occupied_sections_from_plates(original_plates)
    elif original_volumes:
        source = (
            "derived_mass_volume_sections_incomplete_explicit_plates"
            if original_plates
            else "derived_mass_volume_sections"
        )
        sections, failed_checks = _occupied_sections_from_volumes(
            original_volumes,
            floor_height=floor_height,
        )
    else:
        source = "incomplete_explicit_floor_plates"
        sections, failed_checks = [], ["incomplete_explicit_floor_plates"]
    if failed_checks:
        return _reject(
            source=source,
            failed_checks=failed_checks,
            checked_floor_count=0,
            original_height_m=original_height,
        )

    repaired = False
    truncation_reasons: list[str] = []
    plates: list[dict[str, Any]] = []
    canonical_volumes: list[dict[str, Any]] = []
    previous_top = 0.0
    for floor, top_height, occupied, roles in sections:
        if top_height > envelope.height_limit + 0.1:
            repaired = True
            truncation_reasons.append(f"height_limit_at_floor:{floor}")
            break
        allowed = allowed_footprint_at_height(envelope, top_height, sunlight_envelope)
        if allowed is None:
            repaired = True
            truncation_reasons.append(f"no_allowed_footprint_at_floor:{floor}")
            break
        legal = occupied.intersection(allowed)
        if legal.is_empty:
            repaired = True
            truncation_reasons.append(f"empty_legal_intersection_at_floor:{floor}")
            break
        if not isinstance(legal, Polygon):
            legal = _largest_areal_polygon(legal)
        if legal is None:
            repaired = True
            truncation_reasons.append(f"non_polygon_legal_intersection_at_floor:{floor}")
            break
        if legal.area < _MIN_OCCUPIED_AREA_M2:
            repaired = True
            truncation_reasons.append(f"undersized_legal_intersection_at_floor:{floor}")
            break
        outside_area = float(occupied.difference(allowed).area)
        if outside_area > _AREA_TOLERANCE_M2:
            repaired = True
        geometry = mapping(utm_to_wgs84(legal))
        plate = {
            "floor": len(plates) + 1,
            "top_height": round(float(top_height), 2),
            "area": round(float(legal.area), 2),
            "geometry": geometry,
        }
        plates.append(plate)
        canonical_volumes.append({
            "band": len(canonical_volumes),
            "bottom_height": round(previous_top, 2),
            "top_height": round(float(top_height), 2),
            "geometry": geometry,
            "role": "floorwise_legal_mass",
            "source_roles": roles,
            "floorwise_legal": True,
        })
        previous_top = float(top_height)

    if not plates:
        return _reject(
            source=source,
            failed_checks=truncation_reasons or ["no_legal_occupied_floor"],
            checked_floor_count=0,
            original_height_m=original_height,
        )

    has_authored_visual = _has_authored_profiled_visual(feature, authored_source)
    rebound_source: SourceMass | None = None
    if has_authored_visual:
        if authored_source is None:
            return _reject(
                source=source,
                failed_checks=[
                    "authored_floorwise_visual_reprojection_failed",
                    "authored_source_unavailable",
                ],
                checked_floor_count=len(plates),
                original_height_m=original_height,
            )
        authored_legal_sections = tuple(
            allowed_footprint_at_height(
                envelope,
                float(plate["top_height"]),
                sunlight_envelope,
            )
            for plate in plates
        )
        if any(section is None for section in authored_legal_sections):
            return _reject(
                source=source,
                failed_checks=[
                    "authored_floorwise_visual_reprojection_failed",
                    "authored_legal_section_unavailable",
                ],
                checked_floor_count=len(plates),
                original_height_m=original_height,
            )
        rebound_source = materialize_floorwise_legal_source(
            authored_source,
            legal_sections=authored_legal_sections,
            target_plan_coverage=0.95,
            floor_capacity_plan_hash=str(
                (
                    authored_source.metadata.get("floorwise_legal_matrix_stack")
                    or {}
                ).get("floor_capacity_plan_hash")
                or ""
            ),
            target_floor_areas_m2=tuple(
                float(plate["area"])
                for plate in plates
            ),
        )
        if rebound_source is None:
            return _reject(
                source=source,
                failed_checks=[
                    "authored_floorwise_visual_reprojection_failed",
                    "authored_visual_projection_not_certified",
                ],
                checked_floor_count=len(plates),
                original_height_m=original_height,
            )
        rebound_stack = _canonical_stack_from_materialized_source(
            rebound_source,
            floor_count=len(plates),
            floor_height=floor_height,
        )
        if rebound_stack is None:
            return _reject(
                source=source,
                failed_checks=[
                    "authored_floorwise_visual_reprojection_failed",
                    "materialized_capacity_stack_invalid",
                ],
                checked_floor_count=len(plates),
                original_height_m=original_height,
            )
        plates, canonical_volumes = rebound_stack
        repaired = True

    ground = _polygon(plates[0]["geometry"])
    if ground is None:
        return _reject(
            source=source,
            failed_checks=["invalid_repaired_ground_plate"],
            checked_floor_count=0,
            original_height_m=original_height,
        )
    site_area = float(envelope.site_area_m2)
    floor_area = sum(float(plate["area"]) for plate in plates)
    footprint_area = float(ground.area)
    props["building_type"] = building_type
    props["floor_height"] = floor_height
    props["num_floors"] = len(plates)
    props["height"] = round(float(plates[-1]["top_height"]), 2)
    props["footprint_area"] = round(footprint_area, 2)
    props["floor_area"] = round(floor_area, 2)
    props["bcr"] = round(footprint_area / site_area * 100.0, 2) if site_area > 0 else 0.0
    props["far"] = round(floor_area / site_area * 100.0, 2) if site_area > 0 else 0.0
    props["min_setback"] = round(float(ground.distance(envelope.site_utm.boundary)), 2)
    props["open_pct"] = round(max(0.0, 100.0 - props["bcr"]), 2)
    props["floor_plates"] = plates
    props["mass_volumes"] = canonical_volumes
    props["floor_groups"] = build_floor_groups(
        plates,
        site_area_m2=site_area,
        building_type=building_type,
    )
    props["typology_bands"] = [
        {
            "role": "floorwise_legal",
            "from_floor": plate["floor"],
            "to_floor": plate["floor"],
            "geometry": plate["geometry"],
        }
        for plate in plates
    ]
    candidate["geometry"] = plates[0]["geometry"]
    props.pop("upper_geometry", None)
    props.pop("lower_height", None)
    props.pop("step_floor", None)

    legal_metrics = {
        key: props.get(key)
        for key in (
            "far",
            "bcr",
            "height",
            "num_floors",
            "footprint_area",
            "floor_area",
            "min_setback",
            "open_pct",
        )
    }
    model["floor_plates"] = plates
    model["floor_groups"] = props["floor_groups"]
    model["volumes"] = canonical_volumes
    model["legal_metrics"] = legal_metrics
    props["maas_model"] = model
    props["source_volumes"] = copy.deepcopy(canonical_volumes)
    model["source_volumes"] = copy.deepcopy(canonical_volumes)
    props.pop("section_source_surfaces", None)
    props.pop("section_profile_materialized", None)
    model.pop("section_source_surfaces", None)
    model.pop("section_profile_materialized", None)
    previous_signature = props.get("source_signature")
    if not isinstance(previous_signature, dict):
        previous_signature = model.get("source_signature")
    previous_signature = previous_signature if isinstance(previous_signature, dict) else {}
    areas = [float(plate["area"]) for plate in plates]
    total_height = max(float(plates[-1]["top_height"]), floor_height)
    typed_volumes = tuple(
        SourceVolume(
            role="floorwise_legal_mass",
            footprint=_polygon(plate["geometry"]),
            bottom_fraction=(index * floor_height) / total_height,
            top_fraction=float(plate["top_height"]) / total_height,
            verb="floorwise_legal_matrix4",
        )
        for index, plate in enumerate(plates)
    )
    coherence = evaluate_source_volume_coherence(typed_volumes)
    intent_keys = (
        "family",
        "formal_principle",
        "dominant_gesture",
        "primary_language",
        "secondary_language",
        "architectural_ambition_evidence",
        "parameter_provenance",
        "parameter_default_count",
        "parameter_authored_count",
        "parameter_default_ratio",
        "rule_prior_param_count",
        "llm_authored_param_count",
        "invalid_rule_param_count",
        "rule_prior_param_ratio",
    )
    if rebound_source is not None:
        source_signature = rebound_source.signature()
        source_signature["status"] = "floorwise_legal_revalidated"
        source_signature["floorwise_legal_revalidated"] = True
        source_signature["design_intent_provenance"] = {
            key: copy.deepcopy(previous_signature[key])
            for key in (
                "family",
                "formal_principle",
                "dominant_gesture",
                "verb_profile",
            )
            if key in previous_signature
        }
        surfaces = _projected_surface_records(
            rebound_source,
        )
        certificate = copy.deepcopy(
            rebound_source.metadata["floorwise_visual_projection"]
        )
        props["source_surfaces"] = surfaces
        model["source_surfaces"] = copy.deepcopy(surfaces)
        props["source_surface_summary"] = {
            "raw_surface_count": len(surfaces),
            "profiled_surface_count": len(surfaces),
            "surface_roles": sorted({
                str(surface.get("role") or "")
                for surface in surfaces
            }),
            "surface_types": sorted({
                str(surface.get("surface_type") or "")
                for surface in surfaces
            }),
            "materialization": "final_floorwise_reprojection",
        }
        props["floorwise_visual_projection"] = certificate
        model["floorwise_visual_projection"] = copy.deepcopy(certificate)
        matrix_stack = copy.deepcopy(
            rebound_source.metadata.get("floorwise_legal_matrix_stack") or {}
        )
        props["floorwise_legal_matrix_stack"] = matrix_stack
        model["floorwise_legal_matrix_stack"] = copy.deepcopy(matrix_stack)
    else:
        props.pop("source_surfaces", None)
        model.pop("source_surfaces", None)
        source_signature = {
            "schema_version": "arr.maas.source_geometry.signature.v1",
            "status": "floorwise_legal_revalidated",
            **{
                key: copy.deepcopy(previous_signature[key])
                for key in intent_keys
                if key in previous_signature
            },
            "volume_count": len(canonical_volumes),
            "surface_count": 0,
            "effective_surface_count": 0,
            "ground_area_m2": round(areas[0], 2),
            "upper_area_m2": round(areas[-1], 2),
            "area_profile_m2": [round(area, 2) for area in areas],
            "upper_to_ground_ratio": round(
                areas[-1] / max(areas[0], 1e-9),
                4,
            ),
            "verb_profile": ["floorwise_legal_matrix4"],
            "source_volume_roles": ["floorwise_legal_mass"],
            "surface_roles": [],
            "composition_layer_roles": ["floorwise_legal_mass"],
            "composition_rule": "floorwise_height_field_revalidation",
            "role_pattern": "floorwise_legal_contiguous_stack",
            "coherence_evidence": coherence,
            "floorwise_legal_revalidated": True,
            "design_intent_provenance": {
                key: copy.deepcopy(previous_signature[key])
                for key in (
                    "family",
                    "formal_principle",
                    "dominant_gesture",
                    "verb_profile",
                )
                if key in previous_signature
            },
        }
        proxy_certificate = {
            "schema_version": "arr.maas.floorwise_visual_projection.v1",
            "status": "not_applicable_no_authored_mesh",
            "hard_pass": True,
            "failure_reasons": [],
            "visual_hash": "",
            "source_surface_count": 0,
            "projected_surface_count": 0,
            "legal_sample_count": 0,
            "capacity_gfa_m2": round(floor_area, 4),
            "capacity_authority": "floorwise_legal_volumes",
        }
        props["floorwise_visual_projection"] = proxy_certificate
        model["floorwise_visual_projection"] = copy.deepcopy(proxy_certificate)
    props["source_signature"] = source_signature
    model["source_signature"] = copy.deepcopy(source_signature)
    geometry_resolution = {
        "schema_version": "arr.maas.geometry_resolution.v1",
        "status": "floorwise_legal_revalidated",
        "source": "final_floorwise_legal",
        "legal_action": "canonical_occupied_sections_clipped_and_rebound",
        "fallback": source,
    }
    props["geometry_resolution"] = geometry_resolution
    model["geometry_resolution"] = geometry_resolution

    metric_failures = failed_constraint_metrics(props, envelope)
    if metric_failures:
        return _reject(
            source=source,
            failed_checks=[f"constraint:{name}" for name in sorted(metric_failures)],
            checked_floor_count=len(plates),
            original_height_m=original_height,
        )

    evidence = {
        "schema_version": "arr.maas.floorwise_legal.v1",
        "status": "pass",
        "source": source,
        "repair_applied": repaired,
        "checked_floor_count": len(plates),
        "checked_mass_volume_count": len(canonical_volumes),
        "original_mass_volume_count": len(original_volumes),
        "original_height_m": round(original_height, 2),
        "validated_height_m": props["height"],
        "truncation_reasons": truncation_reasons,
        "checks": {
            "bcr": "pass",
            "far": "pass",
            "height": "pass",
            "setback": "pass",
            "sunlight_height_field": "pass",
            "occupied_sections": "pass",
        },
        "canonical_geometry_fields": [
            "geometry",
            "properties.floor_plates",
            "properties.mass_volumes",
            "properties.source_volumes",
            "properties.maas_model.floor_plates",
            "properties.maas_model.volumes",
            "properties.maas_model.source_volumes",
        ],
        "visual_authority": (
            "certified_projected_authored_mesh"
            if rebound_source is not None
            else "floorwise_capacity_proxy_only"
        ),
    }
    props["floorwise_legal_evidence"] = evidence
    model["floorwise_legal_evidence"] = evidence
    return FloorwiseLegalResult(
        feature=candidate,
        evidence=evidence,
        # The projected source is a renderer product whose tessellated surface
        # count and local frame no longer satisfy the authored-mesh input
        # contract.  Keep the immutable authored authority for any later legal
        # revalidation; the certified projected product is already serialized
        # on ``candidate`` above.
        authored_source=authored_source,
    )


__all__ = ["FloorwiseLegalResult", "revalidate_final_floorwise_feature"]
