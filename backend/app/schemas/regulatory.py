from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math
from typing import Literal

RegulatoryStatus = Literal["pass", "fail", "not_checked"]
RegulatoryValue = bool | float | int | str | None
_VALID_STATUSES = {"pass", "fail", "not_checked"}


def _validate_status(status: str) -> None:
    if status not in _VALID_STATUSES:
        raise ValueError("regulatory status must be pass, fail, or not_checked")


def _validate_value(value: RegulatoryValue, name: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{name} must be a finite JSON scalar or None")
    if value is not None and not isinstance(value, (bool, int, float, str)):
        raise TypeError(f"{name} must be a JSON scalar or None")


@dataclass(frozen=True)
class ExitSeparationEvidence:
    nearest_doorway_segment_distance_m: float | None
    connected_passage_verified: bool | None
    exit_portal_ids: tuple[str, ...] = ()
    measurement_method: str = "nearest-doorway-segment-distance"

    def __post_init__(self) -> None:
        distance = self.nearest_doorway_segment_distance_m
        if distance is not None and (
            not isinstance(distance, (int, float))
            or isinstance(distance, bool)
            or not math.isfinite(float(distance))
            or float(distance) < 0
        ):
            raise ValueError(
                "nearest doorway distance must be finite and nonnegative or None"
            )
        if (
            self.connected_passage_verified is not None
            and not isinstance(self.connected_passage_verified, bool)
        ):
            raise TypeError(
                "connected_passage_verified must be bool or None"
            )
        if not isinstance(self.exit_portal_ids, tuple) or any(
            not isinstance(exit_id, str) or not exit_id.strip()
            for exit_id in self.exit_portal_ids
        ):
            raise TypeError(
                "exit_portal_ids must be a tuple of non-empty strings"
            )
        if len(set(self.exit_portal_ids)) != len(self.exit_portal_ids):
            raise ValueError("exit_portal_ids must be unique")
        if distance is not None and len(self.exit_portal_ids) != 2:
            raise ValueError(
                "measured doorway separation requires exactly two exit portals"
            )
        if self.measurement_method != "nearest-doorway-segment-distance":
            raise ValueError("unsupported exit-separation measurement method")


@dataclass(frozen=True)
class RegulatoryCheck:
    rule_id: str
    status: RegulatoryStatus
    source_url: str
    effective_date: str
    measured_value: RegulatoryValue
    threshold: RegulatoryValue
    applicability: bool | None
    assumptions: tuple[str, ...]
    source_effective_date: str | None = None

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise ValueError("rule_id must not be empty")
        _validate_status(self.status)
        if not self.source_url.strip():
            raise ValueError("source_url must not be empty")
        if not self.effective_date.strip():
            raise ValueError("effective_date must not be empty")
        if self.source_effective_date is None:
            object.__setattr__(
                self,
                "source_effective_date",
                self.effective_date,
            )
        elif (
            not isinstance(self.source_effective_date, str)
            or not self.source_effective_date.strip()
        ):
            raise ValueError("source_effective_date must not be empty")
        elif self.source_effective_date != self.effective_date:
            raise ValueError(
                "source_effective_date must match legacy effective_date"
            )
        _validate_value(self.measured_value, "measured_value")
        _validate_value(self.threshold, "threshold")
        if self.applicability is not None and not isinstance(
            self.applicability,
            bool,
        ):
            raise TypeError("applicability must be bool or None")
        if not isinstance(self.assumptions, tuple) or any(
            not isinstance(item, str) or not item
            for item in self.assumptions
        ):
            raise TypeError("assumptions must be a tuple of non-empty strings")


@dataclass(frozen=True)
class RegulatoryScreening:
    ruleset_id: str
    status: RegulatoryStatus
    checks: tuple[RegulatoryCheck, ...]
    unresolved_facts: tuple[str, ...] = ()
    floor_index: int | None = None
    generated_direct_stair_count: int | None = None
    verified_direct_stair_count: int | None = None
    screened_required_direct_stair_count: int | None = None
    analysis_as_of_date: str | None = None
    exit_separation_evidence: ExitSeparationEvidence | None = None

    def __post_init__(self) -> None:
        if not self.ruleset_id.strip():
            raise ValueError("ruleset_id must not be empty")
        _validate_status(self.status)
        if not isinstance(self.checks, tuple) or any(
            not isinstance(check, RegulatoryCheck) for check in self.checks
        ):
            raise TypeError("checks must be a tuple of RegulatoryCheck")
        if not isinstance(self.unresolved_facts, tuple) or any(
            not isinstance(item, str) or not item
            for item in self.unresolved_facts
        ):
            raise TypeError(
                "unresolved_facts must be a tuple of non-empty strings"
            )
        if self.floor_index is not None and (
            not isinstance(self.floor_index, int)
            or isinstance(self.floor_index, bool)
            or self.floor_index < 1
        ):
            raise ValueError("floor_index must be a positive integer or None")
        for name in (
            "generated_direct_stair_count",
            "verified_direct_stair_count",
            "screened_required_direct_stair_count",
        ):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
            ):
                raise ValueError(f"{name} must be a nonnegative integer or None")
        if self.screened_required_direct_stair_count not in {None, 1, 2}:
            raise ValueError(
                "screened_required_direct_stair_count must be 1, 2, or None"
            )
        if self.analysis_as_of_date is not None:
            if (
                not isinstance(self.analysis_as_of_date, str)
                or not self.analysis_as_of_date.strip()
            ):
                raise TypeError(
                    "analysis_as_of_date must be a non-empty string or None"
                )
            try:
                date.fromisoformat(self.analysis_as_of_date)
            except ValueError as error:
                raise ValueError(
                    "analysis_as_of_date must use ISO YYYY-MM-DD"
                ) from error
        if self.exit_separation_evidence is not None and not isinstance(
            self.exit_separation_evidence,
            ExitSeparationEvidence,
        ):
            raise TypeError(
                "exit_separation_evidence must be ExitSeparationEvidence or None"
            )
        if self.status == "pass" and (
            not self.checks
            or any(check.status != "pass" for check in self.checks)
            or self.unresolved_facts
        ):
            raise ValueError(
                "regulatory screening pass requires all checks to pass "
                "and no unresolved facts"
            )
        if self.status == "fail" and not any(
            check.status == "fail" for check in self.checks
        ):
            raise ValueError(
                "regulatory screening fail requires at least one failed check"
            )
