"""Shared contracts for identity-bound creative facade views."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Protocol

FACADE_VIEWS = ("front", "right", "back", "left")


class MultiViewCritic(Protocol):
    name: str

    def evaluate(
        self,
        *,
        identity: Mapping[str, str],
        strategy: Mapping[str, Any],
        artifacts: Mapping[str, Mapping[str, Any]],
        montage_path: Path,
    ) -> dict[str, Any]:
        """Evaluate all four creative facade views in one bounded call."""


def proposal_identity(bundle: Mapping[str, Any]) -> dict[str, str]:
    bundle_identity = (
        bundle.get("identity")
        if isinstance(bundle.get("identity"), Mapping)
        else {}
    )
    condition_pack = (
        bundle.get("condition_pack")
        if isinstance(bundle.get("condition_pack"), Mapping)
        else {}
    )
    condition_identity = (
        condition_pack.get("identity")
        if isinstance(condition_pack.get("identity"), Mapping)
        else {}
    )
    identity = {
        "execution_id": _matching_identity(
            "execution",
            bundle.get("execution_id"),
            bundle_identity.get("execution_id"),
            condition_identity.get("execution_id"),
        ),
        "program_hash": _matching_identity(
            "program",
            bundle.get("program_hash"),
            bundle_identity.get("program_hash"),
            condition_identity.get("program_hash"),
        ),
        "geometry_hash": _matching_identity(
            "geometry",
            bundle.get("geometry_hash"),
            bundle_identity.get("geometry_hash"),
            condition_identity.get("geometry_hash"),
        ),
        "final_geometry_hash": _matching_identity(
            "final geometry",
            bundle.get("final_geometry_hash"),
            bundle.get("final_legal_geometry_hash"),
            bundle_identity.get("final_geometry_hash"),
            bundle_identity.get("final_legal_geometry_hash"),
            condition_pack.get("final_geometry_hash"),
            condition_pack.get("final_legal_geometry_hash"),
            condition_identity.get("final_geometry_hash"),
            condition_identity.get("final_legal_geometry_hash"),
        ),
        "visual_hash": _matching_identity(
            "visual",
            bundle.get("visual_hash"),
            bundle_identity.get("visual_hash"),
            condition_pack.get("visual_hash"),
            condition_identity.get("visual_hash"),
        ),
        "floor_capacity_plan_hash": _matching_identity(
            "floor capacity plan",
            bundle.get("floor_capacity_plan_hash"),
            bundle_identity.get("floor_capacity_plan_hash"),
            condition_pack.get("floor_capacity_plan_hash"),
            condition_identity.get("floor_capacity_plan_hash"),
        ),
        "legal_floor_field_hash": _matching_identity(
            "legal floor field",
            bundle.get("legal_floor_field_hash"),
            bundle_identity.get("legal_floor_field_hash"),
            condition_pack.get("legal_floor_field_hash"),
            condition_identity.get("legal_floor_field_hash"),
        ),
        "candidate_actual_gfa_stop_hash": _matching_identity(
            "actual GFA stop",
            bundle.get("candidate_actual_gfa_stop_hash"),
            bundle_identity.get("candidate_actual_gfa_stop_hash"),
            condition_pack.get("candidate_actual_gfa_stop_hash"),
            condition_identity.get("candidate_actual_gfa_stop_hash"),
        ),
    }
    identity["final_legal_geometry_hash"] = identity[
        "final_geometry_hash"
    ]
    if not all(identity.values()):
        raise ValueError("multi-view proposal requires complete execution identity")
    bundle_certificate = bundle.get("candidate_actual_gfa_stop_certificate")
    condition_certificate = condition_pack.get(
        "candidate_actual_gfa_stop_certificate"
    )
    if (
        bundle.get("approved_for_final_elevation") is not True
        or not isinstance(bundle_certificate, Mapping)
        or not isinstance(condition_certificate, Mapping)
        or dict(bundle_certificate) != dict(condition_certificate)
        or bundle_certificate.get("hard_pass") is not True
        or bundle_certificate.get("status") != "certified"
        or bundle_certificate.get("candidate_actual_gfa_stop_hash")
        != identity["candidate_actual_gfa_stop_hash"]
        or bundle_certificate.get("legal_floor_field_hash")
        != identity["legal_floor_field_hash"]
        or bundle_certificate.get("program_hash")
        != identity["program_hash"]
        or bundle_certificate.get("final_geometry_hash")
        != identity["final_geometry_hash"]
        or bundle_certificate.get("visual_hash")
        != identity["visual_hash"]
    ):
        raise ValueError(
            "multi-view proposal requires certified elevation identity"
        )
    return identity


def _matching_identity(label: str, *values: Any) -> str:
    resolved = [
        str(value).strip()
        for value in values
        if str(value or "").strip()
    ]
    if not resolved:
        return ""
    if len(set(resolved)) != 1:
        raise ValueError(
            f"multi-view proposal {label} identity mismatch"
        )
    return resolved[0]


__all__ = ["FACADE_VIEWS", "MultiViewCritic", "proposal_identity"]
