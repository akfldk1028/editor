"""Cache-first supply coordination for pre-legal creative programs."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from backend.app.modules.design.generation.maas.creative_program_author import CreativeAuthoredProgram, normalize_authored_programs
from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.llm_adapter import GeometryAuthorError


FreshAuthor = Callable[[int, int], Iterable[GeometryProgram]]
RetainedCount = Callable[[tuple[CreativeAuthoredProgram, ...]], int]


@dataclass(frozen=True)
class CreativeAuthorAttempt:
    attempt_index: int
    source: str
    status: str
    requested_count: int
    returned_count: int
    provider_executed: bool
    http_status: int | None = None
    category: str = ""

    def evidence(self) -> dict[str, Any]:
        return {
            "attempt_index": self.attempt_index,
            "source": self.source,
            "status": self.status,
            "requested_count": self.requested_count,
            "returned_count": self.returned_count,
            "provider_executed": self.provider_executed,
            "http_status": self.http_status,
            "category": self.category,
        }


@dataclass(frozen=True)
class CreativeAuthorSupplyResult:
    status: str
    programs: tuple[CreativeAuthoredProgram, ...]
    attempts: tuple[CreativeAuthorAttempt, ...]
    counts: dict[str, int]

    def evidence(self) -> dict[str, Any]:
        return {
            "schema_version": "arr.maas.creative_author_supply.v1",
            "status": self.status,
            "program_count": len(self.programs),
            "attempts": [item.evidence() for item in self.attempts],
            "counts": dict(sorted(self.counts.items())),
        }


def collect_creative_author_supply(
    *,
    target_count: int,
    cached_programs: Iterable[CreativeAuthoredProgram],
    fresh_author: FreshAuthor,
    retained_count: RetainedCount,
    max_fresh_requests: int = 3,
) -> CreativeAuthorSupplyResult:
    """Merge cache-first authored supply and stop transport after typed 429."""

    target = max(1, int(target_count))
    maximum_fresh = max(0, int(max_fresh_requests))
    counts: Counter[str] = Counter({
        "cache_programs_accepted": 0,
        "duplicate_program_hash": 0,
        "fresh_programs_accepted": 0,
        "fresh_programs_returned": 0,
        "fresh_transport_attempted": 0,
        "fresh_transport_deferred": 0,
        "fresh_transport_error": 0,
        "http_429": 0,
    })
    selected: list[CreativeAuthoredProgram] = []
    seen_program_hashes: set[str] = set()
    attempts: list[CreativeAuthorAttempt] = []

    for authored in normalize_authored_programs(cached_programs):
        program_hash = authored.program.program_hash()
        if program_hash in seen_program_hashes:
            counts["duplicate_program_hash"] += 1
            continue
        seen_program_hashes.add(program_hash)
        selected.append(authored)
        counts["cache_programs_accepted"] += 1

    for attempt_index in range(1, maximum_fresh + 1):
        retained = int(retained_count(tuple(selected)))
        if retained >= target:
            break
        requested_count = max(1, target - retained)
        counts["fresh_transport_attempted"] += 1
        try:
            returned = tuple(fresh_author(requested_count, attempt_index))
        except GeometryAuthorError as exc:
            provider_error = exc.diagnostics.get("provider_error")
            if not isinstance(provider_error, dict):
                provider_error = {}
            category = str(provider_error.get("category") or "")
            raw_http_status = provider_error.get("http_status")
            try:
                http_status = int(raw_http_status)
            except (TypeError, ValueError):
                http_status = None
            is_rate_limited = http_status == 429
            counts["http_429" if is_rate_limited else "fresh_transport_error"] += 1
            attempts.append(CreativeAuthorAttempt(
                attempt_index=attempt_index,
                source="fresh_author",
                status="rate_limited" if is_rate_limited else "error",
                requested_count=requested_count,
                returned_count=0,
                provider_executed=True,
                http_status=http_status,
                category=category,
            ))
            if not is_rate_limited:
                continue
            for deferred_index in range(
                attempt_index + 1,
                maximum_fresh + 1,
            ):
                counts["fresh_transport_deferred"] += 1
                attempts.append(CreativeAuthorAttempt(
                    attempt_index=deferred_index,
                    source="fresh_author",
                    status="deferred_after_429",
                    requested_count=requested_count,
                    returned_count=0,
                    provider_executed=False,
                    http_status=429,
                    category=category,
                ))
            break

        counts["fresh_programs_returned"] += len(returned)
        accepted_count = 0
        for authored in normalize_authored_programs(returned):
            program_hash = authored.program.program_hash()
            if program_hash in seen_program_hashes:
                counts["duplicate_program_hash"] += 1
                continue
            seen_program_hashes.add(program_hash)
            selected.append(authored)
            accepted_count += 1
            counts["fresh_programs_accepted"] += 1
        attempts.append(CreativeAuthorAttempt(
            attempt_index=attempt_index,
            source="fresh_author",
            status="accepted",
            requested_count=requested_count,
            returned_count=len(returned),
            provider_executed=True,
            category="",
        ))

    status = (
        "complete"
        if int(retained_count(tuple(selected))) >= target
        else "partial"
    )
    return CreativeAuthorSupplyResult(
        status=status,
        programs=tuple(selected),
        attempts=tuple(attempts),
        counts=dict(counts),
    )


__all__ = [
    "CreativeAuthorAttempt",
    "CreativeAuthorSupplyResult",
    "FreshAuthor",
    "RetainedCount",
    "collect_creative_author_supply",
]
