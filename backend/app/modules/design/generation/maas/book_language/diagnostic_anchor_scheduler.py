"""Typed anchor probes for bounded target3 diagnostic generation.

The scheduler reserves three program-independent morphology intentions before
the exhaustive parent stream.  It does not certify the resulting phenotype:
the compiled final mesh remains the only selection authority.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from typing import Any, Mapping, Sequence

from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.base_seeds import base_seed_programs
from backend.app.modules.design.generation.maas.geometry_language.universal_form_bank import universal_form_programs
from backend.app.modules.design.generation.maas.grammar.verb_sequence import VerbSequence
from backend.app.modules.design.generation.maas.program_massing import book_sentence_variants


_ANCHOR_NOTE_PREFIX = "geometry_program_diagnostic_anchor_"
_GEOMETRY_NOTE_PREFIXES = (
    "geometry_program_directive=",
    "geometry_program_payload=",
    "geometry_program_source_seed=",
    "geometry_program_edits=",
    "geometry_program_rationale=",
    "geometry_program_legal_fit_strength=",
    "geometry_program_source=",
    "geometry_program_form_bank_page=",
    "geometry_program_preservation_control=",
    "geometry_program_preservation_control_ordinal=",
    _ANCHOR_NOTE_PREFIX,
)


@dataclass(frozen=True)
class DiagnosticAnchorSpec:
    body_family: str
    principle_id: str
    scope_label: str = "1/1"
    orientation: str = "long_axis"
    variant_index: int = 5


_ANCHOR_SPECS = (
    DiagnosticAnchorSpec("prismatic", "book:operative:skew"),
    DiagnosticAnchorSpec(
        "stepped",
        "book:operative:expand",
        orientation="short_axis",
        variant_index=7,
    ),
    DiagnosticAnchorSpec("oblique", "book:operative:notch"),
)


def diagnostic_anchor_schedule_active(
    *,
    recursive_only: bool,
    evaluation_cap: int,
    parent_indices: Sequence[int],
    has_capacity_contract: bool,
    target_count: int,
    llm_author_only: bool = False,
) -> bool:
    """Limit anchors to legacy target3 diagnostics, never LLM-only supply."""

    return bool(
        recursive_only
        and int(evaluation_cap) >= 12
        and tuple(parent_indices) == (0,)
        and has_capacity_contract
        and int(target_count) in {0, 3}
        and not llm_author_only
    )


def _note_map(seed: VerbSequence) -> dict[str, str]:
    return {
        note.split("=", 1)[0]: note.split("=", 1)[1]
        for note in seed.notes
        if "=" in note
    }


def diagnostic_anchor_spec(
    seed: VerbSequence,
) -> DiagnosticAnchorSpec | None:
    notes = _note_map(seed)
    body_family = notes.get(
        "geometry_program_diagnostic_anchor_body_family",
        "",
    )
    principle_id = notes.get(
        "geometry_program_diagnostic_anchor_principle_id",
        "",
    )
    if not body_family or not principle_id:
        return None
    try:
        variant_index = int(notes.get(
            "geometry_program_diagnostic_anchor_variant_index",
            "5",
        ))
    except (TypeError, ValueError):
        return None
    return DiagnosticAnchorSpec(
        body_family=body_family,
        principle_id=principle_id,
        scope_label=notes.get(
            "geometry_program_diagnostic_anchor_scope",
            "1/1",
        ),
        orientation=notes.get(
            "geometry_program_diagnostic_anchor_orientation",
            "long_axis",
        ),
        variant_index=variant_index,
    )


def _typed_anchor_programs() -> Mapping[str, GeometryProgram]:
    base_programs = {
        str((program.metadata.get("base_seed") or {}).get("seed_id") or ""):
        program
        for program in base_seed_programs()
    }
    prism = base_programs.get("bar")
    page = universal_form_programs(1)
    stepped = next((
        program
        for program in page
        if any(node.operator == "stepped_mass" for node in program.nodes)
    ), None)
    # The anchor wants an oblique *body*; which base seed carries it is
    # incidental. Requiring slab specifically made this lookup depend on the
    # exact composition of a bounded page, and it returned nothing - dropping
    # all three anchors - as soon as a new supply lane displaced that one
    # program. Prefer slab, accept any sliced body.
    sliced = tuple(
        program
        for program in page
        if any(node.operator == "slice" for node in program.nodes)
    )
    oblique = next(
        (
            program for program in sliced
            if str(program.metadata.get("base_seed") or "") == "slab"
        ),
        sliced[0] if sliced else None,
    )
    if prism is None or stepped is None or oblique is None:
        return {}
    return {
        "prismatic": prism,
        "stepped": stepped,
        "oblique": oblique,
    }


def _anchor_parent(
    carrier: VerbSequence,
    *,
    program: GeometryProgram,
    spec: DiagnosticAnchorSpec,
) -> VerbSequence:
    retained_notes = tuple(
        note
        for note in carrier.notes
        if not note.startswith(_GEOMETRY_NOTE_PREFIXES)
    )
    source_seed = _note_map(carrier).get(
        "geometry_program_source_seed",
        carrier.name,
    )
    payload = json.dumps(
        program.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return replace(
        carrier,
        name=f"{carrier.name}__diagnostic_anchor_{spec.body_family}",
        notes=(
            *retained_notes,
            f"geometry_program_payload={payload}",
            f"geometry_program_source_seed={source_seed}",
            "geometry_program_edits=[]",
            (
                "geometry_program_rationale="
                "typed diagnostic morphology anchor before exhaustive supply"
            ),
            "geometry_program_legal_fit_strength=0.0",
            "geometry_program_source=diagnostic_anchor_scheduler",
            (
                "geometry_program_diagnostic_anchor_body_family="
                f"{spec.body_family}"
            ),
            (
                "geometry_program_diagnostic_anchor_principle_id="
                f"{spec.principle_id}"
            ),
            (
                "geometry_program_diagnostic_anchor_scope="
                f"{spec.scope_label}"
            ),
            (
                "geometry_program_diagnostic_anchor_orientation="
                f"{spec.orientation}"
            ),
            (
                "geometry_program_diagnostic_anchor_variant_index="
                f"{spec.variant_index}"
            ),
        ),
    )


def schedule_diagnostic_anchor_parents(
    parent_seeds: Sequence[VerbSequence],
) -> tuple[VerbSequence, ...]:
    """Prepend typed target3 anchors without deleting exhaustive parents."""

    parents = tuple(parent_seeds)
    if not parents:
        return ()
    if any(diagnostic_anchor_spec(seed) is not None for seed in parents):
        return parents
    programs = _typed_anchor_programs()
    if set(programs) != {spec.body_family for spec in _ANCHOR_SPECS}:
        return parents
    carrier = parents[0]
    anchors = tuple(
        _anchor_parent(
            carrier,
            program=programs[spec.body_family],
            spec=spec,
        )
        for spec in _ANCHOR_SPECS
    )
    return (*anchors, *parents)


def diagnostic_anchor_principles(
    seed: VerbSequence,
    principle_by_id: Mapping[str, Any],
    default: Sequence[Any],
) -> tuple[Any, ...]:
    spec = diagnostic_anchor_spec(seed)
    if spec is None:
        return tuple(default)
    principle = principle_by_id.get(spec.principle_id)
    return (principle,) if principle is not None else ()


def diagnostic_anchor_scope(
    seed: VerbSequence,
    *,
    default_label: str,
    default_orientation: str,
) -> tuple[str, str]:
    spec = diagnostic_anchor_spec(seed)
    if spec is None:
        return default_label, default_orientation
    return spec.scope_label, spec.orientation


def diagnostic_anchor_capacity_schedule_index(
    seed: VerbSequence,
    *,
    default_index: int,
) -> int:
    """Keep typed target3 anchors on the verified spatial-reserve lane."""

    if diagnostic_anchor_spec(seed) is not None:
        return 0
    return int(default_index)


def diagnostic_anchor_sentence_variants(
    seed: VerbSequence,
    execution_verbs: Sequence[str],
    *,
    default_count: int,
) -> tuple[tuple[Any, ...], ...]:
    """Return the operation tuple at the anchor's real lattice index."""

    spec = diagnostic_anchor_spec(seed)
    if spec is None:
        return tuple(book_sentence_variants(
            execution_verbs,
            count=default_count,
        ))
    lattice = tuple(book_sentence_variants(execution_verbs, count=12))
    return (lattice[spec.variant_index],)


__all__ = [
    "DiagnosticAnchorSpec",
    "diagnostic_anchor_capacity_schedule_index",
    "diagnostic_anchor_schedule_active",
    "diagnostic_anchor_principles",
    "diagnostic_anchor_sentence_variants",
    "diagnostic_anchor_scope",
    "diagnostic_anchor_spec",
    "schedule_diagnostic_anchor_parents",
]
