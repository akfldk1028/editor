from __future__ import annotations

from backend.app.schemas.loop import CandidateRecord


def rank_candidate(record: CandidateRecord) -> tuple:
    report = record.validation
    return (
        0 if report.accepted else 1,
        report.hard_violation_count,
        report.violation_score,
        -report.total_score,
        record.fingerprint,
    )


def select_frontier(
    records: list[CandidateRecord],
    beam_width: int,
) -> list[CandidateRecord]:
    return sorted(records, key=rank_candidate)[:beam_width]
