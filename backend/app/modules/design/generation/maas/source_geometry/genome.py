"""Intermediate massing genome for architecture-grade MAAS generation.

The genome is the contract between language agents and geometry compilation.
It keeps architectural intent separate from low-level source-volume math so
words such as "taper" or "lift" cannot accidentally collapse every candidate
back into a stepped/podium template.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.modules.design.generation.maas.grammar.verb_sequence import VerbSequence

from backend.app.modules.design.generation.maas.source_geometry.formal_principles import normalize_formal_principle


GENOME_SCHEMA_VERSION = "arr.maas.massing_genome.v1"
GENOME_CIRCUIT_SCHEMA_VERSION = "arr.maas.genome_attribution_circuit.v1"

FAMILY_FORMAL_PRINCIPLES = {
    "courtyard": "carved_atrium",
    "void_notch": "carved_monolith",
    "embed": "carved_monolith",
    "nest": "carved_monolith",
    "split": "split_bridge_connector",
    "diagonal_connect": "split_bridge_connector",
    "sloped_roof": "folded_section",
    "terrace_link": "folded_section",
    "overlap": "stacked_shifted_platforms",
    "offset": "stacked_shifted_platforms",
    "array_cluster": "stacked_shifted_platforms",
    "reflected_pair": "stacked_shifted_platforms",
    "stack": "stacked_shifted_platforms",
    "interlock": "torqued_stack",
    "bend": "continuous_ribbon_field",
    "branch": "torqued_stack",
    "pinch": "torqued_stack",
    "extrude": "slender_podium_tower",
    "slender_bar": "folded_section",
    "stepback_tower": "slender_podium_tower",
}

PRINCIPLE_REFERENCE_BASIS = {
    "slender_podium_tower": "Trimage-like podium/tower proportion principle",
    "undercut_tapered_tower": "Vancouver House/BIG-like undercut and taper principle",
    "torqued_stack": "BIG-like torque/stacked plate transformation principle",
    "stacked_shifted_platforms": "OMA/Seattle Library-like shifted platform and diagrammatic section principle",
    "folded_section": "folded section and legal-envelope roof-plane principle",
    "continuous_ribbon_field": "continuous circulation and roof-field massing principle",
    "carved_atrium": "courtyard/atrium figure-ground carving principle",
    "split_bridge_connector": "split mass with bridge connector principle",
    "carved_monolith": "carved monolith and embedded void principle",
}

PRINCIPLE_DOMINANT_GESTURE = {
    "slender_podium_tower": "podium anchors a more slender upper mass",
    "undercut_tapered_tower": "ground is carved while the upper mass tapers",
    "torqued_stack": "stacked plates rotate around a stabilizing core",
    "stacked_shifted_platforms": "program platforms shift into a readable sectional diagram",
    "folded_section": "roof and mass fold with the legal envelope",
    "continuous_ribbon_field": "a connected plan ribbon rises as a continuous roof and circulation field",
    "carved_atrium": "solid bars define an atrium void",
    "split_bridge_connector": "two masses are separated and reconnected by a bridge",
    "carved_monolith": "a compact solid is carved by a legible void",
}

PRINCIPLE_STRATEGIES = {
    "slender_podium_tower": {
        "void_strategy": "ground_or_podium_carve",
        "vertical_strategy": "podium_tower",
        "connector_strategy": "core_or_liner",
        "silhouette_strategy": "slender_upper",
    },
    "undercut_tapered_tower": {
        "void_strategy": "undercut_ground",
        "vertical_strategy": "tapered_upper",
        "connector_strategy": "core",
        "silhouette_strategy": "taper",
    },
    "torqued_stack": {
        "void_strategy": "plate_gap",
        "vertical_strategy": "rotated_stack",
        "connector_strategy": "stabilizing_core",
        "silhouette_strategy": "torque",
    },
    "stacked_shifted_platforms": {
        "void_strategy": "platform_offset_gap",
        "vertical_strategy": "shifted_platforms",
        "connector_strategy": "datum_core",
        "silhouette_strategy": "stepped_without_stair_envelope",
    },
    "folded_section": {
        "void_strategy": "sectional_cut",
        "vertical_strategy": "folded_planes",
        "connector_strategy": "fold_or_ribbon",
        "silhouette_strategy": "folded_roof",
    },
    "continuous_ribbon_field": {
        "void_strategy": "inter_ribbon_courts",
        "vertical_strategy": "continuous_rising_field",
        "connector_strategy": "ribbon_overlap",
        "silhouette_strategy": "flowing_profile",
    },
    "carved_atrium": {
        "void_strategy": "atrium_court",
        "vertical_strategy": "bar_around_void",
        "connector_strategy": "bridge_or_liner",
        "silhouette_strategy": "figure_ground",
    },
    "split_bridge_connector": {
        "void_strategy": "split_gap",
        "vertical_strategy": "separated_wings",
        "connector_strategy": "bridge",
        "silhouette_strategy": "linked_masses",
    },
    "carved_monolith": {
        "void_strategy": "carved_solid",
        "vertical_strategy": "monolith_with_void",
        "connector_strategy": "void_liner",
        "silhouette_strategy": "carved_block",
    },
}


@dataclass(frozen=True)
class MassingGenome:
    family: str
    formal_principle: str
    reference_basis: str
    dominant_gesture: str
    void_strategy: str
    vertical_strategy: str
    connector_strategy: str
    silhouette_strategy: str
    inference_source: str
    stair_like_risk: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": GENOME_SCHEMA_VERSION,
            "family": self.family,
            "formal_principle": self.formal_principle,
            "reference_basis": self.reference_basis,
            "dominant_gesture": self.dominant_gesture,
            "void_strategy": self.void_strategy,
            "vertical_strategy": self.vertical_strategy,
            "connector_strategy": self.connector_strategy,
            "silhouette_strategy": self.silhouette_strategy,
            "inference_source": self.inference_source,
            "stair_like_risk": self.stair_like_risk,
        }

    def to_circuit(self) -> dict[str, Any]:
        nodes = [
            {
                "id": "source.family",
                "layer": "source",
                "kind": "language_feature",
                "label": self.family,
                "evidence": {"family": self.family, "inference_source": self.inference_source},
            },
            {
                "id": "concept.formal_principle",
                "layer": "concept",
                "kind": "formal_principle",
                "label": self.formal_principle,
                "evidence": {
                    "reference_basis": self.reference_basis,
                    "dominant_gesture": self.dominant_gesture,
                },
            },
            {
                "id": "strategy.void",
                "layer": "strategy",
                "kind": "void_strategy",
                "label": self.void_strategy,
            },
            {
                "id": "strategy.vertical",
                "layer": "strategy",
                "kind": "vertical_strategy",
                "label": self.vertical_strategy,
            },
            {
                "id": "strategy.connector",
                "layer": "strategy",
                "kind": "connector_strategy",
                "label": self.connector_strategy,
            },
            {
                "id": "strategy.silhouette",
                "layer": "strategy",
                "kind": "silhouette_strategy",
                "label": self.silhouette_strategy,
            },
            {
                "id": "risk.stair_like",
                "layer": "critic",
                "kind": "risk_feature",
                "label": self.stair_like_risk,
            },
            {
                "id": "action.source_geometry_compile",
                "layer": "agent_action",
                "kind": "compiler_action",
                "label": "compile source volumes inside legal envelope",
            },
        ]
        edges = [
            {
                "source": "source.family",
                "target": "concept.formal_principle",
                "kind": "evidence_to_concept",
                "weight": 1.0 if self.inference_source == "family_priority" else 0.72,
                "evidence": self.inference_source,
            },
            {
                "source": "concept.formal_principle",
                "target": "strategy.void",
                "kind": "concept_to_strategy",
                "weight": 0.85,
            },
            {
                "source": "concept.formal_principle",
                "target": "strategy.vertical",
                "kind": "concept_to_strategy",
                "weight": 0.85,
            },
            {
                "source": "concept.formal_principle",
                "target": "strategy.connector",
                "kind": "concept_to_strategy",
                "weight": 0.70,
            },
            {
                "source": "concept.formal_principle",
                "target": "strategy.silhouette",
                "kind": "concept_to_strategy",
                "weight": 0.85,
            },
            {
                "source": "strategy.silhouette",
                "target": "risk.stair_like",
                "kind": "strategy_to_critic",
                "weight": 0.40 if self.stair_like_risk == "managed" else 0.90,
            },
            {
                "source": "strategy.void",
                "target": "action.source_geometry_compile",
                "kind": "strategy_to_action",
                "weight": 0.80,
            },
            {
                "source": "strategy.vertical",
                "target": "action.source_geometry_compile",
                "kind": "strategy_to_action",
                "weight": 0.90,
            },
            {
                "source": "strategy.connector",
                "target": "action.source_geometry_compile",
                "kind": "strategy_to_action",
                "weight": 0.72,
            },
            {
                "source": "risk.stair_like",
                "target": "action.source_geometry_compile",
                "kind": "critic_to_action_gate",
                "weight": 0.35 if self.stair_like_risk == "managed" else -0.70,
            },
        ]
        return {
            "schema_version": GENOME_CIRCUIT_SCHEMA_VERSION,
            "graph_type": "layered_attribution_flow",
            "note": "Not a true LLM activation graph; this is an evidence-backed MAAS agent decision circuit.",
            "nodes": nodes,
            "edges": edges,
        }


def _language_tokens(
    sequence: VerbSequence,
    *,
    family: str | None,
    primary_language: str,
    secondary_language: str,
) -> str:
    return " ".join(
        [
            sequence.name,
            sequence.label,
            family or "",
            primary_language,
            secondary_language,
            " ".join(sequence.notes),
        ]
    ).lower()


def infer_formal_principle_from_language(
    sequence: VerbSequence,
    *,
    family: str | None,
    primary_language: str = "",
    secondary_language: str = "",
) -> tuple[str, str]:
    if family in FAMILY_FORMAL_PRINCIPLES:
        return FAMILY_FORMAL_PRINCIPLES[family], "family_priority"
    tokens = _language_tokens(
        sequence,
        family=family,
        primary_language=primary_language,
        secondary_language=secondary_language,
    )
    if any(token in tokens for token in ("podium", "tower", "타워", "포디움")):
        return "slender_podium_tower", "language_token"
    if any(token in tokens for token in ("torque", "twist", "interlock", "교차")):
        return "torqued_stack", "language_token"
    if any(token in tokens for token in ("overlap", "shift", "stack", "slab", "플랫폼", "스택", "어긋")):
        return "stacked_shifted_platforms", "language_token"
    if any(token in tokens for token in ("split", "bridge", "connector", "diagonal", "분절", "브릿지", "사선")):
        return "split_bridge_connector", "language_token"
    if any(token in tokens for token in ("sloped", "roof", "terrace", "fold", "사선지붕", "테라스")):
        return "folded_section", "language_token"
    if any(token in tokens for token in ("courtyard", "atrium", "court", "중정", "아트리움")):
        return "carved_atrium", "language_token"
    if any(token in tokens for token in ("void", "cave", "embed", "nest", "carve", "보이드", "케이브", "임베드", "네스트")):
        return "carved_monolith", "language_token"
    if any(token in tokens for token in ("undercut", "taper", "테이퍼", "vancouver")):
        return "undercut_tapered_tower", "low_priority_taper_token"
    return "", "unresolved"


def build_massing_genome(
    sequence: VerbSequence,
    *,
    family: str | None,
    primary_language: str = "",
    secondary_language: str = "",
    formal_principle: str = "",
    reference_basis: str = "",
    dominant_gesture: str = "",
) -> MassingGenome | None:
    principle = normalize_formal_principle(formal_principle)
    inference_source = "explicit"
    if not principle:
        principle, inference_source = infer_formal_principle_from_language(
            sequence,
            family=family,
            primary_language=primary_language,
            secondary_language=secondary_language,
        )
    if not principle:
        return None
    strategies = PRINCIPLE_STRATEGIES.get(principle, {})
    stair_like_risk = "high" if inference_source == "low_priority_taper_token" else "managed"
    return MassingGenome(
        family=str(family or ""),
        formal_principle=principle,
        reference_basis=reference_basis or PRINCIPLE_REFERENCE_BASIS.get(principle, ""),
        dominant_gesture=dominant_gesture or PRINCIPLE_DOMINANT_GESTURE.get(principle, principle),
        void_strategy=str(strategies.get("void_strategy") or ""),
        vertical_strategy=str(strategies.get("vertical_strategy") or ""),
        connector_strategy=str(strategies.get("connector_strategy") or ""),
        silhouette_strategy=str(strategies.get("silhouette_strategy") or ""),
        inference_source=inference_source,
        stair_like_risk=stair_like_risk,
    )


__all__ = [
    "FAMILY_FORMAL_PRINCIPLES",
    "GENOME_CIRCUIT_SCHEMA_VERSION",
    "GENOME_SCHEMA_VERSION",
    "MassingGenome",
    "build_massing_genome",
    "infer_formal_principle_from_language",
]
