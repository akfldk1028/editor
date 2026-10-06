"""Project accepted BOOK source masses through legal and parking hard gates.

This diagnostic never regenerates a replacement design.  It clips the exact
accepted SourceVolume graph by the PNU-derived buildable/sunlight envelope,
measures source retention, recomputes BCR/FAR/height, and then asks the
structured parking-rule and deterministic layout solvers to evaluate that
same projected footprint.
"""

from __future__ import annotations

from copy import deepcopy
from collections import Counter
import logging
from time import perf_counter
from dataclasses import dataclass, replace
from math import isfinite
from typing import Any, Iterable


logger = logging.getLogger(__name__)

from shapely.affinity import scale, translate
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.legal_envelope import build_legal_envelope
from backend.app.modules.design.generation.maas.geometry_language.execution_passport import enrich_mass_execution_passport
from backend.app.modules.design.generation.maas.geometry_language.floorwise_visual_projection import certify_authored_visual_mesh
from backend.app.modules.design.generation.maas.geometry_language.source_bridge import source_surface_payload_hash, source_volume_payload_hash
from backend.app.modules.design.generation.maas.parking.requirements import load_parking_requirement_rules, resolve_candidate_parking_requirement
from backend.app.modules.design.generation.maas.parking.strategy import infer_parking_strategy
from backend.app.modules.design.generation.maas.program_massing.semantic_carriers import audit_source_semantic_projection, semantic_capacity_measurement_hash, semantic_site_context_hash
from backend.app.modules.design.generation.maas.source_geometry.ir import SourceMass, SourceVolume
from backend.app.modules.design.generation.maas.source_geometry.polygon_quality import repair_source_polygon
from backend.app.modules.design.generation.services.site_geometry import wgs84_to_utm
from backend.app.modules.design.generation.maas.book_language.mass_passport_bridge import resolve_capacity_band_evidence, resolve_shared_floor_contract_hard_gate


@dataclass(frozen=True)
class LegalGenerationContext:
    """The legal domain supplied to generation, not a post-selection repair."""

    envelope: Any
    generation_site: Polygon
    sunlight_ring: tuple[tuple[float, float, float], ...]
    evidence: dict[str, Any]


@dataclass(frozen=True)
class CandidateDownstreamDimensions:
    height_m: float
    floors: int
    authority: str
    publishable: bool


class CandidateDownstreamFloorContextError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code
        self.evidence = {
            "schema_version": (
                "arr.maas.candidate_downstream_floor_context.v1"
            ),
            "status": "rejected",
            "hard_pass": False,
            "failure_code": code,
            "publishable": False,
        }


def _parking_layout_evidence(layout: dict[str, Any]) -> dict[str, Any]:
    """Keep bounded solver evidence needed to diagnose a parking rejection."""

    stalls = layout.get("stalls") if isinstance(layout.get("stalls"), list) else []
    return {
        "placement_mode": layout.get("placement_mode"),
        "reason": layout.get("reason"),
        "adjacency": deepcopy(layout.get("adjacency") or {}),
        "drive_aisle_clearance": deepcopy(
            layout.get("drive_aisle_clearance") or {}
        ),
        "turning_clearance": deepcopy(
            layout.get("turning_clearance") or {}
        ),
        "grid_solver": deepcopy(layout.get("grid_solver") or {}),
        "stall_count": len(stalls),
        "stalls": deepcopy(stalls),
    }


def generation_site_at_height(
    context: LegalGenerationContext,
    height_m: float,
) -> Polygon | None:
    """Return the legal horizontal domain available at a requested height."""
    if not context.sunlight_ring:
        return context.generation_site
    sunlight_allowed = _clip_ring_by_min_height(list(context.sunlight_ring), height_m)
    if sunlight_allowed is None:
        return None
    return repair_source_polygon(
        context.generation_site.intersection(sunlight_allowed),
        minimum_area=1.0,
    )


def inscribed_span_host(legal_section: Polygon) -> Polygon:
    """Find a clean oriented span host fully inside an irregular legal field.

    Long-span program graphs need a coherent structural bay.  This bounded
    search derives one from the legal polygon itself; it contains no parcel
    coordinate or finished-building template.
    """
    rectangle = legal_section.minimum_rotated_rectangle
    origin = rectangle.centroid
    best: Polygon | None = None
    for x_step in range(20, 4, -1):
        for y_step in range(20, 4, -1):
            candidate = scale(
                rectangle,
                xfact=x_step / 20.0,
                yfact=y_step / 20.0,
                origin=origin,
            )
            if legal_section.covers(candidate) and (best is None or candidate.area > best.area):
                best = candidate
    repaired = repair_source_polygon(best, minimum_area=4.0) if best is not None else None
    return repaired if repaired is not None else legal_section


def fit_source_to_sunlight_field(
    source: SourceMass,
    context: LegalGenerationContext,
    *,
    height_m: float,
    floors: int,
) -> SourceMass:
    """Apply one bounded whole-graph fit before program/portfolio selection.

    Volumes and renderer surfaces share the same scale, while translation is
    represented by the transformed source centroid.  Program roles and BOOK
    topology are therefore preserved and re-evaluated after the modifier.
    """
    if not context.sunlight_ring or not source.volumes:
        return source
    source_union = unary_union([volume.footprint for volume in source.volumes])
    if source_union.is_empty:
        return source
    origin = source_union.centroid
    highest_allowed = generation_site_at_height(context, height_m)
    if highest_allowed is None:
        return source
    target = highest_allowed.centroid
    target_dx = float(target.x - origin.x)
    target_dy = float(target.y - origin.y)
    best = source
    best_score = _source_retention_proxy(source.volumes, context, height_m=height_m, floors=floors)
    best_transform = (1.0, 0.0, 0.0)
    for factor in (1.0, 0.96, 0.92, 0.88, 0.84):
        for shift_fraction in (0.0, 0.25, 0.50, 0.75, 1.0):
            dx = target_dx * shift_fraction
            dy = target_dy * shift_fraction
            volumes = tuple(SourceVolume(
                role=volume.role,
                footprint=translate(
                    scale(volume.footprint, xfact=factor, yfact=factor, origin=origin),
                    xoff=dx,
                    yoff=dy,
                ),
                bottom_fraction=volume.bottom_fraction,
                top_fraction=volume.top_fraction,
                verb=volume.verb,
            ) for volume in source.volumes)
            transformed_union = unary_union([volume.footprint for volume in volumes])
            if not context.generation_site.covers(transformed_union):
                continue
            score = _source_retention_proxy(volumes, context, height_m=height_m, floors=floors)
            if (score, factor, -shift_fraction) <= (
                best_score,
                best_transform[0],
                -((abs(best_transform[1]) + abs(best_transform[2])) / max(abs(target_dx) + abs(target_dy), 1e-9)),
            ):
                continue
            footprint = translate(
                scale(source.footprint, xfact=factor, yfact=factor, origin=origin),
                xoff=dx,
                yoff=dy,
            )
            upper = (
                translate(
                    scale(source.upper_footprint, xfact=factor, yfact=factor, origin=origin),
                    xoff=dx,
                    yoff=dy,
                )
                if source.upper_footprint is not None
                else None
            )
            surfaces = tuple(replace(
                surface,
                vertices_m=tuple((x * factor, y * factor, z) for x, y, z in surface.vertices_m),
            ) for surface in source.surfaces)
            best = replace(
                source,
                footprint=footprint,
                upper_footprint=upper,
                volumes=volumes,
                surfaces=surfaces,
            )
            best_score = score
            best_transform = (factor, dx, dy)
    if best is source:
        return source
    metadata = dict(best.metadata)
    evidence = dict(metadata.get("legal_generation_context_evidence") or {})
    evidence.update({
        "legal_field_fit_status": "materialized",
        "legal_field_fit_operator": "bounded_uniform_scale_translate",
        "legal_field_fit_scale": round(best_transform[0], 4),
        "legal_field_fit_translation_m": [round(best_transform[1], 3), round(best_transform[2], 3)],
        "predicted_volume_retention": round(best_score, 4),
    })
    metadata["legal_generation_context_evidence"] = evidence
    return replace(best, metadata=metadata)


def _source_retention_proxy(
    volumes: tuple[SourceVolume, ...],
    context: LegalGenerationContext,
    *,
    height_m: float,
    floors: int,
) -> float:
    source_total = projected_total = 0.0
    floor_step = height_m / max(1, floors)
    for volume in volumes:
        bottom = height_m * float(volume.bottom_fraction)
        top = height_m * float(volume.top_fraction)
        boundaries = [bottom]
        boundaries.extend(
            floor_step * index
            for index in range(1, max(1, floors) + 1)
            if bottom + 1e-6 < floor_step * index < top - 1e-6
        )
        boundaries.append(top)
        for slice_bottom, slice_top in zip(boundaries, boundaries[1:]):
            band_height = max(0.0, slice_top - slice_bottom)
            if band_height <= 1e-6:
                continue
            source_total += float(volume.footprint.area) * band_height
            allowed = context.generation_site
            sunlight_allowed = _clip_ring_by_min_height(list(context.sunlight_ring), slice_top)
            if sunlight_allowed is not None:
                allowed = allowed.intersection(sunlight_allowed)
            projected_total += float(volume.footprint.intersection(allowed).area) * band_height
    return projected_total / source_total if source_total > 0 else 0.0


def build_legal_generation_context(
    *,
    site_local_utm: Polygon,
    site_origin_utm: tuple[float, float],
    building_type: str,
    constraints: list[dict[str, Any]],
    sunlight_envelope: dict[str, Any] | None,
) -> LegalGenerationContext:
    """Materialize the exact envelope used by both generation and hard gates.

    The horizontal buildable footprint is safe at every height.  The sloped
    sunlight field remains height-dependent and is therefore evaluated on the
    compiled SourceVolume graph rather than flattened into one tiny maximum-
    height footprint.
    """
    envelope = build_legal_envelope(
        site_utm=site_local_utm,
        constraints=constraints,
        building_type=building_type,
        sunlight_envelope=None,
    )
    buildable = repair_source_polygon(envelope.buildable_footprint, minimum_area=1.0)
    if buildable is None:
        buildable = repair_source_polygon(site_local_utm, minimum_area=1.0)
    if buildable is None:
        raise ValueError("legal generation context has no buildable footprint")
    sunlight_ring = tuple(_local_sunlight_ring(sunlight_envelope, site_origin_utm))
    return LegalGenerationContext(
        envelope=envelope,
        generation_site=buildable,
        sunlight_ring=sunlight_ring,
        evidence={
            "schema_version": "arr.maas.legal_generation_context.v1",
            "status": "materialized",
            "generation_precedes_selection": True,
            "original_site_area_m2": round(float(site_local_utm.area), 3),
            "generation_site_area_m2": round(float(buildable.area), 3),
            "sunlight_field_status": "materialized" if sunlight_ring else "not_available",
            "bcr_limit_pct": envelope.bcr_limit,
            "far_limit_pct": envelope.far_limit,
            "height_limit_m": envelope.height_limit,
        },
    )


def evaluate_accepted_sources_downstream(
    candidates: Iterable[Any],
    *,
    site_local_utm: Polygon,
    site_origin_utm: tuple[float, float],
    pnu: str,
    building_type: str,
    height_m: float,
    floors: int,
    constraints: list[dict[str, Any]],
    regulation_evidence: dict[str, Any],
    sunlight_envelope: dict[str, Any] | None,
    parking_options: dict[str, Any] | None = None,
    generation_context: LegalGenerationContext | None = None,
    allow_legacy_floor_fallback: bool = False,
) -> dict[str, Any]:
    items = tuple(candidates)
    context = generation_context or build_legal_generation_context(
        site_local_utm=site_local_utm,
        site_origin_utm=site_origin_utm,
        building_type=building_type,
        constraints=constraints,
        sunlight_envelope=sunlight_envelope,
    )
    envelope = context.envelope
    parking_rules = load_parking_requirement_rules(options=parking_options)
    rules = parking_rules.get("rules") if parking_rules.get("status") == "loaded" else None
    sunlight_ring = list(context.sunlight_ring)
    rows = []
    for candidate in items:
        candidate_dimensions = (
            _candidate_downstream_dimensions(
                candidate,
                fallback_height_m=height_m,
                fallback_floors=floors,
                allow_legacy_fallback=allow_legacy_floor_fallback,
            )
        )
        row = _evaluate_candidate(
            candidate,
            site_local_utm=site_local_utm,
            semantic_site_utm=context.generation_site,
            envelope=envelope,
            sunlight_ring=sunlight_ring,
            pnu=pnu,
            building_type=building_type,
            height_m=candidate_dimensions.height_m,
            floors=candidate_dimensions.floors,
            rules=rules,
            parking_rules_provenance={
                "source": parking_rules.get("source"),
                "graph_status": parking_rules.get("graph_status"),
            },
            parking_options=parking_options,
        )
        row["candidate_floor_context_evidence"] = {
            "schema_version": (
                "arr.maas.candidate_downstream_floor_context.v1"
            ),
            "status": "materialized",
            "hard_pass": candidate_dimensions.publishable,
            "authority": candidate_dimensions.authority,
            "candidate_height_m": candidate_dimensions.height_m,
            "candidate_floor_count": candidate_dimensions.floors,
            "publishable": candidate_dimensions.publishable,
        }
        if not candidate_dimensions.publishable:
            legal = row.get("legal_projection")
            if isinstance(legal, dict):
                failures = list(legal.get("failure_reasons") or ())
                failures.append("legacy_floor_context_non_publishable")
                legal["failure_reasons"] = list(dict.fromkeys(failures))
                legal["hard_pass"] = False
            row["combined_hard_pass"] = False
        rows.append(row)
    legal_failures = Counter(
        reason
        for row in rows
        for reason in row["legal_projection"]["failure_reasons"]
    )
    parking_failures = Counter(
        reason
        for row in rows
        for reason in row["parking_hard_gate"]["failure_reasons"]
    )
    geometry_failures = Counter(
        reason
        for row in rows
        for reason in row["legal_projection"]["geometry_failure_reasons"]
    )
    semantic_failures = Counter(
        reason
        for row in rows
        for reason in (
            row.get("semantic_projection_hard_gate", {}).get("failures")
            or ()
        )
    )
    capacity_failures = Counter(
        reason
        for row in rows
        for reason in (
            row.get("capacity_hard_gate", {}).get("failure_reasons")
            or ()
        )
    )
    retentions = [float(row["legal_projection"]["volume_retention"]) for row in rows]
    return {
        "schema_version": "arr.maas.book_downstream_hard_gate.v1",
        "status": "pass" if rows and all(row["combined_hard_pass"] for row in rows) else "fail",
        "same_accepted_source": True,
        "generation_context": context.evidence,
        "candidate_count": len(rows),
        "legal_hard_pass_count": sum(row["legal_projection"]["hard_pass"] for row in rows),
        "geometry_retention_pass_count": sum(row["legal_projection"]["geometry_retention_pass"] for row in rows),
        "parking_hard_pass_count": sum(row["parking_hard_gate"]["hard_pass"] for row in rows),
        "capacity_hard_pass_count": sum(
            row.get("capacity_hard_gate", {}).get("hard_pass", False)
            for row in rows
        ),
        "combined_hard_pass_count": sum(row["combined_hard_pass"] for row in rows),
        "mean_volume_retention": round(sum(retentions) / len(retentions), 4) if retentions else 0.0,
        "minimum_volume_retention": round(min(retentions), 4) if retentions else 0.0,
        "legal_failure_reason_counts": dict(sorted(legal_failures.items())),
        "geometry_failure_reason_counts": dict(sorted(geometry_failures.items())),
        "parking_failure_reason_counts": dict(sorted(parking_failures.items())),
        "capacity_failure_reason_counts": dict(
            sorted(capacity_failures.items())
        ),
        "semantic_failure_reason_counts": dict(
            sorted(semantic_failures.items())
        ),
        "legal_context": {
            "constraint_source": "live_pnu_zone_regulation_calculator",
            "constraints": constraints,
            "regulation_evidence": regulation_evidence,
            "bcr_limit_pct": envelope.bcr_limit,
            "far_limit_pct": envelope.far_limit,
            "height_limit_m": envelope.height_limit,
            "buildable_footprint_area_m2": round(float(envelope.buildable_footprint.area), 3) if envelope.buildable_footprint is not None else 0.0,
            "sunlight_envelope_status": "materialized" if sunlight_ring else "not_available",
        },
        "parking_rule_source": {
            "status": parking_rules.get("status"),
            "source": parking_rules.get("source"),
            "graph_status": parking_rules.get("graph_status"),
            "reason": parking_rules.get("reason") or parking_rules.get("graph_reason"),
        },
        "rows": rows,
    }


# The layout engine's own review vocabulary, mirrored from
# legal_mesh_optimizer's ranking of the same statuses. Anything outside this set
# is refused rather than reviewed, so a new or misspelled status fails closed.
PARKING_DESIGN_REVIEW_STATUSES = frozenset({
    "needs_drive_connectivity_review",
    "needs_aisle_review",
    "needs_swept_path_review",
    "needs_mechanical_parking_review",
})


def parking_layout_verdict(
    *,
    layout_status: Any,
    required_spaces: int,
    provided_spaces: int,
) -> tuple[list[str], list[str]]:
    """Split a non-passing parking layout into violations and design reviews.

    The layout engine already makes this distinction and this gate was
    collapsing it. `fail` is what `parking_layout.py` returns when the required
    count cannot be met. The `needs_*_review` statuses are returned only when
    the count *is* met by a strategy whose detail it does not draw - mechanical
    parking says so in its own evidence: "mechanical equipment bay, pit, and
    structural grid are not modeled". Mechanical parking is a lawful means under
    주차장법, so reading "we did not model this" as "this is illegal" rejected
    complying schemes: 5 of 12 selectable candidates on PNU 4115011300106840001,
    every one of them with its required count satisfied.

    The count stays a hard gate. A review status that has not met the count is
    still a violation, and the review reason travels with the candidate instead
    of being dropped.
    """

    status = str(layout_status or "missing")
    failures: list[str] = []
    reviews: list[str] = []
    count_met = int(provided_spaces) >= int(required_spaces)
    if status != "pass":
        if status in PARKING_DESIGN_REVIEW_STATUSES and count_met:
            reviews.append(f"parking_layout_{status}")
        else:
            failures.append(f"parking_layout_{status}")
    if not count_met:
        failures.append("parking_spaces_below_required")
    return failures, reviews


def _candidate_downstream_dimensions(
    candidate: Any,
    *,
    fallback_height_m: float,
    fallback_floors: int,
    allow_legacy_fallback: bool = False,
) -> CandidateDownstreamDimensions:
    """Use candidate-local N/height when B1 authority is present."""

    source = getattr(candidate, "source", None)
    metadata = getattr(source, "metadata", None)
    metadata = metadata if isinstance(metadata, dict) else {}
    context = metadata.get("candidate_floor_context")
    if context is None:
        if not allow_legacy_fallback:
            raise CandidateDownstreamFloorContextError(
                "missing_candidate_floor_context"
            )
        return CandidateDownstreamDimensions(
            height_m=float(fallback_height_m),
            floors=int(fallback_floors),
            authority="legacy_global_floor_fallback",
            publishable=False,
        )
    if (
        type(context) is not dict
        or context.get("status") != "materialized"
        or context.get("hard_pass") is not True
        or type(context.get("height_m")) not in (int, float)
        or not isfinite(float(context["height_m"]))
        or float(context["height_m"]) <= 0.0
        or type(context.get("floors")) is not int
        or context["floors"] <= 0
        or type(context.get("legal_floor_field_hash")) is not str
        or len(context["legal_floor_field_hash"]) != 64
    ):
        raise CandidateDownstreamFloorContextError(
            "invalid_candidate_downstream_floor_context"
        )
    return CandidateDownstreamDimensions(
        height_m=float(context["height_m"]),
        floors=int(context["floors"]),
        authority="candidate_floor_context",
        publishable=True,
    )


def _evaluate_candidate(
    candidate: Any,
    *,
    site_local_utm: Polygon,
    envelope: Any,
    sunlight_ring: list[tuple[float, float, float]],
    pnu: str,
    building_type: str,
    height_m: float,
    floors: int,
    rules: dict[str, Any] | None,
    parking_options: dict[str, Any] | None,
    parking_rules_provenance: dict[str, Any] | None = None,
    semantic_site_utm: Polygon | None = None,
) -> dict[str, Any]:
    legal_phase_started = perf_counter()
    source = candidate.source
    (
        final_geometry_hash,
        final_authority_failures,
        render_geometry_hash,
        actual_surface_payload_hash,
        surface_payload_matches,
    ) = _final_source_geometry_identity(source)
    authored_visual_failures: list[str] = list(final_authority_failures)
    if (
        source.metadata.get("geometry_authority") not in {
            "authored_projected_surface_payload",
            "authored_compiled_surface_payload",
        }
        and any(
            str(getattr(surface, "surface_type", "") or "").startswith(
                "profiled_"
            )
            for surface in tuple(source.surfaces or ())
        )
    ):
        legal_sections: list[Polygon] = []
        for floor_number in range(1, max(1, floors) + 1):
            allowed = envelope.buildable_footprint
            if allowed is not None and sunlight_ring:
                sunlight_allowed = _clip_ring_by_min_height(
                    sunlight_ring,
                    height_m * floor_number / max(1, floors),
                )
                allowed = (
                    allowed.intersection(sunlight_allowed)
                    if sunlight_allowed is not None
                    else None
                )
            section = (
                repair_source_polygon(allowed, minimum_area=1e-9)
                if allowed is not None
                else None
            )
            if section is None:
                authored_visual_failures.append(
                    "authored_visual_legal_sections_missing"
                )
                legal_sections = []
                break
            legal_sections.append(section)
        if legal_sections:
            validated_visual = certify_authored_visual_mesh(
                source,
                tuple(legal_sections),
            )
            if not validated_visual.certificate.hard_pass:
                authored_visual_failures.extend(
                    validated_visual.certificate.failure_reasons
                    or ("authored_visual_certification_failed",)
                )
            stored_certificate = source.metadata.get(
                "floorwise_visual_projection"
            )
            stored_certificate = (
                stored_certificate
                if isinstance(stored_certificate, dict)
                else {}
            )
            if (
                validated_visual.certificate.hard_pass
                and (
                    stored_certificate.get("status") != "certified"
                    or stored_certificate.get("hard_pass") is not True
                    or stored_certificate.get("certification_mode")
                    != "authored_visual_legal_validation"
                    or str(stored_certificate.get("visual_hash") or "")
                    != validated_visual.certificate.visual_hash
                    or str(
                        stored_certificate.get(
                            "exact_surface_payload_hash"
                        )
                        or ""
                    )
                    != validated_visual.certificate.exact_surface_payload_hash
                )
            ):
                authored_visual_failures.append(
                    "authored_visual_certificate_missing_or_invalid"
                )
    projected: list[SourceVolume] = []
    source_volume_total = projected_volume_total = 0.0
    weighted_intersection = weighted_union = 0.0
    clipped_volume_count = 0
    floor_step = height_m / max(1, floors)
    for volume in source.volumes:
        bottom_height = height_m * float(volume.bottom_fraction)
        top_height = height_m * float(volume.top_fraction)
        boundaries = [bottom_height]
        boundaries.extend(
            floor_step * floor_index
            for floor_index in range(1, max(1, floors) + 1)
            if bottom_height + 1e-6 < floor_step * floor_index < top_height - 1e-6
        )
        boundaries.append(top_height)
        original_clipped = False
        slice_count = max(0, len(boundaries) - 1)
        for slice_index, (slice_bottom, slice_top) in enumerate(zip(boundaries, boundaries[1:])):
            band_height = max(0.0, slice_top - slice_bottom)
            if band_height <= 1e-6:
                continue
            source_measure = float(volume.footprint.area) * band_height
            source_volume_total += source_measure
            allowed = envelope.buildable_footprint
            if allowed is not None and sunlight_ring:
                sunlight_allowed = _clip_ring_by_min_height(sunlight_ring, slice_top)
                allowed = allowed.intersection(sunlight_allowed) if sunlight_allowed is not None else None
            clipped = None if allowed is None else repair_source_polygon(
                volume.footprint.intersection(allowed),
                minimum_area=1.0,
            )
            if clipped is None:
                original_clipped = True
                continue
            containment_epsilon_m2 = max(
                1e-9,
                float(volume.footprint.area) * 1e-12,
            )
            if (
                float(volume.footprint.difference(allowed).area)
                > containment_epsilon_m2
            ):
                original_clipped = True
            projected_measure = float(clipped.area) * band_height
            projected_volume_total += projected_measure
            intersection = float(volume.footprint.intersection(clipped).area)
            union = float(volume.footprint.union(clipped).area)
            weighted_intersection += intersection * band_height
            weighted_union += union * band_height
            projected.append(SourceVolume(
                role=(f"{volume.role}__legal_band_{slice_index}" if slice_count > 1 else volume.role),
                footprint=clipped,
                bottom_fraction=slice_bottom / max(height_m, 1e-9),
                top_fraction=slice_top / max(height_m, 1e-9),
                verb=volume.verb,
            ))
        if original_clipped:
            clipped_volume_count += 1

    shared_floor_contract = (
        source.metadata.get("shared_floor_contract")
        if isinstance(source.metadata.get("shared_floor_contract"), dict)
        else None
    )
    original_metrics = _metrics(
        source.volumes,
        site_local_utm,
        height_m=height_m,
        floors=floors,
        shared_floor_contract=shared_floor_contract,
        geometry_hash=final_geometry_hash,
    )
    projected_metrics = _metrics(
        tuple(projected),
        site_local_utm,
        height_m=height_m,
        floors=floors,
        shared_floor_contract=shared_floor_contract,
        geometry_hash=final_geometry_hash,
    )
    retention = projected_volume_total / source_volume_total if source_volume_total > 0 else 0.0
    weighted_iou = weighted_intersection / weighted_union if weighted_union > 0 else 0.0
    legal_failures = list(dict.fromkeys(authored_visual_failures))
    if not projected:
        legal_failures.append("empty_after_legal_projection")
    if clipped_volume_count:
        legal_failures.append("authored_mass_outside_legal_envelope")
    if original_metrics["bcr_pct"] > envelope.bcr_limit + 0.1:
        legal_failures.append("bcr_limit_exceeded")
    if original_metrics["far_pct"] > envelope.far_limit + 0.1:
        legal_failures.append("far_limit_exceeded")
    if original_metrics["height_m"] > envelope.height_limit + 0.1:
        legal_failures.append("height_limit_exceeded")
    landscaping_limit = _constraint_limit(envelope.outputs_def, "landscaping_pct")
    if landscaping_limit is not None and original_metrics["open_pct"] < landscaping_limit - 0.1:
        legal_failures.append("landscaping_minimum_not_met")
    geometry_retention_pass = bool(
        not final_authority_failures
        and retention >= 0.80
        and weighted_iou >= 0.75
    )
    geometry_failures = list(final_authority_failures)
    if retention < 0.80:
        geometry_failures.append("source_volume_retention_below_80_percent")
    if weighted_iou < 0.75:
        geometry_failures.append("weighted_plan_iou_below_75_percent")

    legal_pre_parking_duration = perf_counter() - legal_phase_started
    parking_phase_started = perf_counter()
    ground = _ground_footprint(tuple(projected))
    requirement = resolve_candidate_parking_requirement(
        pnu=pnu,
        building_type=building_type,
        facility_area_m2=original_metrics["floor_area_m2"],
        options=parking_options,
        rules=rules,
        rules_provenance=parking_rules_provenance,
    )
    parking_props = {
        "footprint_area": original_metrics["footprint_area_m2"],
        "floor_area": original_metrics["floor_area_m2"],
        "num_floors": int(floors),
        "height": height_m,
        "bcr": original_metrics["bcr_pct"],
        "required_parking_spaces": requirement.get("required_spaces"),
        "required_accessible_parking_spaces": (requirement.get("accessible") or {}).get("accessible_min") or 0,
    }
    strategy = infer_parking_strategy(
        parking_props,
        site_area_m2=float(site_local_utm.area),
        building_type=building_type,
        footprint_utm=ground,
        site_utm=site_local_utm,
        road_context=(parking_options or {}).get("road_context"),
    )
    layout = strategy.get("layout_candidate") if isinstance(strategy.get("layout_candidate"), dict) else {}
    required = requirement.get("required_spaces")
    provided = int(layout.get("provided_spaces") or 0)
    parking_failures = []
    parking_reviews: list[str] = []
    parking_failures.extend(final_authority_failures)
    if str(requirement.get("status") or "") not in {"computed", "computed_estimate"} or not isinstance(required, int):
        parking_failures.append("parking_requirement_unresolved")
    if isinstance(required, int) and required > 0:
        layout_failures, layout_reviews = parking_layout_verdict(
            layout_status=layout.get("status"),
            required_spaces=required,
            provided_spaces=provided,
        )
        parking_failures.extend(layout_failures)
        parking_reviews.extend(layout_reviews)
    parking_duration = perf_counter() - parking_phase_started
    legal_post_parking_started = perf_counter()

    legal_hard_pass = not legal_failures
    parking_hard_pass = not parking_failures
    capacity_projection = dict(
        source.metadata.get("capacity_alternative_projection") or {}
    )
    capacity_measurement = dict(
        source.metadata.get("source_capacity_measurement") or {}
    )
    capacity_resolution = resolve_capacity_band_evidence(
        capacity_projection,
        capacity_measurement=capacity_measurement,
    )
    capacity_hard_pass = bool(
        capacity_resolution.get("resolved_capacity_hard_pass")
    )
    capacity_hard_gate = {
        **capacity_projection,
        "measurement": capacity_measurement,
        **capacity_resolution,
        "evaluated": bool(capacity_projection or capacity_measurement),
        "hard_pass": capacity_hard_pass,
        "failure_reasons": (
            []
            if capacity_hard_pass
            else ["resolved_capacity_hard_pass_failed"]
        ),
    }
    shared_floor_gate = resolve_shared_floor_contract_hard_gate(
        shared_floor_contract
    )
    legal_hard_pass = not legal_failures
    semantic_projection_hard_gate = audit_source_semantic_projection(
        source,
        building_type=building_type,
        expected_context={
            "floor_capacity_plan_hash": str(
                (shared_floor_contract or {}).get(
                    "floor_capacity_plan_hash"
                )
                or ""
            ),
            "pnu": pnu,
            "site_context_hash": semantic_site_context_hash(
                pnu=pnu,
                building_type=building_type,
                site=(
                    semantic_site_utm
                    if semantic_site_utm is not None
                    else site_local_utm
                ),
            ),
            "capacity_alternative_id": str(
                capacity_resolution.get(
                    "requested_capacity_alternative_id"
                )
                or ""
            ),
            "achieved_capacity_band": str(
                capacity_resolution.get(
                    "resolved_capacity_alternative_id"
                )
                or ""
            ),
            "capacity_measurement_hash": (
                semantic_capacity_measurement_hash(
                    capacity_measurement,
                    capacity_projection,
                )
            ),
        },
    )
    semantic_hard_pass = bool(
        semantic_projection_hard_gate.get("hard_pass")
    )
    containment_reasons = [
        reason for reason in legal_failures
        if reason in {
            "empty_after_legal_projection",
            "authored_mass_outside_legal_envelope",
        }
    ]
    structural_reasons = list(dict.fromkeys(
        list(final_authority_failures)
        + [
            reason for reason in legal_failures
            if reason.startswith("authored_visual_")
        ]
    ))
    height_reasons = [
        reason for reason in legal_failures
        if reason == "height_limit_exceeded"
    ]
    bcr_reasons = [
        reason for reason in legal_failures
        if reason == "bcr_limit_exceeded"
    ]
    far_reasons = [
        reason for reason in legal_failures
        if reason == "far_limit_exceeded"
    ]
    statutory_component_evidence = {
        "schema_version": "arr.maas.statutory_legal_components.v1",
        "containment": {
            "hard_pass": not containment_reasons,
            "failure_reasons": containment_reasons,
        },
        "structural_surface_validity": {
            "hard_pass": not structural_reasons,
            "failure_reasons": structural_reasons,
        },
        "height": {
            "hard_pass": not height_reasons,
            "failure_reasons": height_reasons,
            "measured_m": original_metrics["height_m"],
            "limit_m": envelope.height_limit,
        },
        "bcr": {
            "hard_pass": not bcr_reasons,
            "failure_reasons": bcr_reasons,
            "measured_pct": original_metrics["bcr_pct"],
            "limit_pct": envelope.bcr_limit,
        },
        "far": {
            "hard_pass": not far_reasons,
            "failure_reasons": far_reasons,
            "measured_pct": original_metrics["far_pct"],
            "limit_pct": envelope.far_limit,
        },
        "statutory_law_graph": {
            "hard_pass": legal_hard_pass,
            "failure_reasons": list(legal_failures),
        },
    }
    legal_duration = (
        legal_pre_parking_duration
        + perf_counter() - legal_post_parking_started
    )
    legal_projection = {
        "evaluated": True,
        "hard_pass": legal_hard_pass,
        "failure_reasons": legal_failures,
        "source_volume_count": len(source.volumes),
        "projected_volume_count": len(projected),
        "clipped_volume_count": clipped_volume_count,
        "volume_retention": round(retention, 4),
        "weighted_plan_iou": round(weighted_iou, 4),
        "geometry_retention_pass": geometry_retention_pass,
        "geometry_failure_reasons": geometry_failures,
        "floor_contract_hash": str(
            (shared_floor_contract or {}).get("floor_contract_hash") or ""
        ),
        "shared_floor_contract_hard_pass": (
            shared_floor_gate["hard_pass"]
        ),
        "shared_floor_failure_reasons": list(
            shared_floor_gate["failure_reasons"]
        ),
        "geometry_hash": final_geometry_hash,
        "component_evidence": statutory_component_evidence,
        "diagnostic_evidence": {
            "geometry_retention": {
                "hard_pass": geometry_retention_pass,
                "failure_reasons": list(geometry_failures),
            },
            "shared_floor": {
                "hard_pass": bool(shared_floor_gate.get("hard_pass")),
                "failure_reasons": list(
                    shared_floor_gate.get("failure_reasons") or ()
                ),
                "hard_gate": False,
            },
            "capacity": {
                "hard_pass": capacity_hard_pass,
                "failure_reasons": list(
                    capacity_hard_gate.get("failure_reasons") or ()
                ),
                "hard_gate": False,
            },
            "semantic_program": {
                "hard_pass": semantic_hard_pass,
                "failure_reasons": list(
                    semantic_projection_hard_gate.get("failures") or ()
                ),
                "hard_gate": False,
            },
        },
    }
    parking_hard_gate = {
        "evaluated": True,
        "hard_pass": parking_hard_pass,
        "failure_reasons": parking_failures,
        "review_reasons": parking_reviews,
        "requires_parking_design_review": bool(parking_reviews),
        "requirement": requirement,
        "selected_strategy": strategy.get("selected_strategy"),
        "layout_status": layout.get("status"),
        "required_spaces": required,
        "provided_spaces": provided,
        "strategy_candidates": list(
            strategy.get("strategy_candidates") or ()
        ),
        "strategy_basis": deepcopy(strategy.get("basis") or {}),
        "site_access_side_in_program_frame": str(
            (
                source.metadata.get("program_context")
                if isinstance(
                    source.metadata.get("program_context"), dict
                )
                else {}
            ).get("site_access_side_in_program_frame")
            or "closed"
        ),
        "layout_evidence": _parking_layout_evidence(layout),
        "mass_stage_parking": dict(
            layout.get("mass_stage_parking") or {}
        ),
        "authority_review_check": dict(
            layout.get("authority_review_check") or {}
        ),
        "rule_repository_source": requirement.get(
            "rule_repository_source"
        ),
        "graph_status": requirement.get("graph_status"),
        "geometry_hash": final_geometry_hash,
    }
    render_evidence = {
        "schema_version": "arr.maas.final_geometry_render_evidence.v1",
        "geometry_authority": str(
            source.metadata.get("geometry_authority") or ""
        ),
        "geometry_hash": render_geometry_hash or final_geometry_hash,
        "surface_count": len(tuple(source.surfaces or ())),
        "surface_payload_hash": actual_surface_payload_hash,
        "surface_payload_matches": surface_payload_matches,
        "hash_matches_measurement": bool(
            final_geometry_hash
            and render_geometry_hash == final_geometry_hash
        ),
    }
    initial_passport = source.metadata.get("mass_execution_passport") or (
        source.metadata.get("geometry_program_compilation") or {}
    ).get("execution_passport") or {}
    mass_execution_passport = (
        enrich_mass_execution_passport(
            initial_passport,
            downstream_evidence={
                "site": {
                    **dict(source.metadata.get("legal_generation_context_evidence") or {}),
                    "status": "passed",
                    "pnu": pnu,
                },
                "capacity": {
                    **capacity_hard_gate,
                    "shared_floor_contract": dict(shared_floor_contract or {}),
                    "floor_contract_hash": str(
                        (shared_floor_contract or {}).get("floor_contract_hash") or ""
                    ),
                },
                "law": legal_projection,
                "parking": parking_hard_gate,
                "program_fit": dict(source.metadata.get("program_massing_evidence") or {}),
            },
        )
        if initial_passport
        else {}
    )
    return {
        "variant_id": str(candidate.feature.get("properties", {}).get("variant_id") or candidate.sequence.name),
        "source_sequence": candidate.sequence.name,
        "book_principle_id": candidate.principle_id,
        "book_scope": str((source.metadata.get("program_book_projection_evidence") or {}).get("scope", {}).get("base_volume_label") or "1/1"),
        "generation_host_mode": str((
            source.metadata.get("legal_generation_context_evidence") or {}
        ).get("generation_host_mode") or "unconstrained_site"),
        "legal_generation_context_evidence": source.metadata.get("legal_generation_context_evidence") or {},
        "original_metrics": original_metrics,
        "projected_metrics": projected_metrics,
        "legal_projection": legal_projection,
        "parking_hard_gate": parking_hard_gate,
        "capacity_hard_gate": capacity_hard_gate,
        "semantic_projection_hard_gate": semantic_projection_hard_gate,
        "render_evidence": render_evidence,
        "mass_execution_passport": mass_execution_passport,
        "combined_hard_pass": bool(
            legal_hard_pass
            and parking_hard_pass
        ),
        "release_component_evidence": {
            "statutory_legal": statutory_component_evidence,
            "parking": deepcopy(parking_hard_gate),
            "capacity_diagnostic": deepcopy(capacity_hard_gate),
            "shared_floor_diagnostic": deepcopy(shared_floor_gate),
            "semantic_program_diagnostic": deepcopy(
                semantic_projection_hard_gate
            ),
            "program_and_capacity_are_not_release_hard_gates": True,
        },
        "phase_durations_seconds": {
            "law": max(legal_duration, 1e-9),
            "parking": max(parking_duration, 1e-9),
        },
    }


def _metrics(
    volumes: tuple[SourceVolume, ...],
    site: Polygon,
    *,
    height_m: float,
    floors: int,
    shared_floor_contract: dict[str, Any] | None = None,
    geometry_hash: str = "",
) -> dict[str, float | str]:
    shared = (
        shared_floor_contract
        if isinstance(shared_floor_contract, dict)
        and shared_floor_contract.get("schema_version")
        == "arr.maas.shared_floor_contract.v1"
        else None
    )
    ground = _ground_footprint(volumes)
    footprint_area = float(ground.area) if ground is not None else 0.0
    floor_area = 0.0
    for floor in range(max(1, floors)):
        fraction = (floor + 0.5) / max(1, floors)
        active = [
            volume.footprint
            for volume in volumes
            if (
                float(volume.bottom_fraction)
                <= fraction
                < float(volume.top_fraction)
            )
        ]
        if active:
            floor_area += float(unary_union(active).area)
    maximum_height = max(
        (height_m * float(volume.top_fraction) for volume in volumes),
        default=0.0,
    )
    site_area = max(float(site.area), 1e-9)
    return {
        "footprint_area_m2": round(footprint_area, 3),
        "floor_area_m2": round(floor_area, 3),
        "bcr_pct": round(footprint_area / site_area * 100.0, 3),
        "far_pct": round(floor_area / site_area * 100.0, 3),
        "height_m": round(maximum_height, 3),
        "open_pct": round(max(0.0, site_area - footprint_area) / site_area * 100.0, 3),
        "floor_contract_hash": str((shared or {}).get("floor_contract_hash") or ""),
        "metric_authority": "visible_authored_source_volume_horizontal_slices",
        "geometry_hash": geometry_hash,
    }


def _final_source_geometry_identity(
    source: SourceMass,
) -> tuple[str, list[str], str, str, bool]:
    metadata = source.metadata if isinstance(source.metadata, dict) else {}
    if metadata.get("geometry_authority") in {
        "final_floorwise_legal_geometry_program",
        "final_floorwise_legal_geometry_authority",
    }:
        return (
            "",
            ["obsolete_geometry_authority_unmarked"],
            "",
            "",
            False,
        )
    if metadata.get("geometry_authority") not in {
        "authored_projected_surface_payload",
        "authored_compiled_surface_payload",
    }:
        return "", [], "", "", True
    bridge = (
        metadata.get("geometry_program_bridge_evidence")
        if isinstance(metadata.get("geometry_program_bridge_evidence"), dict)
        else {}
    )
    compilation = (
        metadata.get("geometry_program_compilation")
        if isinstance(metadata.get("geometry_program_compilation"), dict)
        else {}
    )
    projection = (
        metadata.get("floorwise_legal_projection")
        if isinstance(metadata.get("floorwise_legal_projection"), dict)
        else {}
    )
    final_geometry_hash = str(metadata.get("final_geometry_hash") or "")
    final_program_hash = str(metadata.get("final_program_hash") or "")
    authored_compilation_geometry_hash = str(
        compilation.get("geometry_hash") or ""
    )
    certificate = metadata.get("authored_legal_projection_certificate")
    certificate = certificate if isinstance(certificate, dict) else {}
    bridge_certificate = bridge.get("authored_legal_projection_certificate")
    bridge_certificate = (
        bridge_certificate if isinstance(bridge_certificate, dict) else {}
    )
    render_geometry_hash = final_geometry_hash
    geometry_hashes = (
        final_geometry_hash,
        str(bridge.get("geometry_hash") or ""),
        str(projection.get("final_geometry_hash") or ""),
    )
    program_hashes = (
        final_program_hash,
        str(bridge.get("program_hash") or ""),
        str(projection.get("final_program_hash") or ""),
    )
    failures: list[str] = []
    if (
        projection.get("hard_pass") is not True
        or not final_geometry_hash
        or any(value != final_geometry_hash for value in geometry_hashes)
        or not final_program_hash
        or any(value != final_program_hash for value in program_hashes)
    ):
        failures.append("final_source_hash_mismatch")
    capacity_measurement = metadata.get("capacity_projection_measurement")
    capacity_measurement = (
        capacity_measurement
        if isinstance(capacity_measurement, dict)
        else {}
    )
    legal_floor_field_hash = str(
        capacity_measurement.get("legal_floor_field_hash") or ""
    )
    projection_chain_ok = bool(
        certificate.get("schema_version")
        == "arr.maas.authored_legal_projection_certificate.v1"
        and certificate.get("status") == "verified"
        and certificate.get("hard_pass") is True
        and certificate == bridge_certificate
        and str(certificate.get("input_authored_program_hash") or "")
        == str(bridge.get("post_book_authored_program_hash") or "")
        == final_program_hash
        and str(certificate.get("input_authored_geometry_hash") or "")
        == str(bridge.get("post_book_authored_geometry_hash") or "")
        == authored_compilation_geometry_hash
        and str(certificate.get("legal_floor_field_hash") or "")
        == legal_floor_field_hash
        and len(legal_floor_field_hash) == 64
        and str(certificate.get("projected_surface_hash") or "")
        == final_geometry_hash
        and str(certificate.get("projected_surface_payload_hash") or "")
        == str(metadata.get("final_surface_payload_hash") or "")
    )
    if not projection_chain_ok:
        logger.info(
            "Authored legal projection chain mismatch: %s",
            {
                "certificate_equals_bridge": certificate == bridge_certificate,
                "certificate_input_program_hash": str(
                    certificate.get("input_authored_program_hash") or ""
                ),
                "bridge_post_book_authored_program_hash": str(
                    bridge.get("post_book_authored_program_hash") or ""
                ),
                "final_program_hash": final_program_hash,
                "certificate_input_geometry_hash": str(
                    certificate.get("input_authored_geometry_hash") or ""
                ),
                "bridge_post_book_authored_geometry_hash": str(
                    bridge.get("post_book_authored_geometry_hash") or ""
                ),
                "compilation_geometry_hash": authored_compilation_geometry_hash,
                "certificate_legal_floor_field_hash": str(
                    certificate.get("legal_floor_field_hash") or ""
                ),
                "measurement_legal_floor_field_hash": legal_floor_field_hash,
                "certificate_projected_surface_hash": str(
                    certificate.get("projected_surface_hash") or ""
                ),
                "final_geometry_hash": final_geometry_hash,
                "certificate_projected_surface_payload_hash": str(
                    certificate.get("projected_surface_payload_hash") or ""
                ),
                "final_surface_payload_hash": str(
                    metadata.get("final_surface_payload_hash") or ""
                ),
            },
        )
        failures.append("authored_legal_projection_chain_mismatch")
    surfaces = tuple(source.surfaces or ())
    try:
        actual_surface_payload_hash = source_surface_payload_hash(surfaces)
    except (TypeError, ValueError):
        actual_surface_payload_hash = ""
    try:
        raw_surface_count = int(bridge.get("raw_mesh_triangle_count") or 0)
        exported_surface_count = int(
            bridge.get("exported_surface_count") or 0
        )
    except (TypeError, ValueError):
        raw_surface_count = exported_surface_count = 0
    surface_payload_complete = bool(
        surfaces
        and bridge.get("surface_export_complete") is True
        and raw_surface_count == len(surfaces)
        and exported_surface_count == len(surfaces)
        and actual_surface_payload_hash
    )
    if not surface_payload_complete:
        failures.append("final_source_surface_payload_incomplete")
    stored_surface_hashes = (
        str(bridge.get("surface_payload_hash") or ""),
        str(metadata.get("final_surface_payload_hash") or ""),
    )
    surface_payload_matches = bool(
        surface_payload_complete
        and all(
            value == actual_surface_payload_hash
            for value in stored_surface_hashes
        )
    )
    if surface_payload_complete and not surface_payload_matches:
        failures.append("final_source_surface_payload_mismatch")
    volumes = tuple(source.volumes or ())
    try:
        actual_proxy_volume_payload_hash = source_volume_payload_hash(volumes)
    except (TypeError, ValueError):
        actual_proxy_volume_payload_hash = ""
    try:
        requested_proxy_band_count = int(
            bridge.get("requested_proxy_band_count") or 0
        )
        exported_proxy_band_count = int(
            bridge.get("exported_proxy_band_count") or 0
        )
        exported_proxy_part_count = int(
            bridge.get("exported_proxy_part_count") or 0
        )
        proxy_volume_count = int(bridge.get("proxy_volume_count") or 0)
        proxy_band_part_counts = tuple(
            int(value)
            for value in (bridge.get("proxy_band_part_counts") or ())
        )
    except (TypeError, ValueError):
        requested_proxy_band_count = 0
        exported_proxy_band_count = 0
        exported_proxy_part_count = 0
        proxy_volume_count = 0
        proxy_band_part_counts = ()
    actual_proxy_band_counts = Counter(
        (
            float(volume.bottom_fraction),
            float(volume.top_fraction),
        )
        for volume in volumes
    )
    actual_proxy_band_part_counts = tuple(
        actual_proxy_band_counts[band]
        for band in sorted(actual_proxy_band_counts)
    )
    actual_proxy_band_count = len(actual_proxy_band_part_counts)
    bridge_proxy_volume_hash = str(
        bridge.get("proxy_volume_payload_hash") or ""
    )
    final_proxy_volume_hash = str(
        metadata.get("final_proxy_volume_payload_hash") or ""
    )

    def valid_sha256(value: str) -> bool:
        return (
            len(value) == 64
            and all(character in "0123456789abcdef" for character in value)
        )

    proxy_volume_payload_complete = bool(
        volumes
        and actual_proxy_volume_payload_hash
        and actual_proxy_band_count >= 1
        and requested_proxy_band_count == actual_proxy_band_count
        and exported_proxy_band_count == actual_proxy_band_count
        and exported_proxy_part_count == len(volumes)
        and proxy_volume_count == len(volumes)
        and proxy_band_part_counts == actual_proxy_band_part_counts
        and valid_sha256(bridge_proxy_volume_hash)
        and valid_sha256(final_proxy_volume_hash)
    )
    if not proxy_volume_payload_complete:
        failures.append("final_source_proxy_volume_payload_incomplete")
    proxy_volume_payload_matches = bool(
        proxy_volume_payload_complete
        and bridge_proxy_volume_hash
        == actual_proxy_volume_payload_hash
        and final_proxy_volume_hash
        == actual_proxy_volume_payload_hash
        )
    if (
        proxy_volume_payload_complete
        and not proxy_volume_payload_matches
    ):
        failures.append("final_source_proxy_volume_payload_mismatch")
    return (
        final_geometry_hash,
        failures,
        render_geometry_hash,
        actual_surface_payload_hash,
        surface_payload_matches,
    )


def _ground_footprint(volumes: tuple[SourceVolume, ...]) -> Polygon | None:
    grounded = [volume.footprint for volume in volumes if float(volume.bottom_fraction) <= 0.01]
    if not grounded:
        grounded = [volume.footprint for volume in volumes]
    return repair_source_polygon(unary_union(grounded), minimum_area=1.0) if grounded else None


def _constraint_limit(outputs: list[dict[str, Any]], name: str) -> float | None:
    for item in outputs:
        if item.get("type") == "Constraint" and item.get("name") == name:
            try:
                return float(item.get("val"))
            except (TypeError, ValueError):
                return None
    return None


def _local_sunlight_ring(
    sunlight_envelope: dict[str, Any] | None,
    origin_utm: tuple[float, float],
) -> list[tuple[float, float, float]]:
    slanted = (sunlight_envelope or {}).get("slanted_polygons") or []
    corners = (slanted[0].get("corners") or []) if slanted else []
    result = []
    for corner in corners:
        if not isinstance(corner, (list, tuple)) or len(corner) < 3:
            continue
        try:
            point = wgs84_to_utm(Point(float(corner[0]), float(corner[1])))
            result.append((point.x - origin_utm[0], point.y - origin_utm[1], float(corner[2])))
        except (TypeError, ValueError):
            continue
    if len(result) >= 2 and result[0][:2] == result[-1][:2]:
        result.pop()
    return result


def _clip_ring_by_min_height(
    ring: list[tuple[float, float, float]],
    height_m: float,
) -> Polygon | None:
    if len(ring) < 3:
        return None

    def inside(point: tuple[float, float, float]) -> bool:
        return point[2] >= height_m - 1e-6

    def crossing(left: tuple[float, float, float], right: tuple[float, float, float]):
        denominator = right[2] - left[2]
        if abs(denominator) < 1e-9:
            return right
        amount = (height_m - left[2]) / denominator
        amount = max(0.0, min(1.0, amount))
        return (
            left[0] + (right[0] - left[0]) * amount,
            left[1] + (right[1] - left[1]) * amount,
            height_m,
        )

    output = []
    previous = ring[-1]
    previous_inside = inside(previous)
    for current in ring:
        current_inside = inside(current)
        if current_inside:
            if not previous_inside:
                output.append(crossing(previous, current))
            output.append(current)
        elif previous_inside:
            output.append(crossing(previous, current))
        previous, previous_inside = current, current_inside
    if len(output) < 3:
        return None
    return repair_source_polygon(Polygon([(x, y) for x, y, _height in output]), minimum_area=1.0)


__all__ = [
    "LegalGenerationContext",
    "build_legal_generation_context",
    "generation_site_at_height",
    "inscribed_span_host",
    "fit_source_to_sunlight_field",
    "evaluate_accepted_sources_downstream",
]
