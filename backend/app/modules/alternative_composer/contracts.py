from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

from backend.app.modules.building_quality import BuildingQualityReport
from backend.app.schemas.result import BuildingGenerationResult


@dataclass(frozen=True)
class GeneratorRepairProvenance:
    operator_id: str
    issue_code: str
    policy_version: str
    floor_index: int
    subject_id: str
    room_ids: tuple[str, ...]
    before_value: float
    threshold: float
    after_value: float

    def __post_init__(self) -> None:
        if self.operator_id != "primary_daylight_exterior_allocation/v1":
            raise ValueError("generator repair operator_id is invalid")
        if self.issue_code != "primary_daylight_ratio":
            raise ValueError("generator repair issue_code is invalid")
        if not isinstance(self.policy_version, str) or not self.policy_version.strip():
            raise ValueError("generator repair policy_version must be non-empty")
        if not isinstance(self.subject_id, str) or not self.subject_id.strip():
            raise ValueError("generator repair subject_id must be non-empty")
        if (
            not isinstance(self.floor_index, int)
            or isinstance(self.floor_index, bool)
            or self.floor_index < 1
        ):
            raise ValueError("generator repair floor_index must be positive")
        if (
            not isinstance(self.room_ids, tuple)
            or not self.room_ids
            or any(not isinstance(room_id, str) or not room_id.strip() for room_id in self.room_ids)
            or self.room_ids != tuple(sorted(set(self.room_ids)))
        ):
            raise ValueError("generator repair room_ids must be sorted and unique")
        for name, value in (
            ("before_value", self.before_value),
            ("threshold", self.threshold),
            ("after_value", self.after_value),
        ):
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                or not 0.0 <= value <= 1.0
            ):
                raise ValueError(f"generator repair {name} must be finite and in [0, 1]")


@dataclass(frozen=True)
class StructuralAlternative:
    strategy: str
    building: BuildingGenerationResult
    quality_report: BuildingQualityReport
    core_fingerprint: str
    circulation_fingerprint: str
    room_fingerprint: str
    structural_fingerprint: str
    generator_repairs: tuple[GeneratorRepairProvenance, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.strategy, str) or not self.strategy.strip():
            raise ValueError("structural alternative strategy must be non-empty")
        if not isinstance(self.building, BuildingGenerationResult):
            raise TypeError("structural alternative building is invalid")
        if not isinstance(self.quality_report, BuildingQualityReport):
            raise TypeError("structural alternative quality report is invalid")
        if not self.quality_report.hard_pass:
            raise ValueError("structural alternative quality report must hard-pass")
        components = (
            self.core_fingerprint,
            self.circulation_fingerprint,
            self.room_fingerprint,
        )
        if any(not _is_sha256(value) for value in components):
            raise ValueError("structural component fingerprints must be SHA-256")
        expected = hashlib.sha256(":".join(components).encode()).hexdigest()
        if self.structural_fingerprint != expected:
            raise ValueError("structural fingerprint must match its components")
        _validate_generator_repairs(self.generator_repairs, self.quality_report)


@dataclass(frozen=True)
class StructuralAlternativeRejection:
    strategy: str
    reason_type: str
    reason: str
    quality_report: BuildingQualityReport | None = None
    generator_repairs: tuple[GeneratorRepairProvenance, ...] = ()

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (self.strategy, self.reason_type, self.reason)
        ):
            raise ValueError("structural rejection fields must be non-empty")
        if self.quality_report is not None and not isinstance(
            self.quality_report, BuildingQualityReport
        ):
            raise TypeError("structural rejection quality report is invalid")
        if (
            self.reason_type == "BuildingQualityRejected"
            and self.quality_report is None
        ):
            raise ValueError("building quality rejection requires a quality report")
        _validate_generator_repairs(self.generator_repairs, self.quality_report)


def _validate_generator_repairs(
    repairs: tuple[GeneratorRepairProvenance, ...],
    quality_report: BuildingQualityReport | None,
) -> None:
    if not isinstance(repairs, tuple) or not all(
        isinstance(repair, GeneratorRepairProvenance) for repair in repairs
    ):
        raise TypeError("generator repairs must be immutable provenance records")
    if repairs and quality_report is None:
        raise ValueError("generator repairs require a quality report")
    if quality_report is None:
        return
    floors_by_index = {floor.floor_index: floor for floor in quality_report.floors}
    for repair in repairs:
        if repair.policy_version != quality_report.policy_version:
            raise ValueError("generator repair policy_version must match quality report")
        floor = floors_by_index.get(repair.floor_index)
        if floor is None:
            raise ValueError("generator repair floor_index must match quality report")
        if not math.isclose(
            repair.after_value,
            floor.primary_daylight_ratio,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("generator repair after_value must match quality report")


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
