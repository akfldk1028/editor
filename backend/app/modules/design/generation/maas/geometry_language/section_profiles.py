"""Normalized, program-neutral section profiles for recursive solid macros."""

from __future__ import annotations

from copy import deepcopy


SECTION_PROFILES: dict[str, list[list[float]]] = {
    "ridge": [[0.0, 0.62], [0.5, 1.0], [1.0, 0.62]],
    "shed": [[0.0, 0.58], [1.0, 0.96]],
    "folded": [[0.0, 0.62], [0.28, 0.96], [0.52, 0.70], [0.76, 1.0], [1.0, 0.64]],
    "sawtooth": [[0.0, 0.64], [0.20, 0.94], [0.23, 0.62], [0.50, 0.98], [0.53, 0.64], [0.80, 0.92], [0.83, 0.66], [1.0, 0.86]],
    "stepped": [[0.0, 0.60], [0.30, 0.60], [0.34, 0.78], [0.62, 0.78], [0.66, 0.96], [1.0, 0.96]],
    "barrel": [[0.0, 0.62], [0.16, 0.82], [0.34, 0.96], [0.50, 1.0], [0.66, 0.96], [0.84, 0.82], [1.0, 0.62]],
}


def section_profile_controls(family: str) -> list[list[float]]:
    key = str(family or "").strip().lower()
    if key not in SECTION_PROFILES:
        return []
    return deepcopy(SECTION_PROFILES[key])


__all__ = ["SECTION_PROFILES", "section_profile_controls"]
