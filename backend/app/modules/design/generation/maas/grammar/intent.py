"""Baseline architectural-intent to MAAS sequence resolver.

This is not the final fine-tuned model. It is the deterministic contract layer
that a future model must match: natural language in, strict sequence proposal
out, no raw geometry.
"""

from __future__ import annotations

from backend.app.modules.design.generation import paths as _design_paths

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.app.modules.design.generation.maas.grammar.sequence_library import SEQUENCES, load_sequence_metadata


TERM_ONTOLOGY_PATH = _design_paths.package_root('design/maas/grammar') / "data" / "maas_terms.v0.json"


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def _tokens(text: str) -> set[str]:
    normalized = _normalize(text)
    # Keep Korean substrings usable by also returning the full normalized text.
    parts = set(re.findall(r"[a-z0-9_]+|[가-힣]+", normalized))
    if normalized:
        parts.add(normalized)
    return parts


@lru_cache(maxsize=1)
def load_term_ontology(path: str | Path = TERM_ONTOLOGY_PATH) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as f:
        data = json.load(f)
    if data.get("schema_version") != "arr.maas.term_ontology.v0":
        raise ValueError("unsupported MAAS term ontology schema_version")
    terms = data.get("terms")
    if not isinstance(terms, list):
        raise ValueError("MAAS term ontology must contain a terms array")
    return data


def _term_matches(intent: str) -> tuple[list[str], list[str]]:
    ontology = load_term_ontology()
    normalized = _normalize(intent)
    matched_terms: list[str] = []
    matched_verbs: list[str] = []
    for term in ontology.get("terms", []):
        if not isinstance(term, dict):
            continue
        names = [term.get("id"), *(term.get("ko") or []), *(term.get("en") or [])]
        if any(isinstance(name, str) and _normalize(name) and _normalize(name) in normalized for name in names):
            matched_terms.append(str(term.get("id")))
            matched_verbs.extend(str(verb) for verb in term.get("verbs") or [])
    return matched_terms, matched_verbs


def resolve_intent_to_sequence(intent: str, *, top_k: int = 3) -> dict[str, Any]:
    """Return ranked MAAS sequence proposals for an architectural intent string."""
    if not isinstance(intent, str) or not intent.strip():
        return {
            "status": "needs_intent",
            "intent": intent or "",
            "proposals": [],
            "warnings": ["intent text is required"],
        }

    metadata = load_sequence_metadata()
    intent_norm = _normalize(intent)
    intent_tokens = _tokens(intent)
    matched_terms, matched_verbs = _term_matches(intent)
    matched_verb_set = set(matched_verbs)

    proposals: list[dict[str, Any]] = []
    for sequence in SEQUENCES:
        meta = metadata.get(sequence.name, {})
        aliases = [sequence.label, *meta.get("aliases", []), *meta.get("intent_tags", [])]
        alias_score = 0
        matched_aliases: list[str] = []
        for alias in aliases:
            if not isinstance(alias, str):
                continue
            alias_norm = _normalize(alias)
            if alias_norm and alias_norm in intent_norm:
                alias_score += 3
                matched_aliases.append(alias)
            else:
                overlap = _tokens(alias) & intent_tokens
                if overlap:
                    alias_score += len(overlap)
                    matched_aliases.append(alias)
        sequence_verbs = {call.verb for call in sequence.calls}
        verb_score = len(sequence_verbs & matched_verb_set)
        score = alias_score + verb_score * 2
        if score <= 0:
            continue
        proposals.append({
            "sequence": sequence.name,
            "label": sequence.label,
            "score": score,
            "matched_aliases": matched_aliases,
            "matched_terms": matched_terms,
            "matched_verbs": sorted(sequence_verbs & matched_verb_set),
            "maas_sequence": sequence.to_list(),
            "constraints": {
                "must_validate": ["bcr", "far", "height", "setback", "sunlight", "daylight"],
                "geometry_source_of_truth": "ARR/backend/design/maas",
            },
        })

    proposals.sort(key=lambda item: item["score"], reverse=True)
    if not proposals:
        return {
            "status": "needs_mapping",
            "intent": intent,
            "proposals": [],
            "matched_terms": matched_terms,
            "warnings": ["no sequence matched; add ontology aliases or fine-tuned translator data"],
        }
    return {
        "status": "ok",
        "intent": intent,
        "proposals": proposals[: max(1, top_k)],
        "matched_terms": matched_terms,
        "policy": {
            "llm_must_not_emit_raw_geometry": True,
            "geometry_source_of_truth": "ARR/backend/design/maas",
            "legal_pass_requires_evidence": True,
        },
    }


__all__ = ["TERM_ONTOLOGY_PATH", "load_term_ontology", "resolve_intent_to_sequence"]
