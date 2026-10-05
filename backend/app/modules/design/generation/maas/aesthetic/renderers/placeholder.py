"""Compatibility alias for the deterministic reference PNG renderer."""

from __future__ import annotations

from pathlib import Path

from backend.app.modules.design.generation.maas.aesthetic.renderers.reference_png import ReferencePngRenderer


class PlaceholderReferenceRenderer(ReferencePngRenderer):
    def __init__(self) -> None:
        super().__init__(Path("media") / "maas" / "aesthetic" / "references")


__all__ = ["PlaceholderReferenceRenderer"]
