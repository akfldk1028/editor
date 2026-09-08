from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Literal

from backend.app.modules.building_quality import BuildingQualityReport
from backend.app.modules.generation_loop.contracts import ExteriorAllocationRequest
from backend.app.schemas.result import BuildingGenerationResult


@dataclass(frozen=True)
class GeneratorRepairAttempt:
    operator_id: str
    requests: tuple[ExteriorAllocationRequest, ...]
    outcome: Literal[
        "evaluated",
        "validation_rejected",
        "generation_failed",
    ]
    after_primary_daylight: tuple[tuple[int, float], ...]
    validation_codes: tuple[str, ...]
    error_type: str | None
    error_message: str | None

    def __post_init__(self) -> None:
        if self.operator_id != "primary_daylight_exterior_allocation/v1":
            raise ValueError("generator repair attempt operator_id is invalid")
        if (
            not isinstance(self.requests, tuple)
            or not self.requests
            or not all(
                isinstance(request, ExteriorAllocationRequest)
                for request in self.requests
            )
        ):
            raise TypeError("generator repair attempt requests are invalid")
        floor_indexes = tuple(request.floor_index for request in self.requests)
        if (
            floor_indexes != tuple(sorted(floor_indexes))
            or len(set(floor_indexes)) != len(floor_indexes)
        ):
            raise ValueError("generator repair attempt requests must be floor ordered")
        if self.outcome not in {
            "evaluated",
            "validation_rejected",
            "generation_failed",
        }:
            raise ValueError("generator repair attempt outcome is invalid")
        if not isinstance(self.after_primary_daylight, tuple):
            raise TypeError("generator repair attempt after evidence must be a tuple")
        after_indexes = tuple(
            floor_index for floor_index, _ in self.after_primary_daylight
        )
        if (
            after_indexes != tuple(sorted(after_indexes))
            or len(set(after_indexes)) != len(after_indexes)
            or any(
                not isinstance(floor_index, int)
                or isinstance(floor_index, bool)
                or floor_index < 1
                or not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                or not 0.0 <= value <= 1.0
                for floor_index, value in self.after_primary_daylight
            )
        ):
            raise ValueError("generator repair attempt after evidence is invalid")
        if (
            not isinstance(self.validation_codes, tuple)
            or self.validation_codes
            != tuple(sorted(set(self.validation_codes)))
            or any(
                not isinstance(code, str) or not code.strip()
                for code in self.validation_codes
            )
        ):
            raise ValueError("generator repair attempt validation codes are invalid")
        if self.outcome == "generation_failed":
            if self.after_primary_daylight or self.validation_codes:
                raise ValueError("failed generator repair cannot have after evidence")
            if any(
                not isinstance(value, str) or not value.strip()
                for value in (self.error_type, self.error_message)
            ):
                raise ValueError("failed generator repair requires typed error evidence")
            return
        if after_indexes != floor_indexes:
            raise ValueError(
                "generator repair attempt after evidence must cover requested floors"
            )
        if self.error_type is not None or self.error_message is not None:
            raise ValueError("completed generator repair cannot have error evidence")
        if self.outcome == "validation_rejected" and not self.validation_codes:
            raise ValueError("validation rejection requires validation codes")
        if self.outcome == "evaluated" and self.validation_codes:
            raise ValueError("evaluated generator repair cannot have validation codes")


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
    generator_repair_attempt: GeneratorRepairAttempt | None = None

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
        if self.generator_repair_attempt is not None and not isinstance(
            self.generator_repair_attempt,
            GeneratorRepairAttempt,
        ):
            raise TypeError("structural rejection generator repair attempt is invalid")
        attempt = self.generator_repair_attempt
        if attempt is None:
            if self.generator_repairs:
                raise ValueError("generator repairs require an evaluated repair attempt")
            if self.reason_type in {
                "GeneratorRepairFailed",
                "BuildingValidationRetryRejected",
            }:
                raise ValueError("repair rejection reason requires a repair attempt")
        else:
            expected_reason = {
                "generation_failed": "GeneratorRepairFailed",
                "validation_rejected": "BuildingValidationRetryRejected",
                "evaluated": "BuildingQualityRejected",
            }[attempt.outcome]
            if self.reason_type != expected_reason:
                raise ValueError(
                    "generator repair attempt outcome must match rejection reason"
                )
            if attempt.outcome == "generation_failed" and self.generator_repairs:
                raise ValueError(
                    "generation failed repair attempt cannot have generator repairs"
                )
            if attempt.outcome == "validation_rejected" and self.quality_report is None:
                raise ValueError(
                    "validation repair rejection requires a quality report"
                )
            if (
                attempt.outcome in {"evaluated", "validation_rejected"}
                and not self.generator_repairs
            ):
                raise ValueError(
                    f"{attempt.outcome} repair attempt requires generator repairs"
                )
        _validate_generator_repairs(
            self.generator_repairs,
            self.quality_report,
            attempt=attempt,
        )


def _validate_generator_repairs(
    repairs: tuple[GeneratorRepairProvenance, ...],
    quality_report: BuildingQualityReport | None,
    *,
    attempt: GeneratorRepairAttempt | None = None,
) -> None:
    if not isinstance(repairs, tuple) or not all(
        isinstance(repair, GeneratorRepairProvenance) for repair in repairs
    ):
        raise TypeError("generator repairs must be immutable provenance records")
    if repairs and quality_report is None:
        raise ValueError("generator repairs require a quality report")
    if attempt is not None and attempt.outcome in {
        "evaluated",
        "validation_rejected",
    }:
        if len(repairs) != len(attempt.requests):
            raise ValueError(
                f"generator repairs must exactly match {attempt.outcome} repair attempt"
            )
        after_by_floor = dict(attempt.after_primary_daylight)
        for repair, request in zip(repairs, attempt.requests, strict=True):
            if (
                repair.operator_id != attempt.operator_id
                or repair.floor_index != request.floor_index
                or repair.room_ids != request.room_ids
                or not math.isclose(
                    repair.after_value,
                    after_by_floor[request.floor_index],
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
            ):
                raise ValueError(
                    f"generator repairs must exactly match "
                    f"{attempt.outcome} repair attempt"
                )
    if quality_report is None:
        return
    floors_by_index = {floor.floor_index: floor for floor in quality_report.floors}
    validation_issues_by_floor = {
        issue.floor_index: issue
        for issue in quality_report.issues
        if issue.code == "primary_daylight_ratio" and issue.severity == "hard"
    }
    for repair in repairs:
        if repair.policy_version != quality_report.policy_version:
            raise ValueError("generator repair policy_version must match quality report")
        if attempt is not None and attempt.outcome == "validation_rejected":
            issue = validation_issues_by_floor.get(repair.floor_index)
            if (
                issue is None
                or issue.subject_id is None
                or issue.measured_value is None
                or issue.threshold is None
                or repair.issue_code != issue.code
                or repair.subject_id != issue.subject_id
                or not math.isclose(
                    repair.before_value,
                    issue.measured_value,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
                or not math.isclose(
                    repair.threshold,
                    issue.threshold,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
            ):
                raise ValueError(
                    "validation repair provenance requires its original "
                    "structured hard issue"
                )
            continue
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
