"""MassDSL island evolution for MAAS candidate generation.

This module is intentionally upstream of legal selection. It mutates and
crosses over MassDSL sequences, then hands the resulting variants back to the
existing legal repair/evaluation pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from shapely.geometry import Polygon

from backend.app.modules.design.generation.maas.geometry_language.book_parameter_projection import BOOK_KERNEL_PARAMETER_PROJECTIONS
from backend.app.modules.design.generation.maas.grammar.parameter_schema import PARAMETER_BOUNDS, PARAMETERS_BY_VERB
from backend.app.modules.design.generation.maas.grammar.verb_sequence import VerbCall, VerbSequence
from backend.app.modules.design.generation.maas.morphology_operators import MorphologyVariant


Interpreter = Callable[[Polygon, VerbSequence], MorphologyVariant | None]


@dataclass(frozen=True)
class EvolutionResult:
    variants: list[MorphologyVariant]
    trace: dict[str, Any]


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _sequence_key(sequence: VerbSequence) -> tuple[str, tuple[tuple[str, tuple[tuple[str, str], ...]], ...]]:
    return (
        sequence.name,
        tuple(
            (
                call.verb,
                tuple(sorted((str(key), str(value)) for key, value in call.params.items())),
            )
            for call in sequence.calls
        ),
    )


def _from_call_dicts(name: str, label: str, calls: Iterable[dict[str, Any]], notes: Iterable[str]) -> VerbSequence | None:
    parsed: list[VerbCall] = []
    for item in calls:
        if not isinstance(item, dict):
            continue
        verb = item.get("verb")
        params = item.get("params") if isinstance(item.get("params"), dict) else {}
        if isinstance(verb, str):
            parsed.append(VerbCall(verb=verb, params=dict(params)))
    if not parsed:
        return None
    sequence = VerbSequence(name=name, label=label, calls=tuple(parsed), notes=tuple(str(note) for note in notes))
    return None if sequence.validate() else sequence


def sequence_from_variant(variant: MorphologyVariant) -> VerbSequence | None:
    calls = getattr(variant, "verb_sequence", ()) or ()
    if not calls:
        return None
    return _from_call_dicts(
        name=str(getattr(variant, "operator", "") or "evolution_seed"),
        label=str(getattr(variant, "operator", "") or "Evolution seed"),
        calls=calls,
        notes=getattr(variant, "notes", ()) or (),
    )


def _island_for(sequence: VerbSequence) -> str:
    # Classify by the dominant topology-defining gesture, not by unordered set
    # precedence. Otherwise an additive `extrude + lift + taper` is mislabeled
    # sectional merely because it contains a common vertical modifier.
    groups = {
        "subtractive": {"courtyard", "notch", "cave", "pinch", "embed", "nest"},
        "hybrid": {"split", "bend", "interlock", "overlap", "branch"},
        "additive": {"array", "offset", "reflect", "bar", "extrude", "stack"},
        "sectional": {"diagonal_connect", "sloped_roof_mass", "terrace_link", "step_envelope", "grade"},
    }
    for call in sequence.calls[1:]:
        for island, verbs in groups.items():
            if call.verb in verbs:
                return island
    if any(call.verb in {"lift", "taper", "shift"} for call in sequence.calls[1:]):
        return "sectional"
    return "generic"


def _mutate_param(call: VerbCall, *, scale: float, turn: int) -> VerbCall:
    params: dict[str, Any] = {}
    for key, value in call.params.items():
        if isinstance(value, bool):
            params[key] = value
        elif isinstance(value, int | float):
            v = float(value)
            if key.endswith("_ratio") or key in {"ratio", "factor", "shift", "upper_ratio", "x_ratio", "y_ratio", "waist_ratio", "slab_ratio"}:
                params[key] = round(_clamp(v * scale, 0.08, 1.18), 3)
            elif key in {"distance_ratio", "shift_ratio"}:
                params[key] = round(_clamp(v * scale, -0.34, 0.34), 3)
            elif key == "angle":
                params[key] = round(_clamp(v + (turn * 7.5), -58.0, 58.0), 2)
            elif key == "lower_floor_fraction":
                params[key] = round(_clamp(v * scale, 0.22, 0.68), 3)
            else:
                params[key] = value
        else:
            params[key] = value
    return VerbCall(call.verb, params=params)


def _seeded_for_mutation(call: VerbCall) -> VerbCall:
    """Give a call whose author left the numbers out something to mutate.

    ``_mutate_param`` scales the values it finds, so a call carrying no numeric
    parameter came through every variant unchanged and compiled at the one
    magnitude the adapter falls back to. Measured on the live run, every
    ``carve`` in the pool was the same carve, and the operative's own range runs
    from a convex-hull departure of 0.004 to 0.200 - the latter being what
    ``branch`` reaches. Names varied and shapes did not.

    The values seeded here are the midpoints of the bounds the grammar already
    declares for that verb, so nothing is invented and nothing is tuned to a
    parcel: a verb is asked for the middle of its own declared range and the
    two scale samples then place it either side. Only the variants are seeded -
    the parent sequence still compiles exactly as it did.
    """

    if call.params:
        return call
    seeded = {}
    for name in PARAMETERS_BY_VERB.get(call.verb, ()):
        # Only the verb's own shape parameters. `upper_ratio` and
        # `lower_floor_fraction` sit on nearly every verb and choose which floor
        # band the operation applies to, not how strongly it applies; seeding
        # those moved the operation up the building instead of enlarging it, and
        # the measured pool fell from 12 candidates over 8 grid cells to 10 over
        # 5. The parameter-projection table already declares, per verb, which
        # source parameters bridge into the kernel macro - that is the list.
        if (call.verb, name) not in BOOK_KERNEL_PARAMETER_PROJECTIONS:
            continue
        bounds = PARAMETER_BOUNDS.get(name)
        if bounds is None:
            continue
        low, high = bounds
        # A range that straddles zero is a direction, not a magnitude, and its
        # midpoint is "no displacement" - seeding an angle to 0.0 would make the
        # variant flatter than the default it replaced. Leave those to the
        # author and to the adapter's own value.
        if low < 0.0 < high:
            continue
        seeded[name] = round((low + high) / 2.0, 3)
    return VerbCall(call.verb, params=seeded) if seeded else call


def _parameter_mutations(sequence: VerbSequence) -> list[VerbSequence]:
    out: list[VerbSequence] = []
    seeded_calls = [
        _seeded_for_mutation(call) if index > 0 else call
        for index, call in enumerate(sequence.calls)
    ]
    mutable_indexes = [i for i, call in enumerate(seeded_calls) if i > 0 and call.params]
    # Use visibly separated, symmetric samples. The old 0.88/1.12 samples and
    # one-direction angle turns collapsed to the same geometry after legal
    # projection, producing many names but too few distinct silhouettes.
    for variant_index, (scale, turn) in enumerate(((0.72, -1), (1.28, 1)), start=1):
        calls = [
            _mutate_param(call, scale=scale, turn=turn) if index in mutable_indexes else call
            for index, call in enumerate(seeded_calls)
        ]
        out.append(VerbSequence(
            name=f"{sequence.name}__evo_param_{variant_index}",
            label=f"{sequence.label} evo param {variant_index}",
            calls=tuple(calls),
            notes=sequence.notes + (
                "evolution_operator=parameter_mutation",
                f"evolution_parent={sequence.name}",
            ),
        ))
    return out


_TOPOLOGY_WEIGHTS = {
    "split": 2.0, "branch": 2.0, "interlock": 2.0, "overlap": 1.5,
    "array": 2.0, "offset": 1.5, "reflect": 1.5, "embed": 1.5,
    "nest": 1.5, "diagonal_connect": 2.0, "terrace_link": 1.5,
    "sloped_roof_mass": 1.5, "courtyard": 1.5, "cave": 1.5,
    "notch": 1.0, "pinch": 1.0, "extrude": 1.0, "bend": 1.5,
}


def _program_complexity(calls: Iterable[VerbCall]) -> float:
    return round(sum(_TOPOLOGY_WEIGHTS.get(call.verb, 0.25 if call.verb != "base" else 0.0) for call in calls), 3)


def _simplification_mutations(sequence: VerbSequence) -> list[VerbSequence]:
    """Create reachable clean anchors with complexity-decreasing rewrites."""
    if len(sequence.calls) <= 3:
        return []
    out: list[VerbSequence] = []
    # Preserve base and the first/dominant architectural gesture.
    for index in range(len(sequence.calls) - 1, 1, -1):
        calls = sequence.calls[:index] + sequence.calls[index + 1:]
        candidate = VerbSequence(
            name=f"{sequence.name}__evo_simplify_{index}",
            label=f"{sequence.label} simplified {index}",
            calls=calls,
            notes=sequence.notes + (
                "evolution_operator=complexity_decreasing_rewrite",
                f"evolution_parent={sequence.name}",
                f"removed_verb={sequence.calls[index].verb}",
            ),
        )
        if not candidate.validate() and _program_complexity(candidate.calls) < _program_complexity(sequence.calls):
            out.append(candidate)
    return out[:2]


def _crossover(a: VerbSequence, b: VerbSequence, index: int) -> VerbSequence | None:
    if len(a.calls) < 3 or len(b.calls) < 3:
        return None
    a_tail = tuple(call for call in a.calls[1:] if call.verb != "base")
    b_tail = tuple(call for call in b.calls[1:] if call.verb != "base")
    if not a_tail or not b_tail:
        return None
    calls = (a.calls[0],) + a_tail[: max(1, len(a_tail) // 2)] + b_tail[max(0, len(b_tail) // 2):]
    # A crossover is rejected when recombination increases program complexity.
    # Evolution must refine a dominant gesture rather than concatenate pieces.
    if (
        len(calls) > 4
        or len(calls) > max(len(a.calls), len(b.calls))
        or _program_complexity(calls) > max(_program_complexity(a.calls), _program_complexity(b.calls))
    ):
        return None
    sequence = VerbSequence(
        name=f"{a.name}__x__{b.name}__evo_cross_{index}",
        label=f"{a.label} x {b.label}",
        calls=calls,
        notes=a.notes + b.notes + (
            "evolution_operator=island_crossover",
            f"evolution_parent_a={a.name}",
            f"evolution_parent_b={b.name}",
        ),
    )
    return None if sequence.validate() else sequence


def _candidate_score(variant: MorphologyVariant, *, base_area: float) -> float:
    area = max(1.0, float(getattr(variant.footprint, "area", 0.0) or 0.0))
    area_ratio = _clamp(area / max(base_area, 1.0), 0.0, 1.4)
    section_bonus = 0.18 if getattr(variant, "upper_footprint", None) is not None else 0.0
    source_bonus = 0.18 if getattr(variant, "source_geometry_status", None) == "compiled" else 0.0
    repair_headroom = 1.0 - abs(area_ratio - 0.72)
    verb_count = len(getattr(variant, "verb_sequence", ()) or ())
    complexity_penalty = max(0, verb_count - 3) * 0.16
    return round(max(0.0, repair_headroom) + section_bonus + source_bonus - complexity_penalty, 4)


def evolve_massdsl_islands(
    *,
    base_footprint: Polygon,
    seed_sequences: Iterable[VerbSequence],
    interpret: Interpreter,
    max_children: int = 36,
) -> EvolutionResult:
    """Create one legal-pipeline-ready generation of MassDSL child variants."""
    seeds: list[VerbSequence] = []
    seen: set[tuple[str, tuple[tuple[str, tuple[tuple[str, str], ...]], ...]]] = set()
    for sequence in seed_sequences:
        key = _sequence_key(sequence)
        if key in seen or sequence.validate():
            continue
        seen.add(key)
        seeds.append(sequence)

    trace: dict[str, Any] = {
        "schema_version": "arr.maas.evolution_trace.v1",
        "method": "massdsl_island_mutation_crossover",
        "paper_alignment_status": "evomass_inspired_first_generation_not_full_ssiea",
        "seed_count": len(seeds),
        "max_children": max_children,
        "island_seed_counts": {},
        "operator_counts": {},
        "children": [],
        "accepted_child_count": 0,
        "rejected_child_count": 0,
        "limitations": [
            "single-generation MassDSL evolution",
            "legal repair and final selection happen downstream",
            "not yet a full SSIEA/Pareto optimizer",
        ],
    }
    if not seeds:
        trace["status"] = "skipped_no_seed_sequences"
        return EvolutionResult([], trace)

    island_map: dict[str, list[VerbSequence]] = {}
    for sequence in seeds:
        island_map.setdefault(_island_for(sequence), []).append(sequence)
    trace["island_seed_counts"] = {key: len(value) for key, value in sorted(island_map.items())}

    children_by_island: dict[str, list[VerbSequence]] = {}
    for island, island_seeds in sorted(island_map.items()):
        island_children: list[VerbSequence] = []
        for sequence in island_seeds[: max(2, max_children // max(len(island_map), 1))]:
            island_children.extend(_simplification_mutations(sequence))
            island_children.extend(_parameter_mutations(sequence))
        if len(island_seeds) >= 2:
            for index, (a, b) in enumerate(zip(island_seeds[::2], island_seeds[1::2]), start=1):
                crossed = _crossover(a, b, index)
                if crossed is not None:
                    island_children.append(crossed)
        children_by_island[island] = island_children

    # True island round-robin: no alphabetically earlier island may consume
    # the complete child budget before the others are evaluated.
    child_sequences: list[VerbSequence] = []
    depth = 0
    while len(child_sequences) < max_children:
        added = False
        for island in sorted(children_by_island):
            bucket = children_by_island[island]
            if depth < len(bucket):
                child_sequences.append(bucket[depth])
                added = True
                if len(child_sequences) >= max_children:
                    break
        if not added:
            break
        depth += 1

    variants: list[MorphologyVariant] = []
    child_seen: set[tuple[str, tuple[tuple[str, tuple[tuple[str, str], ...]], ...]]] = set()
    base_area = max(1.0, float(getattr(base_footprint, "area", 0.0) or 0.0))
    for sequence in child_sequences:
        if len(variants) >= max_children:
            break
        key = _sequence_key(sequence)
        if key in child_seen or sequence.validate():
            continue
        child_seen.add(key)
        variant = interpret(base_footprint, sequence)
        record = {
            "name": sequence.name,
            "island": _island_for(sequence),
            "verbs": [call.verb for call in sequence.calls],
        }
        if variant is None:
            record["status"] = "rejected_by_interpreter"
            trace["rejected_child_count"] += 1
            trace["children"].append(record)
            continue
        score = _candidate_score(variant, base_area=base_area)
        record["status"] = "accepted_for_legal_pipeline"
        record["prelegal_score"] = score
        variants.append(variant)
        trace["accepted_child_count"] += 1
        trace["children"].append(record)

    variants.sort(key=lambda variant: _candidate_score(variant, base_area=base_area), reverse=True)
    counts: dict[str, int] = {}
    for item in trace["children"]:
        if item.get("status") == "accepted_for_legal_pipeline":
            op = str(item.get("verbs", ["unknown"])[-1] if item.get("verbs") else "unknown")
            counts[op] = counts.get(op, 0) + 1
    trace["operator_counts"] = dict(sorted(counts.items()))
    trace["island_child_budget"] = {
        island: sum(1 for item in trace["children"] if item.get("island") == island)
        for island in sorted(island_map)
    }
    trace["status"] = "generated" if variants else "no_accepted_children"
    return EvolutionResult(variants, trace)


__all__ = ["EvolutionResult", "evolve_massdsl_islands", "sequence_from_variant"]
