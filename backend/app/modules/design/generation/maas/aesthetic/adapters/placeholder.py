"""Dry-run provider adapter.

This adapter does not call an image model. It preserves the contract so tests
and next-session agents can wire the pipeline without mutating legal geometry.
"""

from __future__ import annotations

from typing import Any

from backend.app.modules.design.generation.maas.aesthetic.contracts import ProviderResult, RenderedReference


class PlaceholderProviderAdapter:
    name = "placeholder"

    def __init__(self, provider: str = "placeholder") -> None:
        self.name = provider

    def generate(self, job: dict[str, Any], reference: RenderedReference) -> ProviderResult:
        return ProviderResult(
            provider=self.name,
            status="needs_provider",
            assets=[],
            metadata={
                "source_bundle_id": job.get("source_bundle_id"),
                "candidate_id": job.get("candidate_id"),
                "reference_asset_id": reference.asset_id,
                "reason": "real image provider adapter is not configured",
            },
            issues=[
                {
                    "code": "provider_not_configured",
                    "message": "Configure gpt-image, Nano Banana, or UniTEX worker to generate assets.",
                }
            ],
        )


__all__ = ["PlaceholderProviderAdapter"]
