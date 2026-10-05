"""Process-local paid geometry-author admission records.

Only the OpenAI author boundary records these entries.  Candidate metadata is
therefore insufficient by itself to claim paid-provider authorship.
"""

from __future__ import annotations

from typing import Any


_ADMITTED_PAID_PROGRAMS: set[tuple[str, str, str, str]] = set()


def admit_paid_provider_program(program: Any) -> None:
    """Record a program returned by the paid author boundary in this process."""

    metadata = getattr(program, "metadata", {})
    if not isinstance(metadata, dict):
        return
    response_id = str(metadata.get("author_response_id") or "").strip()
    request_kind = str(
        metadata.get("author_provider_request_kind") or ""
    ).strip()
    prompt_contract = str(
        metadata.get("author_prompt_contract") or ""
    ).strip()
    program_hash = str(program.program_hash() or "").strip()
    if response_id and request_kind and prompt_contract and program_hash:
        _ADMITTED_PAID_PROGRAMS.add(
            (response_id, request_kind, prompt_contract, program_hash)
        )


def is_admitted_paid_provider_program(
    *,
    response_id: str,
    request_kind: str,
    prompt_contract: str,
    program_hash: str,
) -> bool:
    """Return true only for an exact author-boundary admission in this process."""

    return (
        str(response_id or "").strip(),
        str(request_kind or "").strip(),
        str(prompt_contract or "").strip(),
        str(program_hash or "").strip(),
    ) in _ADMITTED_PAID_PROGRAMS
