"""Recompile and measure one immutable certified geometry artifact."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import os
from types import SimpleNamespace
from typing import Any

from shapely.geometry import Polygon

from backend.app.modules.design.generation.maas.geometry_language import GeometryProgram, compile_geometry_program
from backend.app.modules.design.generation.maas.geometry_language.compiler import revalidate_compilation_mesh
from backend.app.modules.design.generation.maas.geometry_language.gate import compilation_gate
from backend.app.modules.design.generation.maas.geometry_language.projected_visual_contract import CertifiedMassArtifact, FINAL_AUTHORITY_CERTIFICATION_MODE, validate_projected_visual_artifact
from backend.app.modules.design.generation.maas.source_geometry.ir import SourceMass, SourceSurface, SourceVolume

from backend.app.modules.design.generation.maas.program_massing.competition_gestalt import CompetitionGestaltKey, _layer_sections, competition_gestalt_key


@dataclass(frozen=True)
class AuthoritativeCertifiedMeshMeasurement:
    program_hash: str
    final_geometry_hash: str
    visual_hash: str
    exact_mesh_payload_hash: str
    gestalt_key: CompetitionGestaltKey
    morphology: dict[str, Any]


class AuthoritativeArtifactMeasurementError(ValueError):
    def __init__(self, evidence: dict[str, Any]):
        self.evidence = dict(evidence)
        super().__init__(str(self.evidence.get("reason") or "authoritative_artifact_error"))


def _load_exact_selected_certified_artifact(
    artifact: dict[str, Any],
    *,
    final_semantic_anchor: dict[str, Any] | None,
    semantic_projection_audit: dict[str, Any] | None,
    expected_core_hash: str,
) -> CertifiedMassArtifact:
    if not isinstance(final_semantic_anchor, dict) or not final_semantic_anchor:
        raise AuthoritativeArtifactMeasurementError({
            "reason": "certified_artifact_authority_context_missing",
        })
    if not isinstance(semantic_projection_audit, dict) or not semantic_projection_audit:
        raise AuthoritativeArtifactMeasurementError({
            "reason": "certified_artifact_semantic_audit_missing",
        })
    if artifact.get("semanticProjectionAudit") != semantic_projection_audit:
        raise AuthoritativeArtifactMeasurementError({
            "reason": "certified_artifact_semantic_audit_mismatch",
        })
    if not str(expected_core_hash or ""):
        raise AuthoritativeArtifactMeasurementError({
            "reason": "certified_artifact_core_hash_missing",
        })
    try:
        certified = CertifiedMassArtifact.load(
            artifact,
            authority_context=final_semantic_anchor,
        )
    except ValueError as exc:
        raise AuthoritativeArtifactMeasurementError({
            "reason": "certified_artifact_authority_context_mismatch",
            "detail": str(exc),
        }) from exc
    if certified.core_hash != str(expected_core_hash):
        raise AuthoritativeArtifactMeasurementError({
            "reason": "certified_artifact_core_hash_mismatch",
            "expected_core_hash": str(expected_core_hash),
            "actual_core_hash": certified.core_hash,
        })
    return certified


def exact_compilation_mesh_payload_hash(compilation: Any) -> str:
    """Hash the canonical indexed mesh used by the certified compilation."""

    return hashlib.sha256(
        json.dumps(
            {
                "vertices": [
                    [float(value) for value in vertex]
                    for vertex in compilation.vertices
                ],
                "triangles": [
                    [int(value) for value in triangle]
                    for triangle in compilation.triangles
                ],
            },
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def measure_authoritative_geometry_artifact(
    artifact: dict[str, Any] | None,
    *,
    expected_program_hash: str,
    expected_final_geometry_hash: str,
    expected_visual_hash: str,
    semantic_projection_hard_gate: dict[str, Any] | None = None,
    expected_section_geometry_binding_hash: str = "",
    final_semantic_anchor: dict[str, Any] | None = None,
    semantic_projection_audit: dict[str, Any] | None = None,
    expected_certified_mass_artifact_core_hash: str = "",
) -> AuthoritativeCertifiedMeshMeasurement:
    """Recompile AST, validate exact visual bytes, then remeasure morphology."""

    if not isinstance(artifact, dict) or not artifact:
        raise ValueError("authoritative_geometry_artifact_missing")
    if artifact.get("schemaVersion") != "arr.maas.geometry_artifact.v1":
        raise ValueError("authoritative_geometry_artifact_schema_mismatch")
    certificate = artifact.get("projectedVisualCertificate")
    certificate = certificate if isinstance(certificate, dict) else {}
    final_authority = (
        certificate.get("certification_mode")
        == FINAL_AUTHORITY_CERTIFICATION_MODE
    )
    program_payload = artifact.get("geometryProgram")
    if final_authority:
        certified_program_hash = str(
            certificate.get("final_program_hash") or ""
        )
        program_payload = next((
            payload for payload in (
                artifact.get("authoredGeometryProgram"),
                artifact.get("geometryProgram"),
            )
            if isinstance(payload, dict)
            and GeometryProgram.from_dict(payload).program_hash()
            == certified_program_hash
        ), None)
    if not isinstance(program_payload, dict):
        raise ValueError(
            "authoritative_geometry_program_identity_missing"
            if final_authority
            else "authoritative_geometry_program_missing"
        )
    program = GeometryProgram.from_dict(program_payload)
    compilation = compile_geometry_program(program)
    if compilation.status != "compiled" or compilation_gate(compilation):
        raise ValueError("authoritative_geometry_program_not_compiled")

    identity = artifact.get("identity")
    identity = identity if isinstance(identity, dict) else {}
    program_hash = str(program.program_hash() or "")
    final_geometry_hash = str(
        artifact.get("finalLegalGeometryHash") or ""
    )
    identity_mismatches: list[str] = []
    if not program_hash:
        identity_mismatches.append("program_hash_missing")
    if program_hash != str(expected_program_hash or ""):
        identity_mismatches.append("expected_program_hash")
    if str(identity.get("programHash") or "") != program_hash:
        identity_mismatches.append("identity_program_hash")
    if not final_geometry_hash:
        identity_mismatches.append("final_geometry_hash_missing")
    if final_geometry_hash != str(expected_final_geometry_hash or ""):
        identity_mismatches.append("expected_final_geometry_hash")
    if (
        str(identity.get("finalLegalGeometryHash") or "")
        != final_geometry_hash
    ):
        identity_mismatches.append("identity_final_legal_geometry_hash")
    if (
        not final_authority
        and compilation.geometry_hash != final_geometry_hash
    ):
        identity_mismatches.append("compiled_final_geometry_hash")
    if identity_mismatches:
        raise ValueError(
            "authoritative_geometry_identity_mismatch:"
            + ",".join(identity_mismatches)
        )

    if final_authority:
        validated = _load_exact_selected_certified_artifact(
            artifact,
            final_semantic_anchor=final_semantic_anchor,
            semantic_projection_audit=semantic_projection_audit,
            expected_core_hash=expected_certified_mass_artifact_core_hash,
        ).validated_visual
    else:
        semantic_gate = (
            semantic_projection_hard_gate
            if isinstance(semantic_projection_hard_gate, dict)
            else {}
        )
        validated = validate_projected_visual_artifact(
            artifact,
            expected_semantic_context=semantic_gate.get("audited_context"),
            expected_semantic_projection_hash=str(
                semantic_gate.get("semantic_projection_hash") or ""
            ),
            expected_section_geometry_binding_hash=str(
                expected_section_geometry_binding_hash or ""
            ),
        )
    if validated is None:
        raise ValueError("authoritative_projected_visual_missing")
    visual_hash = str(validated.visual_hash or "")
    if (
        not visual_hash
        or visual_hash != str(expected_visual_hash or "")
        or str(identity.get("geometryHash") or "") != visual_hash
    ):
        raise ValueError("authoritative_visual_identity_mismatch")

    certified_compilation = revalidate_compilation_mesh(replace(
        compilation,
        vertices=validated.vertices,
        triangles=validated.triangles,
        metrics={
            "coordinate_space": validated.coordinate_space,
            "geometry_authority": "certified_projected_visual_mesh",
            "exact_payload_hash": validated.exact_payload_hash,
            "capacity_geometry_hash": compilation.geometry_hash,
        },
        geometry_hash=visual_hash,
    ))
    certified_gate_issues = tuple(
        issue for issue in compilation_gate(certified_compilation)
    )
    allow_tiny_gate_failures = (
        os.getenv("MAAS_ALLOW_TINY_GEOMETRY_GATES", "").strip().lower()
        in {"1", "true", "yes", "on"}
    )
    if (
        certified_compilation.status != "compiled"
        or (
            certified_gate_issues
            and (
                not allow_tiny_gate_failures
                or any(
                    str(issue.code) not in {"tiny_face", "tiny_edge"}
                    for issue in certified_gate_issues
                )
            )
        )
    ):
        raise ValueError("authoritative_projected_visual_not_compiled")

    source = _certified_source_from_compilation(
        program_payload=program_payload,
        compilation=certified_compilation,
        projection_mode=str(
            certificate.get("certification_mode")
            or "certified_projected_visual_mesh"
        ),
    )
    gestalt_key = competition_gestalt_key(source)
    morphology = _measured_morphology(source)
    return AuthoritativeCertifiedMeshMeasurement(
        program_hash=program_hash,
        final_geometry_hash=final_geometry_hash,
        visual_hash=visual_hash,
        exact_mesh_payload_hash=exact_compilation_mesh_payload_hash(
            certified_compilation
        ),
        gestalt_key=gestalt_key,
        morphology=morphology,
    )


def _certified_source_from_compilation(
    *,
    program_payload: dict[str, Any],
    compilation: Any,
    projection_mode: str,
) -> SourceMass:
    root_operator = (
        compilation.program.node_map[
            compilation.program.root_id
        ].operator
    )
    surfaces = tuple(
        SourceSurface(
            role=f"certified_visual_mesh_{index}",
            volume_role="certified_visual_mesh",
            verb="geometry_program",
            surface_type="profiled_recursive_solid_mesh",
            vertices_m=tuple(
                tuple(float(value) for value in compilation.vertices[
                    vertex_index
                ])
                for vertex_index in triangle
            ),
            operator=root_operator,
            semantic_patch_id=f"certified_visual_mesh:triangle:{index}",
        )
        for index, triangle in enumerate(compilation.triangles)
    )
    triangles = tuple(surface.vertices_m for surface in surfaces)
    sections = _layer_sections(triangles)
    if not sections:
        raise ValueError("authoritative_mesh_plan_section_missing")
    footprint = max(
        (section for _height, section in sections),
        key=lambda section: float(section.area),
    )
    upper_footprint = sections[-1][1]
    if not isinstance(footprint, Polygon) or footprint.is_empty:
        raise ValueError("authoritative_mesh_plan_section_missing")
    z_values = [
        float(vertex[2])
        for vertex in compilation.vertices
    ]
    minimum_z = min(z_values)
    maximum_z = max(z_values)
    height_span = maximum_z - minimum_z
    if height_span <= 1e-9:
        raise ValueError("authoritative_mesh_height_span_missing")
    section_heights = [height for height, _section in sections]
    layer_bounds = (
        [minimum_z]
        + [
            (left + right) / 2.0
            for left, right in zip(
                section_heights,
                section_heights[1:],
            )
        ]
        + [maximum_z]
    )
    volumes = tuple(
        SourceVolume(
            role=f"certified_mesh_layer_{index}",
            footprint=section,
            bottom_fraction=max(
                0.0,
                min(1.0, (layer_bounds[index] - minimum_z) / height_span),
            ),
            top_fraction=max(
                0.0,
                min(
                    1.0,
                    (layer_bounds[index + 1] - minimum_z) / height_span,
                ),
            ),
            verb="geometry_program",
        )
        for index, (_height, section) in enumerate(sections)
    )
    metadata = {
        "geometry_program": program_payload,
        "geometry_program_compilation": (
            compilation.to_dict(include_mesh=False)
        ),
        "geometry_program_bridge_evidence": {
            "schema_version": (
                "arr.maas.geometry_program_source_bridge.v1"
            ),
            "status": "materialized",
            "program_hash": compilation.program.program_hash(),
            "geometry_hash": compilation.geometry_hash,
        },
        "authored_legal_preservation": {
            "status": "certified",
            "hard_pass": True,
            "projection_mode": projection_mode,
        },
    }
    return SourceMass(
        name="authoritative_certified_mesh",
        footprint=footprint,
        upper_footprint=upper_footprint,
        volumes=volumes,
        surfaces=surfaces,
        metadata=metadata,
    )


def _measured_morphology(source: SourceMass) -> dict[str, Any]:
    # Imported lazily because candidate_analysis itself imports
    # competition_gestalt.
    from backend.app.modules.design.generation.maas.book_language.candidate_analysis import _chassis_family, _plan_family, _roof_archetype, _solid_morphology_metrics

    measured = _solid_morphology_metrics(source)
    candidate = SimpleNamespace(
        source=source,
        sequence=SimpleNamespace(name="authoritative_certified_mesh"),
    )
    body_phenotype = str(
        measured.get("body_phenotype")
        or measured.get("phenotype")
        or ""
    )
    return {
        "body_phenotype": body_phenotype,
        "roof_archetype": _roof_archetype(candidate),
        "chassis_family": _chassis_family(candidate),
        "plan_family": _plan_family(source),
        "solid_genus": int(measured.get("genus") or 0),
        "wedge_like": measured.get("wedge_like") is True,
        "pyramidal_like": measured.get("pyramidal_like") is True,
        "winged_or_curved": body_phenotype in {"winged", "curved"},
    }


__all__ = [
    "AuthoritativeCertifiedMeshMeasurement",
    "exact_compilation_mesh_payload_hash",
    "measure_authoritative_geometry_artifact",
]
