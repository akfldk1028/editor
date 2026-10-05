"""
Data schemas for the design app.

Pure dataclasses for type documentation.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class JobSpec:
    inputs: list[dict] = field(default_factory=list)
    outputs: list[dict] = field(default_factory=list)
    options: dict = field(default_factory=dict)


@dataclass
class MassParams:
    x_offset: float = 0.0
    y_offset: float = 0.0
    width: float = 10.0
    depth: float = 10.0
    height: float = 12.0
    num_floors: int = 4
    rotation: float = 0.0


@dataclass
class EvaluationResult:
    bcr: float = 0.0
    far: float = 0.0
    height: float = 0.0
    floor_area: float = 0.0
    daylight_score: float = 0.0
    setback_ok: bool = True
    mass_polygon: dict | None = None
