"""Bounded paid-authorship policy for BOOK portfolio generation."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from backend.app.modules.design.generation.maas.geometry_language import synthesis_requests_from_program_profile

from backend.app.modules.design.generation.maas.book_language.run_budget import progressive_mass_run_budget


MAX_LIVE_LLM_AUTHORED_PROGRAMS = 12
MAX_LLM_AUTHOR_BATCH_SIZE = 24
REQUIRED_ARCHITECTURAL_STRATEGIES = (
    "interlock",
    "overlap",
    "split",
    "courtyard",
    "void_notch",
    "pinch",
    "terrace_link",
    "lift",
    "bridge",
    "wing",
    "shear",
    "taper",
    "rotate",
)


def live_llm_authored_program_target(target_count: int) -> int:
    """Resolve broad progressive supply without unbounding legacy diagnostics."""

    try:
        return progressive_mass_run_budget(target_count).raw_target
    except ValueError:
        return max(1, min(MAX_LIVE_LLM_AUTHORED_PROGRAMS, int(target_count)))


def bounded_llm_author_batch_count(requested_count: int) -> int:
    return max(1, min(MAX_LLM_AUTHOR_BATCH_SIZE, int(requested_count)))


def bounded_live_llm_synthesis_requests(
    building_type: str,
    *,
    source_seed_names: Iterable[str],
    target_count: int,
    prior_requests: Iterable[Mapping[str, Any]] = (),
) -> tuple[dict[str, Any], ...]:
    """Create one paid LLM request; exact-solid VLM remains a later stage."""

    source_seed = next(
        (str(name) for name in source_seed_names if str(name)),
        "",
    )
    if not source_seed:
        return ()
    authored_count = live_llm_authored_program_target(target_count)
    profile_requests = synthesis_requests_from_program_profile(
        building_type,
        source_seeds=(source_seed,),
        candidates_per_lineage=bounded_llm_author_batch_count(authored_count),
    )
    if not profile_requests:
        return ()
    prior = tuple(
        dict(request)
        for request in prior_requests
        if isinstance(request, Mapping)
    )
    intent_tags = list(dict.fromkeys((
        *REQUIRED_ARCHITECTURAL_STRATEGIES,
        *(
        str(tag)
        for request in prior
        for tag in (request.get("intent_tags") or ())
        if str(tag)
        ),
    )))
    request = dict(profile_requests[0])
    if intent_tags:
        request["intent_tags"] = intent_tags
    batch_counts: list[int] = []
    remaining = authored_count
    while remaining > 0:
        batch_count = bounded_llm_author_batch_count(remaining)
        batch_counts.append(batch_count)
        remaining -= batch_count
    return tuple({
        **request,
        "candidate_count": batch_count,
        "live_llm_author": True,
        "llm_author_only": True,
        "llm_author_count": batch_count,
        "llm_author_batch_index": batch_index,
        "llm_author_batch_count": len(batch_counts),
        "llm_author_variation_offset": sum(batch_counts[:batch_index]),
        "required_architectural_strategies": list(
            REQUIRED_ARCHITECTURAL_STRATEGIES
        ),
        "authorship_completion_policy": "all_selected_llm_authored",
        "legal_authority": "deterministic_only",
        "shape_reference_policy": "capability_not_template",
        "live_vlm_revision": False,
        "synthesis_request_source": "bounded_live_llm_portfolio_author",
    } for batch_index, batch_count in enumerate(batch_counts))


__all__ = [
    "MAX_LIVE_LLM_AUTHORED_PROGRAMS",
    "MAX_LLM_AUTHOR_BATCH_SIZE",
    "REQUIRED_ARCHITECTURAL_STRATEGIES",
    "bounded_live_llm_synthesis_requests",
    "bounded_llm_author_batch_count",
    "live_llm_authored_program_target",
]
