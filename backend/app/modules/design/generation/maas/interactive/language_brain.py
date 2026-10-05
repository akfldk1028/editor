"""Reference principles to program-neutral architectural-language mutations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.modules.design.generation.maas.grammar.verb_sequence import VerbSequence
from backend.app.modules.design.generation.maas.program_massing.creative import creative_seed_sequences


LANGUAGE_BRAIN_SCHEMA_VERSION = "arr.maas.architectural_language_brain.v1"

LANGUAGE_SIGNALS = {
    "creative_ribbon_campus": ("flowing", "ribbon", "landscape roof", "continuous roof", "유선", "리본", "흐르는"),
    "creative_arc_court": ("curved court", "arc", "embracing", "곡선 중정", "감싸는", "호형"),
    "creative_folded_spine": ("folded", "fold", "ridge", "sectional roof", "접힌", "절판", "지붕 골"),
    "creative_voxel_cascade": ("interlocking", "voxel", "lego", "modular blocks", "레고", "맞물", "블록"),
    "creative_cluster_village": ("village", "cluster", "small blocks", "campus", "마을", "군집", "클러스터"),
    "creative_cross_cantilever": ("cross", "cantilever", "projecting bars", "십자", "캔틸레버", "돌출"),
    "creative_fan_plates": ("fan", "radiating", "splayed plates", "부채", "방사", "펼쳐"),
    "creative_bridge_canyon": ("canyon", "bridge", "split wings", "협곡", "브리지", "분리동"),
    "creative_sky_bridge_court": ("sky bridge", "elevated connector", "공중 브리지", "상부 연결"),
    "creative_diagonal_court": ("diagonal", "oblique", "사선", "대각"),
    "creative_gateway_court": ("gateway", "portal", "threshold", "게이트", "문", "진입"),
    "creative_terrace_bowl": ("bowl", "sunken court", "terraced court", "그릇", "선큰", "단차 중정"),
    "creative_ring_stack": ("ring", "raised courtyard", "elevated ring", "링", "환형", "들린 중정"),
    "creative_pinwheel_court": ("pinwheel", "rotating court", "바람개비", "회전 중정"),
    "creative_court_bar": ("courtyard", "perimeter", "중정", "ㅁ자", "안뜰"),
    "creative_cantilever_stack": ("stacked cantilever", "floating slab", "부유", "적층 캔틸레버"),
    "creative_zigzag_terraces": ("zigzag", "terraces", "지그재그", "테라스"),
    "creative_terraced_cluster": ("stepped cluster", "terraced cluster", "단차 군집", "계단식 군집"),
    "creative_podium_twins": ("twin towers", "podium", "쌍둥이", "포디움"),
    "creative_shifted_bar": ("shifted bars", "offset bars", "엇갈린", "시프트 바"),
}

DIVERSITY_GROUPS = {
    "ribbon": {"creative_ribbon_campus", "creative_arc_court", "creative_folded_spine"},
    "cluster": {"creative_voxel_cascade", "creative_cluster_village"},
    "cantilever": {"creative_cross_cantilever", "creative_fan_plates", "creative_cantilever_stack"},
    "bridge": {"creative_bridge_canyon", "creative_sky_bridge_court", "creative_gateway_court"},
    "court": {"creative_terrace_bowl", "creative_ring_stack", "creative_pinwheel_court", "creative_court_bar"},
    "bars": {"creative_diagonal_court", "creative_zigzag_terraces", "creative_terraced_cluster", "creative_podium_twins", "creative_shifted_bar"},
}

# Conversational language names are stable UI concepts.  They resolve to the
# program-neutral formal graph library; they are not separate fixed component
# assemblies.  This keeps reference-driven revisions compatible while ensuring
# that a "ribbon" or "cluster" request enters the same graph mutation/compiler
# path as autonomous exploration.
LANGUAGE_GRAPH_BINDINGS = {
    "creative_ribbon_campus": "creative_graph_bend_ribbon_court",
    "creative_arc_court": "creative_graph_bend_ribbon_court",
    "creative_folded_spine": "creative_graph_sloped_roof_envelope",
    "creative_voxel_cascade": "creative_graph_interlock_step_taper",
    "creative_cluster_village": "creative_graph_branch_pinch_taper",
    "creative_cross_cantilever": "creative_graph_interlock_step_taper",
    "creative_fan_plates": "creative_graph_branch_pinch_taper",
    "creative_bridge_canyon": "creative_graph_split_lift_stepback",
    "creative_sky_bridge_court": "creative_graph_diagonal_step_connector",
    "creative_diagonal_court": "creative_graph_diagonal_step_connector",
    "creative_gateway_court": "creative_graph_split_lift_stepback",
    "creative_terrace_bowl": "creative_graph_courtyard_lift_taper",
    "creative_ring_stack": "creative_graph_clean_courtyard_block",
    "creative_pinwheel_court": "creative_graph_branch_pinch_taper",
    "creative_court_bar": "creative_graph_clean_courtyard_block",
    "creative_cantilever_stack": "creative_graph_overlap_shift_terrace",
    "creative_zigzag_terraces": "creative_graph_terrace_ribbon_stepback",
    "creative_terraced_cluster": "creative_graph_overlap_shift_terrace",
    "creative_podium_twins": "creative_graph_podium_tower_offset",
    "creative_shifted_bar": "creative_graph_clean_shifted_slab",
}


def _bound_language_sequences() -> dict[str, VerbSequence]:
    graphs = {seed.name: seed for seed in creative_seed_sequences()}
    result: dict[str, VerbSequence] = {}
    for language_name, graph_name in LANGUAGE_GRAPH_BINDINGS.items():
        graph = graphs.get(graph_name)
        if graph is None:
            continue
        result[language_name] = VerbSequence(
            name=language_name,
            label=graph.label,
            calls=graph.calls,
            notes=graph.notes + (f"language_alias_for={graph_name}",),
        )
    return result


@dataclass(frozen=True)
class LanguageMutationProposal:
    sequence: VerbSequence
    diversity_group: str
    confidence: float
    matched_signals: tuple[str, ...]
    alternatives: tuple[dict[str, Any], ...]

    def evidence(self) -> dict[str, Any]:
        return {
            "schema_version": LANGUAGE_BRAIN_SCHEMA_VERSION,
            "operation": "replace_topology",
            "target_language": self.sequence.name,
            "diversity_group": self.diversity_group,
            "confidence": self.confidence,
            "matched_signals": list(self.matched_signals),
            "alternatives": list(self.alternatives),
            "program_conditioned": False,
            "law_parking_override": False,
        }


def propose_language_mutation(
    *,
    reference_intent: dict[str, Any],
    instruction: str = "",
    current_language: str = "",
    used_languages: tuple[str, ...] = (),
) -> LanguageMutationProposal | None:
    text = " ".join([
        str(instruction or ""),
        *[str(item) for item in reference_intent.get("reference_principles") or []],
        *[str(item) for item in reference_intent.get("operation_rationales") or []],
    ]).lower()
    used = set(used_languages)
    seeds = _bound_language_sequences()
    ranked: list[tuple[float, str, tuple[str, ...]]] = []
    for name, signals in LANGUAGE_SIGNALS.items():
        if name not in seeds:
            continue
        matches = tuple(signal for signal in signals if signal in text)
        score = float(len(matches))
        if name == current_language:
            score -= 1.25
        if name in used:
            score -= 3.0
        ranked.append((score, name, matches))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    if not ranked or ranked[0][0] <= 0.0:
        return None
    score, name, matches = ranked[0]
    group = next((key for key, values in DIVERSITY_GROUPS.items() if name in values), "other")
    confidence = round(min(0.96, 0.58 + score * 0.10), 3)
    alternatives = tuple({
        "target_language": candidate_name,
        "score": round(candidate_score, 3),
        "matched_signals": list(candidate_matches),
    } for candidate_score, candidate_name, candidate_matches in ranked[:4])
    return LanguageMutationProposal(seeds[name], group, confidence, matches, alternatives)


__all__ = ["LANGUAGE_BRAIN_SCHEMA_VERSION", "LanguageMutationProposal", "propose_language_mutation"]
