"""Attach aesthetic generation artifacts to an evidence-like dict."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from backend.app.modules.design.generation.maas.aesthetic.contracts import ProviderResult, RenderedReference


def attach_aesthetic_assets(
    evidence: dict[str, Any],
    *,
    job: dict[str, Any],
    reference: RenderedReference,
    provider_result: ProviderResult,
    validation: dict[str, Any],
) -> dict[str, Any]:
    next_evidence = deepcopy(evidence)
    assets = next_evidence.setdefault("assets", {})
    assets.setdefault("aesthetic", [])
    assets["aesthetic"].append(
        {
            "type": "maas_aesthetic_generation",
            "source_bundle_id": job.get("source_bundle_id"),
            "candidate_id": job.get("candidate_id"),
            "reference": {
                "asset_id": reference.asset_id,
                "uri": reference.uri,
                "media_type": reference.media_type,
                "metadata": reference.metadata,
            },
            "provider_result": {
                "provider": provider_result.provider,
                "status": provider_result.status,
                "assets": provider_result.assets,
                "metadata": provider_result.metadata,
                "issues": provider_result.issues,
            },
            "validation": validation,
            "legal_status_effect": "none",
        }
    )

    provenance = next_evidence.setdefault("provenance", {})
    provenance.setdefault("entities", [])
    provenance.setdefault("relations", [])
    provenance["entities"].append(
        {
            "id": reference.asset_id,
            "type": "ReferenceRender",
            "source": "maas_aesthetic_pipeline",
        }
    )
    for asset in provider_result.assets:
        asset_id = asset.get("asset_id") or asset.get("id")
        if asset_id:
            provenance["relations"].append(
                {
                    "type": "wasGeneratedFrom",
                    "entity": asset_id,
                    "source": reference.asset_id,
                }
            )
    return next_evidence


__all__ = ["attach_aesthetic_assets"]
