"""Adapt existing BOOK gate evidence into the portfolio evaluation ledger."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from backend.app.modules.design.generation.maas.book_language.portfolio_evaluation_contract import EVALUATION_STAGES, StageDecision
from backend.app.modules.design.generation.maas.book_language.portfolio_evaluation_ledger import PortfolioEvaluationLedger


_PASS_STATUSES = frozenset({"pass", "passed", "accepted", "selected"})
_FAIL_STATUSES = frozenset({"fail", "failed", "rejected"})
_NOT_EVALUATED_STATUSES = frozenset({
    "",
    "not_evaluated",
    "not_requested",
    "not_run",
    "skipped",
})
_REASON_KEYS = (
    "failure_reasons",
    "failures",
    "reasons",
    "geometry_failure_reasons",
    "legal_failure_reasons",
    "parking_failure_reasons",
    "capacity_failure_reasons",
    "program_failure_reasons",
)


@dataclass(frozen=True)
class PortfolioEvaluationInput:
    candidate_id: str
    program_hash: str
    geometry_hash: str
    gate_evidence: Mapping[str, Mapping[str, Any]] = field(
        default_factory=dict
    )
    preview_path: str = ""
    lineage: Mapping[str, Any] = field(default_factory=dict)
    selected: bool = False
    integrity_failures: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "gate_evidence",
            deepcopy({
                str(stage): dict(evidence)
                for stage, evidence in self.gate_evidence.items()
            }),
        )
        object.__setattr__(self, "lineage", deepcopy(dict(self.lineage)))


def book_candidate_evaluation_input(
    *,
    candidate_id: str,
    program_hash: str,
    geometry_hash: str,
    metadata: Mapping[str, Any],
    downstream_row: Mapping[str, Any] | None,
    selected: bool,
    selection_reasons: tuple[str, ...] = (),
    lineage: Mapping[str, Any] | None = None,
    preview_path: str = "",
) -> PortfolioEvaluationInput:
    """Bind existing BOOK metadata and downstream rows to typed stages."""

    row = deepcopy(dict(downstream_row or {}))
    source_metadata = deepcopy(dict(metadata or {}))
    legal = deepcopy(dict(row.get("legal_projection") or {}))
    geometry = deepcopy(legal)
    if "geometry_retention_pass" in geometry:
        geometry["hard_pass"] = bool(
            geometry.get("geometry_retention_pass")
        )
    elif not geometry:
        compilation = deepcopy(dict(
            source_metadata.get("geometry_program_compilation") or {}
        ))
        if compilation:
            geometry = compilation
            geometry["hard_pass"] = not bool(
                compilation.get("issues")
            )
    capacity = deepcopy(dict(row.get("capacity_hard_gate") or {}))
    parking = deepcopy(dict(row.get("parking_hard_gate") or {}))
    program = deepcopy(dict(
        source_metadata.get("program_gate_result") or {}
    ))
    semantic = deepcopy(dict(
        row.get("semantic_projection_hard_gate") or {}
    ))
    if semantic:
        program["semantic_projection_hard_gate"] = semantic
        if "hard_pass" in program and "hard_pass" in semantic:
            program["hard_pass"] = bool(
                program.get("hard_pass")
                and semantic.get("hard_pass")
            )
    selection = {
        "status": "selected" if selected else "rejected",
        "failure_reasons": list(selection_reasons),
    }
    vlm = deepcopy(dict(
        source_metadata.get("final_book_vlm_audit") or {}
    ))
    candidate_image = (
        (vlm.get("vlm_image_inputs") or {}).get("candidate") or {}
        if isinstance(vlm.get("vlm_image_inputs"), dict)
        else {}
    )
    resolved_preview_path = str(
        preview_path
        or (
            candidate_image.get("local_path")
            if isinstance(candidate_image, dict)
            else ""
        )
        or ""
    ).strip()
    return PortfolioEvaluationInput(
        candidate_id=candidate_id,
        program_hash=program_hash,
        geometry_hash=geometry_hash,
        preview_path=resolved_preview_path,
        lineage=dict(lineage or {}),
        gate_evidence={
            "geometry": geometry,
            "law": legal,
            "capacity": capacity,
            "parking": parking,
            "program": program,
            "vlm": vlm,
            "selection": selection,
        },
        selected=selected,
    )


def _gate_status(
    stage: str,
    evidence: Mapping[str, Any],
    *,
    selected: bool,
) -> str:
    if stage == "selection" and selected:
        return "pass"
    if not evidence:
        return "not_evaluated"
    status = str(evidence.get("status") or "").strip().lower()
    if status in _PASS_STATUSES:
        return "pass"
    if status in _FAIL_STATUSES:
        return "fail"
    if status in _NOT_EVALUATED_STATUSES and "hard_pass" not in evidence:
        return "not_evaluated"
    hard_pass = evidence.get("hard_pass")
    if hard_pass is True:
        return "pass"
    if hard_pass is False:
        return "fail"
    return "not_evaluated"


def _gate_reasons(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    reasons: list[str] = []
    for key in _REASON_KEYS:
        values = evidence.get(key) or ()
        if isinstance(values, str):
            values = (values,)
        for value in values:
            reason = str(value or "").strip()
            if reason and reason not in reasons:
                reasons.append(reason)
    return tuple(reasons)


def build_portfolio_evaluation_ledger(
    *,
    run_id: str,
    pnu: str,
    target_count: int,
    candidates: Iterable[PortfolioEvaluationInput],
) -> PortfolioEvaluationLedger:
    """Copy existing gate outcomes without changing their decisions."""

    ledger = PortfolioEvaluationLedger(
        run_id=run_id,
        pnu=pnu,
        target_count=target_count,
    )
    for candidate in candidates:
        ledger.begin_candidate(
            candidate_id=candidate.candidate_id,
            program_hash=candidate.program_hash,
            geometry_hash=candidate.geometry_hash,
            preview_path=candidate.preview_path,
            lineage=dict(candidate.lineage),
        )
        for stage in EVALUATION_STAGES:
            evidence = deepcopy(dict(
                candidate.gate_evidence.get(stage) or {}
            ))
            ledger.record_stage(
                candidate.candidate_id,
                StageDecision(
                    stage=stage,
                    status=_gate_status(
                        stage,
                        evidence,
                        selected=candidate.selected,
                    ),
                    reasons=_gate_reasons(evidence),
                    evidence=evidence,
                ),
            )
        ledger.finalize_candidate(
            candidate.candidate_id,
            selected=candidate.selected,
            integrity_failures=candidate.integrity_failures,
        )
    return ledger


__all__ = [
    "PortfolioEvaluationInput",
    "book_candidate_evaluation_input",
    "build_portfolio_evaluation_ledger",
]
