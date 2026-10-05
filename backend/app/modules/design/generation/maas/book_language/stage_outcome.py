"""Typed, exact-once evidence for candidate generation stage transitions."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Generic, Literal, Mapping, MutableMapping, TypeVar


T = TypeVar("T")
StageOutcomeKind = Literal["passed", "failed", "diagnostic"]
CounterUpdate = tuple[MutableMapping[str, int], str]


@dataclass(frozen=True)
class StageOutcome(Generic[T]):
    stage: str
    kind: StageOutcomeKind
    reason: str
    evidence: Mapping[str, Any]
    value: T | None = None

    def __post_init__(self) -> None:
        if not str(self.stage).strip():
            raise ValueError("stage outcome requires a stage")
        if self.kind not in {"passed", "failed", "diagnostic"}:
            raise ValueError("invalid stage outcome kind")
        if not isinstance(self.evidence, Mapping) or not self.evidence:
            raise ValueError("stage outcome requires evidence")
        if self.kind == "passed" and self.reason:
            raise ValueError("passed stage outcome cannot carry a failure reason")
        if self.kind in {"failed", "diagnostic"} and not str(self.reason).strip():
            raise ValueError(f"{self.kind} stage outcome requires a reason")
        if self.kind == "failed" and self.value is not None:
            raise ValueError("failed stage outcome cannot carry a continuing value")
        object.__setattr__(
            self,
            "evidence",
            MappingProxyType(deepcopy(dict(self.evidence))),
        )

    @classmethod
    def passed(
        cls,
        stage: str,
        *,
        evidence: Mapping[str, Any],
        value: T | None = None,
    ) -> "StageOutcome[T]":
        return cls(stage=stage, kind="passed", reason="", evidence=evidence, value=value)

    @classmethod
    def failed(
        cls,
        stage: str,
        reason: str,
        *,
        evidence: Mapping[str, Any],
    ) -> "StageOutcome[T]":
        return cls(stage=stage, kind="failed", reason=reason, evidence=evidence)

    @classmethod
    def diagnostic(
        cls,
        stage: str,
        reason: str,
        *,
        evidence: Mapping[str, Any],
        value: T | None = None,
    ) -> "StageOutcome[T]":
        return cls(
            stage=stage,
            kind="diagnostic",
            reason=reason,
            evidence=evidence,
            value=value,
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "schema_version": "arr.maas.stage_outcome.v1",
            "stage": self.stage,
            "kind": self.kind,
            "reason": self.reason,
            "evidence": deepcopy(dict(self.evidence)),
        }


def record_stage_outcome(
    outcome: StageOutcome[Any],
    *,
    records: list[dict[str, Any]],
    counter_updates: tuple[CounterUpdate, ...] = (),
    terminal_recorder: Callable[[StageOutcome[Any]], None] | None = None,
) -> None:
    """Persist one outcome, its legacy counters, and failed terminal evidence."""

    if outcome.kind == "failed" and terminal_recorder is None:
        raise ValueError("failed stage outcome requires a terminal recorder")
    seen_updates: set[tuple[int, str]] = set()
    for counters, key in counter_updates:
        identity = (id(counters), str(key))
        if identity in seen_updates:
            raise ValueError("duplicate counter update in one stage outcome")
        seen_updates.add(identity)
    records.append(outcome.to_record())
    for counters, key in counter_updates:
        counters[key] = counters.get(key, 0) + 1
    if outcome.kind == "failed":
        terminal_recorder(outcome)
