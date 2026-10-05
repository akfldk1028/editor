"""Failure evidence for strict MASS portfolios without false publication."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Callable, Iterable

from backend.app.modules.design.generation.maas.geometry_language.projected_visual_contract import CertifiedMassArtifact


def _certified_witness_visual_authority(
    feature: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    properties = (
        feature.get("properties")
        if isinstance(feature, dict)
        and isinstance(feature.get("properties"), dict)
        else {}
    )
    artifact = properties.get("geometry_artifact")
    artifact = artifact if isinstance(artifact, dict) else {}
    try:
        certified = CertifiedMassArtifact.load(
            artifact,
            authority_context=(
                properties.get("final_semantic_anchor")
                if isinstance(properties.get("final_semantic_anchor"), dict)
                else {}
            ),
        )
    except (TypeError, ValueError) as exc:
        return False, {
            "status": "invalid_certified_mass_artifact",
            "reason": str(exc),
            "certified_mass_artifact_core_hash": "",
        }
    properties.update(certified.feature_binding())
    certificate = certified.certificate()
    surfaces = properties.get("source_surfaces") or []
    authority = {
        "schema_version": str(certificate.get("schema_version") or ""),
        "status": str(certificate.get("status") or ""),
        "hard_pass": certificate.get("hard_pass") is True,
        "visual_hash_present": bool(certified.validated_visual.visual_hash),
        "projected_surface_count": int(
            certificate.get("projected_surface_count") or 0
        ),
        "source_surface_count": len(surfaces),
        "profiled_surface_count": len(surfaces),
        "artifact_hash_matches": True,
        "certified_mass_artifact_core_hash": certified.core_hash,
    }
    return True, authority


def persist_portfolio_witness(
    output_dir: Path,
    *,
    program_slug: str,
    target_count: int,
    selected_count: int,
    records: Iterable[dict[str, Any]],
    features: Iterable[dict[str, Any]],
    failure_histogram: dict[str, int],
    renderer: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Persist a clearly non-publishable board when strict selection fails."""

    if int(selected_count) >= int(target_count):
        return {
            "schema_version": "arr.maas.portfolio_witness.v1",
            "status": "not_required",
            "publishable": False,
            "target_count": int(target_count),
            "selected_count": int(selected_count),
        }

    normalized_records = [deepcopy(record) for record in records]
    candidate_features = [deepcopy(feature) for feature in features]
    normalized_features: list[dict[str, Any]] = []
    feature_exclusions: list[dict[str, Any]] = []
    for index, feature in enumerate(candidate_features):
        properties = feature.setdefault("properties", {})
        record = (
            normalized_records[index]
            if index < len(normalized_records)
            else {}
        )
        properties["portfolio_witness"] = {
            "candidate_id": str(record.get("candidate_id") or ""),
            "publishable": False,
            "status": str(record.get("status") or "diagnostic"),
            "failure_reasons": list(record.get("failure_reasons") or ()),
        }
        properties["portfolio_selection_status"] = str(
            record.get("status") or "diagnostic"
        )
        certified, authority = _certified_witness_visual_authority(feature)
        if certified:
            normalized_features.append(feature)
            continue
        exclusion = {
            "candidate_id": str(record.get("candidate_id") or ""),
            "feature_index": index,
            "reason": "witness_feature_uncertified_authored_visual",
            "authority": authority,
        }
        feature_exclusions.append(exclusion)
        if index < len(normalized_records):
            normalized_records[index]["witness_feature_exclusion"] = deepcopy(
                exclusion
            )

    directory = Path(output_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    board = directory / f"maas-book-{program_slug}-{int(target_count)}-witness.png"
    manifest = directory / f"maas-book-{program_slug}-{int(target_count)}-witness.json"
    if renderer is None and normalized_features:
        from backend.app.modules.design.generation.maas.program_massing.benchmark import render_archive_sheet

        renderer = render_archive_sheet
    if normalized_features:
        assert renderer is not None
        has_selected_witness = any(
            str(record.get("status") or "") == "selected"
            for record in normalized_records
        )
        renderer(
            normalized_features,
            board,
            title=(
                f"MAAS {program_slug} - {len(normalized_features)} WITNESSES - "
                + (
                    "INCOMPLETE PORTFOLIO / NOT PUBLISHABLE"
                    if has_selected_witness
                    else "NOT SELECTED / NOT PUBLISHABLE"
                )
            ),
        )
    evidence = {
        "schema_version": "arr.maas.portfolio_witness.v1",
        "status": "failed_portfolio_witness",
        "publishable": False,
        "target_count": int(target_count),
        "selected_count": int(selected_count),
        "candidate_count": len(normalized_records),
        "rendered_candidate_count": len(normalized_features),
        "excluded_feature_count": len(feature_exclusions),
        "feature_exclusions": feature_exclusions,
        "failure_histogram": {
            str(key): int(value)
            for key, value in sorted(failure_histogram.items())
        },
        "records": normalized_records,
        "board_path": str(board) if normalized_features else "",
        "board_sha256": (
            sha256(board.read_bytes()).hexdigest()
            if normalized_features
            else ""
        ),
        "manifest_path": str(manifest),
    }
    manifest.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return evidence


__all__ = ["persist_portfolio_witness"]
