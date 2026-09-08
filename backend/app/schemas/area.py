from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal

Point = tuple[float, float]
AreaBucket = Literal[
    "gross",
    "core",
    "circulation",
    "remote_stair",
    "service",
    "primary",
    "net",
    "unassigned",
]
AreaStatus = Literal["pass", "fail", "not_checked"]
AreaMethod = Literal["polygon_union", "derived_sum", "residual"]

AREA_BUCKETS: tuple[AreaBucket, ...] = (
    "gross",
    "core",
    "circulation",
    "remote_stair",
    "service",
    "primary",
    "net",
    "unassigned",
)
MIN_AREA_TOLERANCE_M2 = 1e-6
MAX_AREA_TOLERANCE_M2 = 1.0


@dataclass(frozen=True)
class AreaGeometry:
    source_id: str
    polygon: tuple[Point, ...]
    holes: tuple[tuple[Point, ...], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, str) or not self.source_id.strip():
            raise ValueError("area geometry source_id must be non-empty")
        if not isinstance(self.polygon, tuple):
            raise TypeError("area geometry polygon must be an immutable tuple")
        if not isinstance(self.holes, tuple) or any(
            not isinstance(hole, tuple) for hole in self.holes
        ):
            raise TypeError("area geometry holes must be immutable tuples")


@dataclass(frozen=True)
class AreaProvenance:
    method: AreaMethod
    source_ids: tuple[str, ...]
    classification_rule: str
    formula: str

    def __post_init__(self) -> None:
        if self.method not in {"polygon_union", "derived_sum", "residual"}:
            raise ValueError("area provenance method is invalid")
        if not isinstance(self.source_ids, tuple) or any(
            not isinstance(source_id, str) or not source_id.strip()
            for source_id in self.source_ids
        ):
            raise TypeError(
                "area provenance source_ids must be immutable non-empty strings"
            )
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("area provenance source_ids must be unique")
        for name in ("classification_rule", "formula"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"area provenance {name} must be non-empty")


@dataclass(frozen=True)
class AreaLedgerEntry:
    bucket: AreaBucket
    area_m2: float | None
    provenance: AreaProvenance

    def __post_init__(self) -> None:
        if self.bucket not in AREA_BUCKETS:
            raise ValueError("area ledger bucket is invalid")
        if self.area_m2 is not None and (
            not isinstance(self.area_m2, (int, float))
            or isinstance(self.area_m2, bool)
            or not math.isfinite(self.area_m2)
            or self.area_m2 < 0
        ):
            raise ValueError("area_m2 must be finite, nonnegative, or None")
        if not isinstance(self.provenance, AreaProvenance):
            raise TypeError("area ledger provenance must be typed")


@dataclass(frozen=True)
class FloorAreaLedger:
    floor_index: int
    status: AreaStatus
    entries: tuple[AreaLedgerEntry, ...]
    overlap_area_m2: float
    out_of_boundary_area_m2: float
    tolerance_m2: float
    unresolved_facts: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.floor_index, int)
            or isinstance(self.floor_index, bool)
            or self.floor_index < 1
        ):
            raise ValueError("floor_index must be a positive integer")
        if self.status not in {"pass", "fail", "not_checked"}:
            raise ValueError("floor area ledger status is invalid")
        _validate_entries(self.entries, "floor")
        for name in (
            "overlap_area_m2",
            "out_of_boundary_area_m2",
            "tolerance_m2",
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(f"{name} must be finite and nonnegative")
        if not (
            MIN_AREA_TOLERANCE_M2
            <= self.tolerance_m2
            <= MAX_AREA_TOLERANCE_M2
        ):
            raise ValueError(
                "tolerance_m2 must be within the supported architectural "
                f"range [{MIN_AREA_TOLERANCE_M2}, {MAX_AREA_TOLERANCE_M2}]"
            )
        _validate_unresolved(self.unresolved_facts)
        values = tuple(entry.area_m2 for entry in self.entries)
        if self.status == "not_checked" and any(value is not None for value in values):
            raise ValueError("not_checked floor entries must not fabricate areas")
        if self.status != "not_checked" and any(value is None for value in values):
            raise ValueError("checked floor entries require measured areas")


@dataclass(frozen=True)
class BuildingAreaLedger:
    floors: tuple[FloorAreaLedger, ...]
    totals: tuple[AreaLedgerEntry, ...]
    status: AreaStatus

    def __post_init__(self) -> None:
        if not isinstance(self.floors, tuple) or not self.floors:
            raise ValueError("building area ledger requires floors")
        if not all(isinstance(floor, FloorAreaLedger) for floor in self.floors):
            raise TypeError("building area ledger floors must be typed")
        indexes = tuple(floor.floor_index for floor in self.floors)
        if indexes != tuple(sorted(set(indexes))):
            raise ValueError("building floor indexes must be unique and sorted")
        if indexes != tuple(range(1, indexes[-1] + 1)):
            raise ValueError(
                "building floor indexes must be consecutive from floor 1"
            )
        _validate_entries(self.totals, "building total")
        if self.status not in {"pass", "fail", "not_checked"}:
            raise ValueError("building area ledger status is invalid")


def _validate_entries(
    entries: tuple[AreaLedgerEntry, ...],
    label: str,
) -> None:
    if not isinstance(entries, tuple) or not all(
        isinstance(entry, AreaLedgerEntry) for entry in entries
    ):
        raise TypeError(f"{label} area entries must be an immutable typed tuple")
    if tuple(entry.bucket for entry in entries) != AREA_BUCKETS:
        raise ValueError(f"{label} area entries must expose all eight buckets")


def _validate_unresolved(values: tuple[str, ...]) -> None:
    if not isinstance(values, tuple) or any(
        not isinstance(value, str) or not value.strip() for value in values
    ):
        raise TypeError("unresolved_facts must be immutable non-empty strings")
    if len(set(values)) != len(values):
        raise ValueError("unresolved_facts must be unique")
