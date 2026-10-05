"""Typed, serializable contracts for deterministic MASS elevations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


ELEVATION_IDENTITY_KEYS = (
    "execution_id",
    "program_hash",
    "geometry_hash",
    "final_geometry_hash",
    "final_legal_geometry_hash",
    "visual_hash",
    "floor_capacity_plan_hash",
    "legal_floor_field_hash",
    "candidate_actual_gfa_stop_hash",
)


@dataclass(frozen=True)
class ElevationViewArtifact:
    view: str
    path: str
    preview_url: str
    sha256: str
    width_px: int
    height_px: int
    projection_axes: dict[str, list[float]]
    view_matrix4: list[list[float]]
    projected_bounds: list[list[float]]
    depth_range: list[float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ElevationBundle:
    execution_id: str
    program_hash: str
    geometry_hash: str
    final_geometry_hash: str
    visual_hash: str
    floor_capacity_plan_hash: str
    legal_floor_field_hash: str
    candidate_actual_gfa_stop_hash: str
    candidate_actual_gfa_stop_certificate: dict[str, Any]
    output_directory: str
    manifest_path: str
    condition_pack_path: str
    views: tuple[ElevationViewArtifact, ...]
    condition_pack: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        identity = {
            "execution_id": self.execution_id,
            "program_hash": self.program_hash,
            "geometry_hash": self.geometry_hash,
            "final_geometry_hash": self.final_geometry_hash,
            "final_legal_geometry_hash": self.final_geometry_hash,
            "visual_hash": self.visual_hash,
            "floor_capacity_plan_hash": self.floor_capacity_plan_hash,
            "legal_floor_field_hash": self.legal_floor_field_hash,
            "candidate_actual_gfa_stop_hash": (
                self.candidate_actual_gfa_stop_hash
            ),
        }
        return {
            "schema_version": "arr.elevation_agent.bundle.v1",
            "status": "generated",
            "approved_for_final_elevation": True,
            "identity": identity,
            "execution_id": self.execution_id,
            "program_hash": self.program_hash,
            "geometry_hash": self.geometry_hash,
            "final_geometry_hash": self.final_geometry_hash,
            "final_legal_geometry_hash": self.final_geometry_hash,
            "visual_hash": self.visual_hash,
            "floor_capacity_plan_hash": self.floor_capacity_plan_hash,
            "legal_floor_field_hash": self.legal_floor_field_hash,
            "candidate_actual_gfa_stop_hash": (
                self.candidate_actual_gfa_stop_hash
            ),
            "candidate_actual_gfa_stop_certificate": (
                self.candidate_actual_gfa_stop_certificate
            ),
            "output_directory": self.output_directory,
            "manifest_path": self.manifest_path,
            "condition_pack_path": self.condition_pack_path,
            "view_count": len(self.views),
            "views": [
                {**view.to_dict(), "identity": identity}
                for view in self.views
            ],
            "condition_pack": self.condition_pack,
        }


def certified_elevation_identity(
    *,
    execution_id: str,
    program_hash: str,
    geometry_hash: str,
    final_legal_geometry_hash: str,
    visual_hash: str,
    floor_capacity_plan_hash: str,
    legal_floor_field_hash: str,
    candidate_actual_gfa_stop_hash: str,
    candidate_actual_gfa_stop_certificate: Mapping[str, Any] | None,
    shared_floor_contract: Mapping[str, Any] | None,
) -> tuple[dict[str, str], int]:
    """Resolve one fail-closed identity for final elevation consumers."""

    certificate = (
        candidate_actual_gfa_stop_certificate
        if isinstance(candidate_actual_gfa_stop_certificate, Mapping)
        else {}
    )
    shared_floor = (
        shared_floor_contract
        if isinstance(shared_floor_contract, Mapping)
        else {}
    )
    certificate_identity = (
        certificate.get("identity")
        if isinstance(certificate.get("identity"), Mapping)
        else {}
    )
    final_hash = _matching_identity(
        "final geometry",
        final_legal_geometry_hash,
        certificate.get("final_geometry_hash"),
        certificate_identity.get("final_geometry_hash"),
    )
    resolved_visual_hash = _matching_identity(
        "visual",
        visual_hash,
        geometry_hash,
        certificate.get("visual_hash"),
        certificate_identity.get("visual_hash"),
    )
    resolved_program_hash = _matching_identity(
        "program",
        program_hash,
        certificate.get("program_hash"),
        certificate_identity.get("program_hash"),
    )
    resolved_capacity_hash = _matching_identity(
        "floor capacity plan",
        floor_capacity_plan_hash,
        shared_floor.get("floor_capacity_plan_hash"),
        _nested_identity_value(
            shared_floor,
            "floor_capacity_plan_hash",
        ),
    )
    resolved_legal_hash = _matching_identity(
        "legal floor field",
        legal_floor_field_hash,
        shared_floor.get("legal_floor_field_hash"),
        _nested_identity_value(shared_floor, "legal_floor_field_hash"),
        certificate.get("legal_floor_field_hash"),
    )
    resolved_stop_hash = _matching_identity(
        "actual GFA stop",
        candidate_actual_gfa_stop_hash,
        shared_floor.get("candidate_actual_gfa_stop_hash"),
        _nested_identity_value(
            shared_floor,
            "candidate_actual_gfa_stop_hash",
        ),
        certificate.get("candidate_actual_gfa_stop_hash"),
    )
    if (
        certificate.get("status") != "certified"
        or certificate.get("hard_pass") is not True
        or certificate.get("geometry_was_mutated") is not False
        or shared_floor.get("hard_pass") is not True
        or shared_floor.get("candidate_actual_gfa_stop_hard_pass") is not True
    ):
        raise ValueError(
            "elevationAgent requires a hard-pass actual GFA stop certificate"
        )
    selected_floor_count = certificate.get("selected_floor_count")
    terminal_floor_number = certificate.get("terminal_floor_number")
    if (
        type(terminal_floor_number) is not int
        or terminal_floor_number != selected_floor_count
    ):
        raise ValueError(
            "elevationAgent terminal floor number mismatch"
        )
    plates = shared_floor.get("plates")
    if (
        type(selected_floor_count) is not int
        or selected_floor_count <= 0
        or not isinstance(plates, list)
        or len(plates) != selected_floor_count
        or any(
            not isinstance(plate, Mapping)
            or plate.get("hard_pass") is not True
            for plate in plates
        )
    ):
        raise ValueError(
            "elevationAgent selected floor count mismatch"
        )
    return ({
        "execution_id": _required_identity("execution", execution_id),
        "program_hash": resolved_program_hash,
        "geometry_hash": resolved_visual_hash,
        "final_geometry_hash": final_hash,
        "final_legal_geometry_hash": final_hash,
        "visual_hash": resolved_visual_hash,
        "floor_capacity_plan_hash": resolved_capacity_hash,
        "legal_floor_field_hash": resolved_legal_hash,
        "candidate_actual_gfa_stop_hash": resolved_stop_hash,
    }, selected_floor_count)


def _nested_identity_value(
    value: Mapping[str, Any],
    key: str,
) -> Any:
    identity = value.get("identity")
    return identity.get(key) if isinstance(identity, Mapping) else None


def _matching_identity(label: str, *values: Any) -> str:
    resolved = [
        str(value).strip()
        for value in values
        if str(value or "").strip()
    ]
    if not resolved or len(set(resolved)) != 1:
        raise ValueError(f"elevationAgent {label} identity mismatch")
    return resolved[0]


def _required_identity(label: str, value: Any) -> str:
    resolved = str(value or "").strip()
    if not resolved:
        raise ValueError(f"elevationAgent requires {label} identity")
    return resolved


__all__ = [
    "ELEVATION_IDENTITY_KEYS",
    "ElevationBundle",
    "ElevationViewArtifact",
    "certified_elevation_identity",
]
