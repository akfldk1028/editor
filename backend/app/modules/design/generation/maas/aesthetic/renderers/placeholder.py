"""Compatibility alias for the deterministic reference PNG renderer."""

from __future__ import annotations

from pathlib import Path

from backend.app.modules.design.generation.maas.aesthetic.renderers.reference_png import ReferencePngRenderer
from backend.app.modules.design.generation.paths import aesthetic_media_root


class PlaceholderReferenceRenderer(ReferencePngRenderer):
    def __init__(self) -> None:
        super().__init__(aesthetic_media_root() / "references")


__all__ = ["PlaceholderReferenceRenderer"]
