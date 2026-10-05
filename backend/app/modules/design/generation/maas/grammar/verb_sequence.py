"""ARR-local MAAS verb sequence model.

This is intentionally smaller than the reference clone/MAAS grammar. ARR uses
the sequence as a legal massing recipe, then interprets it into Shapely
footprints/floor-plate hints before the legal repair pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class VerbCall:
    verb: str
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"verb": self.verb, "params": dict(self.params)}


@dataclass(frozen=True)
class VerbSequence:
    name: str
    label: str
    calls: tuple[VerbCall, ...]
    notes: tuple[str, ...] = ()

    def validate(self) -> list[str]:
        from backend.app.modules.design.generation.maas.grammar.vocab import SUPPORTED_VERBS

        errors: list[str] = []
        if not self.calls:
            return ["empty sequence"]
        if self.calls[0].verb != "base":
            errors.append(f"first call must be 'base', got {self.calls[0].verb!r}")
        for i, call in enumerate(self.calls):
            if call.verb not in SUPPORTED_VERBS:
                errors.append(f"call {i}: unsupported verb {call.verb!r}")
        return errors

    def to_list(self) -> list[dict[str, Any]]:
        return [call.to_dict() for call in self.calls]


def call(verb: str, **params: Any) -> VerbCall:
    return VerbCall(verb=verb, params=params)


__all__ = ["VerbCall", "VerbSequence", "call"]
