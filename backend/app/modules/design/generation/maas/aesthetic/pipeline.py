"""Orchestrate MAAS aesthetic generation without mutating legal evidence."""

from __future__ import annotations

from typing import Any

from backend.app.modules.design.generation.maas.aesthetic.adapters import get_provider_adapter
from backend.app.modules.design.generation.maas.aesthetic.contracts import AestheticProvider, ProviderResult, ReferenceRenderer
from backend.app.modules.design.generation.maas.aesthetic.image_job import build_aesthetic_image_job
from backend.app.modules.design.generation.maas.aesthetic.projection_assets import attach_facade_panel_assets
from backend.app.modules.design.generation.maas.aesthetic.projection_bake import attach_baked_projection_assets
from backend.app.modules.design.generation.maas.aesthetic.projection_export import attach_textured_mesh_assets
from backend.app.modules.design.generation.maas.aesthetic.renderers import PlaceholderReferenceRenderer
from backend.app.modules.design.generation.maas.aesthetic.storage import attach_aesthetic_assets
from backend.app.modules.design.generation.maas.aesthetic.validators import validate_aesthetic_job, validate_provider_result


def build_aesthetic_pipeline_result(
    evidence: dict[str, Any],
    *,
    provider: str = "placeholder",
    style: str | None = None,
    renderer: ReferenceRenderer | None = None,
    adapter: AestheticProvider | None = None,
    attach_to_evidence: bool = False,
) -> dict[str, Any]:
    """Run the aesthetic pipeline contract.

    The default provider is a dry-run placeholder. Real image providers should be
    injected through `adapter` or registered in `get_provider_adapter`.
    """

    job = build_aesthetic_image_job(evidence, provider=provider, style=style)
    job_validation = validate_aesthetic_job(job)
    if job_validation["status"] != "pass":
        return {
            "status": "fail",
            "job": job,
            "job_validation": job_validation,
            "reference": None,
            "provider_result": None,
            "provider_validation": None,
        }

    selected_renderer = renderer or PlaceholderReferenceRenderer()
    reference = selected_renderer.render(job)
    selected_adapter = adapter or get_provider_adapter(provider)
    provider_result = selected_adapter.generate(job, reference)
    provider_result = attach_facade_panel_assets(provider_result, reference.metadata)
    provider_result = attach_baked_projection_assets(provider_result, reference.metadata)
    provider_result = attach_textured_mesh_assets(provider_result)
    provider_validation = validate_provider_result(job, provider_result)

    result: dict[str, Any] = {
        "status": _overall_status(job_validation, provider_validation, provider_result),
        "job": job,
        "job_validation": job_validation,
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
        "provider_validation": provider_validation,
    }

    if attach_to_evidence:
        result["evidence"] = attach_aesthetic_assets(
            evidence,
            job=job,
            reference=reference,
            provider_result=provider_result,
            validation=provider_validation,
        )
    return result


def _overall_status(
    job_validation: dict[str, Any],
    provider_validation: dict[str, Any],
    provider_result: ProviderResult,
) -> str:
    if job_validation["status"] != "pass" or provider_validation["status"] == "fail":
        return "fail"
    if provider_result.status in {"pass", "complete", "completed"}:
        return "pass"
    return "needs_provider"


__all__ = ["build_aesthetic_pipeline_result"]
