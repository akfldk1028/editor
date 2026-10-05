"""Validation helpers for MAAS aesthetic image jobs."""

from __future__ import annotations

from typing import Any

from backend.app.modules.design.generation.maas.aesthetic.contracts import ProviderResult


def validate_aesthetic_job(job: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    prompt = job.get("prompt") if isinstance(job.get("prompt"), dict) else {}
    reference = job.get("reference_render") if isinstance(job.get("reference_render"), dict) else {}
    policy = job.get("evidence_policy") if isinstance(job.get("evidence_policy"), dict) else {}

    if not job.get("source_bundle_id"):
        issues.append(_issue("missing_source_bundle", "Aesthetic job must reference a MAAS evidence bundle."))
    if not job.get("candidate_id"):
        issues.append(_issue("missing_candidate", "Aesthetic job must reference a candidate_id."))
    if not prompt.get("constraints", {}).get("lock_silhouette"):
        issues.append(_issue("silhouette_not_locked", "Prompt constraints must lock the silhouette."))
    if not reference.get("geometry_lock"):
        issues.append(_issue("missing_geometry_lock", "Reference render must include geometry_lock."))
    if not job.get("locked_geometry", {}).get("mass_geojson"):
        issues.append(_issue("missing_locked_geometry", "Aesthetic job must carry locked MAAS geometry for rendering."))
    if policy.get("legal_status_effect") != "none":
        issues.append(_issue("legal_status_mutation", "Image generation must not change legal status."))

    return {
        "status": "pass" if not issues else "fail",
        "issues": issues,
    }


def _issue(code: str, message: str) -> dict[str, Any]:
    return {"code": code, "message": message}


def validate_provider_result(job: dict[str, Any], result: ProviderResult) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    if result.status in {"pass", "complete", "completed"} and not result.assets:
        issues.append(_issue("missing_generated_assets", "Completed provider result must include generated assets."))
    for asset in result.assets:
        if asset.get("legal_status_effect") not in {None, "none"}:
            issues.append(_issue("asset_mutates_legal_status", "Generated aesthetic assets must not change legal status."))
        if asset.get("source_bundle_id") not in {None, job.get("source_bundle_id")}:
            issues.append(_issue("asset_source_bundle_mismatch", "Generated asset references a different evidence bundle."))
        if asset.get("candidate_id") not in {None, job.get("candidate_id")}:
            issues.append(_issue("asset_candidate_mismatch", "Generated asset references a different candidate."))
    return {
        "status": "pass" if not issues else "fail",
        "issues": issues,
    }


__all__ = ["validate_aesthetic_job", "validate_provider_result"]
