"""Causal scheduling for the BOOK 30/20/9/10 language corpus."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import Any, Literal

from backend.app.modules.design.generation.maas.book_language.registry import build_book_language_registry


BookPrincipleKind = Literal[
    "base_operative",
    "combination",
    "aggregation",
    "case_study",
]


class AppliedBookCandidateReason(str, Enum):
    APPLIED_BOOK = "applied_book"
    RAW_BASE = "raw_base"
    MISSING_LINEAGE = "missing_lineage"
    UNKNOWN_PRINCIPLE = "unknown_principle"
    PRINCIPLE_ID_MISMATCH = "principle_id_mismatch"
    PRINCIPLE_KIND_MISMATCH = "principle_kind_mismatch"
    INVALID_LINEAGE = "invalid_lineage"
    PROJECTION_NOT_MATERIALIZED = "projection_not_materialized"


@dataclass(frozen=True)
class AppliedBookCandidateClassification:
    eligible: bool
    reason: AppliedBookCandidateReason
    principle_id: str = ""
    principle_kind: BookPrincipleKind | None = None


@lru_cache(maxsize=1)
def _canonical_book_principles() -> dict[str, dict[str, Any]]:
    return {
        str(principle["principle_id"]): principle
        for principle in build_book_language_registry()["principles"]
    }


def classify_applied_book_candidate(
    candidate: Any,
) -> AppliedBookCandidateClassification:
    """Classify canonical applied BOOK evidence without label heuristics."""
    principle_id = str(getattr(candidate, "principle_id", "") or "")
    principle_kind = str(getattr(candidate, "principle_kind", "") or "")
    source = getattr(candidate, "source", None)
    metadata = getattr(source, "metadata", {}) if source is not None else {}
    metadata = metadata if isinstance(metadata, dict) else {}
    lineage = metadata.get("book_generation_lineage")
    projection = metadata.get("program_book_projection_evidence")

    if not principle_id and not principle_kind and not lineage and not projection:
        return AppliedBookCandidateClassification(
            False,
            AppliedBookCandidateReason.RAW_BASE,
        )
    if not isinstance(lineage, dict) or not lineage:
        return AppliedBookCandidateClassification(
            False,
            AppliedBookCandidateReason.MISSING_LINEAGE,
            principle_id,
        )

    principle = _canonical_book_principles().get(principle_id)
    if principle is None:
        return AppliedBookCandidateClassification(
            False,
            AppliedBookCandidateReason.UNKNOWN_PRINCIPLE,
            principle_id,
        )
    if str(lineage.get("principle_id") or "") != principle_id:
        return AppliedBookCandidateClassification(
            False,
            AppliedBookCandidateReason.PRINCIPLE_ID_MISMATCH,
            principle_id,
        )

    canonical_kind = str(principle.get("kind") or "")
    if (
        principle_kind != canonical_kind
        or str(lineage.get("principle_kind") or "") != canonical_kind
    ):
        return AppliedBookCandidateClassification(
            False,
            AppliedBookCandidateReason.PRINCIPLE_KIND_MISMATCH,
            principle_id,
        )

    expected_base_id = str(
        principle.get("lineage_base_operative_id")
        or principle_id
    )
    if (
        str(lineage.get("schema_version") or "")
        != "arr.maas.book_generation_lineage.v1"
        or str(lineage.get("base_operative_id") or "") != expected_base_id
        or not canonical_lineage_parent_key(lineage)
    ):
        return AppliedBookCandidateClassification(
            False,
            AppliedBookCandidateReason.INVALID_LINEAGE,
            principle_id,
        )
    if (
        not isinstance(projection, dict)
        or projection.get("status") != "materialized"
    ):
        return AppliedBookCandidateClassification(
            False,
            AppliedBookCandidateReason.PROJECTION_NOT_MATERIALIZED,
            principle_id,
        )

    return AppliedBookCandidateClassification(
        True,
        AppliedBookCandidateReason.APPLIED_BOOK,
        principle_id,
        canonical_kind,
    )


def canonical_lineage_parent_key(lineage: dict[str, Any]) -> str:
    """Return the v1 parent key only when every key component agrees."""
    if not isinstance(lineage, dict):
        return ""
    source_seed = str(lineage.get("source_seed") or "")
    base_id = str(lineage.get("base_operative_id") or "")
    scope_label = str(lineage.get("scope_label") or "")
    orientation = str(lineage.get("orientation") or "")
    try:
        variant_index = int(lineage["variant_index"])
    except (KeyError, TypeError, ValueError):
        return ""
    if not all((source_seed, base_id, scope_label, orientation)):
        return ""
    canonical = "|".join((
        source_seed,
        base_id,
        scope_label,
        orientation,
        f"v{variant_index}",
    ))
    return canonical if str(lineage.get("parent_key") or "") == canonical else ""


def staged_principle_schedule(
    principles: tuple[dict[str, Any], ...],
    seed_index: int,
    *,
    count: int,
) -> tuple[tuple[int, dict[str, Any]], ...]:
    """Return base parents first and only then their recorded descendants."""
    if not principles:
        return ()
    wanted = max(6, min(len(principles), int(count)))
    indexed = tuple(enumerate(principles))
    bases = tuple(
        item for item in indexed
        if str(item[1].get("generation_stage") or item[1].get("kind"))
        in {"base", "base_operative"}
    )
    if not bases:
        return indexed[:wanted]

    descendants_by_base: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for item in indexed:
        base_id = str(item[1].get("lineage_base_operative_id") or "")
        if base_id and str(item[1].get("principle_id") or "") != base_id:
            descendants_by_base.setdefault(base_id, []).append(item)
    rich_bases = tuple(
        item for item in bases
        if str(item[1].get("principle_id") or "") in descendants_by_base
    )

    root_target = min(len(bases), max(1, wanted // 2))
    rich_target = min(len(rich_bases), max(1, root_target - 2))
    chosen_bases: list[tuple[int, dict[str, Any]]] = []

    def rotating(source, amount: int, offset: int):
        result = []
        if not source or amount <= 0:
            return result
        cursor = offset % len(source)
        visited = 0
        while len(result) < amount and visited < len(source) * 2:
            item = source[cursor]
            if item not in chosen_bases and item not in result:
                result.append(item)
            cursor = (cursor + 7) % len(source)
            visited += 1
        return result

    chosen_bases.extend(rotating(rich_bases, rich_target, int(seed_index) * 5))
    chosen_bases.extend(rotating(
        bases,
        root_target - len(chosen_bases),
        int(seed_index) * 11,
    ))
    scheduled: list[tuple[int, dict[str, Any]]] = list(chosen_bases)
    child_depth = 0
    while len(scheduled) < wanted:
        added = False
        for _base_index, base in chosen_bases:
            children = descendants_by_base.get(str(base.get("principle_id") or ""), ())
            if not children:
                continue
            child = children[(child_depth + int(seed_index)) % len(children)]
            if child not in scheduled:
                scheduled.append(child)
                added = True
                if len(scheduled) >= wanted:
                    break
        if not added:
            break
        child_depth += 1
    if len(scheduled) < wanted:
        scheduled.extend(rotating(
            bases,
            wanted - len(scheduled),
            int(seed_index) * 13 + 1,
        ))
    return tuple(scheduled[:wanted])


def lineage_record(
    principle: dict[str, Any],
    *,
    source_seed: str,
    scope_label: str,
    orientation: str,
    variant_index: int,
) -> dict[str, Any]:
    """Build the stable parent key shared by a base and its descendants."""
    base_id = str(
        principle.get("lineage_base_operative_id")
        or principle.get("principle_id")
        or ""
    )
    parent_key = "|".join((
        source_seed,
        base_id,
        scope_label,
        orientation,
        f"v{int(variant_index)}",
    ))
    return {
        "schema_version": "arr.maas.book_generation_lineage.v1",
        "stage": str(principle.get("generation_stage") or principle.get("kind") or "base"),
        "stage_order": int(principle.get("generation_stage_order") or 1),
        "principle_id": str(principle.get("principle_id") or ""),
        "principle_label": str(principle.get("label") or ""),
        "principle_kind": str(principle.get("kind") or ""),
        "execution_verbs": list(principle.get("execution_verbs") or ()),
        "implementation_elements": list(principle.get("implementation_elements") or ()),
        "base_operative_id": base_id,
        "parent_principle_id": principle.get("lineage_parent_principle_id"),
        "parent_key": parent_key,
        "source_seed": source_seed,
        "scope_label": scope_label,
        "orientation": orientation,
        "variant_index": int(variant_index),
    }


def gate_descendants_by_base(
    candidates: list[Any],
    *,
    known_viable_base_keys: set[str] | None = None,
    require_known_viable_base_keys: bool = False,
) -> tuple[list[Any], dict[str, Any]]:
    """Keep descendants whose exact base passed before or after QD compaction."""
    def family(candidate: Any) -> str:
        raw_program = candidate.source.metadata.get("geometry_program") or {}
        metadata = raw_program.get("metadata") if isinstance(raw_program, dict) else {}
        return str(
            (metadata or {}).get("family")
            or candidate.source.metadata.get("family")
            or "unclassified"
        )

    retained_pool_base_keys = {
        str((candidate.source.metadata.get("book_generation_lineage") or {}).get("parent_key") or "")
        for candidate in candidates
        if str((candidate.source.metadata.get("book_generation_lineage") or {}).get("stage") or "") == "base"
    }
    retained_base_keys = (
        retained_pool_base_keys & (known_viable_base_keys or set())
        if require_known_viable_base_keys
        else retained_pool_base_keys
    )
    base_keys = {
        key
        for key in (
            *retained_base_keys,
            *(known_viable_base_keys or set()),
        )
        if key
    }
    retained = []
    rejected = 0
    retained_via_known_base = 0
    family_counts: dict[str, dict[str, int]] = {}
    for candidate in candidates:
        lineage = candidate.source.metadata.get("book_generation_lineage") or {}
        stage = str(lineage.get("stage") or "")
        candidate_family = family(candidate)
        counts = family_counts.setdefault(candidate_family, {
            "input_base_count": 0,
            "input_descendant_count": 0,
            "retained_base_count": 0,
            "retained_descendant_count": 0,
            "rejected_descendant_without_viable_base_count": 0,
        })
        counts["input_base_count" if stage == "base" else "input_descendant_count"] += 1
        parent_key = str(lineage.get("parent_key") or "")
        if stage == "base" or parent_key in base_keys:
            retained.append(candidate)
            counts["retained_base_count" if stage == "base" else "retained_descendant_count"] += 1
            if (
                stage != "base"
                and parent_key not in retained_base_keys
                and parent_key in (known_viable_base_keys or set())
            ):
                retained_via_known_base += 1
        else:
            rejected += 1
            counts["rejected_descendant_without_viable_base_count"] += 1
    return retained, {
        "schema_version": "arr.maas.book_lineage_gate.v1",
        "input_count": len(candidates),
        "base_parent_count": len(base_keys),
        "retained_pool_base_parent_count": len(retained_pool_base_keys),
        "known_viable_base_parent_count": len(known_viable_base_keys or set()),
        "retained_count": len(retained),
        "retained_via_known_base_count": retained_via_known_base,
        "descendant_without_viable_base_count": rejected,
        "capacity_target_pass_input_count": sum(
            bool(
                (
                    candidate.source.metadata.get(
                        "capacity_alternative_projection"
                    )
                    or {}
                ).get("target_hard_pass")
            )
            for candidate in candidates
        ),
        "capacity_target_pass_retained_count": sum(
            bool(
                (
                    candidate.source.metadata.get(
                        "capacity_alternative_projection"
                    )
                    or {}
                ).get("target_hard_pass")
            )
            for candidate in retained
        ),
        "by_geometry_family": dict(sorted(family_counts.items())),
        "hard_pass": rejected == 0,
    }


__all__ = [
    "AppliedBookCandidateClassification",
    "AppliedBookCandidateReason",
    "BookPrincipleKind",
    "canonical_lineage_parent_key",
    "classify_applied_book_candidate",
    "gate_descendants_by_base",
    "lineage_record",
    "staged_principle_schedule",
]
