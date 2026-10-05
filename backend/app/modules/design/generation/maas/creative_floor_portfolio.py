"""Bounded pre-legal authored MASS portfolio for frontend choice graphs."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
import hashlib
import json
import os
from math import isfinite, sqrt
from typing import Any, Iterable

from backend.app.modules.design.generation.maas.creative_family_contract import CreativeRecipeResult
from backend.app.modules.design.generation.maas.creative_book_supply import AUTHORED_SCHEDULE_POLICY, authored_book_schedule_key, creative_book_evidence, creative_book_schedule, project_creative_book_program
from backend.app.modules.design.generation.maas.creative_family_registry import balanced_family_schedule, registered_creative_recipes
from backend.app.modules.design.generation.maas.creative_program_author import CreativeAuthoredProgram, authored_program_result, normalize_authored_programs, posthoc_family_label
from backend.app.modules.design.generation.maas.creative_morphology import GLOBAL_MORPHOLOGY_THRESHOLD, MORPHOLOGY_SCHEMA, WITHIN_FAMILY_MORPHOLOGY_THRESHOLD, accept_morphology, build_morphology_descriptor
from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryNode, GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.compiler import CompilationResult, compile_geometry_program
from backend.app.modules.design.generation.maas.geometry_language.book_adapter import BookProjectionFailure
from backend.app.modules.design.generation.maas.geometry_language.gate import GeometryGatePolicy, compilation_gate


CREATIVE_FLOOR_PORTFOLIO_SCHEMA = (
    "arr.maas.creative_floor_portfolio.v1"
)
STOREY_HEIGHT_M = 3.3
CAPACITY_BANDS = (
    "spatial_reserve",
    "balanced_yield",
    "brief_target",
    "maximum_target",
)
CAPACITY_TARGET_RATIOS = {
    "spatial_reserve": 0.70,
    "balanced_yield": 0.80,
    "brief_target": 0.90,
    "maximum_target": 1.00,
}
_CONNECTED_POLICY = GeometryGatePolicy(maximum_components=1)


@dataclass(frozen=True)
class CreativePortfolioRejection:
    input_index: int
    stage: str
    reason_code: str
    program_hash: str = ""
    geometry_hash: str = ""
    principle_id: str = ""
    scope_label: str = ""

    def evidence(self) -> dict[str, Any]:
        return {
            "input_index": self.input_index,
            "stage": self.stage,
            "reason_code": self.reason_code,
            "program_hash": self.program_hash,
            "geometry_hash": self.geometry_hash,
            "principle_id": self.principle_id,
            "scope_label": self.scope_label,
        }


@dataclass(frozen=True)
class CreativeFloorPortfolioReport:
    status: str
    target_count: int
    candidates: tuple[dict[str, Any], ...]
    stage_counts: dict[str, int]
    rejection_counts: dict[str, int]
    rejections: tuple[CreativePortfolioRejection, ...]
    language_coverage: dict[str, Any]
    schedule_evidence: dict[str, Any] | None = None

    @property
    def exploration_count(self) -> int:
        return sum(row.get("candidate_origin") == "book_exploration" for row in self.candidates)

    @property
    def deficit(self) -> int:
        return max(0, self.target_count - self.exploration_count)

    def evidence(self) -> dict[str, Any]:
        return {
            "schema_version": (
                "arr.maas.creative_floor_portfolio_report.v1"
            ),
            "status": self.status,
            "target_count": self.target_count,
            "candidate_count": len(self.candidates),
            "exploration_count": self.exploration_count,
            "original_count": sum(row.get("candidate_origin") == "authored_original" for row in self.candidates),
            "target_count_scope": "book_exploration",
            "deficit": self.deficit,
            "stage_counts": dict(sorted(self.stage_counts.items())),
            "rejection_counts": dict(sorted(self.rejection_counts.items())),
            "rejections": [item.evidence() for item in self.rejections],
            "language_coverage": dict(self.language_coverage),
            **({"book_schedule": self.schedule_evidence} if self.schedule_evidence is not None else {}),
        }


def _book_language_coverage(
    candidates: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    evidence_rows = [
        row.get("book_language_evidence") or {}
        for row in candidates
    ]
    materialized = [
        row for row in evidence_rows if row.get("materialized") is True
    ]
    principle_ids = {
        str(row.get("principle_id") or "")
        for row in materialized
        if str(row.get("principle_id") or "")
    }
    principle_ids_by_kind = {
        kind: {
            str(row.get("principle_id") or "")
            for row in materialized
            if str(row.get("principle_kind") or "") == kind
            and str(row.get("principle_id") or "")
        }
        for kind in ("base_operative", "combination", "aggregation")
    }
    expected_ids = {
        item.principle_id for item in creative_book_schedule(59)
    }
    return {
        "schema_version": "arr.maas.creative_book_coverage.v1",
        "candidate_count": len(evidence_rows),
        "materialized_count": len(materialized),
        "distinct_principle_count": len(principle_ids),
        "principle_ids": sorted(principle_ids),
        "base_operative_count": len(
            principle_ids_by_kind["base_operative"]
        ),
        "combination_count": len(
            principle_ids_by_kind["combination"]
        ),
        "aggregation_count": len(
            principle_ids_by_kind["aggregation"]
        ),
        "missing_principle_ids": sorted(expected_ids - principle_ids),
        "principle_kind_counts": dict(sorted(Counter(
            str(row.get("principle_kind") or "")
            for row in materialized
            if str(row.get("principle_kind") or "")
        ).items())),
        "scope_counts": dict(sorted(Counter(
            str(row.get("scope_label") or "")
            for row in materialized
            if str(row.get("scope_label") or "")
        ).items())),
    }


def _structural_rejection_reason(
    compilation: CompilationResult,
) -> str:
    metrics = compilation.metrics
    if int(metrics.get("component_count") or 0) != 1:
        return "disconnected"
    if metrics.get("watertight") is not True:
        return "non_watertight"
    if metrics.get("manifold") is not True:
        return "non_manifold"
    if compilation_gate(compilation, _CONNECTED_POLICY):
        return "geometry_gate"
    return ""


def build_creative_floor_portfolio_report(
    *,
    target_count: int,
    capacity_ceiling_m2: float,
    authored_programs: Iterable[
        GeometryProgram | CreativeAuthoredProgram
    ],
) -> CreativeFloorPortfolioReport:
    """Keep up to target originals plus target explicitly derived BOOK options.

    Target and completion refer to exploration supply, never to its parents.
    Originals remain eligible even when no BOOK slot can transform them.
    """

    target = int(target_count)
    ceiling = float(capacity_ceiling_m2)
    # 200, with the command: the cycle's BOOK track authors BOOK_COUNT
    # programs (120 for comp18).
    if target < 1 or target > 200:
        raise ValueError("target_count must be between 1 and 200")
    if not isfinite(ceiling) or ceiling <= 0.0:
        raise ValueError("capacity_ceiling_m2 must be positive")

    inputs = tuple(authored_programs)
    stage_counts = {
        "author_input": len(inputs),
        "normalized_program": 0,
        "unique_program_hash": 0,
        "book_projection_pass": 0,
        "book_authority_pass": 0,
        "book_compile_pass": 0,
        "book_structural_pass": 0,
        "canonical_compile_pass": 0,
        "structural_pass": 0,
        "physical_candidate_pass": 0,
        "unique_geometry_hash": 0,
        "unique_normalized_mesh_hash": 0,
        "morphology_retained": 0,
        "authored_original_retained": 0,
    }
    rejection_counts: Counter[str] = Counter()
    rejections: list[CreativePortfolioRejection] = []
    candidates: list[dict[str, Any]] = []
    program_hashes: set[str] = set()
    geometry_hashes: set[str] = set()
    normalized_mesh_hashes: set[str] = set()

    def reject(
        input_index: int,
        stage: str,
        reason_code: str,
        *,
        program_hash: str = "",
        geometry_hash: str = "",
        principle_id: str = "",
        scope_label: str = "",
    ) -> None:
        rejection_counts[reason_code] += 1
        rejections.append(CreativePortfolioRejection(
            input_index=input_index,
            stage=stage,
            reason_code=reason_code,
            program_hash=program_hash,
            geometry_hash=geometry_hash,
            principle_id=principle_id,
            scope_label=scope_label,
        ))

    # Phase A: every program that stands on its own, before any book slot
    # touches it. Verbatim from the single-pass version.
    eligible: list[tuple[int, Any, str]] = []
    for input_index, raw_authored in enumerate(inputs):
        try:
            authored = normalize_authored_programs((raw_authored,))[0]
        except (RuntimeError, TypeError, ValueError):
            reject(input_index, "normalized_program", "normalization_error")
            continue
        stage_counts["normalized_program"] += 1
        source_program_hash = authored.program.program_hash()
        if source_program_hash in program_hashes:
            reject(
                input_index,
                "unique_program_hash",
                "duplicate_program_hash",
                program_hash=source_program_hash,
            )
            continue
        program_hashes.add(source_program_hash)
        stage_counts["unique_program_hash"] += 1
        try:
            source_compilation = compile_geometry_program(authored.program)
        except (RuntimeError, TypeError, ValueError):
            reject(
                input_index,
                "canonical_compile_pass",
                "compiler_exception",
                program_hash=source_program_hash,
            )
            continue
        stage_counts["canonical_compile_pass"] += 1
        source_structural_reason = _structural_rejection_reason(
            source_compilation
        )
        if source_structural_reason:
            reject(
                input_index,
                "structural_pass",
                source_structural_reason,
                program_hash=source_program_hash,
                geometry_hash=source_compilation.geometry_hash,
            )
            continue
        stage_counts["structural_pass"] += 1
        eligible.append((input_index, authored, source_program_hash))

    # Originals are the first `target` eligible programs, and the payload's
    # order decided which: comp22's author wrote its 120 sentences grouped
    # by base volume, so all twelve originals (and the explorations derived
    # from them) were 1/1 while the other five labels waited behind them.
    # The eligible list is interleaved by base seed, one from each in turn,
    # payload order kept within a seed; programs without a seed are one group.
    # Orientation too: with the seeds alone interleaved, all twelve of the
    # same payload were long_axis. Within a seed the orientations take
    # turns, and each seed starts its turn one orientation later than the
    # seed before it, so twelve originals are six seeds by two orientations.
    def _round_robin(queues):
        out: list[tuple[int, Any, str]] = []
        live = [list(queue) for queue in queues if queue]
        while live:
            for queue in list(live):
                out.append(queue.pop(0))
                if not queue:
                    live.remove(queue)
        return out

    # And the principle: comp25's twelve were nine of one principle
    # (join:split), the author's first sentence for every seed and
    # orientation. Within an orientation the principles take turns too.
    by_seed: dict[str, dict[str, dict[str, list[tuple[int, Any, str]]]]] = {}
    for item in eligible:
        metadata = item[1].program.metadata if isinstance(item[1].program.metadata, dict) else {}
        by_seed.setdefault(str(metadata.get("base_seed") or ""), {}).setdefault(
            str(metadata.get("book_orientation") or ""), {}).setdefault(
            str(metadata.get("book_principle_id") or ""), []).append(item)
    seed_queues = []
    for seed_index, orientations in enumerate(by_seed.values()):
        keys = list(orientations)
        start = seed_index % len(keys)
        orientation_queues = []
        for orientation_index, key in enumerate(keys[start:] + keys[:start]):
            principles = list(orientations[key].values())
            turn = (seed_index + orientation_index) % len(principles)
            orientation_queues.append(_round_robin(principles[turn:] + principles[:turn]))
        seed_queues.append(_round_robin(orientation_queues))
    eligible = _round_robin(seed_queues)

    source_ids = sorted({source_hash for _index, _authored, source_hash in eligible})
    # A round salt: the same payload in a later round meets a different
    # rotation of the 59 principles, so reuse does not mean repetition.
    schedule_salt = str(os.environ.get("MAAS_BOOK_SCHEDULE_SALT") or "").strip()
    schedule_ids = source_ids + ([f"round:{schedule_salt}"] if schedule_salt else [])
    book_schedule = creative_book_schedule(target, authored_source_ids=schedule_ids)
    schedule_evidence = {
        "policy": AUTHORED_SCHEDULE_POLICY,
        "key": authored_book_schedule_key(source_ids),
        "identity_basis": "sorted unique normalized structurally eligible authored source program hashes",
        "source_ids": source_ids,
        "ordered_assignments": [assignment.evidence() for assignment in book_schedule],
        "authority": "offered exploration assignments; actual materialization is measured in language_coverage",
    }

    # Preserve genuine author alternatives before exploring BOOK assignments.
    # Physical materialization may scale a programme into metres; the exact
    # authored AST is retained separately so that this never poses as a rewrite.
    originals: list[dict[str, Any]] = []
    for input_index, authored, source_program_hash in eligible:
        if len(originals) >= target:
            break
        try:
            compilation = compile_geometry_program(authored.program)
            candidate = _compile_candidate(
                authored_program_result(authored),
                family=posthoc_family_label(authored.program, compilation),
                source_family="llm_authored",
                family_index=input_index,
                variation_index=input_index,
                candidate_index=len(candidates),
                capacity_band=CAPACITY_BANDS[input_index % len(CAPACITY_BANDS)],
                capacity_ceiling_m2=ceiling,
                author_evidence=dict(authored.author_evidence),
            )
        except (RuntimeError, TypeError, ValueError):
            candidate = None
        if candidate is None:
            reject(input_index, "original_physical_candidate", "original_physical_candidate", program_hash=source_program_hash)
            continue
        geometry_hash = str(candidate["geometry_hash"])
        mesh_hash = str(candidate["normalized_authored_mesh_hash"])
        if geometry_hash in geometry_hashes or mesh_hash in normalized_mesh_hashes:
            reject(input_index, "original_unique_geometry", "original_duplicate_geometry", program_hash=source_program_hash, geometry_hash=geometry_hash)
            continue
        decision = accept_morphology(candidate, originals)
        if not decision:
            reject(input_index, "original_morphology_retained", "original_morphology_distance", program_hash=source_program_hash, geometry_hash=geometry_hash)
            continue
        candidate["morphology_evidence"]["decision"] = decision.to_dict()
        candidate["morphology_evidence"]["comparison_scope"] = "authored_originals"
        candidate["candidate_origin"] = "authored_original"
        raw_program = getattr(inputs[input_index], "program", inputs[input_index])
        candidate["source_program_hash"] = raw_program.program_hash()
        candidate["normalized_source_program_hash"] = source_program_hash
        candidate["authored_geometry_program"] = raw_program.to_dict()
        # Only actual author-supplied BOOK lineage can be credited here.
        candidate["book_language_evidence"] = creative_book_evidence(authored.program)
        originals.append(candidate)
        candidates.append(candidate)
        geometry_hashes.add(geometry_hash)
        normalized_mesh_hashes.add(mesh_hash)
        stage_counts["authored_original_retained"] += 1

    # Phase B: match figures to book slots. A slot is one operative at one
    # fraction scope; whether a figure can carry it is only known by
    # projecting, compiling and checking it stands, so feasibility is
    # computed lazily and cached. The single-pass version handed each
    # program the next unfilled slot and the payload's ORDER decided which
    # figures survived (35 of 40 in one ordering, 40 after a rotation, no
    # figure changed); greedy search left the last program with the last
    # slot. Augmenting paths, as the fixture path has done all along: a
    # program whose feasible slots are taken asks their owners to move.
    pair_cache: dict[tuple[int, int], tuple] = {}
    pairs_tried: Counter[int] = Counter()

    def pair(e_index: int, slot_index: int) -> tuple:
        key = (e_index, slot_index)
        if key in pair_cache:
            return pair_cache[key]
        pairs_tried[e_index] += 1
        input_index, authored, source_program_hash = eligible[e_index]
        assignment = book_schedule[slot_index]
        try:
            projected = project_creative_book_program(
                authored.program,
                assignment,
            )
        except BookProjectionFailure as exc:
            result = ("fail", assignment, "book_projection_pass",
                      str(exc.evidence.get("code") or "book_projection_failure"),
                      source_program_hash, None)
        except (RuntimeError, TypeError, ValueError):
            result = ("fail", assignment, "book_projection_pass",
                      "book_projection_failure", source_program_hash, None)
        else:
            evidence = creative_book_evidence(projected)
            if not evidence:
                result = ("fail", assignment, "book_authority_pass",
                          "book_authority_missing", source_program_hash, None)
            else:
                projected_hash = projected.program_hash()
                try:
                    compilation = compile_geometry_program(projected)
                except (RuntimeError, TypeError, ValueError):
                    result = ("fail", assignment, "book_compile_pass",
                              "book_compiler_exception", projected_hash, None)
                else:
                    reason = _structural_rejection_reason(compilation)
                    if reason:
                        result = ("fail", assignment, "book_structural_pass",
                                  f"book_{reason}", projected_hash,
                                  compilation.geometry_hash)
                    elif _normalized_mesh_hash(compilation) in normalized_mesh_hashes:
                        result = ("fail", assignment, "book_projection_pass",
                                  "book_duplicates_original", projected_hash,
                                  compilation.geometry_hash)
                    else:
                        try:
                            physical_candidate = _compile_candidate(
                                authored_program_result(replace(authored, program=projected)),
                                family=posthoc_family_label(projected, compilation),
                                source_family="llm_authored",
                                family_index=input_index,
                                variation_index=input_index,
                                candidate_index=0,
                                capacity_band=CAPACITY_BANDS[input_index % len(CAPACITY_BANDS)],
                                capacity_ceiling_m2=ceiling,
                                author_evidence=dict(authored.author_evidence),
                            )
                        except (RuntimeError, TypeError, ValueError):
                            physical_candidate = None
                        if physical_candidate is None:
                            result = ("fail", assignment, "physical_candidate_pass", "physical_candidate", projected_hash, compilation.geometry_hash)
                        elif (str(physical_candidate["geometry_hash"]) in geometry_hashes or str(physical_candidate["normalized_authored_mesh_hash"]) in normalized_mesh_hashes):
                            result = ("fail", assignment, "book_projection_pass", "book_duplicates_original", projected_hash, compilation.geometry_hash)
                        else:
                            result = ("ok", assignment, projected, evidence, compilation, physical_candidate)
        pair_cache[key] = result
        return result

    slot_owner: dict[int, int] = {}
    program_slot: dict[int, int] = {}

    def augment(e_index: int, visited: set[int]) -> bool:
        # A program's own slot first - what the single pass always gave it -
        # then the rest in order.
        for offset in range(target):
            slot_index = (e_index + offset) % target
            if slot_index in visited:
                continue
            if pair(e_index, slot_index)[0] != "ok":
                continue
            visited.add(slot_index)
            previous = slot_owner.get(slot_index)
            if previous is not None and not augment(previous, visited):
                continue
            slot_owner[slot_index] = e_index
            program_slot[e_index] = slot_index
            return True
        return False

    for e_index, (input_index, authored, source_program_hash) in enumerate(eligible):
        if len(slot_owner) >= target:
            break  # every slot has a figure; the rest of the supply is spare
        if augment(e_index, set()):
            continue
        # No slot will take this figure, and no owner can make room. The
        # rejection carries its own slot's stage and reason, as it always did.
        own = pair(e_index, e_index % target)
        if own[0] == "ok":
            reject(input_index, "book_projection_pass", "book_slot_unavailable",
                   program_hash=source_program_hash)
            continue
        _kind, assignment, stage, reason_code, failed_hash, failed_geometry = own
        reject(
            input_index,
            stage,
            reason_code,
            program_hash=failed_hash,
            **({"geometry_hash": failed_geometry} if failed_geometry else {}),
            principle_id=assignment.principle_id,
            scope_label=assignment.scope_label,
        )

    # Phase C: the matched pairs, in slot order, through the stages that
    # depend on what came before them - exactly as the single pass ran them.
    explorations: list[dict[str, Any]] = []
    for slot_index in sorted(slot_owner):
        e_index = slot_owner[slot_index]
        input_index, authored, source_program_hash = eligible[e_index]
        _kind, assignment, projected_program, book_evidence, authored_compilation, candidate = (
            pair(e_index, slot_index)
        )
        for stage in ("book_projection_pass", "book_authority_pass",
                      "book_compile_pass", "book_structural_pass"):
            stage_counts[stage] += 1
        authored = replace(authored, program=projected_program)
        program_hash = authored.program.program_hash()
        candidate["candidate_id"] = f"creative-{len(candidates) + 1:03d}"
        if candidate is None:
            reject(
                input_index,
                "physical_candidate_pass",
                "physical_candidate",
                program_hash=program_hash,
                geometry_hash=authored_compilation.geometry_hash,
            )
            continue
        stage_counts["physical_candidate_pass"] += 1
        geometry_hash = str(candidate["geometry_hash"])
        if geometry_hash in geometry_hashes:
            reject(
                input_index,
                "unique_geometry_hash",
                "duplicate_geometry_hash",
                program_hash=program_hash,
                geometry_hash=geometry_hash,
            )
            continue
        geometry_hashes.add(geometry_hash)
        stage_counts["unique_geometry_hash"] += 1
        normalized_mesh_hash = str(
            candidate["normalized_authored_mesh_hash"]
        )
        if normalized_mesh_hash in normalized_mesh_hashes:
            reject(
                input_index,
                "unique_normalized_mesh_hash",
                "duplicate_normalized_authored_mesh_hash",
                program_hash=program_hash,
                geometry_hash=geometry_hash,
            )
            continue
        normalized_mesh_hashes.add(normalized_mesh_hash)
        stage_counts["unique_normalized_mesh_hash"] += 1
        morphology_decision = accept_morphology(candidate, explorations)
        candidate["book_language_evidence"] = book_evidence
        candidate["morphology_evidence"]["decision"] = (
            morphology_decision.to_dict()
        )
        candidate["morphology_evidence"]["comparison_scope"] = "book_explorations"
        if not morphology_decision:
            reject(
                input_index,
                "morphology_retained",
                "morphology_distance",
                program_hash=program_hash,
                geometry_hash=geometry_hash,
            )
            continue
        candidate["book_slot_search"] = {
            "slot": slot_index,
            "principle_id": assignment.principle_id,
            "scope_label": assignment.scope_label,
            "pairs_tried": int(pairs_tried[e_index]),
        }
        candidate["candidate_origin"] = "book_exploration"
        raw_parent = getattr(inputs[input_index], "program", inputs[input_index])
        candidate["source_program_hash"] = raw_parent.program_hash()
        candidate["parent_program_hash"] = raw_parent.program_hash()
        candidate["normalized_source_program_hash"] = source_program_hash
        candidate["parent_geometry_program"] = raw_parent.to_dict()
        candidate["authored_geometry_program"] = projected_program.to_dict()
        candidates.append(candidate)
        explorations.append(candidate)
        stage_counts["morphology_retained"] += 1

    language_coverage = _book_language_coverage(explorations)
    # Command writers already persist this evidence field. Keep offered supply
    # explicit and separate from the materialized coverage counters above.
    language_coverage["offered_schedule"] = schedule_evidence
    coverage_complete = (
        target != 20
        or (
            language_coverage["distinct_principle_count"] == 20
            and set(language_coverage["scope_counts"])
            == {"1/1", "3/8", "1/2", "1/4", "1/8", "1/16"}
        )
    )
    return CreativeFloorPortfolioReport(
        status=(
            "complete"
            if len(explorations) >= target and coverage_complete
            else "partial"
        ),
        target_count=target,
        candidates=tuple(candidates),
        stage_counts=stage_counts,
        rejection_counts=dict(rejection_counts),
        rejections=tuple(rejections),
        language_coverage=language_coverage,
        schedule_evidence=schedule_evidence,
    )


def build_creative_floor_portfolio(
    *,
    count: int = 100,
    capacity_ceiling_m2: float = 332.322,
    authored_programs: Iterable[
        GeometryProgram | CreativeAuthoredProgram
    ] | None = None,
) -> dict[str, Any]:
    """Return a deterministic compiled choice pool with no legal approval."""

    requested_count = int(count)
    ceiling = float(capacity_ceiling_m2)
    if requested_count < 1 or requested_count > 200:
        raise ValueError("count must be between 1 and 200")
    if not isfinite(ceiling) or ceiling <= 0.0:
        raise ValueError("capacity_ceiling_m2 must be positive")

    if authored_programs is not None:
        report = build_creative_floor_portfolio_report(
            target_count=requested_count,
            capacity_ceiling_m2=ceiling,
            authored_programs=authored_programs,
        )
        if report.status != "complete":
            raise RuntimeError(
                "authored creative portfolio incomplete: "
                f"{report.exploration_count}/{requested_count} explorations"
            )
        payload = _creative_portfolio_payload(
            list(report.candidates),
            capacity_ceiling_m2=ceiling,
            author_mode="authored_programs",
        )
        payload["book_language_coverage"] = report.language_coverage
        evidence = report.evidence()
        for key in ("exploration_count", "original_count", "target_count_scope", "book_schedule"):
            payload[key] = evidence[key]
        return payload

    program_hashes: set[str] = set()
    geometry_hashes: set[str] = set()
    normalized_authored_mesh_hashes: set[str] = set()
    candidates: list[dict[str, Any]] = []

    schedule = balanced_family_schedule(requested_count)
    recipes_by_family = {
        recipe.family_id: recipe
        for recipe in registered_creative_recipes()
    }
    family_order = {
        recipe.family_id: index
        for index, recipe in enumerate(registered_creative_recipes())
    }
    book_assignments = creative_book_schedule(requested_count)
    pair_cache: dict[tuple[int, int], dict[str, Any] | None] = {}
    pair_failures: dict[tuple[int, int], str] = {}

    def compile_pair(item_index: int, assignment_index: int):
        key = (item_index, assignment_index)
        if key in pair_cache:
            return pair_cache[key]
        item = schedule[item_index]
        recipe = recipes_by_family[item.family_id]
        assignment = book_assignments[assignment_index]
        context = replace(
            item.context,
            book_scope_label=assignment.scope_label,
            book_principle_id=assignment.principle_id,
            book_principle_kind=assignment.principle_kind,
            book_execution_verbs=assignment.execution_verbs,
            book_aggregation_methods=assignment.aggregation_methods,
        )
        try:
            recipe_result = recipe.builder(context)
        except BookProjectionFailure as exc:
            pair_cache[key] = None
            pair_failures[key] = str(
                exc.evidence.get("code") or "book_projection_failure"
            )
            return None
        author_evidence = {
            "schema_version": "arr.maas.creative_author_evidence.v1",
            "source_kind": "recipe_fixture",
            "provider": "deterministic_fixture",
            "model": "",
            "response_id": "",
            "cache_hit": True,
            "prompt_contract": "",
        }
        candidate = _compile_candidate(
            recipe_result,
            family=recipe.family_id,
            source_family=str(
                recipe_result.recipe_parameters.get("source_family")
                or recipe.family_id
            ),
            family_index=family_order[recipe.family_id],
            variation_index=context.variation_index,
            candidate_index=item_index,
            capacity_band=context.capacity_band,
            capacity_ceiling_m2=ceiling,
            author_evidence=author_evidence,
        )
        if candidate is None:
            pair_cache[key] = None
            pair_failures[key] = "physical_candidate"
            return None
        book_evidence = creative_book_evidence(recipe_result.program)
        if not book_evidence:
            pair_cache[key] = None
            pair_failures[key] = "book_authority_missing"
            return None
        candidate["book_language_evidence"] = book_evidence
        pair_cache[key] = {
            "candidate": candidate,
            "context": context,
            "recipe_result": recipe_result,
        }
        return pair_cache[key]

    assignment_owner: dict[int, int] = {}
    item_assignment: dict[int, int] = {}

    def augment(item_index: int, visited: set[int]) -> bool:
        for offset in range(requested_count):
            assignment_index = (item_index + offset) % requested_count
            if assignment_index in visited:
                continue
            if compile_pair(item_index, assignment_index) is None:
                continue
            visited.add(assignment_index)
            previous_item = assignment_owner.get(assignment_index)
            if previous_item is not None and not augment(
                previous_item,
                visited,
            ):
                continue
            assignment_owner[assignment_index] = item_index
            item_assignment[item_index] = assignment_index
            return True
        return False

    for item_index, item in enumerate(schedule):
        if not augment(item_index, set()):
            recipe = recipes_by_family[item.family_id]
            failures = [
                (
                    book_assignments[assignment_index].principle_id,
                    pair_failures.get(
                        (item_index, assignment_index),
                        "assignment_conflict",
                    ),
                )
                for assignment_index in range(requested_count)
            ]
            raise RuntimeError(
                "invalid scheduled creative candidate: "
                f"family={recipe.family_id},"
                f"recipe={recipe.recipe_id},"
                f"variation={item.context.variation_index},"
                f"book_scope={item.context.book_scope_label},"
                f"capacity_band={item.context.capacity_band},"
                f"failures={failures}"
            )

    for item_index in range(requested_count):
        selected = compile_pair(item_index, item_assignment[item_index])
        assert selected is not None
        candidate = selected["candidate"]
        duplicate_fields = [
            field
            for field, seen in (
                ("program_hash", program_hashes),
                ("geometry_hash", geometry_hashes),
                (
                    "normalized_authored_mesh_hash",
                    normalized_authored_mesh_hashes,
                ),
            )
            if candidate[field] in seen
        ]
        if duplicate_fields:
            raise RuntimeError(
                "duplicate scheduled creative candidate: "
                f"family={schedule[item_index].family_id},"
                f"variation={selected['context'].variation_index},"
                f"duplicate_fields={','.join(duplicate_fields)}"
            )
        morphology_decision = accept_morphology(candidate, candidates)
        candidate["morphology_evidence"]["decision"] = (
            morphology_decision.to_dict()
        )
        if not morphology_decision:
            raise RuntimeError(
                "morphology quota exhausted: "
                f"family={schedule[item_index].family_id},"
                f"variation={selected['context'].variation_index},"
                f"{morphology_decision.diagnostic}"
            )
        candidates.append(candidate)
        program_hashes.add(candidate["program_hash"])
        geometry_hashes.add(candidate["geometry_hash"])
        normalized_authored_mesh_hashes.add(
            candidate["normalized_authored_mesh_hash"]
        )

    return _creative_portfolio_payload(
        candidates,
        capacity_ceiling_m2=ceiling,
        author_mode="recipe_fixture",
    )


def _creative_portfolio_payload(
    candidates: list[dict[str, Any]],
    *,
    capacity_ceiling_m2: float,
    author_mode: str,
) -> dict[str, Any]:
    family_counts = Counter(row["family"] for row in candidates)
    capacity_counts = Counter(row["capacity_band"] for row in candidates)
    nearest_distances = [
        float(row["morphology_evidence"]["decision"]["nearest_distance"])
        for row in candidates[1:]
    ]
    return {
        "schema_version": CREATIVE_FLOOR_PORTFOLIO_SCHEMA,
        "author_mode": author_mode,
        "status": "materialized",
        "choice_pool": True,
        "candidate_count": len(candidates),
        "candidate_origin_counts": dict(Counter(row.get("candidate_origin", author_mode) for row in candidates)),
        "capacity_ceiling_m2": round(capacity_ceiling_m2, 6),
        "capacity_authority": "user_supplied_prelegal_target",
        "family_quotas": dict(family_counts),
        "capacity_band_quotas": dict(capacity_counts),
        "legal_review_status": "not_evaluated",
        "paid_vlm_request_count": 0,
        "book_language_coverage": _book_language_coverage(candidates),
        "morphology_evidence": {
            "schema_version": MORPHOLOGY_SCHEMA,
            "decision": "accepted",
            "accepted_count": len(candidates),
            "rejected_count": 0,
            "global_threshold": GLOBAL_MORPHOLOGY_THRESHOLD,
            "within_family_threshold": (
                WITHIN_FAMILY_MORPHOLOGY_THRESHOLD
            ),
            "nearest_distance_distribution": _distance_distribution(
                nearest_distances
            ),
        },
        "candidates": candidates,
    }


def _normalized_mesh_hash(compilation: CompilationResult) -> str:
    bounds = compilation.metrics.get("bounds") or ()
    if len(bounds) != 2 or not compilation.vertices:
        return ""
    minimum, maximum = bounds
    spans = tuple(
        float(maximum[index]) - float(minimum[index])
        for index in range(3)
    )
    if any(span <= 1e-9 for span in spans):
        return ""
    vertices = [
        [
            round(
                (float(vertex[index]) - float(minimum[index]))
                / spans[index],
                8,
            )
            for index in range(3)
        ]
        for vertex in compilation.vertices
    ]
    payload = {
        "vertices": vertices,
        "triangles": [list(face) for face in compilation.triangles],
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _compile_candidate(
    recipe_result: CreativeRecipeResult,
    *,
    family: str,
    source_family: str,
    family_index: int,
    variation_index: int,
    candidate_index: int,
    capacity_band: str,
    capacity_ceiling_m2: float,
    author_evidence: dict[str, Any] | None = None,
    physical_contract: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    resolved_author_evidence = author_evidence or {
        "schema_version": "arr.maas.creative_author_evidence.v1",
        "source_kind": "recipe_fixture",
        "provider": "deterministic_fixture",
        "model": "",
        "response_id": "",
        "cache_hit": True,
        "prompt_contract": "",
    }
    authored = recipe_result.program
    from backend.app.modules.design.generation.maas.dimensional_intent import program_intent
    dimensional_intent = program_intent(authored)
    if dimensional_intent is not None:
        if physical_contract is not None:
            raise ValueError("dimensional intent cannot override exact development inheritance")
        physical_contract = dimensional_intent
        capacity_band = "authored_target"
    authored_compilation = compile_geometry_program(authored)
    if not _connected_compilation(authored_compilation):
        return None
    normalized_authored_mesh_hash = _normalized_mesh_hash(
        authored_compilation
    )
    if not normalized_authored_mesh_hash:
        return None

    storey_count = (int(physical_contract["storey_count"]) if physical_contract is not None
                    else 3 + ((family_index + variation_index) % 4))
    storey_height_m = (float(physical_contract["storey_height_m"]) if physical_contract is not None
                       else STOREY_HEIGHT_M)
    target_height_m = storey_count * storey_height_m
    target_gfa_m2 = float(physical_contract["target_gfa_m2"]) if physical_contract is not None else (
        capacity_ceiling_m2 * CAPACITY_TARGET_RATIOS[capacity_band]
    )
    # Report bounds are rounded for export. The sizing matrix and section
    # ruler must use the same live solid, otherwise non-decimal roof peaks
    # acquire a tiny Z stretch and fail exact dimensional delivery.
    if authored_compilation._solid is None:
        return None
    live_bounds = authored_compilation._solid.bounding_box()
    minimum, maximum = live_bounds[:3], live_bounds[3:]
    normalized_height = float(maximum[2]) - float(minimum[2])
    if normalized_height <= 1e-9:
        return None

    normalized_floor_areas = _slice_floor_areas(
        authored_compilation,
        storey_count=storey_count,
        minimum_z=float(minimum[2]),
        height=normalized_height,
    )
    normalized_gfa = sum(normalized_floor_areas)
    if normalized_gfa <= 1e-9:
        return None
    plan_scale = sqrt(target_gfa_m2 / normalized_gfa)
    height_scale = target_height_m / normalized_height
    center_x = (float(minimum[0]) + float(maximum[0])) / 2.0
    center_y = (float(minimum[1]) + float(maximum[1])) / 2.0
    physical_matrix = (
        (plan_scale, 0.0, 0.0, -center_x * plan_scale),
        (0.0, plan_scale, 0.0, -center_y * plan_scale),
        (0.0, 0.0, height_scale, -float(minimum[2]) * height_scale),
        (0.0, 0.0, 0.0, 1.0),
    )
    physical_envelope = _with_physical_matrix(
        authored,
        matrix=physical_matrix,
        family=family,
        capacity_band=capacity_band,
        storey_count=storey_count,
        target_gfa_m2=target_gfa_m2,
    )
    envelope_compilation = compile_geometry_program(physical_envelope)
    if not _connected_compilation(envelope_compilation):
        return None
    if envelope_compilation._solid is None:
        return None
    envelope_bounds = envelope_compilation._solid.bounding_box()
    physical_bounds = (envelope_bounds[:3], envelope_bounds[3:])
    physical, cutter_ids, plate_ids = _with_occupied_floor_plates(
        physical_envelope,
        bounds=physical_bounds,
        storey_count=storey_count,
        storey_height_m=storey_height_m,
    )
    compilation = compile_geometry_program(physical)
    if not _connected_compilation(compilation):
        return None
    actual_floor_areas = _slice_floor_areas(
        compilation,
        storey_count=storey_count,
        minimum_z=0.0,
        height=target_height_m,
    )
    if (
        len(actual_floor_areas) != storey_count
        or any(area <= 1e-9 for area in actual_floor_areas)
    ):
        return None

    relation_node = physical.node_map.get(recipe_result.contact_node_id)
    if relation_node is None:
        return None
    candidate_id = f"creative-{candidate_index + 1:03d}"
    elevations = [
        round(index * storey_height_m, 6)
        for index in range(storey_count + 1)
    ]
    actual_gfa = sum(actual_floor_areas)
    metrics = compilation.metrics
    trace_by_node = {
        str(trace.get("node_id") or ""): trace
        for trace in compilation.trace
    }
    witness_trace = trace_by_node.get(relation_node.id) or {}
    witness_volume = float(witness_trace.get("volume") or 0.0)
    plate_volumes = tuple(
        float((trace_by_node.get(node_id) or {}).get("volume") or 0.0)
        for node_id in plate_ids
    )
    final_component_count = int(metrics.get("component_count") or 0)
    if witness_volume <= 0.0 or any(volume <= 0.0 for volume in plate_volumes):
        return None
    matrix_nodes = tuple(
        node
        for node in physical.nodes
        if node.kind == "transform" and node.operator == "matrix4"
    )
    morphology_descriptor = build_morphology_descriptor(
        vertices=compilation.vertices,
        triangles=compilation.triangles,
        floor_areas=actual_floor_areas,
        component_count=final_component_count,
        contact_topology=recipe_result.contact_type,
    )
    return {
        **({"dimensional_intent_evidence": {
            "requested": dimensional_intent,
            "effective": {"storey_count": storey_count,
                          "storey_height_m": storey_height_m,
                          "height_m": target_height_m, "gfa_m2": actual_gfa},
            "programme_status": "unknown",
        }} if dimensional_intent is not None else {}),
        "candidate_id": candidate_id,
        "family": family,
        "source_family": source_family,
        "posthoc_family": posthoc_family_label(
            authored,
            authored_compilation,
        ),
        "form_class": recipe_result.form_class,
        "variation_index": variation_index,
        "capacity_band": capacity_band,
        "program_hash": physical.program_hash(),
        "geometry_hash": compilation.geometry_hash,
        "normalized_authored_mesh_hash": normalized_authored_mesh_hash,
        "geometry_program": physical.to_dict(),
        "author_evidence": resolved_author_evidence,
        "matrix4_trace": [
            {
                "node_id": node.id,
                "semantic_role": node.semantic_role,
                "matrix4": node.parameters["matrix4"],
            }
            for node in matrix_nodes
        ],
        "mesh": {
            "vertices": [list(vertex) for vertex in compilation.vertices],
            "triangles": [list(face) for face in compilation.triangles],
        },
        "mesh_evidence": {
            "connected": int(metrics.get("component_count") or 0) == 1,
            "watertight": metrics.get("watertight") is True,
            "manifold": metrics.get("manifold") is True,
            "closed_solid": metrics.get("closed_solid") is True,
            "component_count": int(metrics.get("component_count") or 0),
            "bounds": metrics.get("bounds"),
            "triangle_count": int(metrics.get("triangle_count") or 0),
            # The GATE reads these three and is fail-closed on a missing key,
            # so dropping them from the persisted evidence made every archived
            # candidate fail on self_intersection_unchecked / inverted_normals /
            # empty_or_tiny_solid while its own mesh was watertight and manifold.
            "self_intersection_checked_by_kernel": (
                metrics.get("self_intersection_checked_by_kernel") is True
            ),
            "outward_normals": metrics.get("outward_normals") is True,
            "volume": float(metrics.get("volume") or 0.0),
        },
        "storey_evidence": {
            "schema_version": "arr.maas.creative_storey_evidence.v1",
            "storey_count": storey_count,
            "typical_storey_height_m": storey_height_m,
            "floor_elevations_m": elevations,
            "floor_center_elevations_m": [
                round((index + 0.5) * storey_height_m, 6)
                for index in range(storey_count)
            ],
            "actual_floor_areas_m2": [
                round(area, 6) for area in actual_floor_areas
            ],
            "actual_gfa_m2": round(actual_gfa, 6),
            "target_gfa_m2": round(target_gfa_m2, 6),
            "capacity_band": capacity_band,
            "capacity_authority": ("soft_authored_target; programme_unknown" if dimensional_intent is not None else "user_supplied_prelegal_target"),
            "floor_cutter_node_ids": list(cutter_ids),
            "floor_plate_node_ids": list(plate_ids),
            "floor_plate_compiled_volumes_m3": [
                round(volume, 6) for volume in plate_volumes
            ],
            "authority": "authored_prelegal_horizontal_sections",
            "legal_certified": False,
            "measurement": (
                "final_manifold_occupied_floor_plate_center_slice"
            ),
        },
        "connectivity_evidence": {
            "schema_version": "arr.maas.creative_contact_witness.v1",
            "hard_pass": True,
            "contact_type": recipe_result.contact_type,
            "witness_node_id": relation_node.id,
            "witness_operator": relation_node.operator,
            "witness_compiled_volume": round(witness_volume, 6),
            "final_component_count": final_component_count,
            "compiled_component_count": final_component_count,
            "measurement": (
                "compiler_trace_positive_volume_and_final_component_count"
            ),
        },
        "morphology_evidence": {
            "schema_version": MORPHOLOGY_SCHEMA,
            "descriptor": morphology_descriptor.to_dict(),
        },
        "legal_review": {
            "schema_version": "arr.maas.prelegal_review.v1",
            "status": "not_evaluated",
            "hard_pass": False,
            "capacity_ceiling_m2": round(capacity_ceiling_m2, 6),
            "capacity_authority": "user_supplied_prelegal_target",
            "required_authorities": [
                "neo4j_law_agent",
                "exact_geometry_gate",
            ],
        },
        "lineage": {
            "schema_version": "arr.maas.creative_lineage.v1",
            "stages": [
                *(
                    ["llm_authored_geometry_program"]
                    if resolved_author_evidence.get("source_kind")
                    == "llm_authored_geometry_program"
                    else []
                ),
                "canonical_unitbox",
                "physical_storey_capacity_matrix4",
                "typed_book_relation",
                "connected_mass",
                "storey_contract",
                "legal_review_pending",
            ],
            "unitbox_node_id": _canonical_unitbox(physical).id,
            "relation_node_id": relation_node.id,
            "physical_envelope_node_id": physical_envelope.root_id,
            "physical_root_node_id": physical.root_id,
        },
    }


def _distance_distribution(values: list[float]) -> dict[str, Any]:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return {
            "count": 0,
            "minimum": None,
            "median": None,
            "maximum": None,
        }
    middle = len(ordered) // 2
    median = (
        ordered[middle]
        if len(ordered) % 2
        else (ordered[middle - 1] + ordered[middle]) / 2.0
    )
    return {
        "count": len(ordered),
        "minimum": round(ordered[0], 12),
        "median": round(median, 12),
        "maximum": round(ordered[-1], 12),
    }


def _with_physical_matrix(
    program: GeometryProgram,
    *,
    matrix: tuple[tuple[float, float, float, float], ...],
    family: str,
    capacity_band: str,
    storey_count: int,
    target_gfa_m2: float,
) -> GeometryProgram:
    node = GeometryNode(
        "creative_physical_storey_capacity_matrix4",
        "transform",
        "matrix4",
        inputs=(program.root_id,),
        parameters={"matrix4": [list(row) for row in matrix]},
        semantic_role="physical_storey_capacity_fit",
        provenance={
            "creative_family": family,
            "capacity_band": capacity_band,
            "storey_count": storey_count,
            "target_gfa_m2": round(target_gfa_m2, 6),
        },
    )
    return replace(
        program,
        nodes=(*program.nodes, node),
        root_id=node.id,
        name=f"{program.name}__creative_physical",
        metadata={
            **program.metadata,
            "creative_capacity_band": capacity_band,
            "creative_storey_count": storey_count,
            "creative_target_gfa_m2": round(target_gfa_m2, 6),
        },
    )


def _with_occupied_floor_plates(
    program: GeometryProgram,
    *,
    bounds: tuple[Any, Any] | list[Any],
    storey_count: int,
    storey_height_m: float = STOREY_HEIGHT_M,
) -> tuple[GeometryProgram, tuple[str, ...], tuple[str, ...]]:
    minimum, maximum = bounds
    minimum_x, minimum_y, minimum_z = (
        float(minimum[0]),
        float(minimum[1]),
        float(minimum[2]),
    )
    maximum_x, maximum_y, maximum_z = (
        float(maximum[0]),
        float(maximum[1]),
        float(maximum[2]),
    )
    span_x = maximum_x - minimum_x
    span_y = maximum_y - minimum_y
    height = maximum_z - minimum_z
    unitbox = _canonical_unitbox(program)
    cutter_thickness = min(0.12, storey_height_m * 0.04)
    margin = max(span_x, span_y, 1.0) * 0.02
    nodes = list(program.nodes)
    cutter_ids: list[str] = []
    plate_ids: list[str] = []
    for index in range(storey_count):
        center_z = minimum_z + height * (index + 0.5) / storey_count
        cutter_id = f"creative_floor_{index + 1:02d}_cutter_matrix4"
        plate_id = f"creative_floor_{index + 1:02d}_occupied_plate"
        cutter = GeometryNode(
            cutter_id,
            "transform",
            "matrix4",
            inputs=(unitbox.id,),
            parameters={
                "matrix4": [
                    [span_x + 2.0 * margin, 0.0, 0.0, minimum_x - margin],
                    [0.0, span_y + 2.0 * margin, 0.0, minimum_y - margin],
                    [
                        0.0,
                        0.0,
                        cutter_thickness,
                        center_z - cutter_thickness / 2.0,
                    ],
                    [0.0, 0.0, 0.0, 1.0],
                ],
            },
            semantic_role="occupied_floor_cutter",
            provenance={
                "authority": "canonical_unitbox",
                "storey_number": index + 1,
                "prelegal": True,
            },
        )
        plate = GeometryNode(
            plate_id,
            "boolean",
            "intersection",
            inputs=(program.root_id, cutter_id),
            semantic_role="occupied_floor_plate",
            provenance={
                "authority": "authored_prelegal_storey_contract",
                "storey_number": index + 1,
                "center_elevation_m": round(center_z, 6),
                "legal_certified": False,
            },
        )
        nodes.extend((cutter, plate))
        cutter_ids.append(cutter_id)
        plate_ids.append(plate_id)
    root = GeometryNode(
        "creative_occupied_storeys_union",
        "boolean",
        "union",
        inputs=(program.root_id, *plate_ids),
        semantic_role="connected_mass_with_occupied_floor_plates",
        provenance={
            "authority": "authored_prelegal_storey_contract",
            "floor_plate_node_ids": list(plate_ids),
            "set_identity": "host_union_subsets_equals_host",
            "legal_certified": False,
        },
    )
    nodes.append(root)
    return (
        replace(
            program,
            nodes=tuple(nodes),
            root_id=root.id,
            metadata={
                **program.metadata,
                "creative_floor_cutter_node_ids": list(cutter_ids),
                "creative_floor_plate_node_ids": list(plate_ids),
            },
        ),
        tuple(cutter_ids),
        tuple(plate_ids),
    )


def _slice_floor_areas(
    compilation: CompilationResult,
    *,
    storey_count: int,
    minimum_z: float,
    height: float,
) -> tuple[float, ...]:
    if compilation._solid is None:
        return ()
    areas: list[float] = []
    for floor_index in range(storey_count):
        z = minimum_z + height * (floor_index + 0.5) / storey_count
        try:
            area = abs(float(compilation._solid.slice(z).area()))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return ()
        if not isfinite(area) or area <= 1e-9:
            return ()
        areas.append(area)
    return tuple(areas)


def _connected_compilation(compilation: CompilationResult) -> bool:
    return bool(
        not compilation_gate(compilation, _CONNECTED_POLICY)
        and int(compilation.metrics.get("component_count") or 0) == 1
        and compilation.metrics.get("watertight") is True
        and compilation.metrics.get("manifold") is True
    )


def _canonical_unitbox(program: GeometryProgram) -> GeometryNode:
    matches = tuple(
        node
        for node in program.nodes
        if (
            node.kind == "primitive"
            and node.operator == "box"
            and node.parameters
            == {"width": 1.0, "depth": 1.0, "height": 1.0}
        )
    )
    if len(matches) != 1:
        raise ValueError("creative program requires one canonical UnitBox")
    return matches[0]


__all__ = [
    "CAPACITY_BANDS",
    "CREATIVE_FLOOR_PORTFOLIO_SCHEMA",
    "STOREY_HEIGHT_M",
    "balanced_family_schedule",
    "build_creative_floor_portfolio",
]
