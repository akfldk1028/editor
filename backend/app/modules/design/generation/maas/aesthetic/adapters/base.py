"""Provider adapter registry."""

from __future__ import annotations

from backend.app.modules.design.generation.maas.aesthetic.contracts import AestheticProvider
from backend.app.modules.design.generation.maas.aesthetic.adapters.nano_banana import NanoBananaAdapter
from backend.app.modules.design.generation.maas.aesthetic.adapters.openai_image import OpenAIImageAdapter
from backend.app.modules.design.generation.maas.aesthetic.adapters.placeholder import PlaceholderProviderAdapter


class ProviderNotConfigured(RuntimeError):
    """Raised when a real image provider has not been configured yet."""


def get_provider_adapter(provider: str) -> AestheticProvider:
    normalized = (provider or "").strip().lower()
    if normalized in {"placeholder", "dry-run", "dry_run"}:
        return PlaceholderProviderAdapter(provider="placeholder")
    if normalized in {"gpt-image", "gpt_image", "openai", "openai-image"}:
        return OpenAIImageAdapter()
    if normalized in {"nano-banana", "nanobanana", "nano_banana"}:
        return NanoBananaAdapter()
    if normalized in {"unitex"}:
        raise ProviderNotConfigured("UniTEX must run as a separate CUDA worker; adapter boundary is not configured yet.")
    raise ProviderNotConfigured(f"Unknown aesthetic provider: {provider}")


__all__ = ["ProviderNotConfigured", "get_provider_adapter"]
