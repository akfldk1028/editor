"""Bounded adaptive author -> compile -> VLM -> archive replenishment.

One MAAS board is deliberately allowed to fail honestly.  This coordinator
turns that diagnosis into the next graph-author round while preserving exact
accepted graphs and content-addressed VLM evidence.  It does not weaken visual,
novelty, capacity, legal, or parking gates to fill a presentation sheet.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.app.modules.design.generation.maas.program_massing.vlm_a2a import generation_feedback_from_result, run_neighborhood_vlm_a2a_loop


def _unique_paths(paths: tuple[Path, ...] | list[Path]) -> tuple[Path, ...]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        resolved = str(Path(path).resolve()).lower()
        if resolved in seen:
            continue
        seen.add(resolved)
        result.append(Path(path))
    return tuple(result)


def _round_path(path: Path, round_number: int) -> Path:
    if round_number <= 1:
        return path
    return path.with_name(f"{path.stem}-r{round_number}{path.suffix}")


def _round_quality_key(result: dict[str, Any]) -> tuple[float, ...]:
    """Rank complete round artifacts without allowing later-round regression."""
    missing = result.get("missing_language_groups") or {}
    missing_count = sum(max(0, int(value or 0)) for value in missing.values())
    rows = result.get("rows") or []
    vlm_scores = [
        float(row.get("vlm_design_score") or 0.0)
        for row in rows
        if isinstance(row, dict)
    ]
    mean_vlm = sum(vlm_scores) / len(vlm_scores) if vlm_scores else 0.0
    visual_pass = (
        result.get("status") == "technical_pass"
        and result.get("visual_status") == "review_required"
    )
    return (
        1.0 if visual_pass else 0.0,
        -float(missing_count),
        float(result.get("selected_count") or 0),
        float(result.get("capacity_target_met_count") or 0),
        float(result.get("geometric_language_count") or 0),
        mean_vlm,
    )


def run_adaptive_neighborhood_vlm_a2a_loop(
    *,
    output_json: Path,
    output_png: Path,
    max_rounds: int = 2,
    generation_feedback: dict[str, Any] | None = None,
    author_cache_path: Path | None = None,
    supplemental_author_cache_paths: tuple[Path, ...] = (),
    accepted_seed_result_paths: tuple[Path, ...] = (),
    vlm_cache_path: Path | None = None,
    supplemental_vlm_cache_paths: tuple[Path, ...] = (),
    **loop_kwargs: Any,
) -> dict[str, Any]:
    """Run bounded fresh-author rounds until the honest visual floor passes.

    Every failed round remains an immutable artifact.  The next round receives
    only typed diagnosis, accepted executable seeds, prior author populations,
    and geometry-keyed VLM cache entries.  A failed board is never padded with
    rejected or pose-duplicate candidates.
    """
    rounds = max(1, int(max_rounds))
    feedback = dict(generation_feedback or {}) or None
    accepted_paths = list(accepted_seed_result_paths)
    author_history = list(supplemental_author_cache_paths)
    vlm_history = list(supplemental_vlm_cache_paths)
    audit: list[dict[str, Any]] = []
    result: dict[str, Any] = {}
    best_result: dict[str, Any] = {}
    best_round_number = 0
    best_quality: tuple[float, ...] | None = None

    for round_number in range(1, rounds + 1):
        round_json = _round_path(output_json, round_number)
        round_png = _round_path(output_png, round_number)
        round_author_cache = (
            author_cache_path
            if round_number == 1 and author_cache_path is not None
            else round_json.with_name(f"{round_json.stem}-author-graph-cache.json")
        )
        round_vlm_cache = (
            vlm_cache_path
            if round_number == 1 and vlm_cache_path is not None
            else round_json.with_name(f"{round_json.stem}-vlm-score-cache.json")
        )
        result = run_neighborhood_vlm_a2a_loop(
            output_json=round_json,
            output_png=round_png,
            generation_feedback=feedback,
            author_cache_path=round_author_cache,
            supplemental_author_cache_paths=_unique_paths(author_history),
            accepted_seed_result_paths=_unique_paths(accepted_paths),
            vlm_cache_path=round_vlm_cache,
            supplemental_vlm_cache_paths=_unique_paths(vlm_history),
            **loop_kwargs,
        )
        audit.append({
            "round": round_number,
            "json": str(round_json),
            "png": str(round_png),
            "author_cache": str(round_author_cache),
            "vlm_cache": str(round_vlm_cache),
            "status": result.get("status"),
            "visual_status": result.get("visual_status"),
            "selected_count": result.get("selected_count"),
            "missing_language_groups": result.get("missing_language_groups") or {},
            "quality_key": list(_round_quality_key(result)),
        })
        quality = _round_quality_key(result)
        if best_quality is None or quality > best_quality:
            best_result = result
            best_round_number = round_number
            best_quality = quality
        if result.get("status") == "technical_pass" and result.get("visual_status") == "review_required":
            break

        feedback = generation_feedback_from_result(result)
        accepted_paths.append(round_json)
        author_history.append(round_author_cache)
        vlm_history.append(round_vlm_cache)

    result = best_result or result
    result["adaptive_replenishment"] = {
        "schema_version": "arr.maas.adaptive_replenishment.v1",
        "status": "visual_floor_reached" if result.get("visual_status") == "review_required" else "round_budget_exhausted",
        "requested_rounds": rounds,
        "completed_rounds": len(audit),
        "best_round": best_round_number,
        "best_json": audit[best_round_number - 1]["json"] if best_round_number else None,
        "last_round": len(audit),
        "monotonic_best_so_far": True,
        "rounds": audit,
        "gate_policy": "never_pad_with_rejected_or_duplicate_candidates",
    }
    final_path = Path(audit[best_round_number - 1]["json"] if best_round_number else audit[-1]["json"])
    final_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


__all__ = ["run_adaptive_neighborhood_vlm_a2a_loop"]
