"""Cross-run recovery pool for exact, context-compatible MASS artifacts."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.app.modules.design.generation.maas.book_language.legal_mass_archive import _final_surface_payload_hash


POOL_SCHEMA_VERSION = "arr.maas.cumulative_candidate_pool.v1"
EXACT_ARCHIVE_FILENAME = "maas-book-exact-geometry-artifacts.json"


def build_cumulative_candidate_pool(
    archive_roots: Sequence[Path],
    *,
    pnu: str,
    legal_floor_field_hash: str = "",
    floor_capacity_plan_hash: str = "",
) -> dict[str, Any]:
    """Collect exact artifacts without mixing legal contexts or run duplicates."""

    archive_paths = _discover_archive_paths(archive_roots)
    malformed_archives: list[dict[str, str]] = []
    normalized_records: list[dict[str, Any]] = []
    source_record_count = 0
    for archive_path in archive_paths:
        try:
            archive = _read_archive(archive_path)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            malformed_archives.append(
                {
                    "archive_path": str(archive_path),
                    "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                }
            )
            continue
        archive_pnu = str(archive.get("pnu") or "").strip()
        for record_index, record in enumerate(archive.get("records") or (), start=1):
            if not isinstance(record, Mapping):
                continue
            source_record_count += 1
            artifact = _artifact(record)
            if not artifact:
                normalized_records.append(
                    {
                        "source_archive": str(archive_path),
                        "source_record_index": record_index,
                        "invalid_reasons": ["geometry_artifact_missing"],
                        "pnu": archive_pnu,
                    }
                )
                continue
            normalized_records.append(
                _normalize_artifact(
                    artifact,
                    archive_path=archive_path,
                    record_index=record_index,
                    archive_pnu=archive_pnu,
                )
            )

    requested_pnu = str(pnu).strip()
    pnu_records = [
        record
        for record in normalized_records
        if str(record.get("pnu") or "") == requested_pnu
    ]
    resolved_legal_hash, resolved_floor_hash = _resolve_context_hashes(
        pnu_records,
        legal_floor_field_hash=str(legal_floor_field_hash).strip(),
        floor_capacity_plan_hash=str(floor_capacity_plan_hash).strip(),
    )
    compatible_records: list[dict[str, Any]] = []
    incompatible_record_count = 0
    for record in normalized_records:
        compatible = (
            str(record.get("pnu") or "") == requested_pnu
            and str(record.get("legal_floor_field_hash") or "")
            == resolved_legal_hash
            and str(record.get("floor_capacity_plan_hash") or "")
            == resolved_floor_hash
        )
        if compatible:
            compatible_records.append(record)
        else:
            incompatible_record_count += 1

    candidates_by_geometry: dict[str, dict[str, Any]] = {}
    duplicate_record_count = 0
    invalid_record_count = 0
    for record in compatible_records:
        geometry_hash = str(record.get("geometry_hash") or "")
        if record.get("invalid_reasons") or not geometry_hash:
            invalid_record_count += 1
            continue
        if geometry_hash in candidates_by_geometry:
            duplicate_record_count += 1
            continue
        candidates_by_geometry[geometry_hash] = record

    candidates = list(candidates_by_geometry.values())
    phenotype_counts = Counter(
        str(candidate.get("body_phenotype") or "")
        for candidate in candidates
        if candidate.get("mass_eligible") is True
        and candidate.get("morphology_measured") is True
    )
    return {
        "schema_version": POOL_SCHEMA_VERSION,
        "selection_effect": "cumulative_recovery_only_not_canonical",
        "context": {
            "pnu": requested_pnu,
            "legal_floor_field_hash": resolved_legal_hash,
            "floor_capacity_plan_hash": resolved_floor_hash,
        },
        "archive_roots": [str(Path(root).resolve()) for root in archive_roots],
        "archive_file_count": len(archive_paths),
        "parsed_archive_count": len(archive_paths) - len(malformed_archives),
        "malformed_archive_count": len(malformed_archives),
        "malformed_archives": malformed_archives,
        "source_record_count": source_record_count,
        "compatible_record_count": len(compatible_records),
        "incompatible_record_count": incompatible_record_count,
        "duplicate_record_count": duplicate_record_count,
        "invalid_record_count": invalid_record_count,
        "unique_candidate_count": len(candidates),
        "mass_eligible_unique_count": sum(
            candidate.get("mass_eligible") is True for candidate in candidates
        ),
        "publishable_unique_count": sum(
            candidate.get("publishable") is True for candidate in candidates
        ),
        "measured_non_stepped_unique_count": sum(
            candidate.get("mass_eligible") is True
            and candidate.get("morphology_measured") is True
            and candidate.get("visible_stepped") is not True
            for candidate in candidates
        ),
        "measured_phenotype_counts": dict(sorted(phenotype_counts.items())),
        "candidates": candidates,
    }


def select_recovery_records(
    pool: Mapping[str, Any],
    *,
    target_count: int,
) -> list[dict[str, Any]]:
    """Select diverse eligible identities and hydrate only their exact surfaces."""

    remaining = [
        dict(candidate)
        for candidate in pool.get("candidates") or ()
        if isinstance(candidate, Mapping) and candidate.get("mass_eligible") is True
    ]
    measured_non_stepped = [
        candidate
        for candidate in remaining
        if candidate.get("morphology_measured") is True
        and candidate.get("visible_stepped") is not True
    ]
    if len(measured_non_stepped) >= max(0, int(target_count)):
        remaining = measured_non_stepped
    selected_candidates: list[dict[str, Any]] = []
    seen_scopes: set[str] = set()
    seen_families: set[str] = set()
    seen_principles: set[str] = set()
    seen_phenotypes: set[str] = set()
    for _ in range(max(0, int(target_count))):
        if not remaining:
            break
        candidate = max(
            remaining,
            key=lambda item: (
                str(item.get("body_phenotype") or "") not in seen_phenotypes,
                str(item.get("book_scope") or "") not in seen_scopes,
                str(item.get("family") or "") not in seen_families,
                float(item.get("utilization") or 0.0),
                str(item.get("book_principle_id") or "") not in seen_principles,
                str(item.get("geometry_hash") or ""),
            ),
        )
        remaining.remove(candidate)
        selected_candidates.append(candidate)
        seen_scopes.add(str(candidate.get("book_scope") or ""))
        seen_families.add(str(candidate.get("family") or ""))
        seen_principles.add(str(candidate.get("book_principle_id") or ""))
        seen_phenotypes.add(str(candidate.get("body_phenotype") or ""))
    return [_hydrate_archive_record(candidate) for candidate in selected_candidates]


def _discover_archive_paths(archive_roots: Sequence[Path]) -> list[Path]:
    paths: set[Path] = set()
    for root_value in archive_roots:
        root = Path(root_value).resolve()
        if root.is_file() and root.name == EXACT_ARCHIVE_FILENAME:
            paths.add(root)
        elif root.is_dir():
            paths.update(root.rglob(EXACT_ARCHIVE_FILENAME))
    return sorted(paths, key=lambda path: str(path).lower())


def _read_archive(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("exact geometry archive must contain a JSON object")
    return value


def _artifact(record: Mapping[str, Any]) -> dict[str, Any]:
    for key in ("geometry_artifact", "artifact"):
        value = record.get(key)
        if isinstance(value, Mapping):
            return dict(value)
    return {}


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _nested(mapping: Mapping[str, Any], *keys: str) -> Any:
    value: Any = mapping
    for key in keys:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _first_text(*values: Any) -> str:
    return next((str(value).strip() for value in values if str(value or "").strip()), "")


def _normalize_artifact(
    artifact: Mapping[str, Any],
    *,
    archive_path: Path,
    record_index: int,
    archive_pnu: str,
) -> dict[str, Any]:
    identity = _mapping(artifact.get("identity"))
    certificate = _mapping(artifact.get("projectedVisualCertificate"))
    capacity = _mapping(artifact.get("capacityAlternative"))
    matrix_stack = _mapping(artifact.get("floorwiseLegalMatrixStack"))
    audited_context = _mapping(
        _nested(artifact, "semanticProjectionAudit", "audited_context")
    )
    hard_gates = _mapping(artifact.get("hardGates"))
    measured_morphology = _mapping(
        _nested(
            hard_gates,
            "program",
            "evidence",
            "program_form_gate",
            "measured_morphology",
        )
    )
    geometry_program = _mapping(artifact.get("geometryProgram"))
    authored_program = _mapping(artifact.get("authoredGeometryProgram"))
    program_metadata = _mapping(geometry_program.get("metadata")) or _mapping(
        authored_program.get("metadata")
    )
    surfaces = _nested(artifact, "projectedVisualMesh", "triangles")
    expected_surface_hash = _first_text(
        artifact.get("finalSurfacePayloadHash"),
        certificate.get("final_surface_payload_hash"),
    )
    invalid_reasons: list[str] = []
    if not isinstance(surfaces, list) or not surfaces:
        invalid_reasons.append("exact_surface_payload_missing")
    else:
        try:
            actual_surface_hash = _final_surface_payload_hash(surfaces)
        except (TypeError, ValueError):
            actual_surface_hash = ""
        if not expected_surface_hash or actual_surface_hash != expected_surface_hash:
            invalid_reasons.append("exact_surface_payload_hash_mismatch")
    geometry_hash = _first_text(
        artifact.get("finalLegalGeometryHash"),
        identity.get("finalLegalGeometryHash"),
        certificate.get("final_geometry_hash"),
    )
    program_hash = _first_text(
        identity.get("programHash"),
        certificate.get("final_program_hash"),
        _nested(artifact, "executionPassport", "program_hash"),
    )
    if not geometry_hash:
        invalid_reasons.append("final_legal_geometry_hash_missing")
    if not program_hash:
        invalid_reasons.append("program_hash_missing")
    clean = _nested(hard_gates, "cleanMass", "hard_pass") is True
    legal = _nested(hard_gates, "legal", "hard_pass") is True
    parking = _nested(hard_gates, "parking", "hard_pass") is True
    program = _nested(hard_gates, "program", "hard_pass") is True
    finalization = (
        _nested(hard_gates, "candidateFinalization", "hard_pass") is True
    )
    law_graph = (
        _nested(hard_gates, "lawGraph", "law_graph_evidence_hard_pass") is True
        or artifact.get("law_graph_evidence_hard_pass") is True
    )
    mass_eligible = not invalid_reasons and clean and legal and parking and program
    publishable = mass_eligible and finalization and law_graph
    recertification_reasons: list[str] = []
    if mass_eligible and not finalization:
        recertification_reasons.append("candidate_finalization_missing")
    if mass_eligible and not law_graph:
        recertification_reasons.append("law_graph_evidence_missing")
    return {
        "geometry_hash": geometry_hash,
        "program_hash": program_hash,
        "visual_hash": _first_text(
            artifact.get("projectedVisualGeometryHash"),
            certificate.get("visual_hash"),
            _nested(artifact, "executionPassport", "visual_hash"),
        ),
        "surface_payload_hash": expected_surface_hash,
        "pnu": _first_text(archive_pnu, audited_context.get("pnu")),
        "legal_floor_field_hash": _first_text(
            artifact.get("legalFloorFieldHash"),
            capacity.get("legal_floor_field_hash"),
        ),
        "floor_capacity_plan_hash": _first_text(
            matrix_stack.get("floor_capacity_plan_hash"),
            _nested(artifact, "executionPassport", "floor_capacity_plan_hash"),
        ),
        "book_scope": str(artifact.get("bookScope") or ""),
        "book_principle_id": str(artifact.get("bookPrincipleId") or ""),
        "family": str(program_metadata.get("family") or ""),
        "morphology_measured": bool(measured_morphology),
        "body_phenotype": _first_text(
            measured_morphology.get("body_phenotype"),
            measured_morphology.get("phenotype"),
        ),
        "visible_stepped": measured_morphology.get("visible_stepped") is True,
        "utilization": float(capacity.get("achieved_utilization") or 0.0),
        "gate_status": {
            "clean_mass": clean,
            "legal": legal,
            "parking": parking,
            "program": program,
            "candidate_finalization": finalization,
            "law_graph": law_graph,
        },
        "invalid_reasons": invalid_reasons,
        "mass_eligible": mass_eligible,
        "publishable": publishable,
        "status": (
            "publishable"
            if publishable
            else "needs_recertification"
            if mass_eligible
            else "rejected"
        ),
        "recertification_reasons": recertification_reasons,
        "source_archive": str(archive_path),
        "source_run_id": archive_path.parent.name,
        "source_record_index": int(record_index),
    }


def _resolve_context_hashes(
    records: Sequence[Mapping[str, Any]],
    *,
    legal_floor_field_hash: str,
    floor_capacity_plan_hash: str,
) -> tuple[str, str]:
    pairs = Counter(
        (
            str(record.get("legal_floor_field_hash") or ""),
            str(record.get("floor_capacity_plan_hash") or ""),
        )
        for record in records
        if str(record.get("legal_floor_field_hash") or "")
        and str(record.get("floor_capacity_plan_hash") or "")
        and (
            not legal_floor_field_hash
            or str(record.get("legal_floor_field_hash") or "")
            == legal_floor_field_hash
        )
        and (
            not floor_capacity_plan_hash
            or str(record.get("floor_capacity_plan_hash") or "")
            == floor_capacity_plan_hash
        )
    )
    if not pairs:
        return legal_floor_field_hash, floor_capacity_plan_hash
    resolved_pair = min(
        pairs,
        key=lambda pair: (-pairs[pair], pair[0], pair[1]),
    )
    return resolved_pair


def _hydrate_archive_record(candidate: Mapping[str, Any]) -> dict[str, Any]:
    archive_path = Path(str(candidate.get("source_archive") or ""))
    record_index = int(candidate.get("source_record_index") or 0)
    archive = _read_archive(archive_path)
    records = [record for record in archive.get("records") or () if isinstance(record, Mapping)]
    if record_index < 1 or record_index > len(records):
        raise ValueError("cumulative candidate source record is unavailable")
    artifact = _artifact(records[record_index - 1])
    surfaces = deepcopy(_nested(artifact, "projectedVisualMesh", "triangles"))
    surface_hash = str(candidate.get("surface_payload_hash") or "")
    if not isinstance(surfaces, list) or _final_surface_payload_hash(surfaces) != surface_hash:
        raise ValueError("cumulative candidate exact surface identity changed")
    return {
        "schema_version": "arr.maas.legal_mass_archive.v1",
        "geometry_hash": str(candidate.get("geometry_hash") or ""),
        "program_hash": str(candidate.get("program_hash") or ""),
        "final_authored_surface_payload": surfaces,
        "final_surface_payload_hash": surface_hash,
        "normalized_source_surface_payload_hash": str(
            artifact.get("normalizedSourceSurfacePayloadHash") or ""
        ),
        "surface_coordinate_frame": str(
            _nested(artifact, "projectedVisualMesh", "coordinateSpace") or ""
        ),
        "policy_evidence": {
            "compiler_clean": True,
            "contained": True,
            "authored_surface_certified": True,
            "legal_hard_pass": True,
        },
        "capacity_evidence": {
            "feasible_capacity_utilization": float(
                candidate.get("utilization") or 0.0
            ),
            "capacity_objective_status": str(candidate.get("status") or ""),
            "parking_status": (
                "pass" if _nested(candidate, "gate_status", "parking") is True else "fail"
            ),
            "vlm_status": "not_recertified",
        },
        "scope": {"book_scope": str(candidate.get("book_scope") or "")},
        "family": str(candidate.get("family") or ""),
        "lineage": {
            "source_run_id": str(candidate.get("source_run_id") or ""),
            "source_archive": str(candidate.get("source_archive") or ""),
            "source_record_index": record_index,
            "book_principle_id": str(candidate.get("book_principle_id") or ""),
            "body_phenotype": str(candidate.get("body_phenotype") or ""),
            "visible_stepped": candidate.get("visible_stepped") is True,
        },
        "non_selection_reason": "cumulative recovery proof; current publishable recertification pending",
    }


__all__ = [
    "POOL_SCHEMA_VERSION",
    "build_cumulative_candidate_pool",
    "select_recovery_records",
]
