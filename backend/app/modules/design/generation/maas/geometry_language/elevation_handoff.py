"""Hash-bound handoff from an executed GeometryProgram MASS to elevation work."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import uuid
from typing import Any, Mapping

from backend.app.modules.design.generation.maas.geometry_language.executed_archive import compile_executed_mass, executed_mass_manifest, materialize_executed_mass_passport, materialize_executed_mass_preview


SCHEMA_VERSION = "arr.maas.elevation_handoff.v1"


def resolve_elevation_handoff_identity(
    *,
    program_hash: str,
    geometry_hash: str,
    artifact: Mapping[str, Any],
    passport: Mapping[str, Any],
    row: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> tuple[dict[str, str], bool]:
    """Resolve archive consumer identity without backfilling legacy evidence."""

    artifact_identity = (
        artifact.get("identity")
        if isinstance(artifact.get("identity"), Mapping)
        else {}
    )
    passport_certificate = passport.get(
        "candidate_actual_gfa_stop_certificate"
    )
    artifact_certificate = artifact.get(
        "candidateActualGfaStopCertificate"
    )
    row_certificate = row.get(
        "candidate_actual_gfa_stop_certificate"
    )
    final_hash, final_ok = _exact_identity(
        artifact.get("finalLegalGeometryHash"),
        artifact_identity.get("finalLegalGeometryHash"),
        passport.get("final_legal_geometry_hash"),
        row.get("final_legal_geometry_hash"),
    )
    visual_hash, visual_ok = _exact_identity(
        geometry_hash,
        artifact.get("projectedVisualGeometryHash"),
        artifact_identity.get("geometryHash"),
        passport.get("geometry_hash"),
        passport.get("visual_hash"),
        row.get("geometry_hash"),
        row.get("visual_hash"),
    )
    resolved_program_hash, program_ok = _exact_identity(
        program_hash,
        artifact_identity.get("programHash"),
        passport.get("program_hash"),
        row.get("program_hash"),
    )
    capacity_hash, capacity_ok = _exact_identity(
        artifact.get("floorCapacityPlanHash"),
        passport.get("floor_capacity_plan_hash"),
        row.get("floor_capacity_plan_hash"),
    )
    legal_hash, legal_ok = _exact_identity(
        manifest.get("legal_floor_field_hash"),
        artifact.get("legalFloorFieldHash"),
        passport.get("legal_floor_field_hash"),
        row.get("legal_floor_field_hash"),
        _certificate_value(passport_certificate, "legal_floor_field_hash"),
        _certificate_value(artifact_certificate, "legal_floor_field_hash"),
        _certificate_value(row_certificate, "legal_floor_field_hash"),
    )
    stop_hash, stop_ok = _exact_identity(
        artifact.get("candidateActualGfaStopHash"),
        passport.get("candidate_actual_gfa_stop_hash"),
        row.get("candidate_actual_gfa_stop_hash"),
        _certificate_value(
            passport_certificate,
            "candidate_actual_gfa_stop_hash",
        ),
        _certificate_value(
            artifact_certificate,
            "candidate_actual_gfa_stop_hash",
        ),
        _certificate_value(
            row_certificate,
            "candidate_actual_gfa_stop_hash",
        ),
    )
    certificate_ok = bool(
        isinstance(passport_certificate, Mapping)
        and isinstance(artifact_certificate, Mapping)
        and isinstance(row_certificate, Mapping)
        and dict(passport_certificate) == dict(artifact_certificate)
        and dict(passport_certificate) == dict(row_certificate)
        and passport_certificate.get("status") == "certified"
        and passport_certificate.get("hard_pass") is True
        and passport_certificate.get("program_hash")
        == resolved_program_hash
        and passport_certificate.get("final_geometry_hash")
        == final_hash
        and passport_certificate.get("visual_hash") == visual_hash
    )
    identity = {
        "program_hash": resolved_program_hash,
        "geometry_hash": visual_hash,
        "final_geometry_hash": final_hash,
        "final_legal_geometry_hash": final_hash,
        "visual_hash": visual_hash,
        "floor_capacity_plan_hash": capacity_hash,
        "legal_floor_field_hash": legal_hash,
        "candidate_actual_gfa_stop_hash": stop_hash,
    }
    return identity, all((
        program_ok,
        final_ok,
        visual_ok,
        capacity_ok,
        legal_ok,
        stop_ok,
        certificate_ok,
        all(identity.values()),
    ))


def _exact_identity(*values: Any) -> tuple[str, bool]:
    resolved = [str(value or "").strip() for value in values]
    return (
        resolved[0] if resolved else "",
        bool(resolved and all(resolved) and len(set(resolved)) == 1),
    )


def _certificate_value(value: Any, key: str) -> Any:
    return value.get(key) if isinstance(value, Mapping) else None


def build_executed_mass_elevation_handoff(*, run_id: str, index: int) -> dict[str, Any]:
    """Expose immutable elevation inputs from projected or genuine legacy archives.

    This packet does not claim that elevations were generated. It closes the
    identity/mesh boundary without promoting the capacity replay program to
    renderer-visible geometry authority.
    """

    compilation, artifact, row, _archive_path = compile_executed_mass(index, run_id)
    passport = materialize_executed_mass_passport(index, run_id)
    manifest = executed_mass_manifest(run_id)
    preview = materialize_executed_mass_preview(index, run_id).resolve()
    vlm = artifact.get("vlmAudit") if isinstance(artifact.get("vlmAudit"), dict) else {}
    identity = artifact.get("identity") if isinstance(artifact.get("identity"), dict) else {}
    projected_visual_mesh = (
        artifact.get("projectedVisualMesh")
        if isinstance(artifact.get("projectedVisualMesh"), dict)
        else {}
    )
    projected_visual_certificate = (
        artifact.get("projectedVisualCertificate")
        if isinstance(artifact.get("projectedVisualCertificate"), dict)
        else {}
    )
    is_projected_visual = bool(projected_visual_mesh)
    geometry_hash = str(compilation.geometry_hash or identity.get("geometryHash") or "")
    program_hash = compilation.program.program_hash()
    certified_identity, stop_chain_approved = (
        resolve_elevation_handoff_identity(
            program_hash=program_hash,
            geometry_hash=geometry_hash,
            artifact=artifact,
            passport=passport,
            row=row,
            manifest=manifest,
        )
    )
    handoff_id = hashlib.sha256(
        f"{run_id}|{index}|{program_hash}|{geometry_hash}".encode("utf-8")
    ).hexdigest()
    program_fit = vlm.get("program_fit_hard_pass")
    return {
        "schema_version": SCHEMA_VERSION,
        "handoff_id": f"elevation:{handoff_id[:24]}",
        "identity": {
            "run_id": str(run_id),
            "mass_index": int(index),
            "variant_id": str(row.get("variant_id") or f"maas_{int(index):02d}"),
            "pnu": str(manifest.get("pnu") or ""),
            **certified_identity,
        },
        "authority": {
            "source": (
                "validated_archived_projected_visual_mesh"
                if is_projected_visual
                else "recompiled_executed_geometry_program"
            ),
            "geometry_hash_replay_match": (
                geometry_hash
                == (
                    str(artifact.get("projectedVisualGeometryHash") or "")
                    if is_projected_visual
                    else str(identity.get("geometryHash") or "")
                )
            ),
            "projected_visual_certificate_hard_pass": (
                is_projected_visual
                and projected_visual_certificate.get("hard_pass") is True
            ),
            "authored_projected_surface_visual_authority": (
                is_projected_visual
            ),
            "base_relative_parametric_geometry": not is_projected_visual,
            "facade_may_not_modify_mass_geometry": True,
        },
        "geometry_program": compilation.program.to_dict(),
        "geometry_program_role": (
            "authored_projected_surface_program_and_provenance"
            if is_projected_visual
            else "executable_geometry"
        ),
        "projected_visual_certificate": projected_visual_certificate,
        "indexed_triangle_mesh": {
            "coordinate_space": str(
                projected_visual_mesh.get("coordinateSpace") or "local_model_m"
            ),
            "vertices": [list(vertex) for vertex in compilation.vertices],
            "triangles": [list(face) for face in compilation.triangles],
            "vertex_count": len(compilation.vertices),
            "triangle_count": len(compilation.triangles),
            "metrics": compilation.metrics,
        },
        "visual_evidence": {
            "actual_mass_preview_path": str(preview),
            "actual_mass_preview_sha256": hashlib.sha256(preview.read_bytes()).hexdigest(),
            "individual_vlm_evaluated": bool(vlm),
            "individual_vlm_model": str(vlm.get("model") or ""),
            "individual_vlm_response_id": str(vlm.get("response_id") or ""),
            "individual_vlm_program_fit_hard_pass": program_fit,
            "individual_vlm_actions": [str(value) for value in vlm.get("critic_actions") or ()],
            "vlm_image_inputs": vlm.get("vlm_image_inputs") or {},
        },
        "selection_state": {
            "mass_hard_gates_pass": bool((passport.get("executed_mass") or {}).get("hard_pass")),
            "individual_vlm_program_fit_pass": program_fit is True,
            "approved_for_final_elevation": bool(
                (passport.get("executed_mass") or {}).get("hard_pass")
                and program_fit is True
                and stop_chain_approved
            ),
            "candidate_actual_gfa_stop_chain_hard_pass": (
                stop_chain_approved
            ),
            "development_use_allowed": True,
        },
        "elevation_contract": {
            "required_views": ["front", "right", "back", "left", "axon", "top"],
            "required_conditions": [
                "camera_poses", "silhouette", "metric_depth", "surface_normals",
                "floor_guides", "facade_planes", "projection_manifest",
            ],
            "output_identity_fields": [
                "run_id", "program_hash", "geometry_hash",
                "final_geometry_hash", "visual_hash",
                "floor_capacity_plan_hash", "legal_floor_field_hash",
                "candidate_actual_gfa_stop_hash", "handoff_id",
            ],
            "status": "mesh_handoff_ready_condition_pack_adapter_pending",
            "next_adapter": (
                "validated projected visual mesh -> multi-view elevation condition pack"
                if is_projected_visual
                else "executed GeometryProgram mesh -> multi-view elevation condition pack"
            ),
        },
        "research_memory": {
            "paper_map": "docs/ai-session-memory/maas-aesthetic-texturing/PAPERS.md",
            "implementation_memory": "docs/ai-session-memory/maas-aesthetic-texturing/IMPLEMENTATION_DECISIONS.md",
            "next_steps": "docs/ai-session-memory/maas-aesthetic-texturing/NEXT_STEPS.md",
        },
    }


def write_executed_mass_elevation_handoff(*, run_id: str, index: int, output_path: str | Path) -> Path:
    output = Path(output_path).resolve()
    payload = build_executed_mass_elevation_handoff(run_id=run_id, index=index)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(f"{output.suffix}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    return output


__all__ = [
    "SCHEMA_VERSION",
    "build_executed_mass_elevation_handoff",
    "resolve_elevation_handoff_identity",
    "write_executed_mass_elevation_handoff",
]
