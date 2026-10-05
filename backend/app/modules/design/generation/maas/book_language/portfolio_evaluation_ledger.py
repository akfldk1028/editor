"""Run-local storage for complete MASS candidate evaluation evidence."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from backend.app.modules.design.generation.maas.book_language.portfolio_evaluation_contract import CandidateEvaluation, StageDecision


@dataclass
class _LedgerCandidate:
    candidate_id: str
    program_hash: str
    geometry_hash: str
    preview_path: str = ""
    lineage: dict[str, Any] = field(default_factory=dict)
    stages: dict[str, StageDecision] = field(default_factory=dict)
    selected: bool = False
    integrity_failures: tuple[str, ...] = ()
    finalized: bool = False

    def evidence(self) -> dict[str, Any]:
        evaluation = CandidateEvaluation(
            candidate_id=self.candidate_id,
            program_hash=self.program_hash,
            geometry_hash=self.geometry_hash,
            stages=self.stages,
            selected=self.selected,
            integrity_failures=self.integrity_failures,
        ).evidence()
        return {
            **evaluation,
            "preview_path": self.preview_path,
            "lineage": deepcopy(self.lineage),
            "finalized": self.finalized,
        }


class PortfolioEvaluationLedger:
    schema_version = "arr.maas.portfolio_evaluation_ledger.v1"

    def __init__(
        self,
        run_id: str,
        pnu: str,
        target_count: int,
        *,
        record_limit: int = 128,
    ) -> None:
        self.run_id = str(run_id or "").strip()
        self.pnu = str(pnu or "").strip()
        self.target_count = max(0, int(target_count))
        self.record_limit = max(0, int(record_limit))
        self._records: dict[str, _LedgerCandidate] = {}

    def begin_candidate(
        self,
        *,
        candidate_id: str,
        program_hash: str,
        geometry_hash: str,
        preview_path: str = "",
        lineage: dict[str, Any] | None = None,
    ) -> None:
        identity = (
            str(candidate_id or "").strip(),
            str(program_hash or "").strip(),
            str(geometry_hash or "").strip(),
        )
        if not identity[0]:
            raise ValueError("candidate_id is required")
        existing = self._records.get(identity[0])
        if existing is not None:
            if (
                existing.program_hash,
                existing.geometry_hash,
            ) != identity[1:]:
                raise ValueError(
                    f"candidate identity rebinding: {identity[0]}"
                )
            return
        self._records[identity[0]] = _LedgerCandidate(
            candidate_id=identity[0],
            program_hash=identity[1],
            geometry_hash=identity[2],
            preview_path=str(preview_path or "").strip(),
            lineage=deepcopy(dict(lineage or {})),
        )

    def record_stage(
        self,
        candidate_id: str,
        decision: StageDecision,
    ) -> None:
        record = self._require_candidate(candidate_id)
        if not isinstance(decision, StageDecision):
            raise TypeError("decision must be a StageDecision")
        record.stages[decision.stage] = decision

    def finalize_candidate(
        self,
        candidate_id: str,
        *,
        selected: bool = False,
        integrity_failures: tuple[str, ...] = (),
    ) -> None:
        record = self._require_candidate(candidate_id)
        record.selected = bool(selected)
        record.integrity_failures = tuple(integrity_failures)
        record.finalized = True

    def evidence(self) -> dict[str, Any]:
        all_records = [
            record.evidence()
            for record in self._records.values()
        ]
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "pnu": self.pnu,
            "target_count": self.target_count,
            "record_count": len(all_records),
            "records": deepcopy(all_records[:self.record_limit]),
            "records_truncated": len(all_records) > self.record_limit,
        }

    def _require_candidate(self, candidate_id: str) -> _LedgerCandidate:
        normalized = str(candidate_id or "").strip()
        try:
            return self._records[normalized]
        except KeyError as exc:
            raise KeyError(
                f"candidate not started: {normalized}"
            ) from exc


__all__ = ["PortfolioEvaluationLedger"]
