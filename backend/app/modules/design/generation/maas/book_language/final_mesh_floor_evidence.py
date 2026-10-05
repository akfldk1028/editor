"""Read-only floor evidence measured from the certified visible mesh."""

from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from math import hypot, isfinite
from typing import Any, Mapping

from shapely.affinity import translate
from shapely.geometry import LineString, Polygon, shape
from shapely.ops import polygonize, unary_union

from backend.app.modules.design.generation.maas.design_space import capacities_under_band, coverage_band as resolve_coverage_band
from backend.app.modules.design.generation.maas.geometry_language.compiler import CompilationResult
from backend.app.modules.design.generation.maas.geometry_language.projected_visual_contract import AUTHORED_COORDINATE_SPACE, FINAL_AUTHORITY_CERTIFICATION_MODE

from backend.app.modules.design.generation.maas.book_language.actual_gfa_stop_certificate import IDENTITY_KEYS
from backend.app.modules.design.generation.maas.book_language.actual_gfa_stop_certificate import certify_candidate_actual_gfa_stop, validate_candidate_actual_gfa_stop_certificate
from backend.app.modules.design.generation.maas.book_language.legal_floor_field import validate_legal_floor_field


SCHEMA_VERSION = "arr.maas.final_mesh_floor_evidence.v1"
SECTION_EPSILON = 1e-9
LEGAL_OVERLAY_AREA_EPSILON_M2 = 1e-7
LEGAL_OVERLAY_MEAN_DEPTH_EPSILON_M = 1e-6


@dataclass(frozen=True)
class FinalMeshFloorEvidence:
    actual_floor_areas_m2: tuple[float, ...]
    containment_evidence: tuple[dict[str, Any], ...]
    measured_identity: dict[str, str]


@dataclass(frozen=True)
class CandidateFinalizationContext:
    candidate_height_m: float
    candidate_floor_count: int
    candidate_target_gfa_m2: float
    legal_floor_field_hash: str


class FinalMeshFloorEvidenceError(ValueError):
    """Typed fail-closed rejection at the final visible-mesh boundary."""

    def __init__(self, code: str, **details: Any) -> None:
        super().__init__(code)
        self.code = code
        self.evidence = {
            "schema_version": SCHEMA_VERSION,
            "status": "rejected",
            "hard_pass": False,
            "failure_code": code,
            **details,
        }


def measure_final_mesh_floor_evidence(
    *,
    certified_compilation: CompilationResult,
    projected_visual_certificate: Mapping[str, Any],
    legal_floor_field: Mapping[str, Any],
    expected_legal_floor_field_hash: str,
    candidate_height_m: float,
    candidate_floor_count: int,
    expected_identity: Mapping[str, str],
) -> FinalMeshFloorEvidence:
    """Slice the already-certified visible mesh without replay or mutation."""

    field = _validated_field(
        legal_floor_field,
        expected_hash=expected_legal_floor_field_hash,
    )
    floor_count = _validated_candidate_floor_count(
        candidate_floor_count,
        field_count=field["measured_usable_floor_count"],
    )
    candidate_height = _validated_candidate_height(
        candidate_height_m,
        floor_count=floor_count,
        floor_tops=field["legal_floor_top_heights_m"],
    )
    measured_identity = _validated_visible_mesh_identity(
        certified_compilation,
        projected_visual_certificate,
        expected_identity=expected_identity,
    )
    origin = _validated_visual_origin(projected_visual_certificate)
    vertices, triangles = _validated_visible_mesh(
        certified_compilation,
        maximum_height_m=candidate_height,
    )

    areas: list[float] = []
    containment_rows: list[dict[str, Any]] = []
    floor_height = float(field["typical_floor_height_m"])
    legal_sections = field["legal_floor_sections"]
    legal_caps = field["bcr_adjusted_floor_capacities_m2"]
    for index, raw_top in enumerate(field["legal_floor_top_heights_m"]):
        floor_number = index + 1
        if floor_number > floor_count:
            area = 0.0
        else:
            physical_mid_z = float(raw_top) - floor_height / 2.0
            normalized_z = physical_mid_z / candidate_height
            if (
                not isfinite(normalized_z)
                or normalized_z <= 0.0
                or normalized_z >= 1.0
            ):
                raise FinalMeshFloorEvidenceError(
                    "invalid_final_mesh_sample_height",
                    floor_number=floor_number,
                    normalized_z=normalized_z,
                )
            raw_boundary_segments = _mesh_section_segments(
                vertices,
                triangles,
                physical_mid_z,
            )
            if not raw_boundary_segments:
                raise FinalMeshFloorEvidenceError(
                    "final_mesh_floor_section_missing",
                    floor_number=floor_number,
                    normalized_z=round(normalized_z, 12),
                )
            legal_section = shape(legal_sections[index])
            raw_world_segments = tuple(
                translate(
                    segment,
                    xoff=origin[0],
                    yoff=origin[1],
                )
                for segment in raw_boundary_segments
            )
            escaped_segments = tuple(
                segment
                for segment in raw_world_segments
                if not legal_section.covers(segment)
            )
            escaped_boundary_length = 0.0
            if escaped_segments:
                escaped_boundary = unary_union(tuple(
                    segment.difference(legal_section)
                    for segment in escaped_segments
                ))
                escaped_boundary_length = float(
                    escaped_boundary.length
                )
            local_section = _polygonize_section_segments(
                raw_boundary_segments
            )
            if (
                local_section is None
                or local_section.is_empty
                or not local_section.is_valid
                or float(local_section.area) <= SECTION_EPSILON
            ):
                raise FinalMeshFloorEvidenceError(
                    "final_mesh_floor_section_missing",
                    floor_number=floor_number,
                    normalized_z=round(normalized_z, 12),
                )
            raw_section_area = float(local_section.area)
            if (
                not isfinite(raw_section_area)
                or raw_section_area <= SECTION_EPSILON
            ):
                raise FinalMeshFloorEvidenceError(
                    "invalid_final_mesh_section_topology",
                    floor_number=floor_number,
                )
            world_section = translate(
                local_section,
                xoff=origin[0],
                yoff=origin[1],
            )
            escaped_area = float(world_section.difference(legal_section).area)
            escaped_mean_depth = (
                escaped_area / escaped_boundary_length
                if escaped_boundary_length > SECTION_EPSILON
                else float("inf")
            )
            numeric_overlay_equivalent = (
                escaped_area <= max(
                    LEGAL_OVERLAY_AREA_EPSILON_M2,
                    escaped_boundary_length
                    * LEGAL_OVERLAY_MEAN_DEPTH_EPSILON_M
                    + LEGAL_OVERLAY_MEAN_DEPTH_EPSILON_M ** 2,
                )
                and escaped_mean_depth
                <= LEGAL_OVERLAY_MEAN_DEPTH_EPSILON_M
            )
            # GEOS overlay can report a nanometre-deep boundary strip outside
            # an otherwise identical legal polygon. Numeric equivalence is
            # bounded by both total area and mean strip depth, so a small but
            # genuinely positive displacement remains fail-closed.
            if (
                not legal_section.covers(world_section)
                and not numeric_overlay_equivalent
            ):
                raise FinalMeshFloorEvidenceError(
                    "final_mesh_legal_escape",
                    floor_number=floor_number,
                    escaped_boundary_length_m=(
                        escaped_boundary_length
                    ),
                    escaped_area_m2=round(escaped_area, 9),
                    escaped_mean_depth_m=escaped_mean_depth,
                )
            area = round(raw_section_area, 6)
            if area <= 0.0:
                raise FinalMeshFloorEvidenceError(
                    "final_mesh_floor_section_missing",
                    floor_number=floor_number,
                    normalized_z=round(normalized_z, 12),
                )
            if raw_section_area > float(legal_caps[index]) + 1e-6:
                raise FinalMeshFloorEvidenceError(
                    "final_mesh_floor_capacity_exceeded",
                    floor_number=floor_number,
                    actual_area_m2=area,
                    legal_capacity_m2=float(legal_caps[index]),
                )
        areas.append(area)
        containment_rows.append({
            "floor_number": floor_number,
            "contained": True,
            "actual_area_m2": area,
            "legal_floor_field_hash": expected_legal_floor_field_hash,
            **measured_identity,
        })

    return FinalMeshFloorEvidence(
        actual_floor_areas_m2=tuple(areas),
        containment_evidence=tuple(containment_rows),
        measured_identity=measured_identity,
    )


def resolve_candidate_finalization_context(
    source_metadata: Mapping[str, Any],
    *,
    trusted_legal_floor_field: Mapping[str, Any],
    expected_legal_floor_field_hash: str,
    expected_pnu: str,
) -> CandidateFinalizationContext:
    """Resolve one candidate's N/height/target from mutually bound metadata."""

    if (
        type(source_metadata) is not dict
        or type(trusted_legal_floor_field) is not dict
        or not validate_legal_floor_field(trusted_legal_floor_field)
        or trusted_legal_floor_field.get("legal_floor_field_hash")
        != expected_legal_floor_field_hash
        or trusted_legal_floor_field.get("pnu") != expected_pnu
    ):
        raise FinalMeshFloorEvidenceError(
            "invalid_candidate_finalization_context"
        )
    floor_context = source_metadata.get("candidate_floor_context")
    capacity_contract = source_metadata.get("candidate_capacity_contract")
    semantic_context = source_metadata.get(
        "final_semantic_projection_context"
    )
    if (
        type(floor_context) is not dict
        or type(capacity_contract) is not dict
        or type(semantic_context) is not dict
        or floor_context.get("status") != "materialized"
        or floor_context.get("hard_pass") is not True
        or not _valid_sha256(expected_legal_floor_field_hash)
        or not _valid_pnu(expected_pnu)
    ):
        raise FinalMeshFloorEvidenceError(
            "invalid_candidate_finalization_context"
        )
    raw_height = floor_context.get("height_m")
    raw_floors = floor_context.get("floors")
    raw_target = capacity_contract.get("candidate_target_gfa_m2")
    if (
        type(raw_height) not in (int, float)
        or not isfinite(float(raw_height))
        or float(raw_height) <= 0.0
        or type(raw_floors) is not int
        or raw_floors <= 0
        or type(raw_target) not in (int, float)
        or not isfinite(float(raw_target))
        or float(raw_target) <= 0.0
    ):
        raise FinalMeshFloorEvidenceError(
            "invalid_candidate_finalization_context"
        )
    height = float(raw_height)
    floors = raw_floors
    target = float(raw_target)
    capacity_height = capacity_contract.get("requested_height_m")
    capacity_floors = capacity_contract.get("requested_floors")
    target_alias = capacity_contract.get("target_floor_area_m2")
    target_vector = capacity_contract.get("target_floor_areas_m2")
    semantic_floors = semantic_context.get(
        "candidate_requested_floors"
    )
    semantic_target = semantic_context.get("candidate_target_gfa_m2")
    hashes = (
        floor_context.get("legal_floor_field_hash"),
        capacity_contract.get("legal_floor_field_hash"),
        capacity_contract.get("candidate_legal_floor_field_hash"),
        semantic_context.get("legal_floor_field_hash"),
    )
    mismatch_fields = []
    if any(value != expected_legal_floor_field_hash for value in hashes):
        mismatch_fields.append("legal_floor_field_hash")
    if (
        type(capacity_height) not in (int, float)
        or not isfinite(float(capacity_height))
        or float(capacity_height) != height
    ):
        mismatch_fields.append("candidate_height_m")
    if type(capacity_floors) is not int or capacity_floors != floors:
        mismatch_fields.append("capacity_floor_count")
    if type(semantic_floors) is not int or semantic_floors != floors:
        mismatch_fields.append("semantic_floor_count")
    if (
        type(semantic_target) not in (int, float)
        or not isfinite(float(semantic_target))
        or float(semantic_target) != target
    ):
        mismatch_fields.append("candidate_target_gfa_m2")
    if semantic_context.get("pnu") != expected_pnu:
        mismatch_fields.append("pnu")
    if mismatch_fields:
        raise FinalMeshFloorEvidenceError(
            "candidate_finalization_context_mismatch",
            mismatch_fields=mismatch_fields,
            observed_context={
                "floor_height_m": raw_height,
                "capacity_height_m": capacity_height,
                "floor_count": raw_floors,
                "capacity_floor_count": capacity_floors,
                "semantic_floor_count": semantic_floors,
                "capacity_target_gfa_m2": raw_target,
                "semantic_target_gfa_m2": semantic_target,
                "semantic_pnu": semantic_context.get("pnu"),
            },
        )
    if (
        type(target_alias) not in (int, float)
        or not isfinite(float(target_alias))
        or float(target_alias) <= 0.0
        or type(target_vector) is not list
        or len(target_vector) != floors
        or not all(
            type(value) in (int, float)
            and isfinite(float(value))
            and float(value) > 0.0
            for value in target_vector
        )
        or abs(float(target_alias) - target) > 1e-6
        or abs(sum(float(value) for value in target_vector) - target)
        > 1e-6
    ):
        raise FinalMeshFloorEvidenceError(
            "candidate_finalization_target_identity_mismatch"
        )
    _validate_candidate_capacity_prefix(
        floor_context=floor_context,
        capacity_contract=capacity_contract,
        trusted_legal_floor_field=trusted_legal_floor_field,
        floor_count=floors,
        candidate_height_m=height,
    )
    return CandidateFinalizationContext(
        candidate_height_m=height,
        candidate_floor_count=floors,
        candidate_target_gfa_m2=float(target_alias),
        legal_floor_field_hash=expected_legal_floor_field_hash,
    )


def _validate_candidate_capacity_prefix(
    *,
    floor_context: Mapping[str, Any],
    capacity_contract: Mapping[str, Any],
    trusted_legal_floor_field: Mapping[str, Any],
    floor_count: int,
    candidate_height_m: float,
) -> None:
    trusted_tops = trusted_legal_floor_field[
        "legal_floor_top_heights_m"
    ][:floor_count]
    trusted_areas = trusted_legal_floor_field[
        "legal_floor_section_areas_m2"
    ][:floor_count]
    trusted_caps = trusted_legal_floor_field[
        "bcr_adjusted_floor_capacities_m2"
    ][:floor_count]
    # A candidate that declared how much ground it takes was certified against
    # plates bounded by that ground take, so the prefix is re-derived here under
    # the same declaration. This is the third authority to re-derive it, after
    # the candidate itself and _candidate_floor_context; telling only the first
    # two left two of every three selected masses failing finalization with
    # candidate_finalization_prefix_identity_mismatch.
    #
    # Still fail-closed: the band must be one of the fixed legal fractions, the
    # capacity it scales is the trusted field's own 건폐율 capacity, and the
    # comparison is made at the contract's own stated precision rather than by
    # widening the tolerance.
    trusted_prefix_capacity = sum(float(value) for value in trusted_caps)
    declared_band_id = capacity_contract.get("coverage_band_id")
    if declared_band_id is not None:
        if type(declared_band_id) is not str:
            raise FinalMeshFloorEvidenceError(
                "candidate_finalization_prefix_identity_mismatch"
            )
        try:
            declared_band = resolve_coverage_band(declared_band_id)
        except KeyError as error:
            raise FinalMeshFloorEvidenceError(
                "candidate_finalization_prefix_identity_mismatch"
            ) from error
        raw_ground_capacity = trusted_legal_floor_field.get(
            "bcr_footprint_capacity_m2"
        )
        if (
            type(raw_ground_capacity) not in (int, float)
            or not isfinite(float(raw_ground_capacity))
            or float(raw_ground_capacity) <= 0.0
        ):
            raise FinalMeshFloorEvidenceError(
                "candidate_finalization_prefix_identity_mismatch"
            )
        bounded_caps = capacities_under_band(
            trusted_caps,
            ground_capacity_m2=float(raw_ground_capacity),
            band=declared_band,
        )
        trusted_prefix_capacity = round(sum(bounded_caps), 3)
        trusted_caps = [round(value, 3) for value in bounded_caps]
    floor_context_tops = floor_context.get("floor_top_heights_m")
    capacity_tops = capacity_contract.get(
        "candidate_floor_top_heights_m"
    )
    capacity_areas = capacity_contract.get(
        "legal_floor_section_areas_m2"
    )
    capacity_caps = capacity_contract.get(
        "bcr_adjusted_floor_areas_m2"
    )
    prefix_capacity = capacity_contract.get(
        "candidate_prefix_capacity_m2"
    )
    vectors = (
        (floor_context_tops, trusted_tops),
        (capacity_tops, trusted_tops),
        (capacity_areas, trusted_areas),
        (capacity_caps, trusted_caps),
    )
    if (
        capacity_contract.get("candidate_target_reachable") is not True
        or any(
            type(actual) not in (list, tuple)
            or len(actual) != floor_count
            or not all(
                type(value) in (int, float)
                and isfinite(float(value))
                for value in actual
            )
            or any(
                abs(float(value) - float(expected)) > 1e-6
                for value, expected in zip(actual, trusted)
            )
            for actual, trusted in vectors
        )
        or type(prefix_capacity) not in (int, float)
        or not isfinite(float(prefix_capacity))
        or abs(float(prefix_capacity) - trusted_prefix_capacity) > 1e-6
        or abs(float(trusted_tops[-1]) - candidate_height_m) > 1e-6
    ):
        raise FinalMeshFloorEvidenceError(
            "candidate_finalization_prefix_identity_mismatch"
        )


def certify_final_mesh_actual_gfa_stop(
    *,
    certified_compilation: CompilationResult,
    projected_visual_certificate: Mapping[str, Any],
    legal_floor_field: Mapping[str, Any],
    expected_legal_floor_field_hash: str,
    expected_pnu: str,
    candidate_height_m: float,
    candidate_floor_count: int,
    candidate_target_gfa_m2: float,
    candidate_feasible_maximum_gfa_m2: float | None = None,
    candidate_minimum_capacity_utilization: float | None = None,
    candidate_capacity_resolution_hard_pass: bool | None = None,
    expected_identity: Mapping[str, str],
) -> dict[str, Any]:
    """Measure, issue, and immediately independently validate one stop seal."""

    evidence = measure_final_mesh_floor_evidence(
        certified_compilation=certified_compilation,
        projected_visual_certificate=projected_visual_certificate,
        legal_floor_field=legal_floor_field,
        expected_legal_floor_field_hash=expected_legal_floor_field_hash,
        candidate_height_m=candidate_height_m,
        candidate_floor_count=candidate_floor_count,
        expected_identity=expected_identity,
    )
    requested_target = float(candidate_target_gfa_m2)
    certified_actual_target = requested_target
    achieved_capacity_utilization: float | None = None
    capacity_contract_mode = "requested_exact_target"
    capacity_underfill: dict[str, Any] | None = None
    if (
        candidate_feasible_maximum_gfa_m2 is not None
        or candidate_minimum_capacity_utilization is not None
    ):
        raw_feasible = candidate_feasible_maximum_gfa_m2
        raw_minimum = candidate_minimum_capacity_utilization
        if (
            candidate_capacity_resolution_hard_pass is not True
            or
            type(raw_feasible) not in (int, float)
            or not isfinite(float(raw_feasible))
            or float(raw_feasible) <= 0.0
            or type(raw_minimum) not in (int, float)
            or not isfinite(float(raw_minimum))
            or float(raw_minimum) <= 0.0
            or float(raw_minimum) > 1.0
        ):
            raise FinalMeshFloorEvidenceError(
                "invalid_final_mesh_capacity_contract",
                candidate_capacity_resolution_hard_pass=(
                    candidate_capacity_resolution_hard_pass
                ),
                candidate_feasible_maximum_gfa_m2=raw_feasible,
                candidate_minimum_capacity_utilization=raw_minimum,
            )
        certified_actual_target = sum(evidence.actual_floor_areas_m2)
        achieved_capacity_utilization = (
            certified_actual_target / float(raw_feasible)
        )
        if (
            achieved_capacity_utilization + 1e-9
            < float(raw_minimum)
        ):
            # Underfill is advisory, not a rejection. FAR is a statutory
            # ceiling; building less than the maximum is always lawful, and
            # this project's own contract already records that "maximum legal
            # capacity is not a statutory minimum". Rejecting here discarded
            # otherwise fully lawful masses over shortfalls under 4%, and it
            # is the reason a diverse portfolio cannot survive: filling the
            # capacity floor forces every candidate to fill the envelope.
            # Every legal maximum below stays a hard gate.
            capacity_underfill = {
                "schema_version": "arr.maas.capacity_underfill_advisory.v1",
                "status": "advisory_below_requested_minimum",
                "hard_pass": True,
                "requested_candidate_target_gfa_m2": requested_target,
                "achieved_gfa_m2": certified_actual_target,
                "candidate_feasible_maximum_gfa_m2": float(raw_feasible),
                "achieved_capacity_utilization": (
                    achieved_capacity_utilization
                ),
                "candidate_minimum_capacity_utilization": (
                    float(raw_minimum)
                ),
                "statutory_minimum": False,
            }
            capacity_contract_mode = "advisory_actual_gfa_underfill"
        else:
            capacity_contract_mode = "accepted_actual_gfa_minimum_band"
    certificate = certify_candidate_actual_gfa_stop(
        legal_floor_field=legal_floor_field,
        expected_legal_floor_field_hash=expected_legal_floor_field_hash,
        expected_pnu=expected_pnu,
        expected_identity=expected_identity,
        measured_identity=evidence.measured_identity,
        actual_floor_areas_m2=evidence.actual_floor_areas_m2,
        containment_evidence=evidence.containment_evidence,
        target_gfa_m2=certified_actual_target,
    )
    independently_valid = (
        certificate.get("hard_pass") is True
        and validate_candidate_actual_gfa_stop_certificate(
            certificate,
            legal_floor_field=legal_floor_field,
            expected_legal_floor_field_hash=(
                expected_legal_floor_field_hash
            ),
            expected_pnu=expected_pnu,
            expected_identity=expected_identity,
            expected_target=certified_actual_target,
        )
    )
    if not independently_valid:
        raise FinalMeshFloorEvidenceError(
            "candidate_actual_gfa_stop_not_certified",
            certificate=deepcopy(certificate),
        )
    return {
        "schema_version": (
            "arr.maas.candidate_final_mesh_floor_finalization.v2"
        ),
        "status": "certified",
        "hard_pass": True,
        "candidate_height_m": float(candidate_height_m),
        "candidate_floor_count": int(candidate_floor_count),
        "candidate_target_gfa_m2": float(certified_actual_target),
        "requested_candidate_target_gfa_m2": requested_target,
        "achieved_gfa_m2": float(certificate["achieved_gfa_m2"]),
        "candidate_feasible_maximum_gfa_m2": (
            float(candidate_feasible_maximum_gfa_m2)
            if candidate_feasible_maximum_gfa_m2 is not None
            else None
        ),
        "candidate_minimum_capacity_utilization": (
            float(candidate_minimum_capacity_utilization)
            if candidate_minimum_capacity_utilization is not None
            else None
        ),
        "achieved_capacity_utilization": (
            achieved_capacity_utilization
        ),
        "capacity_contract_mode": capacity_contract_mode,
        "capacity_underfill_advisory": (
            dict(capacity_underfill) if capacity_underfill else {}
        ),
        "candidate_capacity_resolution_hard_pass": (
            candidate_capacity_resolution_hard_pass
        ),
        "legal_floor_field_hash": expected_legal_floor_field_hash,
        "candidate_actual_gfa_stop_hash": certificate[
            "candidate_actual_gfa_stop_hash"
        ],
        "candidate_actual_gfa_stop_certificate": deepcopy(certificate),
        "measured_identity": dict(evidence.measured_identity),
    }


def _validated_field(
    value: Mapping[str, Any],
    *,
    expected_hash: str,
) -> dict[str, Any]:
    if (
        type(value) is not dict
        or not _valid_sha256(expected_hash)
        or value.get("legal_floor_field_hash") != expected_hash
    ):
        raise FinalMeshFloorEvidenceError(
            "legal_floor_field_identity_mismatch"
        )
    if not validate_legal_floor_field(value):
        raise FinalMeshFloorEvidenceError("invalid_legal_floor_field")
    return value


def _validated_candidate_floor_count(
    value: Any,
    *,
    field_count: int,
) -> int:
    if (
        type(value) is not int
        or value <= 0
        or value > field_count
    ):
        raise FinalMeshFloorEvidenceError(
            "invalid_candidate_floor_count"
        )
    return value


def _validated_candidate_height(
    value: Any,
    *,
    floor_count: int,
    floor_tops: list[Any],
) -> float:
    if (
        type(value) not in (int, float)
        or not isfinite(float(value))
        or float(value) <= 0.0
    ):
        raise FinalMeshFloorEvidenceError("invalid_candidate_height")
    height = float(value)
    expected_height = float(floor_tops[floor_count - 1])
    if abs(height - expected_height) > 1e-6:
        raise FinalMeshFloorEvidenceError(
            "candidate_height_floor_prefix_mismatch",
            expected_height_m=expected_height,
            candidate_height_m=height,
        )
    return height


def _validated_visible_mesh_identity(
    compilation: Any,
    certificate: Any,
    *,
    expected_identity: Any,
) -> dict[str, str]:
    if (
        not isinstance(compilation, CompilationResult)
        or compilation.status != "compiled"
        or type(compilation.metrics) is not dict
        or compilation.metrics.get("geometry_authority")
        != "certified_projected_visual_mesh"
        or type(certificate) is not dict
        or certificate.get("status") != "certified"
        or certificate.get("hard_pass") is not True
    ):
        raise FinalMeshFloorEvidenceError(
            "invalid_final_mesh_authority"
        )
    if (
        certificate.get("certification_mode")
        != FINAL_AUTHORITY_CERTIFICATION_MODE
    ):
        raise FinalMeshFloorEvidenceError(
            "invalid_final_mesh_authority"
        )
    if (
        compilation.metrics.get("coordinate_space")
        != AUTHORED_COORDINATE_SPACE
        or certificate.get("projected_surface_coordinate_frame")
        != AUTHORED_COORDINATE_SPACE
    ):
        raise FinalMeshFloorEvidenceError(
            "invalid_final_mesh_coordinate_space"
        )
    if (
        type(expected_identity) is not dict
        or frozenset(expected_identity) != frozenset(IDENTITY_KEYS)
        or not all(
            _valid_sha256(expected_identity.get(key))
            for key in IDENTITY_KEYS
        )
    ):
        raise FinalMeshFloorEvidenceError(
            "invalid_expected_final_mesh_identity"
        )
    actual = {
        "program_hash": compilation.program.program_hash(),
        "final_geometry_hash": str(
            certificate.get("final_geometry_hash") or ""
        ),
        "visual_hash": str(compilation.geometry_hash or ""),
    }
    if (
        certificate.get("final_program_hash") != actual["program_hash"]
        or certificate.get("visual_hash") != actual["visual_hash"]
        or any(actual[key] != expected_identity[key] for key in IDENTITY_KEYS)
    ):
        raise FinalMeshFloorEvidenceError(
            "final_mesh_identity_mismatch"
        )
    return actual


def _validated_visual_origin(
    certificate: Mapping[str, Any],
) -> tuple[float, float]:
    raw_origin = certificate.get("source_footprint_centroid_utm")
    if (
        type(raw_origin) not in (list, tuple)
        or len(raw_origin) != 2
        or not all(
            type(value) in (int, float) and isfinite(float(value))
            for value in raw_origin
        )
    ):
        raise FinalMeshFloorEvidenceError(
            "invalid_final_mesh_source_centroid"
        )
    return float(raw_origin[0]), float(raw_origin[1])


def _validated_visible_mesh(
    compilation: CompilationResult,
    *,
    maximum_height_m: float,
) -> tuple[
    tuple[tuple[float, float, float], ...],
    tuple[tuple[int, int, int], ...],
]:
    vertices = compilation.vertices
    triangles = compilation.triangles
    if type(vertices) not in (list, tuple) or not vertices:
        raise FinalMeshFloorEvidenceError("invalid_final_mesh_vertices")
    canonical_vertices: list[tuple[float, float, float]] = []
    for raw_vertex in vertices:
        if type(raw_vertex) not in (list, tuple) or len(raw_vertex) != 3:
            raise FinalMeshFloorEvidenceError("invalid_final_mesh_vertices")
        if not all(
            type(value) in (int, float) and isfinite(float(value))
            for value in raw_vertex
        ):
            raise FinalMeshFloorEvidenceError(
                "nonfinite_final_mesh_vertex"
            )
        vertex = tuple(float(value) for value in raw_vertex)
        if vertex[2] > maximum_height_m + 1e-9:
            raise FinalMeshFloorEvidenceError(
                "final_mesh_above_candidate_height",
                maximum_physical_z_m=vertex[2],
                candidate_height_m=maximum_height_m,
            )
        if vertex[2] < 0.0:
            raise FinalMeshFloorEvidenceError(
                "invalid_final_mesh_physical_z",
                minimum_physical_z_m=vertex[2],
            )
        canonical_vertices.append(vertex)
    if type(triangles) not in (list, tuple) or not triangles:
        raise FinalMeshFloorEvidenceError("invalid_final_mesh_triangles")
    canonical_triangles: list[tuple[int, int, int]] = []
    for raw_triangle in triangles:
        if (
            type(raw_triangle) not in (list, tuple)
            or len(raw_triangle) != 3
            or not all(type(index) is int for index in raw_triangle)
            or len(set(raw_triangle)) != 3
            or any(
                index < 0 or index >= len(canonical_vertices)
                for index in raw_triangle
            )
        ):
            raise FinalMeshFloorEvidenceError(
                "invalid_final_mesh_triangles"
            )
        canonical_triangles.append(tuple(raw_triangle))
    return tuple(canonical_vertices), tuple(canonical_triangles)


def _mesh_section_segments(
    vertices: tuple[tuple[float, float, float], ...],
    triangles: tuple[tuple[int, int, int], ...],
    z: float,
) -> tuple[LineString, ...]:
    segments: list[LineString] = []
    for triangle in triangles:
        points = tuple(vertices[index] for index in triangle)
        if all(
            abs(point[2] - z) <= SECTION_EPSILON
            for point in points
        ):
            # A tessellated horizontal face lies in the sampling plane and is
            # area material, not a section boundary. Adjacent non-coplanar
            # faces supply its true perimeter.
            continue
        intersections: list[tuple[float, float]] = []
        for left, right in zip(points, (*points[1:], points[0])):
            left_delta = left[2] - z
            right_delta = right[2] - z
            if abs(left_delta) <= SECTION_EPSILON:
                intersections.append((left[0], left[1]))
            if left_delta * right_delta < -(SECTION_EPSILON ** 2):
                amount = (z - left[2]) / (right[2] - left[2])
                intersections.append((
                    left[0] + (right[0] - left[0]) * amount,
                    left[1] + (right[1] - left[1]) * amount,
                ))
        unique: list[tuple[float, float]] = []
        for point in intersections:
            if not any(
                hypot(
                    point[0] - other[0],
                    point[1] - other[1],
                )
                <= SECTION_EPSILON
                for other in unique
            ):
                unique.append(point)
        if len(unique) < 2:
            continue
        segment = tuple(
            (float(point[0]), float(point[1]))
            for point in unique[:2]
        )
        if segment[0] != segment[1]:
            segments.append(LineString(segment))
    if not segments:
        return ()
    return tuple(segments)


def _polygonize_section_segments(
    segments: tuple[LineString, ...],
) -> Polygon | Any | None:
    noded_segments = _node_section_segments(segments)
    linework = unary_union(noded_segments)
    if not linework.boundary.is_empty:
        return None
    polygons = tuple(polygonize(linework))
    if not polygons:
        return None
    hole_regions = tuple(
        Polygon(interior)
        for polygon in polygons
        for interior in polygon.interiors
    )
    retained = tuple(
        polygon
        for polygon in polygons
        if not any(
            hole.covers(polygon.representative_point())
            for hole in hole_regions
        )
    )
    return unary_union(retained or polygons)


def _raw_section_area_m2(
    segments: tuple[LineString, ...],
) -> float:
    """Green's-theorem area from unrounded accepted segment coordinates."""

    signed_twice_area = 0.0
    for segment in segments:
        coordinates = tuple(segment.coords)
        left = coordinates[0]
        right = coordinates[-1]
        signed_twice_area += (
            float(left[0]) * float(right[1])
            - float(right[0]) * float(left[1])
        )
    return abs(signed_twice_area) / 2.0


def _node_section_segments(
    segments: tuple[LineString, ...],
) -> tuple[LineString, ...]:
    """Close only numerical endpoint gaps using an original endpoint.

    This establishes graph topology without rounding or averaging accepted
    coordinates. Exact containment is checked separately against every raw
    segment before the polygon can be certified.
    """

    representatives: list[tuple[float, float]] = []

    def node(point: tuple[float, float]) -> int:
        for index, representative in enumerate(representatives):
            if hypot(
                point[0] - representative[0],
                point[1] - representative[1],
            ) <= 1e-8:
                return index
        representatives.append(point)
        return len(representatives) - 1

    edges: list[tuple[int, int]] = []
    for segment in segments:
        coordinates = tuple(segment.coords)
        left = node((
            float(coordinates[0][0]),
            float(coordinates[0][1]),
        ))
        right = node((
            float(coordinates[-1][0]),
            float(coordinates[-1][1]),
        ))
        if left != right:
            edges.append((left, right))
    return tuple(
        LineString((representatives[left], representatives[right]))
        for left, right in edges
    )


def _valid_sha256(value: Any) -> bool:
    return bool(
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _valid_pnu(value: Any) -> bool:
    return bool(
        type(value) is str
        and len(value) == 19
        and all("0" <= character <= "9" for character in value)
    )


__all__ = [
    "CandidateFinalizationContext",
    "FinalMeshFloorEvidence",
    "FinalMeshFloorEvidenceError",
    "certify_final_mesh_actual_gfa_stop",
    "measure_final_mesh_floor_evidence",
    "resolve_candidate_finalization_context",
]
