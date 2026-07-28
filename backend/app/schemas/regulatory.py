from __future__ import annotations

from dataclasses import dataclass
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
class RegulatoryCheck:
    rule_id: str
    status: RegulatoryStatus
    source_url: str
    effective_date: str
    measured_value: RegulatoryValue
    threshold: RegulatoryValue
    applicability: bool | None
    assumptions: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise ValueError("rule_id must not be empty")
        _validate_status(self.status)
        if not self.source_url.strip():
            raise ValueError("source_url must not be empty")
        if not self.effective_date.strip():
            raise ValueError("effective_date must not be empty")
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
