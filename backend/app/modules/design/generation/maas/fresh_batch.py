"""Bounded fresh MASS batches built from the shared recursive geometry language.

The module stores grammar intentions, never finished-form dimensions.  Each
accepted program still starts from the normalized UnitBox seed catalog and is
compiled, gated and persisted by the ordinary single-MASS execution pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from backend.app.modules.design.generation.maas.agents.orchestrator.execution_collaboration import AgentExecutor
from backend.app.modules.design.generation.maas.fresh_family_contracts import build_family_contract_program, family_phenotype_issues
from backend.app.modules.design.generation.maas.geometry_language import apply_book_projection_to_geometry_program, compile_geometry_program
from backend.app.modules.design.generation.maas.geometry_language.gate import compilation_gate
from backend.app.modules.design.generation.maas.geometry_language.synthesis import synthesize_architectural_programs
from backend.app.modules.design.generation.maas.geometry_language.unitbox_normalization import normalize_unitbox_program
from backend.app.modules.design.generation.maas.grammar.verb_sequence import VerbCall, VerbSequence
from backend.app.modules.design.generation.maas.program_massing.book_projection import book_sentence_variants, compose_program_with_book_operations
from backend.app.modules.design.generation.maas.single_execution import execute_single_mass
from backend.app.modules.design.generation.maas.single_execution.persistence import write_json_atomic


@dataclass(frozen=True)
class FreshMassSpec:
    spec_id: str
    family: str
    intent_tags: tuple[str, ...]
    base_seeds: tuple[str, ...]
    book_verbs: tuple[str, ...]
    orientation: str = "long_axis"
    scope_label: str = "1/1"
    source_operator_depth: int = 0


_FRESH_MASS_SPECS = (
    FreshMassSpec(
        "curved-bar",
        "curved_bar",
        ("calm_prismatic", "long_span"),
        ("bar", "slab"),
        ("bend",),
    ),
    FreshMassSpec(
        "open-courtyard",
        "open_courtyard",
        ("calm_prismatic",),
        ("slab", "block"),
        ("inscribe",),
        orientation="short_axis",
    ),
    FreshMassSpec(
        "radial-cross",
        "radial_cross",
        ("calm_prismatic", "long_span"),
        ("bar", "slab"),
        ("rotate", "merge"),
    ),
    FreshMassSpec(
        "stepped-setback",
        "stepped_setback",
        ("calm_prismatic",),
        ("block", "tower"),
        ("stack",),
        orientation="vertical",
    ),
    FreshMassSpec(
        "tapered-leaning",
        "tapered_leaning",
        ("calm_prismatic",),
        ("tower", "block"),
        ("taper",),
        orientation="vertical",
    ),
    FreshMassSpec(
        "diagonal-cut",
        "diagonal_cut",
        ("calm_prismatic",),
        ("block", "tower"),
        ("shear",),
        orientation="vertical",
    ),
    FreshMassSpec(
        "face-attachment",
        "face_attachment",
        ("calm_prismatic",),
        ("block",),
        ("lodge", "shift"),
        orientation="short_axis",
    ),
    FreshMassSpec(
        "profiled-span",
        "profiled_span",
        ("profiled_span_section", "daylight_section"),
        ("profiled_prism",),
        ("extrude",),
        source_operator_depth=2,
    ),
    FreshMassSpec(
        "split-bridge",
        "split_bridge",
        ("calm_prismatic", "long_span"),
        ("bar", "slab"),
        ("split",),
        orientation="short_axis",
    ),
    FreshMassSpec(
        "nested-offset",
        "nested_offset",
        ("calm_prismatic",),
        ("slab", "block"),
        ("offset", "lift"),
    ),
)


def fresh_mass_specs() -> tuple[FreshMassSpec, ...]:
    """Return the stable grammar coverage contract for one ten-MASS batch."""

    return _FRESH_MASS_SPECS


def generate_fresh_mass_batch(
    output_root: str | Path,
    *,
    batch_id: str,
    building_type: str,
    count: int = 10,
    collaboration_executors: Mapping[str, AgentExecutor] | None = None,
) -> dict[str, Any]:
    """Author and execute a bounded set of unique fresh MASS programs.

    Use/program projection is deliberately not applied here.  A form-study
    batch must retain the morphology authored by its Geometry and BOOK layers;
    later program/law agents may review it without silently appending the same
    terminal spatial macro to every candidate.
    """

    requested_count = max(1, min(len(_FRESH_MASS_SPECS), int(count)))
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    archived_program_hashes, archived_geometry_hashes = _archive_hashes(root)
    accepted_program_hashes: set[str] = set()
    accepted_geometry_hashes: set[str] = set()
    executions: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for ordinal, spec in enumerate(_FRESH_MASS_SPECS[:requested_count], start=1):
        accepted = None
        base_offset = _variation_offset(batch_id, spec.spec_id)
        for cycle in range(12):
            variation_offset = (base_offset + cycle * 37) % 4096
            focused = build_family_contract_program(
                spec,
                variation_offset=variation_offset,
            )
            candidates = (
                (focused,)
                if focused is not None
                else synthesize_architectural_programs(
                    {
                        "base_seeds": list(spec.base_seeds),
                        "intent_tags": list(spec.intent_tags),
                        "candidate_count": 12,
                        "maximum_operator_depth": spec.source_operator_depth,
                        "downstream_body_rule_reserve": 2,
                        "balanced_operator_sampling": True,
                        "variation_offset": variation_offset,
                    },
                    building_type=building_type,
                )
            )
            sentences = book_sentence_variants(
                spec.book_verbs,
                count=max(12, len(candidates)),
            )
            for candidate_index, source in enumerate(candidates):
                try:
                    if focused is not None:
                        projected = source
                    else:
                        sequence = compose_program_with_book_operations(
                            VerbSequence(
                                name=f"{batch_id}-{spec.spec_id}-source",
                                label=spec.family,
                                calls=(VerbCall("base", {}),),
                            ),
                            sentences[
                                (variation_offset + candidate_index) % len(sentences)
                            ],
                            name_suffix="-".join(spec.book_verbs),
                            base_volume_label=spec.scope_label,
                            orientation=spec.orientation,
                        )
                        projected = apply_book_projection_to_geometry_program(
                            source,
                            sequence,
                        )
                    projected = normalize_unitbox_program(projected)
                except (TypeError, ValueError) as exc:
                    rejected.append({
                        "spec_id": spec.spec_id,
                        "cycle": cycle,
                        "candidate_index": candidate_index,
                        "reason": f"book_projection:{type(exc).__name__}",
                    })
                    continue
                projected = replace(
                    projected,
                    name=f"{batch_id}_{ordinal:02d}_{spec.spec_id}",
                    metadata={
                        **projected.metadata,
                        "family": spec.family,
                        "generation_mode": "fresh_synthesis",
                        "generation_batch_id": batch_id,
                        "generation_batch_ordinal": ordinal,
                        "generation_building_type": building_type,
                        "generation_request": {
                            "scope": spec.scope_label,
                            "orientation": spec.orientation,
                            "book_sentence": list(spec.book_verbs),
                            "intent_tags": list(spec.intent_tags),
                            "variation_offset": variation_offset,
                        },
                        "program_projection_applied": False,
                        "program_projection_stage": "deferred_until_mass_selection",
                    },
                )
                program_hash = projected.program_hash()
                if (
                    program_hash in accepted_program_hashes
                    or program_hash in archived_program_hashes
                ):
                    rejected.append({
                        "spec_id": spec.spec_id,
                        "cycle": cycle,
                        "candidate_index": candidate_index,
                        "reason": (
                            "duplicate_archive_program_hash"
                            if program_hash in archived_program_hashes
                            else "duplicate_program_hash"
                        ),
                    })
                    continue
                compilation = compile_geometry_program(projected)
                phenotype_issues = family_phenotype_issues(
                    projected,
                    spec,
                    compilation=compilation,
                )
                if phenotype_issues:
                    rejected.append({
                        "spec_id": spec.spec_id,
                        "cycle": cycle,
                        "candidate_index": candidate_index,
                        "reason": "family_phenotype_failed",
                        "issues": list(phenotype_issues),
                    })
                    continue
                gate_issues = compilation_gate(compilation)
                geometry_hash = str(compilation.geometry_hash or "")
                if compilation.status != "compiled" or gate_issues:
                    rejected.append({
                        "spec_id": spec.spec_id,
                        "cycle": cycle,
                        "candidate_index": candidate_index,
                        "reason": "geometry_gate_failed",
                        "issues": [issue.code for issue in gate_issues],
                    })
                    continue
                if (
                    not geometry_hash
                    or geometry_hash in accepted_geometry_hashes
                    or geometry_hash in archived_geometry_hashes
                ):
                    rejected.append({
                        "spec_id": spec.spec_id,
                        "cycle": cycle,
                        "candidate_index": candidate_index,
                        "reason": (
                            "missing_geometry_hash"
                            if not geometry_hash
                            else "duplicate_archive_geometry_hash"
                            if geometry_hash in archived_geometry_hashes
                            else "duplicate_geometry_hash"
                        ),
                    })
                    continue
                accepted = (projected, program_hash, geometry_hash)
                break
            if accepted is not None:
                break
        if accepted is None:
            break

        program, program_hash, geometry_hash = accepted
        execution_id = f"{batch_id}-{ordinal:02d}-{spec.spec_id}"
        result = execute_single_mass(
            program,
            output_root=root,
            execution_id=execution_id,
            title=f"{ordinal:02d} / {spec.family}",
            collaboration_executors=collaboration_executors,
            execution_mode="fresh_synthesis",
        )
        if not result.geometry_ready:
            rejected.append({
                "spec_id": spec.spec_id,
                "reason": "single_execution_geometry_not_ready",
                "execution_id": execution_id,
            })
            continue
        accepted_program_hashes.add(program_hash)
        accepted_geometry_hashes.add(geometry_hash)
        executions.append({
            "execution_id": result.execution_id,
            "execution_mode": result.execution_mode,
            "spec_id": spec.spec_id,
            "family": spec.family,
            "program_hash": result.program_hash,
            "geometry_hash": result.geometry_hash,
            "geometry_ready": result.geometry_ready,
            "preview_path": str(result.preview_path),
            "passport_path": str(result.passport_path),
        })

    payload = {
        "schema_version": "arr.maas.fresh_mass_batch.v1",
        "batch_id": batch_id,
        "building_type": building_type,
        "requested_count": requested_count,
        "accepted_count": len(executions),
        "status": "complete" if len(executions) == requested_count else "incomplete",
        "execution_ids": [row["execution_id"] for row in executions],
        "program_hashes": [row["program_hash"] for row in executions],
        "geometry_hashes": [row["geometry_hash"] for row in executions],
        "paid_image_request_count": 0,
        "executions": executions,
        "rejected_candidates": rejected,
    }
    write_json_atomic(root / f"{batch_id}.batch.json", payload)
    return payload


def _variation_offset(batch_id: str, spec_id: str) -> int:
    digest = hashlib.sha256(f"{batch_id}:{spec_id}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 4096


def _archive_hashes(root: Path) -> tuple[set[str], set[str]]:
    program_hashes: set[str] = set()
    geometry_hashes: set[str] = set()
    for manifest_path in root.glob("*/execution.json"):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        program_hash = str(payload.get("program_hash") or "")
        geometry_hash = str(payload.get("geometry_hash") or "")
        if program_hash:
            program_hashes.add(program_hash)
        if geometry_hash:
            geometry_hashes.add(geometry_hash)
    return program_hashes, geometry_hashes


__all__ = ["FreshMassSpec", "fresh_mass_specs", "generate_fresh_mass_batch"]
