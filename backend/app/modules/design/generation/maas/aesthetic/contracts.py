"""Typed contracts for the MAAS aesthetic pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class RenderedReference:
    """A deterministic render generated from legal MAAS geometry."""

    asset_id: str
    uri: str
    media_type: str = "image/png"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderResult:
    """Raw output from an image/texturing provider."""

    provider: str
    status: str
    assets: list[dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)
    issues: list[dict[str, Any]] = field(default_factory=list)


class ReferenceRenderer(Protocol):
    def render(self, job: dict[str, Any]) -> RenderedReference:
        """Render the locked MAAS geometry into a reference asset."""


class AestheticProvider(Protocol):
    name: str

    def generate(self, job: dict[str, Any], reference: RenderedReference) -> ProviderResult:
        """Generate aesthetic facade/material assets from a locked reference."""


__all__ = ["AestheticProvider", "ProviderResult", "ReferenceRenderer", "RenderedReference"]
