"""Compile program profiles into stable MassDSL seed sequences."""

from __future__ import annotations

from typing import Any

from shapely.geometry import Polygon

from backend.app.modules.design.generation.maas.grammar.verb_sequence import VerbSequence, call
from backend.app.modules.design.generation.maas.program_massing.profiles import resolve_program_profile
from backend.app.modules.design.generation.maas.program_massing.section_graph import program_section_graph_note


def program_seed_sequences(building_type: str) -> tuple[VerbSequence, ...]:
    profile = resolve_program_profile(building_type)
    sequences: list[VerbSequence] = []
    for record in profile.get("sequences") or []:
        calls = tuple(call(str(item["verb"]), **dict(item.get("params") or {})) for item in record.get("calls") or [])
        section_graph = record.get("section_graph") if isinstance(record.get("section_graph"), dict) else None
        section_notes = (program_section_graph_note(section_graph),) if section_graph is not None else ()
        sequence = VerbSequence(
            name=str(record.get("name") or f"program_{profile['id']}_seed"),
            label=f"{profile['id']} program seed",
            calls=calls,
            notes=(
                f"program_profile={profile['id']}",
                f"program_design_intent={profile['design_intent']}",
                "parameter_source=program_massing_profile_v1",
                *section_notes,
            ),
        )
        if not sequence.validate():
            sequences.append(sequence)
    return tuple(sequences)


def program_archive_sequences(
    base_footprint: Polygon,
    building_type: str,
    *,
    target_count: int = 20,
) -> tuple[VerbSequence, ...]:
    """Return program seeds plus searched variations for the legal candidate pool."""
    seeds = list(program_seed_sequences(building_type))
    if not seeds or target_count <= len(seeds):
        return tuple(seeds[:target_count])
    from backend.app.modules.design.generation.maas.program_massing.search import search_program_elites

    profile = resolve_program_profile(building_type)
    floor_min = int((profile.get("target_floor_range") or [1])[0])
    elites, _ = search_program_elites(
        base_footprint,
        building_type=building_type,
        height=max(3.0, floor_min * 3.0),
        floors=max(1, floor_min),
        generations=3,
        offspring_per_seed=10,
        target_count=target_count,
    )
    sequences: list[VerbSequence] = []
    seen: set[tuple[Any, ...]] = set()
    for elite in elites:
        signature = _override_signature(elite.sequence)
        if signature in seen:
            continue
        seen.add(signature)
        sequences.append(elite.sequence)
        if len(sequences) >= target_count:
            break
    for seed in seeds:
        if len(sequences) >= target_count:
            break
        signature = _override_signature(seed)
        if signature not in seen:
            seen.add(signature)
            sequences.append(seed)
    return tuple(sequences[:target_count])


def creative_archive_sequences(
    base_footprint: Polygon,
    *,
    target_count: int = 20,
) -> tuple[VerbSequence, ...]:
    """Return the program-neutral source archive used before program/legal projection."""
    from backend.app.modules.design.generation.maas.program_massing.creative import creative_seed_sequences

    seeds = list(creative_seed_sequences())
    if target_count < len(seeds):
        return tuple(seeds[:target_count])
    from backend.app.modules.design.generation.maas.program_massing.search import search_creative_elites

    elites, _ = search_creative_elites(
        base_footprint,
        generations=3,
        offspring_per_seed=10,
        target_count=target_count,
    )
    sequences: list[VerbSequence] = []
    seen: set[tuple[Any, ...]] = set()
    for elite in elites:
        signature = _override_signature(elite.sequence)
        if signature in seen:
            continue
        seen.add(signature)
        sequences.append(elite.sequence)
        if len(sequences) >= target_count:
            break
    for seed in seeds:
        if len(sequences) >= target_count:
            break
        signature = _override_signature(seed)
        if signature not in seen:
            seen.add(signature)
            sequences.append(seed)
    return tuple(sequences[:target_count])


def _override_signature(sequence: VerbSequence) -> tuple[Any, ...]:
    return tuple(
        (item.verb, tuple(sorted((str(key), str(value)) for key, value in item.params.items())))
        for item in sequence.calls
    )


__all__ = ["creative_archive_sequences", "program_archive_sequences", "program_seed_sequences"]
