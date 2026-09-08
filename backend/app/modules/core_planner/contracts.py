from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CoreCandidate:
    strategy: str
    polygon: tuple[tuple[float, float], ...]
    fingerprint: str
    contained_floor_indices: tuple[int, ...]
