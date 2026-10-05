"""Certify an authored visual mesh against floorwise legal Matrix4 evidence.

Capacity plates remain the only GFA authority.  This module carries only the
renderer-visible profiled mesh through the already-certified floor transforms.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from math import isfinite, sqrt
from typing import Any, Iterable, Sequence

from shapely import from_wkb
from shapely.geometry import LineString, MultiPoint, Point, Polygon
from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.source_geometry.ir import SourceMass, SourceSurface, SourceVolume

from backend.app.modules.design.generation.maas.geometry_language.affine_matrix import Matrix4, transform_point3, validate_matrix4
from backend.app.modules.design.generation.maas.geometry_language.profiled_mesh_clip import clip_profiled_mesh_above_z
from backend.app.modules.design.generation.maas.geometry_language.profiled_mesh_numeric_repair import revalidated_profiled_mesh


@dataclass(frozen=True)
class FloorwiseVisualProjectionCertificate:
    status: str
    hard_pass: bool
    failure_reasons: tuple[str, ...] = ()
    visual_hash: str = ""
    source_surface_count: int = 0
    projected_surface_count: int = 0
    legal_sample_count: int = 0
    capacity_gfa_m2: float = 0.0
    floor_count: int = 0
    certification_mode: str = "floorwise_capacity_projection"
    source_surface_coordinate_frame: str = (
        "source_footprint_centroid_local_xy_normalized_z"
    )
    projected_surface_coordinate_frame: str = (
        "capacity_source_centroid_local_xy_normalized_z"
    )
    visible_geometry_operation: str = "floorwise_matrix_projection"
    exact_surface_payload_hash: str = ""
    capacity_authority: str = "floorwise_legal_volumes"
    visible_step_fallback: bool = False
    section_profile_hash: str = ""
    capacity_volume_hash: str = ""
    floor_capacity_plan_hash: str = ""
    matrix4_stack_hash: str = ""
    authored_program_hash: str = ""
    effective_height_m: float = 0.0
    verified_profiled_sloped_surface_area: float = 0.0
    verified_profiled_sloped_surface_ratio: float = 0.0
    verified_profiled_sloped_surface_hash: str = ""
    section_numeric_epsilon_m: float = 0.0
    floor_center_numeric_equivalence_schema: str = ""
    max_section_area_delta_m2: float = 0.0
    max_section_symdiff_m2: float = 0.0
    max_section_hausdorff_m: float = 0.0
    max_section_area_bound_m2: float = 0.0
    mesh_numeric_repair_schema: str = ""
    mesh_cleanup_collapse_threshold_m: float = 0.0
    mesh_cleanup_max_physical_displacement_m: float = 0.0
    mesh_cleanup_raw_indexed_mesh_hash: str = ""
    mesh_cleanup_raw_gate_failure_codes: tuple[str, ...] = ()
    mesh_cleanup_clean_indexed_mesh_hash: str = ""
    mesh_cleanup_clean_gate_hard_pass: bool = False
    occupied_section_topology: tuple[dict[str, Any], ...] = ()
    legal_section_topology: tuple[dict[str, Any], ...] = ()
    floor_center_topology_metrics: tuple[dict[str, Any], ...] = ()
    final_component_count: int = 0
    final_component_volumes_m3: tuple[float, ...] = ()
    final_closed_manifold_hard_pass: bool = False
    legal_revalidation_witness: dict[str, Any] = field(default_factory=dict)
    failure_witness: dict[str, Any] = field(default_factory=dict)
    section_geometry_binding_schema: str = ""
    section_geometry_binding_hash: str = ""
    occupied_section_wkb_hex: tuple[str, ...] = ()
    legal_section_wkb_hex: tuple[str, ...] = ()
    actual_section_wkb_hex: tuple[str, ...] = ()
    authority_binding_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "arr.maas.floorwise_visual_projection.v1",
            "status": self.status,
            "hard_pass": self.hard_pass,
            "failure_reasons": list(self.failure_reasons),
            "visual_hash": self.visual_hash,
            "source_surface_count": self.source_surface_count,
            "projected_surface_count": self.projected_surface_count,
            "legal_sample_count": self.legal_sample_count,
            "capacity_gfa_m2": round(self.capacity_gfa_m2, 4),
            "floor_count": int(self.floor_count),
            "capacity_authority": self.capacity_authority,
            "certification_mode": self.certification_mode,
            "source_surface_coordinate_frame": (
                self.source_surface_coordinate_frame
            ),
            "projected_surface_coordinate_frame": (
                self.projected_surface_coordinate_frame
            ),
            "matrix_convention": "row_major_column_vector",
            "visible_geometry_operation": self.visible_geometry_operation,
            "exact_surface_payload_hash": self.exact_surface_payload_hash,
            "visible_step_fallback": self.visible_step_fallback,
            "section_profile_hash": self.section_profile_hash,
            "capacity_volume_hash": self.capacity_volume_hash,
            "floor_capacity_plan_hash": self.floor_capacity_plan_hash,
            "matrix4_stack_hash": self.matrix4_stack_hash,
            "authored_program_hash": self.authored_program_hash,
            "effective_height_m": round(self.effective_height_m, 8),
            "verified_profiled_sloped_surface_area": round(
                self.verified_profiled_sloped_surface_area,
                8,
            ),
            "verified_profiled_sloped_surface_ratio": round(
                self.verified_profiled_sloped_surface_ratio,
                8,
            ),
            "verified_profiled_sloped_surface_hash": (
                self.verified_profiled_sloped_surface_hash
            ),
            "section_numeric_epsilon_m": round(
                self.section_numeric_epsilon_m,
                10,
            ),
            "floor_center_numeric_equivalence_schema": (
                self.floor_center_numeric_equivalence_schema
            ),
            "max_section_area_delta_m2": round(
                self.max_section_area_delta_m2,
                10,
            ),
            "max_section_symdiff_m2": round(
                self.max_section_symdiff_m2,
                10,
            ),
            "max_section_hausdorff_m": round(
                self.max_section_hausdorff_m,
                10,
            ),
            "max_section_area_bound_m2": round(
                self.max_section_area_bound_m2,
                10,
            ),
            "mesh_numeric_repair_schema": self.mesh_numeric_repair_schema,
            "mesh_cleanup_collapse_threshold_m": round(
                self.mesh_cleanup_collapse_threshold_m,
                12,
            ),
            "mesh_cleanup_max_physical_displacement_m": round(
                self.mesh_cleanup_max_physical_displacement_m,
                12,
            ),
            "mesh_cleanup_raw_indexed_mesh_hash": (
                self.mesh_cleanup_raw_indexed_mesh_hash
            ),
            "mesh_cleanup_raw_gate_failure_codes": list(
                self.mesh_cleanup_raw_gate_failure_codes
            ),
            "mesh_cleanup_clean_indexed_mesh_hash": (
                self.mesh_cleanup_clean_indexed_mesh_hash
            ),
            "mesh_cleanup_clean_gate_hard_pass": (
                self.mesh_cleanup_clean_gate_hard_pass
            ),
            "occupied_section_topology": [
                dict(row) for row in self.occupied_section_topology
            ],
            "legal_section_topology": [
                dict(row) for row in self.legal_section_topology
            ],
            "floor_center_topology_metrics": [
                dict(row) for row in self.floor_center_topology_metrics
            ],
            "final_component_count": int(self.final_component_count),
            "final_component_volumes_m3": [
                round(float(volume), 10)
                for volume in self.final_component_volumes_m3
            ],
            "final_closed_manifold_hard_pass": (
                self.final_closed_manifold_hard_pass
            ),
            "legal_revalidation_witness": dict(
                self.legal_revalidation_witness
            ),
            "failure_witness": dict(self.failure_witness),
            "section_geometry_binding_schema": self.section_geometry_binding_schema,
            "section_geometry_binding_hash": self.section_geometry_binding_hash,
            "occupied_section_wkb_hex": list(self.occupied_section_wkb_hex),
            "legal_section_wkb_hex": list(self.legal_section_wkb_hex),
            "actual_section_wkb_hex": list(self.actual_section_wkb_hex),
            "authority_binding_hash": self.authority_binding_hash,
        }


@dataclass(frozen=True)
class FloorwiseVisualProjection:
    surfaces: tuple[SourceSurface, ...]
    certificate: FloorwiseVisualProjectionCertificate


def certified_actual_section_areas(
    certificate: dict[str, Any],
) -> tuple[float, ...]:
    """Return areas of the renderer-visible certified floor sections."""

    if certificate.get("hard_pass") is not True:
        return ()
    encoded_sections = certificate.get("actual_section_wkb_hex")
    if not isinstance(encoded_sections, (list, tuple)) or not encoded_sections:
        return ()
    areas: list[float] = []
    try:
        for encoded in encoded_sections:
            geometry = from_wkb(bytes.fromhex(str(encoded)))
            area = float(geometry.area)
            if geometry.is_empty or not isfinite(area) or area <= 0.0:
                return ()
            areas.append(area)
    except (TypeError, ValueError):
        return ()
    return tuple(areas)


FLOORWISE_EXACT_AUTHORITY_CONTRACTS = {
    "floorwise_profiled_continuous_envelope_clip": (
        "authored_profiled_mesh_continuous_legal_envelope_intersection",
        False,
    ),
    "floorwise_profiled_legal_clip": (
        "authored_profiled_mesh_legal_solid_intersection",
        False,
    ),
    "floorwise_csg_section_loft": (
        "exact_legal_section_profile_loft",
        False,
    ),
    "floorwise_matrix_prism_exact_containment": (
        "floorwise_matrix_prism_recomposition",
        True,
    ),
}
FLOORWISE_EXACT_AUTHORITY_MODES = frozenset(
    FLOORWISE_EXACT_AUTHORITY_CONTRACTS
)
FLOOR_CENTER_NUMERIC_EQUIVALENCE_SCHEMA = (
    "arr.maas.floor_center_numeric_equivalence.v1"
)


def valid_floor_center_numeric_equivalence(
    certificate: dict[str, Any],
) -> bool:
    """Fail closed on tampered profiled-clip reconstruction metrics."""

    mode = certificate.get("certification_mode")
    if mode == "floorwise_profiled_continuous_envelope_clip":
        return _valid_continuous_visible_sections(certificate)
    if mode not in {
        "floorwise_profiled_legal_clip",
    }:
        return True
    try:
        epsilon = float(certificate["section_numeric_epsilon_m"])
        area_delta = float(certificate["max_section_area_delta_m2"])
        symdiff = float(certificate["max_section_symdiff_m2"])
        hausdorff = float(certificate["max_section_hausdorff_m"])
        area_bound = float(certificate["max_section_area_bound_m2"])
    except (KeyError, TypeError, ValueError):
        return False
    try:
        collapse_threshold = float(
            certificate.get("mesh_cleanup_collapse_threshold_m") or 0.0
        )
        cleanup_displacement = float(
            certificate.get(
                "mesh_cleanup_max_physical_displacement_m"
            ) or 0.0
        )
    except (TypeError, ValueError):
        return False
    repaired = bool(cleanup_displacement)
    expected_schema = (
        "arr.maas.floor_center_numeric_equivalence.v2"
        if repaired
        else FLOOR_CENTER_NUMERIC_EQUIVALENCE_SCHEMA
    )
    expected_epsilon = round((
        1e-6 + cleanup_displacement + 2e-8
        if repaired
        else 1e-6
    ), 10)
    repair_evidence_valid = (
        not repaired
        or (
            0.0 < cleanup_displacement <= 1e-5
            and collapse_threshold in (
                1e-8, 3e-8, 1e-7, 3e-7, 1e-5,
            )
            and cleanup_displacement <= collapse_threshold
            and certificate.get("mesh_numeric_repair_schema")
            == "arr.maas.profiled_mesh_numeric_repair.v1"
            and certificate.get("mesh_cleanup_raw_gate_failure_codes")
            == ["tiny_edge"]
            and bool(certificate.get("mesh_cleanup_raw_indexed_mesh_hash"))
            and bool(certificate.get("mesh_cleanup_clean_indexed_mesh_hash"))
            and certificate.get("mesh_cleanup_clean_gate_hard_pass") is True
        )
    )
    floor_count = int(certificate.get("floor_count") or 0)
    occupied_topology = certificate.get("occupied_section_topology")
    legal_topology = certificate.get("legal_section_topology")
    topology_metrics = certificate.get("floor_center_topology_metrics")
    final_component_count = int(certificate.get("final_component_count") or 0)
    final_component_volumes = certificate.get("final_component_volumes_m3")
    legal_witness = certificate.get("legal_revalidation_witness")
    topology_valid = bool(
        floor_count > 0
        and isinstance(occupied_topology, list)
        and isinstance(legal_topology, list)
        and isinstance(topology_metrics, list)
        and len(occupied_topology) == floor_count
        and len(legal_topology) == floor_count
        and len(topology_metrics) == floor_count
        and certificate.get("final_closed_manifold_hard_pass") is True
        and final_component_count > 0
        and isinstance(final_component_volumes, list)
        and len(final_component_volumes) == final_component_count
        and all(float(volume) > 0.0 for volume in final_component_volumes)
        and all(
            isinstance(row, dict)
            and row.get("valid") is True
            and int(row.get("component_count") or 0) > 0
            and int(row.get("hole_count") or 0) >= 0
            for row in (*occupied_topology, *legal_topology)
        )
        and all(
            isinstance(row, dict)
            and row.get("hard_pass") is True
            and int(row.get("component_count") or 0)
            == int(row.get("expected_component_count") or 0)
            and int(row.get("hole_count") or 0)
            == int(row.get("expected_hole_count") or 0)
            and int(row.get("contour_count") or 0)
            == int(row.get("component_count") or 0)
            + int(row.get("hole_count") or 0)
            for row in topology_metrics
        )
        and all(
            int(metric.get("expected_component_count") or 0)
            == int(occupied.get("component_count") or 0)
            and int(metric.get("expected_hole_count") or 0)
            == int(occupied.get("hole_count") or 0)
            and int(metric.get("floor_index") or 0)
            == int(occupied.get("floor_index") or 0)
            for occupied, metric in zip(occupied_topology, topology_metrics)
        )
        and isinstance(legal_witness, dict)
        and int(legal_witness.get("maximum_retained_count") or 0) == 64
        and isinstance(legal_witness.get("records"), list)
        and int(legal_witness.get("retained_count") or 0)
        == len(legal_witness["records"])
        and len(legal_witness["records"]) <= 64
        and int(legal_witness.get("total_count") or 0)
        >= len(legal_witness["records"])
        and bool(legal_witness.get("truncated"))
        == (
            int(legal_witness.get("total_count") or 0)
            > len(legal_witness["records"])
        )
    )
    return bool(
        certificate.get("floor_center_numeric_equivalence_schema")
        == expected_schema
        and epsilon == expected_epsilon
        and repair_evidence_valid
        and all(isfinite(value) and value >= 0.0 for value in (
            area_delta,
            symdiff,
            hausdorff,
            area_bound,
        ))
        and hausdorff <= epsilon
        and area_delta <= area_bound
        and symdiff <= area_bound
        and topology_valid
    )


def _valid_continuous_visible_sections(
    certificate: dict[str, Any],
) -> bool:
    """Validate actual authored sections without equating them to capacity."""

    try:
        floor_count = int(certificate.get("floor_count") or 0)
        epsilon = float(certificate["section_numeric_epsilon_m"])
        final_component_count = int(
            certificate.get("final_component_count") or 0
        )
        final_component_volumes = certificate[
            "final_component_volumes_m3"
        ]
        occupied = certificate["occupied_section_topology"]
        legal = certificate["legal_section_topology"]
        metrics = certificate["floor_center_topology_metrics"]
        actual_wkb = certificate["actual_section_wkb_hex"]
        decoded = tuple(
            from_wkb(bytes.fromhex(value))
            for value in actual_wkb
        )
    except (KeyError, TypeError, ValueError):
        return False
    legal_witness = certificate.get("legal_revalidation_witness")
    return bool(
        certificate.get("floor_center_numeric_equivalence_schema")
        == "arr.maas.floor_center_visible_section.v1"
        and floor_count > 0
        and isfinite(epsilon)
        and epsilon > 0.0
        and all(
            isinstance(rows, list) and len(rows) == floor_count
            for rows in (occupied, legal, metrics, actual_wkb)
        )
        and all(
            isinstance(row, dict)
            and row.get("valid") is True
            and row.get("hard_pass") is True
            and row.get("authority")
            == "renderer_visible_authored_section"
            and int(row.get("component_count") or 0) > 0
            and int(row.get("hole_count") or 0) >= 0
            and int(row.get("contour_count") or 0)
            == int(row.get("component_count") or 0)
            + int(row.get("hole_count") or 0)
            and isfinite(float(row.get("area_m2") or 0.0))
            and float(row.get("area_m2") or 0.0) > 0.0
            for row in metrics
        )
        and all(
            geometry.is_valid
            and not geometry.is_empty
            and geometry.normalize().wkb_hex == value
            and abs(float(geometry.area) - float(row["area_m2"]))
            <= max(1e-7, epsilon * max(1.0, float(geometry.length)))
            for geometry, value, row in zip(decoded, actual_wkb, metrics)
        )
        and certificate.get("final_closed_manifold_hard_pass") is True
        and final_component_count > 0
        and isinstance(final_component_volumes, list)
        and len(final_component_volumes) == final_component_count
        and all(float(volume) > 0.0 for volume in final_component_volumes)
        and isinstance(legal_witness, dict)
        and int(legal_witness.get("maximum_retained_count") or 0) == 64
        and isinstance(legal_witness.get("records"), list)
        and int(legal_witness.get("retained_count") or 0)
        == len(legal_witness["records"])
    )


def floorwise_authority_binding_hash(
    *,
    section_profile_hash: str,
    capacity_volume_hash: str,
    floor_capacity_plan_hash: str,
    matrix4_stack_hash: str,
    exact_surface_payload_hash: str,
    certification_mode: str,
    visible_geometry_operation: str,
    visible_step_fallback: bool,
    authored_program_hash: str = "",
    effective_height_m: float = 0.0,
    verified_profiled_sloped_surface_area: float = 0.0,
    verified_profiled_sloped_surface_ratio: float = 0.0,
    verified_profiled_sloped_surface_hash: str = "",
    section_numeric_epsilon_m: float = 0.0,
    floor_center_numeric_equivalence_schema: str = "",
    max_section_area_delta_m2: float = 0.0,
    max_section_symdiff_m2: float = 0.0,
    max_section_hausdorff_m: float = 0.0,
    max_section_area_bound_m2: float = 0.0,
    mesh_numeric_repair_schema: str = "",
    mesh_cleanup_collapse_threshold_m: float = 0.0,
    mesh_cleanup_max_physical_displacement_m: float = 0.0,
    mesh_cleanup_raw_indexed_mesh_hash: str = "",
    mesh_cleanup_raw_gate_failure_codes: Sequence[str] = (),
    mesh_cleanup_clean_indexed_mesh_hash: str = "",
    mesh_cleanup_clean_gate_hard_pass: bool = False,
    section_geometry_binding_hash: str = "",
) -> str:
    """Bind the exact visible payload to its legal/capacity authorities."""

    payload = {
        "section_profile_hash": str(section_profile_hash or ""),
        "capacity_volume_hash": str(capacity_volume_hash or ""),
        "floor_capacity_plan_hash": str(floor_capacity_plan_hash or ""),
        "matrix4_stack_hash": str(matrix4_stack_hash or ""),
        "exact_surface_payload_hash": str(exact_surface_payload_hash or ""),
        "certification_mode": str(certification_mode or ""),
        "visible_geometry_operation": str(
            visible_geometry_operation or ""
        ),
        "visible_step_fallback": bool(visible_step_fallback),
    }
    if (
        authored_program_hash
        or effective_height_m
        or verified_profiled_sloped_surface_area
        or verified_profiled_sloped_surface_ratio
        or verified_profiled_sloped_surface_hash
        or section_numeric_epsilon_m
        or floor_center_numeric_equivalence_schema
        or max_section_area_delta_m2
        or max_section_symdiff_m2
        or max_section_hausdorff_m
        or max_section_area_bound_m2
        or mesh_numeric_repair_schema
        or mesh_cleanup_collapse_threshold_m
        or mesh_cleanup_max_physical_displacement_m
        or mesh_cleanup_raw_indexed_mesh_hash
        or mesh_cleanup_raw_gate_failure_codes
        or mesh_cleanup_clean_indexed_mesh_hash
        or mesh_cleanup_clean_gate_hard_pass
        or section_geometry_binding_hash
    ):
        payload.update({
            "authored_program_hash": str(authored_program_hash or ""),
            "effective_height_m": round(float(effective_height_m or 0.0), 8),
            "verified_profiled_sloped_surface_area": round(
                float(verified_profiled_sloped_surface_area or 0.0),
                8,
            ),
            "verified_profiled_sloped_surface_ratio": round(
                float(verified_profiled_sloped_surface_ratio or 0.0),
                8,
            ),
            "verified_profiled_sloped_surface_hash": str(
                verified_profiled_sloped_surface_hash or ""
            ),
            "section_numeric_epsilon_m": round(
                float(section_numeric_epsilon_m or 0.0),
                10,
            ),
            "floor_center_numeric_equivalence_schema": str(
                floor_center_numeric_equivalence_schema or ""
            ),
            "max_section_area_delta_m2": round(
                float(max_section_area_delta_m2 or 0.0),
                10,
            ),
            "max_section_symdiff_m2": round(
                float(max_section_symdiff_m2 or 0.0),
                10,
            ),
            "max_section_hausdorff_m": round(
                float(max_section_hausdorff_m or 0.0),
                10,
            ),
            "max_section_area_bound_m2": round(
                float(max_section_area_bound_m2 or 0.0),
                10,
            ),
            "mesh_numeric_repair_schema": str(
                mesh_numeric_repair_schema or ""
            ),
            "mesh_cleanup_collapse_threshold_m": round(
                float(mesh_cleanup_collapse_threshold_m or 0.0),
                12,
            ),
            "mesh_cleanup_max_physical_displacement_m": round(
                float(mesh_cleanup_max_physical_displacement_m or 0.0),
                12,
            ),
            "mesh_cleanup_raw_indexed_mesh_hash": str(
                mesh_cleanup_raw_indexed_mesh_hash or ""
            ),
            "mesh_cleanup_raw_gate_failure_codes": [
                str(code) for code in mesh_cleanup_raw_gate_failure_codes
            ],
            "mesh_cleanup_clean_indexed_mesh_hash": str(
                mesh_cleanup_clean_indexed_mesh_hash or ""
            ),
            "mesh_cleanup_clean_gate_hard_pass": bool(
                mesh_cleanup_clean_gate_hard_pass
            ),
            "section_geometry_binding_hash": str(
                section_geometry_binding_hash or ""
            ),
        })
    return sha256(json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


class _BufferedLegalSections:
    """Lazily reuse the exact numerical-tolerance buffer within one certificate."""

    def __init__(
        self,
        legal_sections: Sequence[Any],
        *,
        buffer_distance_m: float = 1e-7,
    ) -> None:
        self._sections = tuple(legal_sections)
        distance = float(buffer_distance_m)
        if not isfinite(distance) or distance < 0.0:
            raise ValueError("legal-section buffer distance must be finite and nonnegative")
        self._buffer_distance_m = distance
        self._buffered: dict[int, Any] = {}

    def __len__(self) -> int:
        return len(self._sections)

    def __getitem__(self, index: int) -> Any:
        normalized = index if index >= 0 else len(self._sections) + index
        if normalized not in self._buffered:
            self._buffered[normalized] = self._sections[normalized].buffer(
                self._buffer_distance_m
            )
        return self._buffered[normalized]


def certify_authored_visual_mesh(
    source: SourceMass,
    legal_sections: Sequence[Any],
) -> FloorwiseVisualProjection:
    """Validate one exact authored triangle skin without projecting it."""

    profiled = tuple(
        surface
        for surface in source.surfaces
        if isinstance(surface, SourceSurface)
        and surface.surface_type.startswith("profiled_")
    )
    if not profiled:
        return _failed(
            "missing_authored_visual_mesh",
            capacity_gfa=0.0,
            source_surface_count=0,
        )
    completeness_failure = _profiled_export_completeness_failure(
        source,
        profiled,
    )
    if completeness_failure:
        return _failed(
            completeness_failure,
            capacity_gfa=0.0,
            source_surface_count=len(profiled),
        )
    if (
        not legal_sections
        or any(
            not isinstance(section, Polygon)
            or section.is_empty
            or not section.is_valid
            or float(section.area) <= 1e-9
            for section in legal_sections
        )
    ):
        return _failed(
            "incomplete_authored_visual_legal_sections",
            capacity_gfa=0.0,
            source_surface_count=len(profiled),
        )
    buffered_legal_sections = _BufferedLegalSections(legal_sections)
    source_origin = source.footprint.centroid
    if not (
        isfinite(float(source_origin.x))
        and isfinite(float(source_origin.y))
    ):
        return _failed(
            "invalid_authored_visual_source_centroid",
            capacity_gfa=0.0,
            source_surface_count=len(profiled),
        )

    section_count = len(legal_sections)
    section_breakpoints = tuple(
        index / section_count
        for index in range(1, section_count)
    )
    legal_sample_count = 0
    for surface in profiled:
        try:
            local_triangle = tuple(
                (float(x), float(y), float(z))
                for x, y, z in surface.vertices_m
            )
        except (TypeError, ValueError):
            return _failed(
                "invalid_authored_visual_triangle",
                capacity_gfa=0.0,
                source_surface_count=len(profiled),
            )
        if not _finite_triangle(local_triangle):
            return _failed(
                "invalid_authored_visual_triangle",
                capacity_gfa=0.0,
                source_surface_count=len(profiled),
            )
        if any(z < 0.0 or z > 1.0 for _x, _y, z in local_triangle):
            return _failed(
                "authored_visual_normalized_z_out_of_range",
                capacity_gfa=0.0,
                source_surface_count=len(profiled),
            )
        world_triangle = tuple(
            (
                float(source_origin.x) + x,
                float(source_origin.y) + y,
                z,
            )
            for x, y, z in local_triangle
        )
        sample_points = _section_evidence_points(
            world_triangle,
            floor_count=section_count,
        )
        for point in sample_points:
            if not _legal_sections_cover_point(
                point,
                legal_sections=buffered_legal_sections,
            ):
                return _failed(
                    "authored_visual_surface_outside_legal_envelope",
                    capacity_gfa=0.0,
                    source_surface_count=len(profiled),
                    legal_sample_count=legal_sample_count + 1,
                )
            legal_sample_count += 1
        pieces = _split_triangle_at_z_breakpoints(
            world_triangle,
            breakpoints=section_breakpoints,
        )
        if not pieces:
            return _failed(
                "invalid_authored_visual_triangle",
                capacity_gfa=0.0,
                source_surface_count=len(profiled),
                legal_sample_count=legal_sample_count,
            )
        for piece in pieces:
            indices = _legal_section_indices_for_triangle(
                piece,
                section_count=section_count,
            )
            if not _legal_sections_cover_triangle(
                piece,
                legal_sections=buffered_legal_sections,
                legal_indices=indices,
            ):
                return _failed(
                    "authored_visual_surface_outside_legal_envelope",
                    capacity_gfa=0.0,
                    source_surface_count=len(profiled),
                    legal_sample_count=legal_sample_count + len(indices),
                )
            legal_sample_count += len(indices)
        boundary_sample_count = _boundary_intersection_sample_count(
            world_triangle,
            legal_sections=buffered_legal_sections,
        )
        if boundary_sample_count is None:
            return _failed(
                "authored_visual_surface_outside_legal_envelope",
                capacity_gfa=0.0,
                source_surface_count=len(profiled),
                legal_sample_count=legal_sample_count + 1,
            )
        legal_sample_count += boundary_sample_count

    visual_hash = _stable_visual_hash(profiled)
    return FloorwiseVisualProjection(
        surfaces=profiled,
        certificate=FloorwiseVisualProjectionCertificate(
            status="certified",
            hard_pass=True,
            visual_hash=visual_hash,
            source_surface_count=len(profiled),
            projected_surface_count=len(profiled),
            legal_sample_count=legal_sample_count,
            floor_count=len(legal_sections),
            certification_mode="authored_visual_legal_validation",
            projected_surface_coordinate_frame=(
                "source_footprint_centroid_local_xy_normalized_z"
            ),
            visible_geometry_operation="validated_without_projection",
            exact_surface_payload_hash=_exact_surface_payload_hash(profiled),
            capacity_authority="separate_not_visual_authority",
        ),
    )


def project_floorwise_visual_mesh(
    source: SourceMass,
    legal_sections: Sequence[Any],
    floor_matrices: Sequence[Sequence[Sequence[float]]],
    capacity_plates: Sequence[SourceVolume],
    *,
    output_origin: Sequence[float] | None = None,
) -> FloorwiseVisualProjection:
    """Project a complete authored triangle skin through the legal matrix field."""

    capacity_gfa = sum(
        max(0.0, float(plate.footprint.area))
        for plate in capacity_plates
    )
    profiled = tuple(
        surface
        for surface in source.surfaces
        if surface.surface_type.startswith("profiled_")
    )
    if not profiled:
        return _not_applicable(
            "not_applicable_no_authored_mesh",
            capacity_gfa=capacity_gfa,
        )
    completeness_failure = _profiled_export_completeness_failure(
        source,
        profiled,
    )
    if completeness_failure:
        return _failed(
            completeness_failure,
            capacity_gfa=capacity_gfa,
            source_surface_count=len(profiled),
        )

    try:
        matrices = tuple(validate_matrix4(matrix) for matrix in floor_matrices)
    except (TypeError, ValueError):
        return _failed(
            "invalid_floorwise_visual_matrix",
            capacity_gfa=capacity_gfa,
            source_surface_count=len(profiled),
        )
    if (
        not matrices
        or len(matrices) != len(legal_sections)
        or not capacity_plates
    ):
        return _failed(
            "incomplete_floorwise_visual_projection_evidence",
            capacity_gfa=capacity_gfa,
            source_surface_count=len(profiled),
        )
    buffered_legal_sections = _BufferedLegalSections(legal_sections)

    capacity_origin = (
        _validated_output_origin(output_origin)
        if output_origin is not None
        else _capacity_origin(capacity_plates)
    )
    if capacity_origin is None:
        return _failed(
            "invalid_capacity_source_centroid",
            capacity_gfa=capacity_gfa,
            source_surface_count=len(profiled),
        )
    source_origin = source.footprint.centroid
    breakpoints = tuple(
        (index + 0.5) / len(matrices)
        for index in range(len(matrices))
    )
    tessellation_levels = tuple(sorted({
        *breakpoints,
        *(
            index / len(matrices)
            for index in range(1, len(matrices))
        ),
    }))
    projected: list[SourceSurface] = []
    legal_sample_count = 0

    for surface in profiled:
        world_triangle = tuple(
            (
                float(source_origin.x) + float(x),
                float(source_origin.y) + float(y),
                float(z),
            )
            for x, y, z in surface.vertices_m
        )
        if not _finite_triangle(world_triangle):
            return _failed(
                "invalid_authored_visual_triangle",
                capacity_gfa=capacity_gfa,
                source_surface_count=len(profiled),
            )
        if any(z < 0.0 or z > 1.0 for _x, _y, z in world_triangle):
            return _failed(
                "authored_visual_normalized_z_out_of_range",
                capacity_gfa=capacity_gfa,
                source_surface_count=len(profiled),
            )

        sample_points = _section_evidence_points(
            world_triangle,
            floor_count=len(matrices),
        )
        for point in sample_points:
            transformed = _transform_with_matrix_field(
                matrices,
                point,
                breakpoints=breakpoints,
            )
            if not _legal_sections_cover_point(
                transformed,
                legal_sections=buffered_legal_sections,
            ):
                return _failed(
                    "projected_visual_mesh_outside_legal_section",
                    capacity_gfa=capacity_gfa,
                    source_surface_count=len(profiled),
                    legal_sample_count=legal_sample_count + 1,
                )
            legal_sample_count += 1

        pieces = _split_triangle_at_z_breakpoints(
            world_triangle,
            breakpoints=tessellation_levels,
        )
        for piece_index, piece in enumerate(pieces, start=1):
            transformed = tuple(
                _transform_with_matrix_field(
                    matrices,
                    point,
                    breakpoints=breakpoints,
                )
                for point in piece
            )
            if not _finite_triangle(transformed):
                return _failed(
                    "degenerate_projected_visual_triangle",
                    capacity_gfa=capacity_gfa,
                    source_surface_count=len(profiled),
                    legal_sample_count=legal_sample_count,
                )
            legal_indices = _legal_section_indices_for_triangle(
                transformed,
                section_count=len(legal_sections),
            )
            if not _legal_sections_cover_triangle(
                transformed,
                legal_sections=buffered_legal_sections,
                legal_indices=legal_indices,
            ):
                return _failed(
                    "projected_visual_mesh_outside_legal_section",
                    capacity_gfa=capacity_gfa,
                    source_surface_count=len(profiled),
                    legal_sample_count=legal_sample_count + len(legal_indices),
                )
            legal_sample_count += len(legal_indices)
            boundary_sample_count = _boundary_intersection_sample_count(
                transformed,
                legal_sections=buffered_legal_sections,
            )
            if boundary_sample_count is None:
                return _failed(
                    "projected_visual_mesh_outside_legal_section",
                    capacity_gfa=capacity_gfa,
                    source_surface_count=len(profiled),
                    legal_sample_count=legal_sample_count + 1,
                )
            legal_sample_count += boundary_sample_count
            local = tuple(
                (
                    x - capacity_origin[0],
                    y - capacity_origin[1],
                    z,
                )
                for x, y, z in transformed
            )
            projected.append(SourceSurface(
                role=(
                    surface.role
                    if len(pieces) == 1
                    else f"{surface.role}:projected_piece_{piece_index:02d}"
                ),
                volume_role=surface.volume_role,
                verb=surface.verb,
                surface_type=surface.surface_type,
                vertices_m=local,
                operator=surface.operator,
                semantic_patch_id=surface.semantic_patch_id,
            ))

    surfaces = tuple(projected)
    visual_hash = _stable_visual_hash(surfaces)
    return FloorwiseVisualProjection(
        surfaces=surfaces,
        certificate=FloorwiseVisualProjectionCertificate(
            status="certified",
            hard_pass=True,
            visual_hash=visual_hash,
            source_surface_count=len(profiled),
            projected_surface_count=len(surfaces),
            legal_sample_count=legal_sample_count,
            capacity_gfa_m2=capacity_gfa,
            floor_count=len(matrices),
        ),
    )


def _not_applicable(
    status: str,
    *,
    capacity_gfa: float,
    source_surface_count: int = 0,
) -> FloorwiseVisualProjection:
    return FloorwiseVisualProjection(
        surfaces=(),
        certificate=FloorwiseVisualProjectionCertificate(
            status=status,
            hard_pass=True,
            source_surface_count=source_surface_count,
            capacity_gfa_m2=capacity_gfa,
        ),
    )


def _failed(
    reason: str,
    *,
    capacity_gfa: float,
    source_surface_count: int,
    legal_sample_count: int = 0,
) -> FloorwiseVisualProjection:
    return FloorwiseVisualProjection(
        surfaces=(),
        certificate=FloorwiseVisualProjectionCertificate(
            status="failed",
            hard_pass=False,
            failure_reasons=(reason,),
            source_surface_count=source_surface_count,
            legal_sample_count=legal_sample_count,
            capacity_gfa_m2=capacity_gfa,
        ),
    )


def _profiled_export_completeness_failure(
    source: SourceMass,
    surfaces: tuple[SourceSurface, ...],
) -> str:
    if (
        len(surfaces) != len(source.surfaces)
        or any(len(surface.vertices_m) != 3 for surface in surfaces)
    ):
        return "incomplete_authored_mesh_export"
    bridge = source.metadata.get("geometry_program_bridge_evidence")
    bridge = bridge if isinstance(bridge, dict) else {}
    raw_count = bridge.get("raw_mesh_triangle_count", 0)
    exported_count = bridge.get("exported_surface_count", 0)
    if (
        type(raw_count) is not int
        or raw_count < 0
        or type(exported_count) is not int
        or exported_count < 0
    ):
        return "incomplete_authored_mesh_export"
    if raw_count or exported_count:
        if raw_count != exported_count or raw_count != len(surfaces):
            return "incomplete_authored_mesh_export"
    if _has_closed_directed_edge_topology(surfaces):
        return ""
    return (
        ""
        if _kernel_certifies_complete_surface_mesh(surfaces)
        else "unproven_authored_mesh_completeness"
    )


def _kernel_certifies_complete_surface_mesh(
    surfaces: tuple[SourceSurface, ...],
) -> bool:
    """Certify complete CSG triangle soups after the edge-count shortcut.

    Manifold boolean output can contain redundant coplanar facets, so a
    topologically closed solid may legitimately have an edge count above one
    in the transported triangle soup. Re-index the exact exported vertices
    and ask the authoritative kernel; open or non-manifold exports still fail.
    """

    vertices: list[tuple[float, float, float]] = []
    vertex_indices: dict[tuple[float, float, float], int] = {}
    triangles: list[tuple[int, int, int]] = []
    try:
        for surface in surfaces:
            triangle: list[int] = []
            for raw_point in surface.vertices_m:
                point = tuple(float(value) for value in raw_point)
                if len(point) != 3 or not all(isfinite(value) for value in point):
                    return False
                if point not in vertex_indices:
                    vertex_indices[point] = len(vertices)
                    vertices.append(point)
                triangle.append(vertex_indices[point])
            if len(triangle) != 3 or len(set(triangle)) != 3:
                return False
            triangles.append(tuple(triangle))
    except (TypeError, ValueError, OverflowError):
        return False
    certified = revalidated_profiled_mesh(
        tuple(vertices),
        tuple(triangles),
    )
    return bool(
        certified is not None
        and certified.status == "compiled"
        and certified.metrics.get("closed_solid") is True
        and certified.metrics.get("manifold") is True
    )


def _has_closed_directed_edge_topology(
    surfaces: tuple[SourceSurface, ...],
) -> bool:
    directed_counts: dict[
        tuple[tuple[float, float, float], tuple[float, float, float]],
        int,
    ] = {}
    for surface in surfaces:
        try:
            vertices = tuple(
                (round(float(x), 8), round(float(y), 8), round(float(z), 8))
                for x, y, z in surface.vertices_m
            )
        except (TypeError, ValueError, OverflowError):
            return False
        for left, right in zip(vertices, (*vertices[1:], vertices[0])):
            directed_counts[(left, right)] = (
                directed_counts.get((left, right), 0) + 1
            )
    return bool(directed_counts) and all(
        count == 1
        and directed_counts.get((right, left), 0) == 1
        for (left, right), count in directed_counts.items()
    )


def _capacity_origin(
    capacity_plates: Sequence[SourceVolume],
) -> tuple[float, float] | None:
    minimum_bottom = min(
        (float(plate.bottom_fraction) for plate in capacity_plates),
        default=None,
    )
    if minimum_bottom is None:
        return None
    ground = unary_union([
        plate.footprint
        for plate in capacity_plates
        if abs(float(plate.bottom_fraction) - minimum_bottom) <= 1e-8
    ])
    if ground.is_empty:
        return None
    center = ground.centroid
    if not (isfinite(float(center.x)) and isfinite(float(center.y))):
        return None
    return float(center.x), float(center.y)


def _validated_output_origin(
    output_origin: Sequence[float],
) -> tuple[float, float] | None:
    try:
        values = tuple(float(value) for value in output_origin)
    except (TypeError, ValueError):
        return None
    if len(values) != 2 or not all(isfinite(value) for value in values):
        return None
    return values


def _matrix_at_z(
    matrices: tuple[Matrix4, ...],
    z: float,
    *,
    breakpoints: tuple[float, ...],
) -> Matrix4:
    if len(matrices) == 1 or z <= breakpoints[0]:
        return matrices[0]
    if z >= breakpoints[-1]:
        return matrices[-1]
    floor_count = len(matrices)
    for index, lower_center in enumerate(breakpoints[:-1]):
        floor_boundary = (index + 1) / floor_count
        upper_center = breakpoints[index + 1]
        if lower_center <= z <= floor_boundary:
            amount = (
                (z - lower_center)
                / max(floor_boundary - lower_center, 1e-12)
            )
            return tuple(tuple(
                matrices[index][row][column] * (1.0 - amount)
                + matrices[index + 1][row][column] * amount
                for column in range(4)
            ) for row in range(4))
        if floor_boundary <= z <= upper_center:
            return matrices[index + 1]
    return matrices[-1]


def _transform_with_matrix_field(
    matrices: tuple[Matrix4, ...],
    point: tuple[float, float, float],
    *,
    breakpoints: tuple[float, ...],
) -> tuple[float, float, float]:
    return transform_point3(
        _matrix_at_z(matrices, point[2], breakpoints=breakpoints),
        point,
    )


def _legal_sections_cover_point(
    point: tuple[float, float, float],
    *,
    legal_sections: Sequence[Any],
) -> bool:
    x, y, z = point
    count = len(legal_sections)
    probe = Point(x, y)
    if z <= 0.0:
        indices = (0,)
    elif z >= 1.0:
        indices = (count - 1,)
    else:
        scaled = z * count
        boundary = round(scaled)
        if abs(scaled - boundary) <= 1e-8 and 0 < boundary < count:
            indices = (boundary - 1, boundary)
        else:
            indices = (min(count - 1, int(scaled)),)
    return all(legal_sections[index].covers(probe) for index in indices)


def _legal_section_indices_for_triangle(
    triangle: tuple[tuple[float, float, float], ...],
    *,
    section_count: int,
) -> tuple[int, ...]:
    minimum_z = max(0.0, min(1.0, min(point[2] for point in triangle)))
    maximum_z = max(0.0, min(1.0, max(point[2] for point in triangle)))
    middle_z = (minimum_z + maximum_z) / 2.0
    primary = min(section_count - 1, max(0, int(middle_z * section_count)))
    return (primary,)


def _legal_sections_cover_triangle(
    triangle: tuple[tuple[float, float, float], ...],
    *,
    legal_sections: Sequence[Any],
    legal_indices: Sequence[int],
) -> bool:
    coordinates = [(float(x), float(y)) for x, y, _z in triangle]
    polygon = Polygon(coordinates)
    projected = (
        polygon
        if not polygon.is_empty and polygon.area > 1e-12
        else LineString((*coordinates, coordinates[0]))
    )
    if projected.is_empty:
        return False
    return all(
        legal_sections[index].covers(projected)
        for index in legal_indices
    )


def _boundary_intersection_sample_count(
    triangle: tuple[tuple[float, float, float], ...],
    *,
    legal_sections: Sequence[Any],
) -> int | None:
    count = len(legal_sections)
    sample_count = 0
    for boundary in range(1, count):
        level = boundary / count
        points = _triangle_plane_intersections(triangle, level)
        unique = tuple(dict.fromkeys(
            (
                round(float(x), 10),
                round(float(y), 10),
            )
            for x, y, _z in points
        ))
        if not unique:
            continue
        intersection = (
            Point(unique[0])
            if len(unique) == 1
            else MultiPoint(unique).convex_hull
        )
        if not all(
            legal_sections[index].covers(intersection)
            for index in (boundary - 1, boundary)
        ):
            return None
        sample_count += 2
    return sample_count


def _section_evidence_points(
    triangle: tuple[tuple[float, float, float], ...],
    *,
    floor_count: int,
) -> tuple[tuple[float, float, float], ...]:
    points = list(triangle)
    points.extend(
        tuple((left[index] + right[index]) / 2.0 for index in range(3))
        for left, right in zip(triangle, (*triangle[1:], triangle[0]))
    )
    points.append(tuple(sum(vertex[index] for vertex in triangle) / 3.0 for index in range(3)))
    levels = {
        index / floor_count
        for index in range(floor_count + 1)
    } | {
        (index + 0.5) / floor_count
        for index in range(floor_count)
    }
    for level in sorted(levels):
        points.extend(_triangle_plane_intersections(triangle, level))
    unique = {
        (
            round(float(point[0]), 10),
            round(float(point[1]), 10),
            round(float(point[2]), 10),
        )
        for point in points
    }
    return tuple(sorted(unique))


def _triangle_plane_intersections(
    triangle: tuple[tuple[float, float, float], ...],
    level: float,
) -> tuple[tuple[float, float, float], ...]:
    points: list[tuple[float, float, float]] = []
    for left, right in zip(triangle, (*triangle[1:], triangle[0])):
        left_delta = left[2] - level
        right_delta = right[2] - level
        if abs(left_delta) <= 1e-10:
            points.append(left)
        if left_delta * right_delta < -1e-12:
            amount = (level - left[2]) / (right[2] - left[2])
            points.append(tuple(
                left[index] + (right[index] - left[index]) * amount
                for index in range(3)
            ))
    return tuple(points)


def _split_triangle_at_z_breakpoints(
    triangle: tuple[tuple[float, float, float], ...],
    *,
    breakpoints: Sequence[float],
) -> tuple[tuple[tuple[float, float, float], ...], ...]:
    polygons: list[tuple[tuple[float, float, float], ...]] = [triangle]
    for level in breakpoints:
        split: list[tuple[tuple[float, float, float], ...]] = []
        for polygon in polygons:
            minimum_z = min(point[2] for point in polygon)
            maximum_z = max(point[2] for point in polygon)
            if (
                maximum_z <= level + 1e-10
                or minimum_z >= level - 1e-10
            ):
                split.append(polygon)
                continue
            below = _clip_polygon_z(polygon, level=level, keep_below=True)
            above = _clip_polygon_z(polygon, level=level, keep_below=False)
            if len(below) >= 3:
                split.append(below)
            if len(above) >= 3:
                split.append(above)
        polygons = split
    triangles: list[tuple[tuple[float, float, float], ...]] = []
    seen: set[tuple[tuple[float, float, float], ...]] = set()
    for polygon in polygons:
        for index in range(1, len(polygon) - 1):
            piece = (polygon[0], polygon[index], polygon[index + 1])
            key = tuple(sorted(
                (
                    round(float(x), 10),
                    round(float(y), 10),
                    round(float(z), 10),
                )
                for x, y, z in piece
            ))
            if _finite_triangle(piece) and key not in seen:
                seen.add(key)
                triangles.append(piece)
    return tuple(triangles)


def _clip_polygon_z(
    polygon: tuple[tuple[float, float, float], ...],
    *,
    level: float,
    keep_below: bool,
) -> tuple[tuple[float, float, float], ...]:
    def inside(point: tuple[float, float, float]) -> bool:
        return point[2] <= level + 1e-10 if keep_below else point[2] >= level - 1e-10

    result: list[tuple[float, float, float]] = []
    previous = polygon[-1]
    previous_inside = inside(previous)
    for current in polygon:
        current_inside = inside(current)
        if current_inside != previous_inside:
            amount = (level - previous[2]) / (current[2] - previous[2])
            result.append(tuple(
                previous[index] + (current[index] - previous[index]) * amount
                for index in range(3)
            ))
        if current_inside:
            result.append(current)
        previous = current
        previous_inside = current_inside
    return tuple(result)


def _finite_triangle(
    triangle: Iterable[tuple[float, float, float]],
) -> bool:
    vertices = tuple(triangle)
    if len(vertices) != 3 or not all(
        isfinite(value)
        for vertex in vertices
        for value in vertex
    ):
        return False
    left = tuple(vertices[1][index] - vertices[0][index] for index in range(3))
    right = tuple(vertices[2][index] - vertices[0][index] for index in range(3))
    cross = (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )
    return sqrt(sum(value * value for value in cross)) > 1e-10


def _stable_visual_hash(surfaces: tuple[SourceSurface, ...]) -> str:
    payload = [
        {
            "role": surface.role,
            "volume_role": surface.volume_role,
            "surface_type": surface.surface_type,
            "semantic_patch_id": surface.semantic_patch_id,
            "vertices": [
                [round(float(x), 8), round(float(y), 8), round(float(z), 8)]
                for x, y, z in surface.vertices_m
            ],
        }
        for surface in surfaces
    ]
    return sha256(json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def projected_surface_visual_hash(
    surfaces: Sequence[SourceSurface],
) -> str:
    """Return the canonical Task-1 hash for projected profiled surfaces."""

    return _stable_visual_hash(tuple(surfaces))


def profiled_sloped_mesh_evidence(
    surfaces: Sequence[SourceSurface],
    *,
    effective_height_m: float,
) -> dict[str, Any]:
    """Measure the current exact mesh's physical non-axis sloped subset."""

    height = float(effective_height_m)
    if not isfinite(height) or height <= 0.0:
        return {
            "effective_height_m": 0.0,
            "sloped_surface_area": 0.0,
            "sloped_surface_ratio": 0.0,
            "sloped_surface_hash": "",
        }
    total_area = 0.0
    sloped_area = 0.0
    records: list[dict[str, Any]] = []
    for surface in surfaces:
        if (
            not isinstance(surface, SourceSurface)
            or surface.surface_type
            != "profiled_recursive_solid_mesh"
            or len(surface.vertices_m) != 3
        ):
            return {
                "effective_height_m": 0.0,
                "sloped_surface_area": 0.0,
                "sloped_surface_ratio": 0.0,
                "sloped_surface_hash": "",
            }
        triangle = tuple(
            (float(x), float(y), float(z) * height)
            for x, y, z in surface.vertices_m
        )
        left = tuple(
            triangle[1][axis] - triangle[0][axis]
            for axis in range(3)
        )
        right = tuple(
            triangle[2][axis] - triangle[0][axis]
            for axis in range(3)
        )
        normal = (
            left[1] * right[2] - left[2] * right[1],
            left[2] * right[0] - left[0] * right[2],
            left[0] * right[1] - left[1] * right[0],
        )
        magnitude = sqrt(sum(value * value for value in normal))
        if not isfinite(magnitude) or magnitude <= 1e-12:
            continue
        area = magnitude / 2.0
        total_area += area
        absolute_z = abs(normal[2]) / magnitude
        if 0.12 < absolute_z < 0.90:
            sloped_area += area
            records.append({
                "vertices_m": sorted([
                    [
                        round(float(x), 8),
                        round(float(y), 8),
                        round(float(z), 8),
                    ]
                    for x, y, z in surface.vertices_m
                ]),
            })
    ratio = sloped_area / max(total_area, 1e-12)
    if sloped_area <= 1e-8 or not records:
        return {
            "effective_height_m": height,
            "sloped_surface_area": 0.0,
            "sloped_surface_ratio": 0.0,
            "sloped_surface_hash": "",
        }
    payload = {
        "effective_height_m": round(height, 8),
        "triangles": sorted(records, key=lambda item: item["vertices_m"]),
    }
    return {
        "effective_height_m": height,
        "sloped_surface_area": sloped_area,
        "sloped_surface_ratio": ratio,
        "sloped_surface_hash": sha256(json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")).hexdigest(),
    }


def _exact_surface_payload_hash(
    surfaces: tuple[SourceSurface, ...],
) -> str:
    payload = [
        {
            "role": surface.role,
            "volume_role": surface.volume_role,
            "verb": surface.verb,
            "surface_type": surface.surface_type,
            "vertices_m": [
                [float(x), float(y), float(z)]
                for x, y, z in surface.vertices_m
            ],
            "operator": surface.operator,
            "semantic_patch_id": surface.semantic_patch_id,
        }
        for surface in surfaces
    ]
    return sha256(json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def clip_and_certify_projected_piloti_visual(
    surfaces: Sequence[SourceSurface],
    certificate: dict[str, Any],
    *,
    void_height_fraction: float,
) -> tuple[tuple[SourceSurface, ...], dict[str, Any]] | None:
    """Clip one certified closed visual skin above a piloti void and cap it."""

    source_surfaces = tuple(surfaces)
    minimum_z = float(void_height_fraction)
    if (
        not source_surfaces
        or not 0.0 < minimum_z < 1.0
        or certificate.get("schema_version")
        != "arr.maas.floorwise_visual_projection.v1"
        or certificate.get("status") != "certified"
        or certificate.get("hard_pass") is not True
        or int(certificate.get("projected_surface_count") or 0)
        != len(source_surfaces)
        or str(certificate.get("visual_hash") or "")
        != _stable_visual_hash(source_surfaces)
    ):
        return None
    floor_count = int(certificate.get("floor_count") or 0)
    if (
        str(certificate.get("certification_mode") or "")
        in FLOORWISE_EXACT_AUTHORITY_MODES
        and (
            floor_count <= 0
            or minimum_z >= 0.5 / floor_count - 1e-10
        )
    ):
        # Exact visual authority is bound to the capacity section at every
        # floor center. A piloti cut reaching the first sample would erase
        # that bound section while leaving its capacity hash unchanged.
        return None
    existing_fraction = certificate.get("piloti_void_height_fraction")
    if existing_fraction is not None:
        if (
            abs(float(existing_fraction) - minimum_z) <= 1e-10
            and certificate.get("piloti_visual_closed_mesh_hard_pass") is True
        ):
            return source_surfaces, dict(certificate)
        return None

    try:
        clipped = clip_profiled_mesh_above_z(
            source_surfaces,
            minimum_z=minimum_z,
        )
    except ValueError:
        return None
    output = clipped.surfaces
    output_exact_hash = _exact_surface_payload_hash(output)
    sloped_evidence = profiled_sloped_mesh_evidence(
        output,
        effective_height_m=float(
            certificate.get("effective_height_m") or 0.0
        ),
    )
    rebound_certificate = dict(certificate)
    rebound_certificate.update({
        "visual_hash": _stable_visual_hash(output),
        "projected_surface_count": len(output),
        "exact_surface_payload_hash": output_exact_hash,
        "effective_height_m": sloped_evidence["effective_height_m"],
        "verified_profiled_sloped_surface_area": (
            sloped_evidence["sloped_surface_area"]
        ),
        "verified_profiled_sloped_surface_ratio": (
            sloped_evidence["sloped_surface_ratio"]
        ),
        "verified_profiled_sloped_surface_hash": (
            sloped_evidence["sloped_surface_hash"]
        ),
        "piloti_void_height_fraction": round(minimum_z, 8),
        "piloti_visual_projection_status": "clipped_and_capped",
        "piloti_visual_closed_mesh_hard_pass": (
            clipped.closed_mesh_hard_pass
        ),
        "piloti_visual_boundary_loop_count": clipped.boundary_loop_count,
        "piloti_visual_removed_degenerate_count": (
            clipped.removed_degenerate_count
        ),
        "piloti_visual_removed_duplicate_count": (
            clipped.removed_duplicate_count
        ),
    })
    binding_fields = (
        "section_profile_hash",
        "capacity_volume_hash",
        "floor_capacity_plan_hash",
        "matrix4_stack_hash",
        "certification_mode",
        "visible_geometry_operation",
    )
    if all(str(rebound_certificate.get(key) or "") for key in binding_fields):
        rebound_certificate["authority_binding_hash"] = (
            floorwise_authority_binding_hash(
                section_profile_hash=str(
                    rebound_certificate["section_profile_hash"]
                ),
                capacity_volume_hash=str(
                    rebound_certificate["capacity_volume_hash"]
                ),
                floor_capacity_plan_hash=str(
                    rebound_certificate["floor_capacity_plan_hash"]
                ),
                matrix4_stack_hash=str(
                    rebound_certificate["matrix4_stack_hash"]
                ),
                exact_surface_payload_hash=output_exact_hash,
                certification_mode=str(
                    rebound_certificate["certification_mode"]
                ),
                visible_geometry_operation=str(
                    rebound_certificate["visible_geometry_operation"]
                ),
                visible_step_fallback=bool(
                    rebound_certificate.get("visible_step_fallback")
                ),
                authored_program_hash=str(
                    rebound_certificate.get("authored_program_hash") or ""
                ),
                effective_height_m=float(
                    rebound_certificate.get("effective_height_m") or 0.0
                ),
                verified_profiled_sloped_surface_area=float(
                    rebound_certificate.get(
                        "verified_profiled_sloped_surface_area"
                    ) or 0.0
                ),
                verified_profiled_sloped_surface_ratio=float(
                    rebound_certificate.get(
                        "verified_profiled_sloped_surface_ratio"
                    ) or 0.0
                ),
                verified_profiled_sloped_surface_hash=str(
                    rebound_certificate.get(
                        "verified_profiled_sloped_surface_hash"
                    ) or ""
                ),
                section_numeric_epsilon_m=float(
                    rebound_certificate.get(
                        "section_numeric_epsilon_m"
                    ) or 0.0
                ),
                floor_center_numeric_equivalence_schema=str(
                    rebound_certificate.get(
                        "floor_center_numeric_equivalence_schema"
                    ) or ""
                ),
                max_section_area_delta_m2=float(
                    rebound_certificate.get(
                        "max_section_area_delta_m2"
                    ) or 0.0
                ),
                max_section_symdiff_m2=float(
                    rebound_certificate.get(
                        "max_section_symdiff_m2"
                    ) or 0.0
                ),
                max_section_hausdorff_m=float(
                    rebound_certificate.get(
                        "max_section_hausdorff_m"
                    ) or 0.0
                ),
                max_section_area_bound_m2=float(
                    rebound_certificate.get(
                        "max_section_area_bound_m2"
                    ) or 0.0
                ),
                mesh_numeric_repair_schema=str(
                    rebound_certificate.get(
                        "mesh_numeric_repair_schema"
                    ) or ""
                ),
                mesh_cleanup_collapse_threshold_m=float(
                    rebound_certificate.get(
                        "mesh_cleanup_collapse_threshold_m"
                    ) or 0.0
                ),
                mesh_cleanup_max_physical_displacement_m=float(
                    rebound_certificate.get(
                        "mesh_cleanup_max_physical_displacement_m"
                    ) or 0.0
                ),
                mesh_cleanup_raw_indexed_mesh_hash=str(
                    rebound_certificate.get(
                        "mesh_cleanup_raw_indexed_mesh_hash"
                    ) or ""
                ),
                mesh_cleanup_raw_gate_failure_codes=tuple(
                    rebound_certificate.get(
                        "mesh_cleanup_raw_gate_failure_codes"
                    ) or ()
                ),
                mesh_cleanup_clean_indexed_mesh_hash=str(
                    rebound_certificate.get(
                        "mesh_cleanup_clean_indexed_mesh_hash"
                    ) or ""
                ),
                mesh_cleanup_clean_gate_hard_pass=bool(
                    rebound_certificate.get(
                        "mesh_cleanup_clean_gate_hard_pass"
                    )
                ),
                section_geometry_binding_hash=str(
                    rebound_certificate.get(
                        "section_geometry_binding_hash"
                    ) or ""
                ),
            )
        )
    return output, rebound_certificate


__all__ = [
    "FLOORWISE_EXACT_AUTHORITY_CONTRACTS",
    "FLOORWISE_EXACT_AUTHORITY_MODES",
    "FloorwiseVisualProjection",
    "FloorwiseVisualProjectionCertificate",
    "certify_authored_visual_mesh",
    "clip_and_certify_projected_piloti_visual",
    "floorwise_authority_binding_hash",
    "valid_floor_center_numeric_equivalence",
    "project_floorwise_visual_mesh",
    "projected_surface_visual_hash",
    "profiled_sloped_mesh_evidence",
]
