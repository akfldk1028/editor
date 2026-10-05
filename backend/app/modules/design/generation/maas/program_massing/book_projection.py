"""Compose program assemblies with executable BOOK operations.

Program templates establish use-specific roles (hall, service spine, entry,
public anchor).  BOOK operations then mutate the dominant occupiable mass in
the compiler while subordinate roles remain available to program validation.
The note is a typed compiler boundary, not a name-based geometry shortcut.
"""

from __future__ import annotations

from collections.abc import Iterable
from math import copysign

from backend.app.modules.design.generation.maas.grammar.verb_sequence import VerbCall, VerbSequence
from backend.app.modules.design.generation.maas.grammar.vocab import AGGREGATION_VERBS, BOOK_BASE_VERBS
from backend.app.modules.design.generation.maas.grammar.parameter_schema import CATEGORICAL_PARAMETER_VALUES, PARAMETER_BOUNDS, PARAMETERS_BY_VERB, bounded_parameter
from backend.app.modules.design.generation.maas.book_language.semantics import semantics_for
from backend.app.modules.design.generation.maas.book_language.variation_lattice import book_variation_indices, categorical_variation_index, variation_fraction
from backend.app.modules.design.generation.maas.program_massing.book_scope import BOOK_SCOPE_VERB, BookProjectionScope, projection_scope
from backend.app.modules.design.generation.maas.program_massing.section_graph import mutate_program_section_graph_for_book, program_section_graph_from_sequence, replace_program_section_graph_note


BOOK_PROJECTION_NOTE = "book_projection_start="
BOOK_EXECUTABLE_VERBS = BOOK_BASE_VERBS | AGGREGATION_VERBS


def compose_program_with_book_operations(
    program_sequence: VerbSequence,
    operations: Iterable[VerbCall],
    *,
    name_suffix: str | None = None,
    base_volume_label: str = "1/1",
    orientation: str = "long_axis",
) -> VerbSequence:
    """Append typed operations after a program seed and mark their boundary."""
    appended = tuple(operations)
    if not appended:
        return program_sequence
    unsupported = [call.verb for call in appended if call.verb not in BOOK_EXECUTABLE_VERBS]
    if unsupported:
        raise ValueError(f"BOOK projection only accepts base operative verbs: {unsupported}")
    start = len(program_sequence.calls)
    scope = projection_scope(base_volume_label, orientation)
    scope_call = VerbCall(BOOK_SCOPE_VERB, {
        "base_volume_label": scope.label,
        "orientation": scope.orientation,
    })
    notes = tuple(program_sequence.notes)
    section_graph = program_section_graph_from_sequence(program_sequence)
    if section_graph:
        section_graph = mutate_program_section_graph_for_book(
            section_graph,
            appended,
            scope_label=scope.label,
            scope_fraction=scope.requested_fraction,
        )
        notes = replace_program_section_graph_note(notes, section_graph)
    suffix = name_suffix or "_".join(call.verb for call in appended)
    return VerbSequence(
        name=f"{program_sequence.name}__book_{suffix}",
        label=f"{program_sequence.label} + BOOK {' + '.join(call.verb for call in appended)}",
        calls=(*program_sequence.calls, scope_call, *appended),
        notes=(*notes, f"{BOOK_PROJECTION_NOTE}{start}"),
    )


def book_projection_calls(sequence: VerbSequence) -> tuple[VerbCall, ...]:
    """Return only explicitly marked BOOK calls; ordinary seeds return none."""
    raw = next((note.removeprefix(BOOK_PROJECTION_NOTE) for note in sequence.notes if note.startswith(BOOK_PROJECTION_NOTE)), "")
    try:
        start = int(raw)
    except (TypeError, ValueError):
        return ()
    if start < 1 or start >= len(sequence.calls):
        return ()
    calls = tuple(call for call in sequence.calls[start:] if call.verb != BOOK_SCOPE_VERB)
    return calls if all(call.verb in BOOK_EXECUTABLE_VERBS for call in calls) else ()


def book_projection_scope(sequence: VerbSequence) -> BookProjectionScope:
    raw = next((note.removeprefix(BOOK_PROJECTION_NOTE) for note in sequence.notes if note.startswith(BOOK_PROJECTION_NOTE)), "")
    try:
        start = int(raw)
        call = sequence.calls[start]
    except (IndexError, TypeError, ValueError):
        return projection_scope()
    if call.verb != BOOK_SCOPE_VERB:
        return projection_scope()
    return projection_scope(
        str(call.params.get("base_volume_label") or "1/1"),
        str(call.params.get("orientation") or "long_axis"),
    )


def _typed_variant(verb: str, index: int, *, active_parameters: frozenset[str] | None) -> VerbCall:
    params: dict[str, object] = {}
    for name in PARAMETERS_BY_VERB.get(verb, ()):
        active = active_parameters is None or name in active_parameters
        if name in CATEGORICAL_PARAMETER_VALUES:
            values = CATEGORICAL_PARAMETER_VALUES[name]
            params[name] = values[categorical_variation_index(name, index, len(values))] if active else values[0]
            continue
        if name not in PARAMETER_BOUNDS:
            continue
        low, high = PARAMETER_BOUNDS[name]
        fraction = variation_fraction(name, index) if active else 0.50
        params[name] = bounded_parameter(name, low + (high - low) * fraction)
    return VerbCall(verb, params)


def book_operation_variants(verb: str, *, count: int = 3) -> tuple[VerbCall, ...]:
    """Create normalized parameter probes from the shared typed schema.

    These are bounded compiler/search probes, not parcel-coordinate recipes.
    Agent/VLM authored values can replace them through the same parameter
    contract after the operation proves executable for a program.
    """
    if verb not in BOOK_BASE_VERBS:
        raise ValueError(f"unknown BOOK base operative: {verb}")
    semantics = semantics_for(verb)
    variation_parameters = frozenset(semantics.variation_parameters)
    return tuple(
        _typed_variant(verb, index, active_parameters=variation_parameters)
        for index in book_variation_indices(count)
    )


def _relational_repeat_variant(previous: VerbCall, candidate: VerbCall) -> VerbCall:
    """Keep a repeated typed move distinct without cancelling its parent."""

    params = dict(candidate.params)
    if candidate.verb in {"split", "fracture"} and params.get("axis") in {"x", "y"}:
        # BOOK p.40 is a recursive split of one child branch, not two
        # orthogonal full-body cuts.  Keep the parent's axis; the recursive
        # solid lowering selects one of the resulting half-width branches.
        params["axis"] = previous.params.get("axis", params["axis"])
    if candidate.verb == "inscribe":
        # p.39 repeats one open inscription concentrically. Changing facade
        # on the second pass cuts off a corner instead of forming the source
        # diagram's parallel nested grooves.
        params["open_side"] = previous.params.get("open_side", "closed")
    for name, prior_raw in previous.params.items():
        bounds = PARAMETER_BOUNDS.get(name)
        current_raw = params.get(name)
        if not bounds or bounds[0] >= 0.0 or bounds[1] <= 0.0:
            continue
        if not isinstance(prior_raw, (int, float)) or not isinstance(current_raw, (int, float)):
            continue
        prior = float(prior_raw)
        current = float(current_raw)
        if abs(prior) <= 1e-9:
            continue
        magnitude = abs(current)
        if magnitude <= 1e-9 or abs(magnitude - abs(prior)) <= 1e-9:
            magnitude = abs(prior) * 0.65
        params[name] = bounded_parameter(name, copysign(magnitude, prior))
    return VerbCall(candidate.verb, params)


def book_sentence_variants(verbs: Iterable[str], *, count: int = 1) -> tuple[tuple[VerbCall, ...], ...]:
    """Materialize a BOOK execution sentence in its recorded operation order.

    A repeated operative is a relation, not the same modifier replayed with
    identical controls.  Offset later occurrences through the same typed
    parameter lattice so ``bend+bend`` and ``split+split`` produce a second
    bounded move while remaining reproducible and schema-driven.
    """
    execution = tuple(str(verb) for verb in verbs)
    unsupported = [verb for verb in execution if verb not in BOOK_EXECUTABLE_VERBS]
    if not execution or unsupported:
        raise ValueError(f"invalid BOOK execution sentence: {unsupported or execution}")
    result: list[tuple[VerbCall, ...]] = []
    repeated_verbs = {verb for verb in execution if execution.count(verb) > 1}
    for index in book_variation_indices(count):
        calls = []
        occurrences: dict[str, int] = {}
        previous_by_verb: dict[str, VerbCall] = {}
        for verb in execution:
            active = frozenset(semantics_for(verb).variation_parameters) if verb in BOOK_BASE_VERBS else None
            occurrence = occurrences.get(verb, 0)
            occurrences[verb] = occurrence + 1
            call = _typed_variant(
                verb,
                index + occurrence * 2,
                active_parameters=active,
            )
            if verb == "split" and verb in repeated_verbs:
                params = dict(call.params)
                params["bridge_ratio"] = max(0.32, float(params.get("bridge_ratio", 0.0)))
                call = VerbCall(verb, params)
            if occurrence:
                call = _relational_repeat_variant(previous_by_verb[verb], call)
            previous_by_verb[verb] = call
            calls.append(call)
        result.append(tuple(calls))
    return tuple(result)


__all__ = ["BOOK_EXECUTABLE_VERBS", "BOOK_PROJECTION_NOTE", "book_operation_variants", "book_projection_calls", "book_projection_scope", "book_sentence_variants", "book_variation_indices", "compose_program_with_book_operations"]
