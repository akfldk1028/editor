from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math

Point = tuple[float, float]


@dataclass(frozen=True)
class FloorCodeContext:
    floor_index: int
    occupancy: str | None = None
    occupant_load: int | None = None
    above_grade: bool | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.floor_index, int) or self.floor_index < 1:
            raise ValueError("floor_index must be a positive integer")
        if self.occupancy is not None and (
            not isinstance(self.occupancy, str) or not self.occupancy.strip()
        ):
            raise TypeError("occupancy must be a non-empty string or None")
        if self.occupant_load is not None and (
            not isinstance(self.occupant_load, int) or self.occupant_load < 1
        ):
            raise ValueError("occupant_load must be a positive integer or None")
        if self.above_grade is not None and not isinstance(self.above_grade, bool):
            raise TypeError("above_grade must be bool or None")


@dataclass(frozen=True)
class BuildingCodeContext:
    jurisdiction: str | None = None
    effective_date: str | None = None
    floor_to_floor_height_m: float | None = None
    sprinklered: bool | None = None
    fire_resistant: bool | None = None
    floor_facts: tuple[FloorCodeContext, ...] = ()

    def __post_init__(self) -> None:
        for name in ("jurisdiction", "effective_date"):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, str) or not value.strip()
            ):
                raise TypeError(f"{name} must be a non-empty string or None")
        if self.effective_date is not None:
            try:
                date.fromisoformat(self.effective_date)
            except ValueError as error:
                raise ValueError("effective_date must use ISO YYYY-MM-DD") from error
        height = self.floor_to_floor_height_m
        if height is not None and (
            not isinstance(height, (int, float))
            or isinstance(height, bool)
            or not math.isfinite(float(height))
            or float(height) <= 0
        ):
            raise ValueError(
                "floor_to_floor_height_m must be finite and positive or None"
            )
        for name in ("sprinklered", "fire_resistant"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, bool):
                raise TypeError(f"{name} must be bool or None")
        if not isinstance(self.floor_facts, tuple) or any(
            not isinstance(fact, FloorCodeContext) for fact in self.floor_facts
        ):
            raise TypeError("floor_facts must be a tuple of FloorCodeContext")
        floor_indices = [fact.floor_index for fact in self.floor_facts]
        if len(set(floor_indices)) != len(floor_indices):
            raise ValueError("floor_facts floor_index values must be unique")


@dataclass(frozen=True)
class MassInput:
    project_id: str
    floors: int
    footprint_polygon: list[Point]
    site_edges: list[dict]
    access_candidates: list[dict]
    use_mix: dict[str, float]
    building_code_context: BuildingCodeContext | None = None

    def __post_init__(self) -> None:
        if self.building_code_context is not None and not isinstance(
            self.building_code_context,
            BuildingCodeContext,
        ):
            raise TypeError(
                "building_code_context must be immutable BuildingCodeContext or None"
            )


@dataclass(frozen=True)
class MassAnalysis:
    project_id: str
    area: float
    floor_area: float
    floors: int
    edge_count: int
    street_edge_indices: list[int]
    access_edge_indices: list[int]
    bounds: tuple[float, float, float, float]
    building_code_context: BuildingCodeContext | None = None
