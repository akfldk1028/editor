"""Shared, coordinate-free view of the lawful buildable field.

`geometry_language/` is a flat module folder; this package exists so the legal
envelope stops being private knowledge of one consumer.  Anything that decides
form — the live LLM author, the deterministic form supply, scheduling — should
read the lawful field through here rather than re-deriving it.

Nothing in this package may emit parcel coordinates, a finished mesh, or a
named building form.  It publishes relations only.
"""

from __future__ import annotations

from backend.app.modules.design.generation.maas.geometry_language.legal_envelope.design_context import AUTHORSHIP_INSTRUCTION, SCHEMA_VERSION, normalized_legal_field_design_context


__all__ = [
    "AUTHORSHIP_INSTRUCTION",
    "SCHEMA_VERSION",
    "normalized_legal_field_design_context",
]
