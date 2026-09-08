from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math
from typing import Literal

Point = tuple[float, float]
OccupancyCategory = Literal[
    "neighborhood_assembly_or_religious_meeting_300",
    "assembly_religious_bar_funeral_200",
    "sales_and_similar",
    "multi_unit_housing_over_4_units_per_floor",
    "officetel",
    "other_supported",
]
TravelConstructionClass = Literal[
    "fire_resistant_or_noncombustible",
    "not_qualified",
]
TravelLimitClassification = Literal[
    "general_30",
    "qualified_50",
    "highrise_residential_40",
]
_OCCUPANCY_CATEGORIES = {
    "neighborhood_assembly_or_religious_meeting_300",
    "assembly_religious_bar_funeral_200",
    "sales_and_similar",
    "multi_unit_housing_over_4_units_per_floor",
    "officetel",
    "other_supported",
}
_TRAVEL_CONSTRUCTION_CLASSES = {
    "fire_resistant_or_noncombustible",
    "not_qualified",
}
_TRAVEL_LIMIT_CLASSIFICATIONS = {
    "general_30",
    "qualified_50",
    "highrise_residential_40",
}


@dataclass(frozen=True)
class FloorFootprint:
    floor_index: int
    footprint_polygon: tuple[Point, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.floor_index, int)
            or isinstance(self.floor_index, bool)
            or self.floor_index < 1
        ):
            raise ValueError("floor_index must be a positive integer")
        if len(self.footprint_polygon) < 3:
            raise ValueError("floor footprint polygon needs at least 3 points")
        normalized: list[Point] = []
        for point in self.footprint_polygon:
            if not isinstance(point, (tuple, list)) or len(point) != 2:
                raise TypeError("floor footprint points must be coordinate pairs")
            x, y = point
            if any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(float(value))
                for value in (x, y)
            ):
                raise ValueError("floor footprint coordinates must be finite")
            normalized.append((float(x), float(y)))
        object.__setattr__(self, "footprint_polygon", tuple(normalized))


@dataclass(frozen=True)
class FloorCodeContext:
    floor_index: int
    occupancy: str | None = None
    occupant_load: int | None = None
    above_grade: bool | None = None
    occupancy_category: OccupancyCategory | None = None
    story_number: int | None = None
    habitable_area_m2: float | None = None
    is_evacuation_floor: bool | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.floor_index, int)
            or isinstance(self.floor_index, bool)
            or self.floor_index < 1
        ):
            raise ValueError("floor_index must be a positive integer")
        if self.occupancy is not None and (
            not isinstance(self.occupancy, str) or not self.occupancy.strip()
        ):
            raise TypeError("occupancy must be a non-empty string or None")
        if self.occupant_load is not None and (
            not isinstance(self.occupant_load, int)
            or isinstance(self.occupant_load, bool)
            or self.occupant_load < 1
        ):
            raise ValueError("occupant_load must be a positive integer or None")
        if self.above_grade is not None and not isinstance(self.above_grade, bool):
            raise TypeError("above_grade must be bool or None")
        if self.is_evacuation_floor is not None and not isinstance(
            self.is_evacuation_floor, bool
        ):
            raise TypeError("is_evacuation_floor must be bool or None")
        if (
            self.occupancy_category is not None
            and self.occupancy_category not in _OCCUPANCY_CATEGORIES
        ):
            raise ValueError("occupancy_category is not supported")
        if self.story_number is not None and (
            not isinstance(self.story_number, int)
            or isinstance(self.story_number, bool)
            or self.story_number < 1
        ):
            raise ValueError("story_number must be a positive integer or None")
        if self.above_grade is False and self.story_number is not None:
            raise ValueError("basement floor must not supply story_number")
        area = self.habitable_area_m2
        if area is not None and (
            not isinstance(area, (int, float))
            or isinstance(area, bool)
            or not math.isfinite(float(area))
            or float(area) < 0
        ):
            raise ValueError("habitable_area_m2 must be finite and nonnegative or None")


@dataclass(frozen=True)
class BuildingCodeContext:
    jurisdiction: str | None = None
    effective_date: str | None = None  # analysis as-of date, not source date
    floor_to_floor_height_m: float | None = None
    sprinklered: bool | None = None
    fire_resistant: bool | None = None
    qualifying_sprinkler_protection: bool | None = None
    travel_construction_class: TravelConstructionClass | None = None
    travel_limit_classification: TravelLimitClassification | None = None
    floor_facts: tuple[FloorCodeContext, ...] = ()

    def __post_init__(self) -> None:
        for name in ("jurisdiction", "effective_date"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
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
        for name in (
            "sprinklered",
            "fire_resistant",
            "qualifying_sprinkler_protection",
        ):
            value = getattr(self, name)
            if value is not None and not isinstance(value, bool):
                raise TypeError(f"{name} must be bool or None")
        if (
            self.travel_construction_class is not None
            and self.travel_construction_class not in _TRAVEL_CONSTRUCTION_CLASSES
        ):
            raise ValueError("travel_construction_class is not supported")
        if (
            self.travel_limit_classification is not None
            and self.travel_limit_classification not in _TRAVEL_LIMIT_CLASSIFICATIONS
        ):
            raise ValueError("travel_limit_classification is not supported")
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
    floor_footprints: tuple[FloorFootprint, ...] = ()

    def __post_init__(self) -> None:
        if self.building_code_context is not None and not isinstance(
            self.building_code_context,
            BuildingCodeContext,
        ):
            raise TypeError(
                "building_code_context must be immutable BuildingCodeContext or None"
            )
        if self.building_code_context is not None:
            outside = [
                fact.floor_index
                for fact in self.building_code_context.floor_facts
                if fact.floor_index > self.floors
            ]
            if outside:
                raise ValueError(
                    "building_code_context floor facts outside supplied floors: "
                    + ", ".join(str(index) for index in outside)
                )
        if not isinstance(self.floor_footprints, tuple) or any(
            not isinstance(footprint, FloorFootprint)
            for footprint in self.floor_footprints
        ):
            raise TypeError("floor_footprints must be a tuple of FloorFootprint")
        floor_indices = [footprint.floor_index for footprint in self.floor_footprints]
        if len(set(floor_indices)) != len(floor_indices):
            raise ValueError("floor_footprints floor_index values must be unique")
        outside = [
            floor_index for floor_index in floor_indices if floor_index > self.floors
        ]
        if outside:
            raise ValueError(
                "floor_footprints outside supplied floors: "
                + ", ".join(str(index) for index in outside)
            )
        if self.floor_footprints:
            expected = set(range(1, self.floors + 1))
            supplied = set(floor_indices)
            if supplied != expected:
                missing = sorted(expected - supplied)
                raise ValueError(
                    "floor_footprints must cover every supplied floor; missing: "
                    + ", ".join(str(index) for index in missing)
                )

    def footprint_for_floor(self, floor_index: int) -> tuple[Point, ...]:
        if (
            not isinstance(floor_index, int)
            or isinstance(floor_index, bool)
            or floor_index < 1
            or floor_index > self.floors
        ):
            raise ValueError("floor_index must be inside supplied floor range")
        override = next(
            (
                footprint
                for footprint in self.floor_footprints
                if footprint.floor_index == floor_index
            ),
            None,
        )
        if override is not None:
            return override.footprint_polygon
        if self.floor_footprints:
            raise ValueError(f"floor_footprints has no record for floor {floor_index}")
        return tuple((float(x), float(y)) for x, y in self.footprint_polygon)


@dataclass(frozen=True)
class FloorPlateAnalysis:
    floor_index: int
    area: float
    edge_count: int
    bounds: tuple[float, float, float, float]
    footprint_polygon: tuple[Point, ...]
    source: str


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
    floor_plates: tuple[FloorPlateAnalysis, ...] = ()

    def floor_plate(self, floor_index: int) -> FloorPlateAnalysis:
        if floor_index < 1 or floor_index > self.floors:
            raise ValueError("floor_index must be inside analyzed floor range")
        if self.floor_plates:
            return next(
                plate for plate in self.floor_plates if plate.floor_index == floor_index
            )
        return FloorPlateAnalysis(
            floor_index=floor_index,
            area=self.area,
            edge_count=self.edge_count,
            bounds=self.bounds,
            footprint_polygon=(),
            source="legacy_mass_analysis",
        )

    def area_for_floor(self, floor_index: int) -> float:
        return self.floor_plate(floor_index).area

    def bounds_for_floor(
        self,
        floor_index: int,
    ) -> tuple[float, float, float, float]:
        return self.floor_plate(floor_index).bounds

    def boundary_for_floor(self, floor_index: int) -> tuple[Point, ...]:
        plate = self.floor_plate(floor_index)
        if plate.footprint_polygon:
            return plate.footprint_polygon
        min_x, min_y, max_x, max_y = plate.bounds
        return (
            (min_x, min_y),
            (max_x, min_y),
            (max_x, max_y),
            (min_x, max_y),
        )
