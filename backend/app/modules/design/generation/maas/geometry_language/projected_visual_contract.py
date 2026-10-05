"""Canonical transport contract for Task 1 certified projected visual meshes."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from math import isfinite
from typing import Any

from shapely import from_wkb
from shapely.geometry import MultiPolygon, Polygon

from backend.app.modules.design.generation.maas.geometry_language.floorwise_visual_projection import FLOORWISE_EXACT_AUTHORITY_CONTRACTS, FLOORWISE_EXACT_AUTHORITY_MODES, floorwise_authority_binding_hash
from backend.app.modules.design.generation.maas.geometry_language.floorwise_profiled_legal_clip import _legal_band_projection_sample_count
from backend.app.modules.design.generation.maas.geometry_language.profiled_mesh_numeric_repair import floor_center_numeric_equivalence, indexed_mesh_section_topology, revalidated_profiled_mesh


MESH_SCHEMA = "arr.maas.projected_visual_mesh.v1"
FINAL_MESH_SCHEMA = "arr.maas.projected_visual_mesh.v2"
CERTIFICATE_SCHEMA = "arr.maas.floorwise_visual_projection.v1"
FINAL_CERTIFICATE_SCHEMA = "arr.maas.floorwise_visual_projection.v2"
COORDINATE_SPACE = "capacity_source_centroid_local_xy_normalized_z"
NORMALIZED_AUTHORED_COORDINATE_SPACE = (
    "source_footprint_centroid_local_xy_normalized_z"
)
AUTHORED_COORDINATE_SPACE = "source_footprint_centroid_local_xyz_m"
RENDERER_COORDINATE_CONTRACT_VERSION = (
    "arr.maas.renderer_coordinate_contract.v2_physical_meter_z"
)
FINAL_AUTHORITY_CERTIFICATION_MODE = (
    "authored_projected_surface_authority"
)
LEGACY_FINAL_AUTHORITY_CERTIFICATION_MODE = (
    "final_floorwise_legal_geometry_authority"
)
PROJECTED_AUTHORITY = "certified_projected_visual_mesh"
CAPACITY_PROGRAM_ROLE = (
    "authored_projected_surface_program_and_provenance"
)
LEGACY_CAPACITY_PROGRAM_ROLE = (
    "capacity_replay_metadata_and_provenance"
)
PERSISTED_LEGACY_AUTHORITY_SCHEMA = (
    "arr.maas.persisted_legacy_visual_authority.v1"
)
PROJECTED_FIELDS = (
    "projectedVisualMesh",
    "projectedVisualCertificate",
    "projectedVisualGeometryHash",
    "projectedVisualPayloadHash",
)
MAX_PROJECTED_VISUAL_SERIALIZED_BYTES = 256 * 1024 * 1024
MAX_PROJECTED_VISUAL_TRIANGLES = 1_000_000
MAX_PROJECTED_VISUAL_FLOORS = 256
MAX_PROJECTED_VISUAL_COMPONENTS = 4096
MAX_PROJECTED_VISUAL_CONTOURS = 8192
MAX_PROJECTED_VISUAL_POINTS = 4_000_000
MAX_AUTHORITY_CERTIFICATE_STRING_LENGTH = 4096
MAX_AUTHORITY_GATE_FAILURE_CODES = 256


@dataclass(frozen=True)
class ValidatedProjectedVisual:
    vertices: tuple[tuple[float, float, float], ...]
    triangles: tuple[tuple[int, int, int], ...]
    visual_hash: str
    exact_payload_hash: str
    coordinate_space: str
    certificate: dict[str, Any]


_CERTIFIED_MASS_CORE_FIELDS = (
    "authority",
    "geometryProgramRole",
    "projectedVisualMesh",
    "projectedVisualCertificate",
    "projectedVisualGeometryHash",
    "projectedVisualPayloadHash",
    "identity",
    "finalLegalGeometryHash",
    "finalSurfacePayloadHash",
    "normalizedSourceSurfacePayloadHash",
    "semanticProjectionHash",
    "semanticProjectionAudit",
    "semanticProjectionAuditPayloadHash",
    "capacityMeasurementProvenance",
)


@dataclass(frozen=True)
class CertifiedMassArtifact:
    """Immutable, fully validated final visual-authority carrier."""

    _payload_json: bytes
    _core_payload_json: bytes
    _authority_context_json: bytes
    _vertices: tuple[tuple[float, float, float], ...]
    _triangles: tuple[tuple[int, int, int], ...]
    _visual_hash: str
    _exact_payload_hash: str
    _coordinate_space: str
    _certificate_json: bytes

    @classmethod
    def issue(
        cls,
        source: Any,
        *,
        semantic_audit: dict[str, Any],
        section_binding_hash: str = "",
    ) -> "CertifiedMassArtifact":
        payload = _serialize_certified_projected_visual_payload(
            source,
            final_semantic_audit=semantic_audit,
        )
        certificate = payload.get("projectedVisualCertificate")
        certificate = certificate if isinstance(certificate, dict) else {}
        if (
            certificate.get("certification_mode")
            != FINAL_AUTHORITY_CERTIFICATION_MODE
        ):
            raise ValueError("certified MASS artifact requires final v2 authority")
        payload["identity"] = {
            "programHash": str(certificate.get("final_program_hash") or ""),
            "geometryHash": str(
                payload.get("projectedVisualGeometryHash") or ""
            ),
            "finalLegalGeometryHash": str(
                payload.get("finalLegalGeometryHash")
                or certificate.get("final_geometry_hash")
                or ""
            ),
        }
        metadata = (
            source.metadata
            if isinstance(getattr(source, "metadata", None), dict)
            else {}
        )
        authority_context = {
            "expected_semantic_context": deepcopy(
                semantic_audit.get("audited_context")
            ),
            "expected_semantic_projection_hash": str(
                semantic_audit.get("semantic_projection_hash") or ""
            ),
            "expected_semantic_audit_payload_hash": (
                semantic_audit_payload_hash(semantic_audit)
            ),
            "expected_section_geometry_binding_hash": str(
                section_binding_hash
                or metadata.get(
                    "profiled_legal_section_authority_binding_hash"
                )
                or certificate.get("section_geometry_binding_hash")
                or ""
            ),
            "expected_normalized_source_surface_payload_hash": str(
                metadata.get("final_surface_payload_hash")
                or certificate.get(
                    "normalized_source_surface_payload_hash"
                )
                or ""
            ),
        }
        return cls.load(payload, authority_context=authority_context)

    @classmethod
    def load(
        cls,
        payload: dict[str, Any],
        *,
        authority_context: dict[str, Any],
    ) -> "CertifiedMassArtifact":
        carrier = deepcopy(payload)
        _, certificate = validate_projected_visual_field_contract(carrier)
        if (
            certificate.get("schema_version") != FINAL_CERTIFICATE_SCHEMA
            or certificate.get("certification_mode")
            != FINAL_AUTHORITY_CERTIFICATION_MODE
        ):
            raise ValueError("certified MASS artifact rejects legacy visual authority")
        context = deepcopy(authority_context)
        validated = _validate_projected_visual_artifact_payload(
            carrier,
            expected_semantic_context=context.get(
                "expected_semantic_context"
            ),
            expected_semantic_projection_hash=str(
                context.get("expected_semantic_projection_hash") or ""
            ),
            expected_semantic_audit_payload_hash=str(
                context.get("expected_semantic_audit_payload_hash") or ""
            ),
            expected_section_geometry_binding_hash=str(
                context.get("expected_section_geometry_binding_hash") or ""
            ),
            expected_normalized_source_surface_payload_hash=str(
                context.get(
                    "expected_normalized_source_surface_payload_hash"
                )
                or ""
            ),
        )
        if validated is None:
            raise ValueError("certified MASS artifact binding is incomplete")
        core_payload = {
            key: deepcopy(carrier[key])
            for key in _CERTIFIED_MASS_CORE_FIELDS
            if key in carrier
        }
        return cls(
            _payload_json=_canonical_artifact_json(carrier),
            _core_payload_json=_canonical_artifact_json(core_payload),
            _authority_context_json=_canonical_artifact_json(context),
            _vertices=validated.vertices,
            _triangles=validated.triangles,
            _visual_hash=validated.visual_hash,
            _exact_payload_hash=validated.exact_payload_hash,
            _coordinate_space=validated.coordinate_space,
            _certificate_json=_canonical_artifact_json(validated.certificate),
        )

    @property
    def core_hash(self) -> str:
        return hashlib.sha256(self._core_payload_json).hexdigest()

    @property
    def validated_visual(self) -> ValidatedProjectedVisual:
        return ValidatedProjectedVisual(
            vertices=self._vertices,
            triangles=self._triangles,
            visual_hash=self._visual_hash,
            exact_payload_hash=self._exact_payload_hash,
            coordinate_space=self._coordinate_space,
            certificate=json.loads(self._certificate_json.decode("utf-8")),
        )

    def payload(self) -> dict[str, Any]:
        return json.loads(self._payload_json.decode("utf-8"))

    def certificate(self) -> dict[str, Any]:
        return json.loads(self._certificate_json.decode("utf-8"))

    def authority_context(self) -> dict[str, Any]:
        return json.loads(self._authority_context_json.decode("utf-8"))

    def feature_binding(self) -> dict[str, Any]:
        payload = self.payload()
        mesh = payload.get("projectedVisualMesh")
        triangles = mesh.get("triangles") if isinstance(mesh, dict) else []
        return {
            "geometry_artifact": payload,
            "floorwise_visual_projection": self.certificate(),
            "source_surfaces": deepcopy(triangles),
            "final_semantic_anchor": self.authority_context(),
            "certified_mass_artifact_core_hash": self.core_hash,
        }


def _canonical_artifact_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _serialize_certified_projected_visual_payload(
    source: Any,
    *,
    final_semantic_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Serialize exact triangle records while retaining Task 1 visual identity."""

    metadata = (
        source.metadata
        if isinstance(getattr(source, "metadata", None), dict)
        else {}
    )
    has_authored_profiled_surface = any(
        str(getattr(surface, "surface_type", "") or "").startswith("profiled_")
        for surface in tuple(getattr(source, "surfaces", ()) or ())
    )
    if metadata.get("geometry_authority") in {
        "authored_projected_surface_payload",
        "authored_compiled_surface_payload",
    }:
        return _serialize_final_authored_surface_authority(
            source,
            metadata,
            final_semantic_audit=final_semantic_audit,
        )
    certificate = metadata.get("floorwise_visual_projection")
    if not isinstance(certificate, dict):
        if has_authored_profiled_surface:
            raise ValueError(
                "authored profiled visual source has no certified projection"
            )
        return {}
    if certificate.get("status") == "not_applicable_no_authored_mesh":
        if has_authored_profiled_surface:
            raise ValueError(
                "authored profiled visual source has no certified projection"
            )
        return {}
    _validate_certificate_status(certificate)

    triangles = [
        _surface_triangle_record(surface)
        for surface in tuple(getattr(source, "surfaces", ()) or ())
    ]
    _validate_projected_visual_resource_bounds(certificate, triangles)
    expected_hash = str(certificate.get("visual_hash") or "")
    expected_count = int(certificate.get("projected_surface_count") or 0)
    if (
        not triangles
        or expected_count != len(triangles)
        or not expected_hash
        or _task1_visual_hash(triangles) != expected_hash
    ):
        raise ValueError(
            "certified projected visual mesh does not match its certificate"
        )
    coordinate_space = str(
        certificate.get("projected_surface_coordinate_frame") or ""
    )
    if coordinate_space != _certificate_coordinate_space(certificate):
        raise ValueError("unsupported projected visual coordinate frame")
    payload_hash = exact_triangle_payload_hash(triangles)
    if (
        certificate.get("certification_mode")
        == "authored_visual_legal_validation"
        and str(certificate.get("exact_surface_payload_hash") or "")
        != payload_hash
    ):
        raise ValueError(
            "certified authored visual exact payload hash mismatch"
        )
    validate_floorwise_authority_binding(
        certificate,
        exact_payload_hash=payload_hash,
        triangle_payload=triangles,
        expected_section_geometry_binding_hash=str(
            metadata.get(
                "profiled_legal_section_authority_binding_hash"
            ) or ""
        ),
    )
    return {
        "authority": PROJECTED_AUTHORITY,
        "geometryProgramRole": CAPACITY_PROGRAM_ROLE,
        "projectedVisualMesh": {
            "schemaVersion": MESH_SCHEMA,
            "coordinateSpace": coordinate_space,
            "triangles": triangles,
            "vertexCount": len(triangles) * 3,
            "triangleCount": len(triangles),
        },
        "projectedVisualCertificate": deepcopy(certificate),
        "projectedVisualGeometryHash": expected_hash,
        "projectedVisualPayloadHash": payload_hash,
    }


def _semantic_authority_audit_payload(
    audit: dict[str, Any],
) -> dict[str, Any]:
    payload = deepcopy(audit)
    payload.pop("semantic_projection_hash", None)
    payload.pop("audited_context_hash", None)
    context = payload.get("audited_context")
    if isinstance(context, dict):
        context = dict(context)
        context.pop("capacity_measurement_hash", None)
        payload["audited_context"] = context
    return payload


def _classify_final_authored_surface_identity(
    source: Any,
    metadata: dict[str, Any],
    *,
    external_audit: dict[str, Any],
) -> dict[str, Any]:
    """Classify immutable authority identity and capacity-only drift once."""

    from backend.app.modules.design.generation.maas.program_massing.semantic_carriers import audit_source_semantic_projection, semantic_audit_context_hash
    from backend.app.modules.design.generation.maas.geometry_language.source_bridge import source_surface_payload_hash

    semantic_evidence = metadata.get("program_semantic_carrier_evidence")
    semantic_evidence = (
        semantic_evidence if isinstance(semantic_evidence, dict) else {}
    )
    program_id = str(semantic_evidence.get("program_id") or "")
    external_context = external_audit.get("audited_context")
    external_context = (
        external_context if isinstance(external_context, dict) else {}
    )
    initial_audit = audit_source_semantic_projection(
        source,
        building_type=program_id,
        expected_context=external_context,
    )
    semantic_hash = str(
        semantic_evidence.get("semantic_projection_hash") or ""
    )
    audited_capacity_hash = str(
        external_context.get("capacity_measurement_hash") or ""
    )
    current_capacity_hash = str(
        semantic_evidence.get("capacity_measurement_hash") or ""
    )
    initial_failures = set(initial_audit.get("failures") or ())
    external_failures = set(external_audit.get("failures") or ())
    identity_failures = initial_failures | external_failures
    capacity_drift = identity_failures == {
        "capacity_measurement_hash_mismatch"
    }

    bridge = metadata.get("geometry_program_bridge_evidence")
    bridge = bridge if isinstance(bridge, dict) else {}
    final_program_hash = str(bridge.get("program_hash") or "")
    final_geometry_hash = str(bridge.get("geometry_hash") or "")
    surfaces = tuple(getattr(source, "surfaces", ()) or ())
    actual_surface_hash = source_surface_payload_hash(surfaces)
    external_semantic_hash = str(
        external_audit.get("semantic_projection_hash") or ""
    )
    independent_hard_identity = bool(
        external_audit.get("schema_version")
        == "arr.maas.final_semantic_projection_audit.v1"
        and str(external_audit.get("audited_context_hash") or "")
        == semantic_audit_context_hash(external_context)
        and final_program_hash
        and final_geometry_hash
        and str(metadata.get("final_program_hash") or "")
        == final_program_hash
        and str(metadata.get("final_geometry_hash") or "")
        == final_geometry_hash
        and str(metadata.get("final_surface_payload_hash") or "")
        == actual_surface_hash
        and str(bridge.get("surface_payload_hash") or "")
        == actual_surface_hash
    )
    strict_semantic_identity = bool(
        external_audit.get("status") == "verified"
        and external_audit.get("hard_pass") is True
        and
        initial_audit.get("hard_pass") is True
        and isinstance(external_audit.get("accepted_carriers"), list)
        and bool(external_audit.get("accepted_carriers"))
        and int(external_audit.get("accepted_carrier_count") or 0)
        == len(external_audit.get("accepted_carriers") or ())
        and semantic_hash
        and external_semantic_hash
        and external_semantic_hash == semantic_hash
        and _canonical_payload_hash(
            _semantic_authority_audit_payload(initial_audit)
        )
        == _canonical_payload_hash(
            _semantic_authority_audit_payload(external_audit)
        )
    )
    hard_pass = bool(
        independent_hard_identity
        and (capacity_drift or strict_semantic_identity)
    )
    if not hard_pass:
        failures = sorted(identity_failures)
        raise ValueError(
            "authored projected surface authority identity audit failed"
            + (f": {','.join(failures)}" if failures else "")
        )
    return {
        "surfaces": surfaces,
        "actual_surface_hash": actual_surface_hash,
        "final_program_hash": final_program_hash,
        "final_geometry_hash": final_geometry_hash,
        # Which of the three routes recorded the identity above. Carried so a
        # refusal downstream can name the writer instead of only the digest.
        "bridge_identity_writer": str(
            bridge.get("bridge_identity_writer") or "unrecorded"
        ),
        "authority_semantic_hash": external_semantic_hash or semantic_hash,
        "capacity_drift": capacity_drift,
        "audited_capacity_hash": audited_capacity_hash,
        "current_capacity_hash": current_capacity_hash,
    }


def _serialize_final_authored_surface_authority(
    source: Any,
    metadata: dict[str, Any],
    *,
    final_semantic_audit: dict[str, Any] | None,
) -> dict[str, Any]:
    """Serialize exact authored surfaces as the sole visual authority."""

    external_audit = (
        final_semantic_audit
        if isinstance(final_semantic_audit, dict)
        else {}
    )
    identity = _classify_final_authored_surface_identity(
        source,
        metadata,
        external_audit=external_audit,
    )
    surfaces = identity["surfaces"]
    actual_surface_hash = identity["actual_surface_hash"]
    final_program_hash = identity["final_program_hash"]
    final_geometry_hash = identity["final_geometry_hash"]
    authority_semantic_hash = identity["authority_semantic_hash"]
    capacity_drift = identity["capacity_drift"]
    audited_capacity_hash = identity["audited_capacity_hash"]
    current_capacity_hash = identity["current_capacity_hash"]

    metric_payload = canonical_metric_surface_payload(source)
    triangles = metric_payload["triangles"]
    if not triangles:
        raise ValueError(
            "authored projected surface authority identity audit failed: "
            "empty_surface_payload"
        )
    payload_hash = exact_triangle_payload_hash(triangles)
    visual_hash = _task1_visual_hash(triangles)
    physical_surface_hash = str(metric_payload["surface_payload_hash"])
    if (
        str(metric_payload["normalized_source_surface_payload_hash"])
        != actual_surface_hash
    ):
        raise ValueError(
            "authored projected surface authority identity audit failed: "
            "normalized_source_surface_payload_hash_mismatch"
        )
    semantic_audit_payload_hash = _canonical_payload_hash(
        external_audit
    )
    origin = getattr(source, "footprint", None)
    origin = getattr(origin, "centroid", None)
    if origin is None:
        raise ValueError(
            "authored projected surface authority identity audit failed: "
            "source_origin_missing"
        )
    certificate = {
        "schema_version": FINAL_CERTIFICATE_SCHEMA,
        "status": "certified",
        "hard_pass": True,
        "certification_mode": FINAL_AUTHORITY_CERTIFICATION_MODE,
        "visual_hash": visual_hash,
        "projected_surface_count": len(triangles),
        "projected_surface_coordinate_frame": AUTHORED_COORDINATE_SPACE,
        "source_surface_coordinate_frame": (
            NORMALIZED_AUTHORED_COORDINATE_SPACE
        ),
        "physical_height_m": metric_payload["physical_height_m"],
        "normalized_source_surface_payload_hash": actual_surface_hash,
        "exact_surface_payload_hash": payload_hash,
        "final_program_hash": final_program_hash,
        "final_geometry_hash": final_geometry_hash,
        "final_surface_payload_hash": physical_surface_hash,
        "semantic_projection_hash": authority_semantic_hash,
        "semantic_projection_audit_hard_pass": True,
        "semantic_audit_context_hash": str(
            external_audit.get("audited_context_hash") or ""
        ),
        "semantic_audit_payload_hash": semantic_audit_payload_hash,
        "section_geometry_binding_hash": str(
            metadata.get(
                "profiled_legal_section_authority_binding_hash"
            )
            or ""
        ),
        "source_footprint_centroid_utm": [
            float(origin.x),
            float(origin.y),
        ],
    }
    upstream = metadata.get("floorwise_visual_projection")
    upstream = upstream if isinstance(upstream, dict) else {}
    # This certificate replaces the upstream one wholesale.  Carry the visible
    # skin's producer through so a legal-section loft can never be read as an
    # authored body downstream.
    certificate["bridge_identity_writer"] = str(
        identity.get("bridge_identity_writer") or "unrecorded"
    )
    certificate["visible_surface_producer"] = str(
        upstream.get("visible_surface_producer") or "unknown"
    )
    certificate["visible_internal_tread_area_ratio"] = float(
        upstream.get("visible_internal_tread_area_ratio") or 0.0
    )
    return {
        "authority": PROJECTED_AUTHORITY,
        "geometryProgramRole": CAPACITY_PROGRAM_ROLE,
        "projectedVisualMesh": {
            "schemaVersion": FINAL_MESH_SCHEMA,
            "coordinateSpace": AUTHORED_COORDINATE_SPACE,
            "triangles": triangles,
            "vertexCount": len(triangles) * 3,
            "triangleCount": len(triangles),
        },
        "projectedVisualCertificate": certificate,
        "projectedVisualGeometryHash": visual_hash,
        "projectedVisualPayloadHash": payload_hash,
        "finalLegalGeometryHash": final_geometry_hash,
        "finalSurfacePayloadHash": physical_surface_hash,
        "normalizedSourceSurfacePayloadHash": actual_surface_hash,
        "semanticProjectionHash": authority_semantic_hash,
        "semanticProjectionAudit": deepcopy(external_audit),
        "semanticProjectionAuditPayloadHash": (
            semantic_audit_payload_hash
        ),
        "capacityMeasurementProvenance": {
            "identity_authority": False,
            "status": (
                "diagnostic_drift" if capacity_drift else "unchanged"
            ),
            "audited_capacity_measurement_hash": audited_capacity_hash,
            "current_capacity_measurement_hash": current_capacity_hash,
        },
    }


def declares_projected_visual_binding(artifact: dict[str, Any]) -> bool:
    """Return true for complete bindings and for downgrade/tamper markers."""

    return (
        any(field in artifact for field in PROJECTED_FIELDS)
        or artifact.get("authority") == PROJECTED_AUTHORITY
        or artifact.get("geometryProgramRole") == CAPACITY_PROGRAM_ROLE
    )


def normalize_persisted_projected_visual_artifact(
    artifact: dict[str, Any],
) -> dict[str, Any]:
    """Normalize explicitly marked persisted aliases at ingestion only."""

    certificate = artifact.get("projectedVisualCertificate")
    certificate = certificate if isinstance(certificate, dict) else {}
    has_legacy_alias = bool(
        artifact.get("geometryProgramRole") == LEGACY_CAPACITY_PROGRAM_ROLE
        or certificate.get("certification_mode")
        == LEGACY_FINAL_AUTHORITY_CERTIFICATION_MODE
    )
    if not has_legacy_alias:
        return artifact
    provenance = artifact.get("persistedLegacyAuthority")
    if (
        not isinstance(provenance, dict)
        or provenance.get("schemaVersion")
        != PERSISTED_LEGACY_AUTHORITY_SCHEMA
        or provenance.get("persistedRecord") is not True
        or not str(provenance.get("sourceSchemaVersion") or "")
    ):
        raise ValueError("unmarked obsolete projected visual authority")
    normalized = deepcopy(artifact)
    if normalized.get("geometryProgramRole") == LEGACY_CAPACITY_PROGRAM_ROLE:
        normalized["geometryProgramRole"] = CAPACITY_PROGRAM_ROLE
    normalized_certificate = normalized.get("projectedVisualCertificate")
    if (
        isinstance(normalized_certificate, dict)
        and normalized_certificate.get("certification_mode")
        == LEGACY_FINAL_AUTHORITY_CERTIFICATION_MODE
    ):
        normalized_certificate["certification_mode"] = (
            FINAL_AUTHORITY_CERTIFICATION_MODE
        )
    return normalized


def _validate_projected_visual_artifact_payload(
    artifact: dict[str, Any],
    *,
    expected_semantic_context: dict[str, Any] | None = None,
    expected_semantic_projection_hash: str = "",
    expected_semantic_audit_payload_hash: str = "",
    expected_section_geometry_binding_hash: str = "",
    expected_normalized_source_surface_payload_hash: str = "",
) -> ValidatedProjectedVisual | None:
    """Validate and hydrate one complete binding; only true legacy returns None.

    Final-authority artifacts require a semantic anchor supplied by their
    caller from evidence outside the artifact.  Legacy projected visuals keep
    their historical no-anchor validation path.
    """

    artifact = normalize_persisted_projected_visual_artifact(artifact)
    if not declares_projected_visual_binding(artifact):
        return None
    if (
        not all(field in artifact for field in PROJECTED_FIELDS)
        or artifact.get("authority") != PROJECTED_AUTHORITY
        or artifact.get("geometryProgramRole") != CAPACITY_PROGRAM_ROLE
    ):
        raise ValueError("incomplete projected visual archive binding")

    mesh, certificate = validate_projected_visual_field_contract(artifact)

    expected_visual_hash = str(artifact.get("projectedVisualGeometryHash") or "")
    expected_payload_hash = str(artifact.get("projectedVisualPayloadHash") or "")
    identity = artifact.get("identity")
    identity = identity if isinstance(identity, dict) else {}
    if (
        not expected_visual_hash
        or str(identity.get("geometryHash") or "") != expected_visual_hash
        or str(certificate.get("visual_hash") or "") != expected_visual_hash
    ):
        raise ValueError("invalid projected visual certificate identity")
    triangle_payload = mesh.get("triangles")
    if not isinstance(triangle_payload, list) or not triangle_payload:
        raise ValueError("invalid projected visual triangle payload")
    _validate_projected_visual_resource_bounds(certificate, triangle_payload)
    try:
        actual_payload_hash = exact_triangle_payload_hash(triangle_payload)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid projected visual triangle payload") from exc
    if not expected_payload_hash or actual_payload_hash != expected_payload_hash:
        raise ValueError(
            "projected visual exact payload hash mismatch: "
            f"expected={expected_payload_hash} actual={actual_payload_hash}"
        )
    if (
        certificate.get("certification_mode")
        in {
            "authored_visual_legal_validation",
            FINAL_AUTHORITY_CERTIFICATION_MODE,
        }
        and str(certificate.get("exact_surface_payload_hash") or "")
        != actual_payload_hash
    ):
        raise ValueError(
            "certified authored visual exact payload hash mismatch"
        )
    normalized: list[dict[str, Any]] = []
    vertices: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    for triangle in triangle_payload:
        record, exact_vertices = _validated_triangle_record(triangle)
        base_index = len(vertices)
        vertices.extend(exact_vertices)
        triangles.append((base_index, base_index + 1, base_index + 2))
        normalized.append(record)

    final_authority = (
        certificate.get("certification_mode")
        == FINAL_AUTHORITY_CERTIFICATION_MODE
    )
    authority_triangles = (
        _normalized_source_triangle_records(normalized, certificate)
        if final_authority
        else normalized
    )
    validate_floorwise_authority_binding(
        certificate,
        exact_payload_hash=actual_payload_hash,
        triangle_payload=authority_triangles,
        expected_section_geometry_binding_hash=(
            expected_section_geometry_binding_hash
        ),
    )

    authority_mismatches: list[str] = []
    if final_authority:
        comparisons = (
            (
                "final_program_hash",
                certificate.get("final_program_hash"),
                identity.get("programHash"),
            ),
            (
                "final_geometry_hash",
                certificate.get("final_geometry_hash"),
                artifact.get("finalLegalGeometryHash"),
            ),
            (
                "identity_final_legal_geometry_hash",
                identity.get("finalLegalGeometryHash"),
                certificate.get("final_geometry_hash"),
            ),
            (
                "final_surface_payload_hash",
                certificate.get("final_surface_payload_hash"),
                artifact.get("finalSurfacePayloadHash"),
            ),
            (
                "semantic_projection_hash",
                certificate.get("semantic_projection_hash"),
                artifact.get("semanticProjectionHash"),
            ),
            (
                "semantic_audit_payload_hash",
                certificate.get("semantic_audit_payload_hash"),
                artifact.get("semanticProjectionAuditPayloadHash"),
            ),
        )
        authority_mismatches.extend(
            name for name, left, right in comparisons
            if str(left or "") != str(right or "")
        )
        if not str(certificate.get("final_surface_payload_hash") or ""):
            authority_mismatches.append("final_surface_payload_hash_missing")
        if not str(certificate.get("semantic_projection_hash") or ""):
            authority_mismatches.append("semantic_projection_hash_missing")
        if certificate.get("semantic_projection_audit_hard_pass") is not True:
            authority_mismatches.append("semantic_projection_audit_not_hard_pass")
        origin = certificate.get("source_footprint_centroid_utm")
        if not isinstance(origin, list) or len(origin) != 2:
            authority_mismatches.append("source_footprint_centroid_utm")
    if final_authority and authority_mismatches:
        raise ValueError(
            "invalid authored projected surface authority certificate: "
            + ",".join(authority_mismatches)
        )
    if final_authority:
        # The expected value is `bridge["geometry_hash"]` - the compiled
        # program mesh, taken before the floorwise legal clip - while the
        # certified surfaces are the clipped mesh. Two different solids, so the
        # identity cannot hold; the pipeline already computes the delivered
        # mesh identity with `final_floorwise_visual_geometry_hash`, and that
        # is what this should be compared against.
        #
        # Recomputing in metres was tried and rejected: it moved the hashed Z
        # from [0,1] to [0,6] on a 6 m building and the digests still differed,
        # because the space was never the difference.
        actual_final_geometry_hash = _final_authority_geometry_hash(
            authority_triangles,
            certificate=certificate,
        )
        actual_surface_hash = _source_surface_payload_hash_from_triangles(
            normalized
        )
        actual_normalized_source_hash = (
            _source_surface_payload_hash_from_triangles(authority_triangles)
        )
        audit = artifact.get("semanticProjectionAudit")
        audit = audit if isinstance(audit, dict) else {}
        if (
            not isinstance(expected_semantic_context, dict)
            or not expected_semantic_context
            or not str(expected_semantic_projection_hash or "")
            or not str(expected_semantic_audit_payload_hash or "")
        ):
            raise ValueError(
                "invalid authored projected surface authority external semantic "
                "anchor"
            )
        expected_context_hash = _canonical_payload_hash(
            expected_semantic_context
        )
        if (
            str(audit.get("audited_context_hash") or "")
            != expected_context_hash
            or _canonical_payload_hash(
                audit.get("audited_context")
                if isinstance(audit.get("audited_context"), dict)
                else {}
            )
            != expected_context_hash
            or str(certificate.get("semantic_audit_context_hash") or "")
            != expected_context_hash
            or str(audit.get("semantic_projection_hash") or "")
            != str(expected_semantic_projection_hash)
            or str(certificate.get("semantic_projection_hash") or "")
            != str(expected_semantic_projection_hash)
            or str(artifact.get("semanticProjectionHash") or "")
            != str(expected_semantic_projection_hash)
            or _canonical_payload_hash(audit)
            != str(expected_semantic_audit_payload_hash)
            or str(certificate.get("semantic_audit_payload_hash") or "")
            != str(expected_semantic_audit_payload_hash)
            or str(
                artifact.get("semanticProjectionAuditPayloadHash") or ""
            )
            != str(expected_semantic_audit_payload_hash)
        ):
            raise ValueError(
                "invalid final floorwise visual authority external semantic "
                "anchor"
            )
        capacity_provenance = artifact.get("capacityMeasurementProvenance")
        capacity_provenance = (
            capacity_provenance
            if isinstance(capacity_provenance, dict)
            else {}
        )
        capacity_only_semantic_drift = bool(
            capacity_provenance.get("identity_authority") is False
            and capacity_provenance.get("status") == "diagnostic_drift"
            and set(audit.get("failures") or ())
            == {"capacity_measurement_hash_mismatch"}
        )
        normalized_source_identity_valid = bool(
            (
                expected_normalized_source_surface_payload_hash
                and str(
                    certificate.get(
                        "normalized_source_surface_payload_hash"
                    )
                    or ""
                )
                == expected_normalized_source_surface_payload_hash
                and str(
                    artifact.get("normalizedSourceSurfacePayloadHash")
                    or ""
                )
                == expected_normalized_source_surface_payload_hash
            )
            or (
                not expected_normalized_source_surface_payload_hash
                and actual_normalized_source_hash
                == str(
                    certificate.get(
                        "normalized_source_surface_payload_hash"
                    )
                    or ""
                )
                and actual_normalized_source_hash
                == str(
                    artifact.get("normalizedSourceSurfacePayloadHash")
                    or ""
                )
            )
        )
        # Nine independent conditions used to collapse into one message, so a
        # run that died here said only that something was wrong. Naming the
        # condition is the difference between reading a stack trace and
        # re-deriving which of nine identities broke.
        certificate_failures = []
        if (
            actual_final_geometry_hash
            != str(certificate.get("final_geometry_hash") or "")
        ):
            # Both hashes run the identical canonical procedure (sort points,
            # round to 5, sort faces, sha256), so a mismatch means the two
            # sides hashed different meshes - not that they disagree on how to
            # hash one. Carry both, and the Z extent of what was hashed, so the
            # next run says which mesh drifted instead of costing another 24
            # minutes to reach this line again.
            hashed_z = [
                float(vertex[2])
                for triangle in authority_triangles
                for vertex in triangle["vertices_m"]
            ]
            # Same procedure and same Z space on both sides was already proven,
            # so the open question is only *which* mesh drifted and how far.
            # Equal triangle counts with different digests means coordinates
            # moved; different counts means the mesh was replaced outright. The
            # identity block names the writer that recorded it, so the next run
            # points at one path instead of costing another 35 minutes.
            identity = artifact.get("identity")
            identity = identity if isinstance(identity, dict) else {}
            certificate_failures.append(
                "final_geometry_hash"
                f"[recomputed={actual_final_geometry_hash[:12]}"
                f" certificate={str(certificate.get('final_geometry_hash') or '')[:12]}"
                f" hashed_z=[{min(hashed_z):.4f},{max(hashed_z):.4f}]"
                f" height_m={certificate.get('physical_height_m')}"
                f" hashed_triangles={len(authority_triangles)}"
                f" identity.geometryHash={str(identity.get('geometryHash') or '')[:12]}"
                f" identity.finalLegalGeometryHash="
                f"{str(identity.get('finalLegalGeometryHash') or '')[:12]}"
                f" bridge_identity_writer={certificate.get('bridge_identity_writer')}"
                f" visible_surface_producer={certificate.get('visible_surface_producer')}]"
            )
        if (
            actual_surface_hash
            != str(certificate.get("final_surface_payload_hash") or "")
        ):
            certificate_failures.append("final_surface_payload_hash")
        if not normalized_source_identity_valid:
            certificate_failures.append("normalized_source_surface_payload_hash")
        if (
            audit.get("schema_version")
            != "arr.maas.final_semantic_projection_audit.v1"
        ):
            certificate_failures.append("audit_schema_version")
        if audit.get("status") != "verified" and not capacity_only_semantic_drift:
            certificate_failures.append(
                f"audit_status={audit.get('status') or 'missing'}"
            )
        if audit.get("hard_pass") is not True and not capacity_only_semantic_drift:
            certificate_failures.append("audit_hard_pass")
        if (
            str(audit.get("semantic_projection_hash") or "")
            != str(certificate.get("semantic_projection_hash") or "")
        ):
            certificate_failures.append("semantic_projection_hash")
        if (
            str(audit.get("audited_context_hash") or "")
            != str(certificate.get("semantic_audit_context_hash") or "")
        ):
            certificate_failures.append("semantic_audit_context_hash")
        if (
            _canonical_payload_hash(audit)
            != str(certificate.get("semantic_audit_payload_hash") or "")
        ):
            certificate_failures.append("semantic_audit_payload_hash")
        if certificate_failures:
            raise ValueError(
                "invalid final floorwise visual authority certificate: "
                + ", ".join(certificate_failures)
                + " (audit failures: "
                + ", ".join(str(reason) for reason in (audit.get("failures") or ()))
                + ")"
            )
    actual_visual_hash = _task1_visual_hash(normalized)
    expected_triangle_count = int(certificate.get("projected_surface_count") or 0)
    if (
        actual_visual_hash != expected_visual_hash
        or expected_triangle_count != len(triangles)
        or int(mesh.get("triangleCount") or 0) != len(triangles)
        or int(mesh.get("vertexCount") or 0) != len(vertices)
    ):
        raise ValueError(
            "projected visual mesh hash mismatch: "
            f"expected={expected_visual_hash} actual={actual_visual_hash}"
        )
    return ValidatedProjectedVisual(
        vertices=tuple(vertices),
        triangles=tuple(triangles),
        visual_hash=expected_visual_hash,
        exact_payload_hash=expected_payload_hash,
        coordinate_space=str(mesh.get("coordinateSpace") or ""),
        certificate=deepcopy(certificate),
    )


def serialize_certified_projected_visual(
    source: Any,
    *,
    final_semantic_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compatibility wrapper; new final-authority code uses issue()."""

    metadata = (
        source.metadata
        if isinstance(getattr(source, "metadata", None), dict)
        else {}
    )
    if str(metadata.get("geometry_authority") or "") in {
        "authored_projected_surface_payload",
        "authored_compiled_surface_payload",
    }:
        if not isinstance(final_semantic_audit, dict):
            return _serialize_certified_projected_visual_payload(source)
        return CertifiedMassArtifact.issue(
            source,
            semantic_audit=final_semantic_audit,
        ).payload()
    return _serialize_certified_projected_visual_payload(
        source,
        final_semantic_audit=final_semantic_audit,
    )


def validate_projected_visual_artifact(
    artifact: dict[str, Any],
    *,
    expected_semantic_context: dict[str, Any] | None = None,
    expected_semantic_projection_hash: str = "",
    expected_semantic_audit_payload_hash: str = "",
    expected_section_geometry_binding_hash: str = "",
) -> ValidatedProjectedVisual | None:
    """Compatibility wrapper; new final-authority code uses load()."""

    certificate = artifact.get("projectedVisualCertificate")
    if (
        isinstance(certificate, dict)
        and certificate.get("certification_mode")
        == FINAL_AUTHORITY_CERTIFICATION_MODE
    ):
        return CertifiedMassArtifact.load(
            artifact,
            authority_context={
                "expected_semantic_context": deepcopy(
                    expected_semantic_context
                ),
                "expected_semantic_projection_hash": str(
                    expected_semantic_projection_hash or ""
                ),
                "expected_semantic_audit_payload_hash": str(
                    expected_semantic_audit_payload_hash or ""
                ),
                "expected_section_geometry_binding_hash": str(
                    expected_section_geometry_binding_hash or ""
                ),
            },
        ).validated_visual
    return _validate_projected_visual_artifact_payload(
        artifact,
        expected_semantic_context=expected_semantic_context,
        expected_semantic_projection_hash=expected_semantic_projection_hash,
        expected_semantic_audit_payload_hash=(
            expected_semantic_audit_payload_hash
        ),
        expected_section_geometry_binding_hash=(
            expected_section_geometry_binding_hash
        ),
    )


def exact_triangle_payload_hash(triangles: list[dict[str, Any]]) -> str:
    """Hash exact JSON triangle records without Task 1's 8-decimal projection."""

    encoded = json.dumps(
        triangles,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_projected_visual_resource_bounds(
    certificate: dict[str, Any],
    triangle_payload: list[dict[str, Any]],
) -> None:
    triangle_count = len(triangle_payload)
    floor_count = int(certificate.get("floor_count") or 0)
    if (
        triangle_count <= 0
        or triangle_count > MAX_PROJECTED_VISUAL_TRIANGLES
        or triangle_count * 3 > MAX_PROJECTED_VISUAL_POINTS
        or floor_count < 0
        or floor_count > MAX_PROJECTED_VISUAL_FLOORS
    ):
        raise ValueError("projected visual resource bound exceeded")
    authority_string_fields = (
        "section_profile_hash",
        "capacity_volume_hash",
        "floor_capacity_plan_hash",
        "matrix4_stack_hash",
        "exact_surface_payload_hash",
        "certification_mode",
        "visible_geometry_operation",
        "authored_program_hash",
        "verified_profiled_sloped_surface_hash",
        "floor_center_numeric_equivalence_schema",
        "mesh_numeric_repair_schema",
        "mesh_cleanup_raw_indexed_mesh_hash",
        "mesh_cleanup_clean_indexed_mesh_hash",
        "section_geometry_binding_hash",
        "authority_binding_hash",
    )
    for field in authority_string_fields:
        value = certificate.get(field)
        if value is None:
            continue
        if (
            not isinstance(value, str)
            or len(value) > MAX_AUTHORITY_CERTIFICATE_STRING_LENGTH
        ):
            raise ValueError("projected visual resource bound exceeded")
    authority_numeric_fields = (
        "effective_height_m",
        "verified_profiled_sloped_surface_area",
        "verified_profiled_sloped_surface_ratio",
        "section_numeric_epsilon_m",
        "max_section_area_delta_m2",
        "max_section_symdiff_m2",
        "max_section_hausdorff_m",
        "max_section_area_bound_m2",
        "mesh_cleanup_collapse_threshold_m",
        "mesh_cleanup_max_physical_displacement_m",
    )
    for field in authority_numeric_fields:
        value = certificate.get(field)
        if value is None:
            continue
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not isfinite(float(value))
        ):
            raise ValueError("projected visual resource bound exceeded")
    for field in (
        "visible_step_fallback",
        "mesh_cleanup_clean_gate_hard_pass",
    ):
        value = certificate.get(field)
        if value is not None and not isinstance(value, bool):
            raise ValueError("projected visual resource bound exceeded")
    raw_gate_failure_codes = certificate.get(
        "mesh_cleanup_raw_gate_failure_codes"
    )
    if raw_gate_failure_codes is not None:
        if (
            not isinstance(raw_gate_failure_codes, list)
            or len(raw_gate_failure_codes) > MAX_AUTHORITY_GATE_FAILURE_CODES
        ):
            raise ValueError("projected visual resource bound exceeded")
        for code in raw_gate_failure_codes:
            if (
                not isinstance(code, str)
                or len(code) > MAX_AUTHORITY_CERTIFICATE_STRING_LENGTH
            ):
                raise ValueError("projected visual resource bound exceeded")
    serialized_bytes = 2
    triangle_string_fields = (
        "role",
        "volume_role",
        "verb",
        "surface_type",
        "operator",
        "semantic_patch_id",
    )
    triangle_allowed_fields = {
        *triangle_string_fields,
        "vertices_m",
    }
    for triangle in triangle_payload:
        if (
            not isinstance(triangle, dict)
            or len(triangle) > len(triangle_allowed_fields)
            or any(
                not isinstance(key, str)
                or key not in triangle_allowed_fields
                for key in triangle
            )
        ):
            raise ValueError("projected visual resource bound exceeded")
        for field in triangle_string_fields:
            value = triangle.get(field, "")
            if not isinstance(value, str) or len(value) > 4096:
                raise ValueError("projected visual resource bound exceeded")
            serialized_bytes += len(value.encode("utf-8")) + len(field) + 6
        vertices = triangle.get("vertices_m")
        if not isinstance(vertices, list) or len(vertices) != 3:
            raise ValueError("projected visual resource bound exceeded")
        for vertex in vertices:
            if not isinstance(vertex, list) or len(vertex) != 3:
                raise ValueError("projected visual resource bound exceeded")
            for value in vertex:
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not isfinite(float(value))
                ):
                    raise ValueError("projected visual resource bound exceeded")
                serialized_bytes += 32
        serialized_bytes += 128
    binding_bytes = 0
    for field in (
        "occupied_section_wkb_hex",
        "legal_section_wkb_hex",
        "actual_section_wkb_hex",
    ):
        values = certificate.get(field) or ()
        if isinstance(values, list):
            if len(values) > MAX_PROJECTED_VISUAL_FLOORS:
                raise ValueError("projected visual resource bound exceeded")
            for value in values:
                if (
                    not isinstance(value, str)
                    or len(value) > MAX_PROJECTED_VISUAL_SERIALIZED_BYTES * 2
                ):
                    raise ValueError("projected visual resource bound exceeded")
                binding_bytes += len(value) // 2
    component_count = 0
    contour_count = 0
    for field in (
        "occupied_section_topology",
        "legal_section_topology",
        "floor_center_topology_metrics",
    ):
        rows = certificate.get(field)
        if rows is None:
            continue
        if not isinstance(rows, list) or len(rows) > MAX_PROJECTED_VISUAL_FLOORS:
            raise ValueError("projected visual resource bound exceeded")
        for row in rows:
            if not isinstance(row, dict) or len(row) > 32:
                raise ValueError("projected visual resource bound exceeded")
            for key, value in row.items():
                if not isinstance(key, str) or len(key) > 128:
                    raise ValueError("projected visual resource bound exceeded")
                if isinstance(value, str):
                    if len(value) > 4096:
                        raise ValueError("projected visual resource bound exceeded")
                elif isinstance(value, list):
                    if (
                        len(value) > MAX_PROJECTED_VISUAL_COMPONENTS
                        or any(
                            isinstance(item, bool)
                            or not isinstance(item, (int, float))
                            or not isfinite(float(item))
                            for item in value
                        )
                    ):
                        raise ValueError("projected visual resource bound exceeded")
                elif value is not None and not isinstance(
                    value, (bool, int, float)
                ):
                    raise ValueError("projected visual resource bound exceeded")
            component_count += max(0, int(row.get("component_count") or 0))
            contour_count += max(0, int(row.get("contour_count") or 0))
    if (
        serialized_bytes + binding_bytes
        > MAX_PROJECTED_VISUAL_SERIALIZED_BYTES
        or component_count > MAX_PROJECTED_VISUAL_COMPONENTS
        or contour_count > MAX_PROJECTED_VISUAL_CONTOURS
    ):
        raise ValueError("projected visual resource bound exceeded")


def validate_floorwise_authority_binding(
    certificate: dict[str, Any],
    *,
    exact_payload_hash: str,
    triangle_payload: list[dict[str, Any]] | None = None,
    expected_section_geometry_binding_hash: str = "",
) -> None:
    mode = str(certificate.get("certification_mode") or "")
    if mode not in FLOORWISE_EXACT_AUTHORITY_MODES:
        component_marker_fields = (
            "section_profile_hash",
            "capacity_volume_hash",
            "floor_capacity_plan_hash",
            "matrix4_stack_hash",
            "authority_binding_hash",
        )
        operation = str(
            certificate.get("visible_geometry_operation") or ""
        )
        task6_operations = {
            contract[0]
            for contract in FLOORWISE_EXACT_AUTHORITY_CONTRACTS.values()
        }
        strong_floorwise_evidence = bool(
            any(
                str(certificate.get(field) or "").strip()
                for field in component_marker_fields
            )
            or operation in task6_operations
            or certificate.get("visible_step_fallback") is True
        )
        if strong_floorwise_evidence:
            raise ValueError(
                "certified floorwise visual authority mode mismatch"
            )
        # Preserve established unrelated certificate lanes when they carry no
        # Task-6 evidence. Their independent exact/final checks remain active.
        if mode in {
            "floorwise_capacity_projection",
            "authored_visual_legal_validation",
            FINAL_AUTHORITY_CERTIFICATION_MODE,
        }:
            return
        authority_marker_fields = (
            *component_marker_fields,
            "exact_surface_payload_hash",
            "visible_geometry_operation",
            "visible_step_fallback",
        )
        if any(
            field in certificate
            for field in authority_marker_fields
        ):
            raise ValueError(
                "certified floorwise visual authority mode mismatch"
            )
        return
    expected_operation, expected_fallback = (
        FLOORWISE_EXACT_AUTHORITY_CONTRACTS[mode]
    )
    if (
        str(certificate.get("visible_geometry_operation") or "")
        != expected_operation
        or certificate.get("visible_step_fallback")
        is not expected_fallback
    ):
        raise ValueError(
            "certified floorwise visual authority mode mismatch"
        )
    certificate_exact_hash = str(
        certificate.get("exact_surface_payload_hash") or ""
    )
    if certificate_exact_hash != str(exact_payload_hash or ""):
        raise ValueError(
            "certified floorwise visual exact payload hash mismatch"
        )
    component_fields = (
        "section_profile_hash",
        "capacity_volume_hash",
        "floor_capacity_plan_hash",
        "matrix4_stack_hash",
        "authority_binding_hash",
    )
    if any(
        not str(certificate.get(field) or "").strip()
        for field in component_fields
    ):
        raise ValueError(
            "certified floorwise visual authority binding mismatch"
        )
    from backend.app.modules.design.generation.maas.geometry_language.floorwise_visual_projection import valid_floor_center_numeric_equivalence

    if not valid_floor_center_numeric_equivalence(certificate):
        raise ValueError(
            "certified floorwise visual numeric equivalence mismatch"
        )
    if mode in {
        "floorwise_profiled_continuous_envelope_clip",
        "floorwise_profiled_legal_clip",
    }:
        if (
            not expected_section_geometry_binding_hash
            or expected_section_geometry_binding_hash
            != str(certificate.get("section_geometry_binding_hash") or "")
        ):
            raise ValueError(
                "profiled external lawful section binding mismatch"
            )
        _validate_profiled_mesh_section_binding(
            certificate,
            triangle_payload=triangle_payload,
        )
    recomputed = _recomputed_floorwise_authority_binding_hash(
        certificate,
        exact_payload_hash=certificate_exact_hash,
    )
    if recomputed != str(certificate.get("authority_binding_hash") or ""):
        raise ValueError(
            "certified floorwise visual authority binding mismatch"
        )


def has_strict_height_dependent_legal_section_contraction(
    certificate: dict[str, Any],
) -> bool:
    """Return true only when every higher certified legal section contracts."""

    if certificate.get("certification_mode") not in {
        "floorwise_profiled_continuous_envelope_clip",
        "floorwise_profiled_legal_clip",
        "floorwise_csg_section_loft",
    }:
        return False
    raw_sections = certificate.get("legal_section_wkb_hex")
    floor_count = int(certificate.get("floor_count") or 0)
    if (
        not isinstance(raw_sections, list)
        or floor_count < 2
        or len(raw_sections) != floor_count
    ):
        return False
    try:
        sections = tuple(
            from_wkb(bytes.fromhex(value))
            for value in raw_sections
            if isinstance(value, str) and value
        )
    except (TypeError, ValueError):
        return False
    if (
        len(sections) != floor_count
        or any(
            section.is_empty
            or not section.is_valid
            or not isfinite(float(section.area))
            or float(section.area) <= 0.0
            for section in sections
        )
    ):
        return False
    transitions = tuple(zip(sections, sections[1:]))
    monotone_nonexpanding = all(
        upper.covered_by(lower)
        and float(upper.area) <= float(lower.area) + 1e-9
        for lower, upper in transitions
    )
    has_strict_contraction = any(
        float(lower.area) - float(upper.area)
        > max(1e-9, float(lower.area) * 1e-9)
        for lower, upper in transitions
    )
    return monotone_nonexpanding and has_strict_contraction


def _recomputed_floorwise_authority_binding_hash(
    certificate: dict[str, Any],
    *,
    exact_payload_hash: str,
) -> str:
    mode = str(certificate.get("certification_mode") or "")
    expected_operation, _ = FLOORWISE_EXACT_AUTHORITY_CONTRACTS[mode]
    return floorwise_authority_binding_hash(
        section_profile_hash=str(certificate["section_profile_hash"]),
        capacity_volume_hash=str(certificate["capacity_volume_hash"]),
        floor_capacity_plan_hash=str(certificate["floor_capacity_plan_hash"]),
        matrix4_stack_hash=str(certificate["matrix4_stack_hash"]),
        exact_surface_payload_hash=exact_payload_hash,
        certification_mode=mode,
        visible_geometry_operation=expected_operation,
        visible_step_fallback=bool(
            certificate.get("visible_step_fallback")
        ),
        authored_program_hash=str(
            certificate.get("authored_program_hash") or ""
        ),
        effective_height_m=float(
            certificate.get("effective_height_m") or 0.0
        ),
        verified_profiled_sloped_surface_area=float(
            certificate.get(
                "verified_profiled_sloped_surface_area"
            ) or 0.0
        ),
        verified_profiled_sloped_surface_ratio=float(
            certificate.get(
                "verified_profiled_sloped_surface_ratio"
            ) or 0.0
        ),
        verified_profiled_sloped_surface_hash=str(
            certificate.get(
                "verified_profiled_sloped_surface_hash"
            ) or ""
        ),
        section_numeric_epsilon_m=float(
            certificate.get("section_numeric_epsilon_m") or 0.0
        ),
        floor_center_numeric_equivalence_schema=str(
            certificate.get(
                "floor_center_numeric_equivalence_schema"
            ) or ""
        ),
        max_section_area_delta_m2=float(
            certificate.get("max_section_area_delta_m2") or 0.0
        ),
        max_section_symdiff_m2=float(
            certificate.get("max_section_symdiff_m2") or 0.0
        ),
        max_section_hausdorff_m=float(
            certificate.get("max_section_hausdorff_m") or 0.0
        ),
        max_section_area_bound_m2=float(
            certificate.get("max_section_area_bound_m2") or 0.0
        ),
        mesh_numeric_repair_schema=str(
            certificate.get("mesh_numeric_repair_schema") or ""
        ),
        mesh_cleanup_collapse_threshold_m=float(
            certificate.get("mesh_cleanup_collapse_threshold_m") or 0.0
        ),
        mesh_cleanup_max_physical_displacement_m=float(
            certificate.get(
                "mesh_cleanup_max_physical_displacement_m"
            ) or 0.0
        ),
        mesh_cleanup_raw_indexed_mesh_hash=str(
            certificate.get("mesh_cleanup_raw_indexed_mesh_hash") or ""
        ),
        mesh_cleanup_raw_gate_failure_codes=tuple(
            certificate.get("mesh_cleanup_raw_gate_failure_codes") or ()
        ),
        mesh_cleanup_clean_indexed_mesh_hash=str(
            certificate.get("mesh_cleanup_clean_indexed_mesh_hash") or ""
        ),
        mesh_cleanup_clean_gate_hard_pass=bool(
            certificate.get("mesh_cleanup_clean_gate_hard_pass")
        ),
        section_geometry_binding_hash=str(
            certificate.get("section_geometry_binding_hash") or ""
        ),
    )


def _validate_profiled_mesh_section_binding(
    certificate: dict[str, Any],
    *,
    triangle_payload: list[dict[str, Any]] | None,
) -> None:
    schema = str(certificate.get("section_geometry_binding_schema") or "")
    binding_hash = str(certificate.get("section_geometry_binding_hash") or "")
    occupied_hex = certificate.get("occupied_section_wkb_hex")
    legal_hex = certificate.get("legal_section_wkb_hex")
    actual_hex = certificate.get("actual_section_wkb_hex")
    continuous_mode = (
        certificate.get("certification_mode")
        == "floorwise_profiled_continuous_envelope_clip"
    )
    floor_count = int(certificate.get("floor_count") or 0)
    if (
        schema != "arr.maas.profiled_legal_section_geometry_binding.v1"
        or not binding_hash
        or not isinstance(occupied_hex, list)
        or not isinstance(legal_hex, list)
        or len(occupied_hex) != floor_count
        or len(legal_hex) != floor_count
        or (
            continuous_mode
            and (
                not isinstance(actual_hex, list)
                or len(actual_hex) != floor_count
            )
        )
        or not triangle_payload
    ):
        raise ValueError("profiled lawful section binding missing")
    binding_payload = {
        "schema": schema,
        "occupied_section_wkb_hex": occupied_hex,
        "legal_section_wkb_hex": legal_hex,
    }
    measured_binding_hash = hashlib.sha256(json.dumps(
        binding_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")).hexdigest()
    if measured_binding_hash != binding_hash:
        raise ValueError("profiled lawful section binding hash mismatch")

    def decode_sections(values: list[Any]) -> tuple[Polygon | MultiPolygon, ...]:
        decoded: list[Polygon | MultiPolygon] = []
        for value in values:
            if not isinstance(value, str):
                raise ValueError("profiled lawful section binding malformed")
            try:
                geometry = from_wkb(bytes.fromhex(value))
            except (TypeError, ValueError) as exc:
                raise ValueError("profiled lawful section binding malformed") from exc
            if (
                not isinstance(geometry, (Polygon, MultiPolygon))
                or geometry.is_empty
                or not geometry.is_valid
                or not isfinite(float(geometry.area))
                or geometry.normalize().wkb_hex != value
            ):
                raise ValueError("profiled lawful section binding malformed")
            decoded.append(geometry)
        return tuple(decoded)

    occupied_sections = decode_sections(occupied_hex)
    legal_sections = decode_sections(legal_hex)
    actual_sections = (
        decode_sections(actual_hex)
        if continuous_mode
        else occupied_sections
    )
    actual_component_count = 0
    actual_contour_count = 0
    actual_point_count = 0
    for geometry in (*occupied_sections, *legal_sections):
        components = (
            tuple(geometry.geoms)
            if isinstance(geometry, MultiPolygon)
            else (geometry,)
        )
        actual_component_count += len(components)
        for component in components:
            actual_contour_count += 1 + len(component.interiors)
            actual_point_count += len(component.exterior.coords)
            actual_point_count += sum(
                len(ring.coords) for ring in component.interiors
            )
    if (
        actual_component_count > MAX_PROJECTED_VISUAL_COMPONENTS
        or actual_contour_count > MAX_PROJECTED_VISUAL_CONTOURS
        or actual_point_count > MAX_PROJECTED_VISUAL_POINTS
    ):
        raise ValueError("projected visual resource bound exceeded")
    vertices: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    for payload in triangle_payload:
        _, exact_vertices = _validated_triangle_record(payload)
        base = len(vertices)
        vertices.extend(exact_vertices)
        triangles.append((base, base + 1, base + 2))
    revalidated = revalidated_profiled_mesh(tuple(vertices), tuple(triangles))
    if revalidated is None:
        raise ValueError("profiled serialized mesh is not a closed manifold")
    measured_component_count = int(
        revalidated.metrics.get("component_count", 0)
    )
    if measured_component_count != int(certificate.get("final_component_count") or 0):
        raise ValueError("profiled serialized mesh component topology mismatch")

    expected_rows = certificate.get("floor_center_topology_metrics")
    occupied_rows = certificate.get("occupied_section_topology")
    legal_rows = certificate.get("legal_section_topology")
    if not all(isinstance(rows, list) and len(rows) == floor_count for rows in (
        expected_rows, occupied_rows, legal_rows,
    )):
        raise ValueError("profiled serialized mesh topology certificate mismatch")
    measured_rows: list[dict[str, Any]] = []
    for floor_index in range(floor_count):
        section_result = indexed_mesh_section_topology(
            tuple(vertices), tuple(triangles), (floor_index + 0.5) / floor_count
        )
        if section_result is None:
            raise ValueError(
                "profiled serialized mesh lawful section midplane topology mismatch"
            )
        measured, contour_count, _ = section_result
        metric = floor_center_numeric_equivalence(
            measured,
            actual_sections[floor_index],
            epsilon_m=float(certificate.get("section_numeric_epsilon_m") or 0.0),
            contour_count=contour_count,
        )
        if metric is None or not metric.get("hard_pass"):
            raise ValueError(
                "profiled serialized mesh lawful section midplane topology mismatch"
            )
        measured_rows.append(metric)
        measured_counts = {
            "component_count": int(metric["component_count"]),
            "hole_count": int(metric["hole_count"]),
            "contour_count": int(metric["contour_count"]),
        }
        if any(int(expected_rows[floor_index].get(key, -1)) != value for key, value in measured_counts.items()):
            raise ValueError(
                "profiled serialized mesh lawful section midplane topology mismatch"
            )
        if continuous_mode and abs(
            float(expected_rows[floor_index].get("area_m2") or 0.0)
            - float(measured.area)
        ) > max(
            1e-7,
            float(certificate.get("section_numeric_epsilon_m") or 0.0)
            * max(1.0, float(measured.length)),
        ):
            raise ValueError(
                "profiled serialized mesh visible section area mismatch"
            )
        occupied = occupied_sections[floor_index]
        legal = legal_sections[floor_index]
        occupied_counts = {
            "component_count": len(occupied.geoms) if isinstance(occupied, MultiPolygon) else 1,
            "hole_count": sum(len(part.interiors) for part in occupied.geoms) if isinstance(occupied, MultiPolygon) else len(occupied.interiors),
        }
        legal_counts = {
            "component_count": len(legal.geoms) if isinstance(legal, MultiPolygon) else 1,
            "hole_count": sum(len(part.interiors) for part in legal.geoms) if isinstance(legal, MultiPolygon) else len(legal.interiors),
        }
        if any(int(occupied_rows[floor_index].get(key, -1)) != value for key, value in occupied_counts.items()):
            raise ValueError("profiled serialized mesh occupied topology mismatch")
        if any(int(legal_rows[floor_index].get(key, -1)) != value for key, value in legal_counts.items()):
            raise ValueError("profiled serialized mesh lawful section topology mismatch")

    measured_area_bound = max(
        float(row["area_bound_m2"]) for row in measured_rows
    )
    section_epsilon = float(
        certificate.get("section_numeric_epsilon_m") or 0.0
    )
    for key, measured, tolerance in (
        ("max_section_area_delta_m2", max(float(row["area_delta_m2"]) for row in measured_rows), measured_area_bound),
        ("max_section_symdiff_m2", max(float(row["symdiff_m2"]) for row in measured_rows), measured_area_bound),
        ("max_section_hausdorff_m", max(float(row["hausdorff_m"]) for row in measured_rows), section_epsilon),
        ("max_section_area_bound_m2", measured_area_bound, section_epsilon),
    ):
        if abs(float(certificate.get(key) or 0.0) - measured) > tolerance:
            raise ValueError(
                "profiled serialized mesh measured topology metrics mismatch: "
                f"metric={key} expected={certificate.get(key)!r} measured={measured!r}"
            )
    legal_count, witness = _legal_band_projection_sample_count(
        tuple(vertices),
        tuple(triangles),
        legal_sections,
        numeric_epsilon_m=section_epsilon,
    )
    if legal_count is None:
        raise ValueError(
            "profiled serialized mesh legal containment failed: "
            + json.dumps(witness, sort_keys=True, separators=(",", ":"))
        )
    if legal_count != int(certificate.get("legal_sample_count") or -1):
        raise ValueError("profiled serialized mesh legal containment count mismatch")


def validate_projected_visual_field_contract(
    artifact: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the canonical mesh/certificate pair after schema/frame checks."""

    mesh = artifact.get("projectedVisualMesh")
    certificate = artifact.get("projectedVisualCertificate")
    if not isinstance(mesh, dict) or not isinstance(certificate, dict):
        raise ValueError("invalid projected visual archive binding")
    _validate_certificate_status(certificate)
    coordinate_space = _certificate_coordinate_space(certificate)
    if (
        mesh.get("schemaVersion") != _mesh_schema(certificate)
        or mesh.get("coordinateSpace") != coordinate_space
        or certificate.get("projected_surface_coordinate_frame")
        != coordinate_space
    ):
        raise ValueError("invalid projected visual mesh coordinate contract")
    return mesh, certificate


def projected_visual_z_coordinate_mode(artifact: dict[str, Any]) -> str:
    """Classify explicit projected mesh Z units for every render consumer."""

    mesh = artifact.get("projectedVisualMesh")
    if not isinstance(mesh, dict):
        raise ValueError("invalid projected visual mesh coordinate contract")
    schema = str(mesh.get("schemaVersion") or "")
    coordinate_space = str(mesh.get("coordinateSpace") or "")
    if (
        schema == FINAL_MESH_SCHEMA
        and coordinate_space == AUTHORED_COORDINATE_SPACE
    ):
        return "physical_meter_z"
    if (
        schema == MESH_SCHEMA
        and coordinate_space in {
            COORDINATE_SPACE,
            NORMALIZED_AUTHORED_COORDINATE_SPACE,
        }
    ):
        return "normalized_height_fraction_z"
    raise ValueError("invalid projected visual mesh coordinate contract")


def _validate_certificate_status(certificate: dict[str, Any]) -> None:
    expected_schema = (
        FINAL_CERTIFICATE_SCHEMA
        if certificate.get("certification_mode")
        == FINAL_AUTHORITY_CERTIFICATION_MODE
        else CERTIFICATE_SCHEMA
    )
    if (
        certificate.get("schema_version") != expected_schema
        or certificate.get("status") != "certified"
        or certificate.get("hard_pass") is not True
    ):
        raise ValueError("selected floorwise visual projection is not certified")


def _certificate_coordinate_space(certificate: dict[str, Any]) -> str:
    mode = str(certificate.get("certification_mode") or "")
    return (
        AUTHORED_COORDINATE_SPACE
        if mode in {
            "authored_visual_legal_validation",
            FINAL_AUTHORITY_CERTIFICATION_MODE,
        }
        else COORDINATE_SPACE
    )


def _mesh_schema(certificate: dict[str, Any]) -> str:
    return (
        FINAL_MESH_SCHEMA
        if certificate.get("certification_mode")
        == FINAL_AUTHORITY_CERTIFICATION_MODE
        else MESH_SCHEMA
    )


def _physical_height_m(source: Any) -> float:
    metadata = (
        source.metadata
        if isinstance(getattr(source, "metadata", None), dict)
        else {}
    )
    contexts = (
        metadata.get("candidate_floor_context"),
        metadata.get("floorwise_visual_projection"),
        metadata.get("floorwise_legal_matrix_stack"),
    )
    for context in contexts:
        if not isinstance(context, dict):
            continue
        for key in (
            "height_m",
            "effective_height_m",
            "candidate_requested_height_m",
            "requested_height_m",
        ):
            try:
                height = float(context.get(key) or 0.0)
            except (TypeError, ValueError):
                continue
            if isfinite(height) and height > 0.0:
                return height
    raise ValueError("certified final visual mesh has no physical height")


# Z here is a fraction of the building's own height, so the tolerance is stated
# as a physical length and converted: 10 micrometres. On a 15 m building that is
# 6.7e-7 in normalized units - far below any geometry a drawing can carry, and
# far above the round-off a mesh operation accumulates while placing a vertex on
# the ground plane. A source exported in metres, which is what this check exists
# to catch, is off by the height itself.
_NORMALIZED_Z_TOLERANCE_M = 1e-5


def canonical_metric_surface_payload(source: Any) -> dict[str, Any]:
    """Return final render/VLM triangles in one local physical-meter frame."""

    normalized = [
        _surface_triangle_record(surface)
        for surface in tuple(getattr(source, "surfaces", ()) or ())
    ]
    height_m = _physical_height_m(source)
    # Every certified source carries normalized Z. Both identity exports in
    # `_compile_geometry_program_to_source_mass` produce it, so one frame is
    # enough and there is no site-bound special case: a source already in
    # metres would make the metric and normalized payloads identical, and the
    # certificate's normalized-source comparison meaningless.
    metric = []
    for triangle in normalized:
        record = deepcopy(triangle)
        vertices = []
        for x, y, z in triangle["vertices_m"]:
            # A vertex sitting exactly on the ground or the roof lands on 0.0 or
            # 1.0 through a subtraction, and float64 puts it a few 1e-17 outside.
            # Rejecting that failed a correctly normalized source: measured on a
            # publishable run, z=-0.000000 over a payload whose full range was
            # [-0.0000, 1.0000]. The tolerance is seven orders below any real
            # normalized value, so a source exported in metres - the failure this
            # check exists to catch - is still refused, and the value handed on is
            # clamped so nothing downstream sees the epsilon.
            tolerance = (
                _NORMALIZED_Z_TOLERANCE_M / height_m
                if height_m > 0.0
                else 0.0
            )
            if z < -tolerance or z > 1.0 + tolerance:
                # Fail closed as before, but say which source and which value.
                # "not normalized" alone cannot be acted on: it does not
                # distinguish a source exported in metres from one vertex that
                # drifted, and both have different repairs.
                raise ValueError(
                    "certified final visual source Z is not normalized: "
                    f"z={float(z)!r} "
                    f"height_m={float(height_m):.3f} "
                    f"triangle_count={len(normalized)} "
                    f"z_range=[{min(v[2] for tri in normalized for v in tri['vertices_m'])!r},"
                    f"{max(v[2] for tri in normalized for v in tri['vertices_m'])!r}] "
                    f"surface_type={str(triangle.get('surface_type') or '')} "
                    f"role={str(triangle.get('role') or '')}"
                )
            # Passed through unchanged, deliberately. Clamping the accepted
            # epsilon to 0.0 rewrote the bytes this payload is hashed from, so
            # the recomputed final_geometry_hash stopped matching the
            # certificate that sealed the unclamped value and the publishable
            # run died on identity instead. In a hash-identity pipeline,
            # tidying a value is changing it.
            vertices.append([float(x), float(y), float(z) * height_m])
        record["vertices_m"] = vertices
        metric.append(record)
    return {
        "schema_version": "arr.maas.canonical_metric_surface_payload.v1",
        "coordinate_space": AUTHORED_COORDINATE_SPACE,
        "source_coordinate_space": NORMALIZED_AUTHORED_COORDINATE_SPACE,
        "physical_height_m": height_m,
        "triangles": metric,
        "exact_payload_hash": exact_triangle_payload_hash(metric),
        "surface_payload_hash": _source_surface_payload_hash_from_triangles(
            metric
        ),
        "normalized_source_surface_payload_hash": (
            _source_surface_payload_hash_from_triangles(normalized)
        ),
    }


def _normalized_source_triangle_records(
    triangles: list[dict[str, Any]],
    certificate: dict[str, Any],
) -> list[dict[str, Any]]:
    try:
        height_m = float(certificate.get("physical_height_m") or 0.0)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid physical visual height") from exc
    if not isfinite(height_m) or height_m <= 0.0:
        raise ValueError("invalid physical visual height")
    normalized = []
    for triangle in triangles:
        record = deepcopy(triangle)
        record["vertices_m"] = [
            [float(x), float(y), float(z) / height_m]
            for x, y, z in triangle["vertices_m"]
        ]
        normalized.append(record)
    return normalized


def _surface_triangle_record(surface: Any) -> dict[str, Any]:
    vertices = tuple(getattr(surface, "vertices_m", ()) or ())
    if len(vertices) != 3:
        raise ValueError("certified projected visual mesh must contain triangles")
    exact_vertices: list[list[float]] = []
    for vertex in vertices:
        if len(vertex) != 3:
            raise ValueError("certified projected visual mesh must contain triangles")
        values = [float(value) for value in vertex]
        if not all(isfinite(value) for value in values):
            raise ValueError("certified projected visual mesh must contain finite triangles")
        exact_vertices.append(values)
    surface_type = str(getattr(surface, "surface_type", "") or "")
    if not surface_type.startswith("profiled_"):
        raise ValueError("certified projected visual surface must be profiled")
    return {
        "role": str(getattr(surface, "role", "") or ""),
        "volume_role": str(getattr(surface, "volume_role", "") or ""),
        "verb": str(getattr(surface, "verb", "") or ""),
        "surface_type": surface_type,
        "vertices_m": exact_vertices,
        "operator": str(getattr(surface, "operator", "") or ""),
        "semantic_patch_id": str(
            getattr(surface, "semantic_patch_id", "") or ""
        ),
    }


def _validated_triangle_record(
    triangle: Any,
) -> tuple[dict[str, Any], list[tuple[float, float, float]]]:
    if not isinstance(triangle, dict):
        raise ValueError("invalid projected visual triangle payload")
    raw_vertices = triangle.get("vertices_m")
    if not isinstance(raw_vertices, list) or len(raw_vertices) != 3:
        raise ValueError("invalid projected visual triangle payload")
    exact_vertices: list[tuple[float, float, float]] = []
    for raw_vertex in raw_vertices:
        if (
            not isinstance(raw_vertex, list)
            or len(raw_vertex) != 3
            or any(isinstance(value, bool) for value in raw_vertex)
        ):
            raise ValueError("invalid projected visual triangle payload")
        try:
            vertex = tuple(float(value) for value in raw_vertex)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid projected visual triangle payload") from exc
        if not all(isfinite(value) for value in vertex):
            raise ValueError("invalid projected visual triangle payload")
        exact_vertices.append(vertex)
    surface_type = str(triangle.get("surface_type") or "")
    if not surface_type.startswith("profiled_"):
        raise ValueError("invalid projected visual surface type")
    record = {
        "role": str(triangle.get("role") or ""),
        "volume_role": str(triangle.get("volume_role") or ""),
        "verb": str(triangle.get("verb") or ""),
        "surface_type": surface_type,
        "vertices_m": [list(vertex) for vertex in exact_vertices],
        "operator": str(triangle.get("operator") or ""),
        "semantic_patch_id": str(triangle.get("semantic_patch_id") or ""),
    }
    return record, exact_vertices


def _task1_visual_hash(triangles: list[dict[str, Any]]) -> str:
    payload = [
        {
            "role": triangle["role"],
            "volume_role": triangle["volume_role"],
            "surface_type": triangle["surface_type"],
            "semantic_patch_id": triangle["semantic_patch_id"],
            "vertices": [
                [round(float(x), 8), round(float(y), 8), round(float(z), 8)]
                for x, y, z in triangle["vertices_m"]
            ],
        }
        for triangle in triangles
    ]
    return hashlib.sha256(json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _final_authority_geometry_hash(
    triangles: list[dict[str, Any]],
    *,
    certificate: dict[str, Any],
) -> str:
    """Recompute compiler mesh identity from exact centroid-local surfaces."""

    raw_origin = certificate.get("source_footprint_centroid_utm")
    if (
        not isinstance(raw_origin, list)
        or len(raw_origin) != 2
        or any(isinstance(value, bool) for value in raw_origin)
    ):
        raise ValueError("invalid final floorwise visual authority certificate")
    try:
        origin_x, origin_y = (float(value) for value in raw_origin)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "invalid final floorwise visual authority certificate"
        ) from exc
    if not all(isfinite(value) for value in (origin_x, origin_y)):
        raise ValueError("invalid final floorwise visual authority certificate")
    canonical = []
    for triangle in triangles:
        points = sorted(
            (
                round(float(vertex[0]) + origin_x, 5),
                round(float(vertex[1]) + origin_y, 5),
                round(float(vertex[2]), 5),
            )
            for vertex in triangle["vertices_m"]
        )
        canonical.append(points)
    canonical.sort()
    return hashlib.sha256(json.dumps(
        canonical,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def final_floorwise_visual_geometry_hash(source: Any) -> str:
    """Return the compiler-style identity of the exact final visual mesh."""

    surfaces = tuple(getattr(source, "surfaces", ()) or ())
    footprint = getattr(source, "footprint", None)
    origin = getattr(footprint, "centroid", None)
    if not surfaces or origin is None:
        raise ValueError("final floorwise visual source is incomplete")
    triangles = [
        _surface_triangle_record(surface)
        for surface in surfaces
    ]
    return _final_authority_geometry_hash(
        triangles,
        certificate={
            "source_footprint_centroid_utm": [
                float(origin.x),
                float(origin.y),
            ],
        },
    )


def _source_surface_payload_hash_from_triangles(
    triangles: list[dict[str, Any]],
) -> str:
    records = tuple(
        json.dumps(
            {
                "operator": triangle["operator"],
                "role": triangle["role"],
                "semantic_patch_id": triangle["semantic_patch_id"],
                "surface_type": triangle["surface_type"],
                "verb": triangle["verb"],
                "vertices_m": [
                    [float(x), float(y), float(z)]
                    for x, y, z in triangle["vertices_m"]
                ],
                "volume_role": triangle["volume_role"],
            },
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        for triangle in triangles
    )
    return hashlib.sha256(
        f"[{','.join(sorted(records))}]".encode("utf-8")
    ).hexdigest()


def _canonical_payload_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def semantic_audit_payload_hash(audit: dict[str, Any]) -> str:
    """Return the canonical hash used to externally anchor a semantic audit."""

    return _canonical_payload_hash(audit)


__all__ = [
    "CertifiedMassArtifact",
    "AUTHORED_COORDINATE_SPACE",
    "RENDERER_COORDINATE_CONTRACT_VERSION",
    "canonical_metric_surface_payload",
    "CAPACITY_PROGRAM_ROLE",
    "COORDINATE_SPACE",
    "PROJECTED_AUTHORITY",
    "FINAL_AUTHORITY_CERTIFICATION_MODE",
    "ValidatedProjectedVisual",
    "declares_projected_visual_binding",
    "exact_triangle_payload_hash",
    "final_floorwise_visual_geometry_hash",
    "has_strict_height_dependent_legal_section_contraction",
    "normalize_persisted_projected_visual_artifact",
    "projected_visual_z_coordinate_mode",
    "semantic_audit_payload_hash",
    "serialize_certified_projected_visual",
    "validate_floorwise_authority_binding",
    "validate_projected_visual_artifact",
]
