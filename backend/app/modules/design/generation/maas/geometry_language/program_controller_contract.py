"""Shared authority rules for use-specific geometry controllers.

BOOK nodes describe how a base solid was transformed.  They are valuable
causal evidence, but they do not by themselves prove that a use-specific
public threshold, court, or passage exists.  This module keeps that boundary
identical in program projection, graph export, and final candidate analysis.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


PROGRAM_PROJECTION_SOURCE = "post_book_program_projection"
BOOK_PROJECTION_SOURCE = "book_recursive_projection"

ACCESS_BOUND_PROGRAM_OPERATORS = frozenset({
    "courtyard", "carve_void", "notch", "lift", "cantilever", "split_wing",
})
USABLE_PUBLIC_SPACE_OPERATORS = frozenset({
    "courtyard", "carve_void", "lift", "split_wing",
})

_PROGRAM_ROLE_TOKENS = frozenset({
    "threshold", "entry", "public", "court", "atrium", "ground", "access",
})


def _value(node: Any, field: str, fallback: Any = None) -> Any:
    if isinstance(node, Mapping):
        return node.get(field, fallback)
    return getattr(node, field, fallback)


def node_provenance(node: Any) -> Mapping[str, Any]:
    value = _value(node, "provenance", {})
    return value if isinstance(value, Mapping) else {}


def node_parameters(node: Any) -> Mapping[str, Any]:
    value = _value(node, "parameters", {})
    return value if isinstance(value, Mapping) else {}


def is_book_language_node(node: Any) -> bool:
    """Return True only for a causal BOOK projection node."""
    return str(node_provenance(node).get("source") or "") == BOOK_PROJECTION_SOURCE


def is_program_relation_candidate(node: Any) -> bool:
    """Whether a non-BOOK node may be resolved into a program controller.

    A generic universal form can contain an authored court or notch before a
    site access side is known.  That relation may be rebound after BOOK, while
    a BOOK Split/Branch/Bend must stay intact as BOOK evidence.
    """
    operator = str(_value(node, "operator", "") or "")
    if operator not in ACCESS_BOUND_PROGRAM_OPERATORS or is_book_language_node(node):
        return False
    provenance = node_provenance(node)
    if str(provenance.get("source") or "") == PROGRAM_PROJECTION_SOURCE:
        return True
    role = str(_value(node, "semantic_role", "") or "").strip().lower()
    return bool(
        provenance.get("program_invariant")
        or any(token in role for token in _PROGRAM_ROLE_TOKENS)
    )


def is_materialized_program_controller(node: Any) -> bool:
    """Return True for an explicit executable use relation, never BOOK alone."""
    return is_program_relation_candidate(node)


def relation_access_side(node: Any) -> str:
    operator = str(_value(node, "operator", "") or "")
    parameters = node_parameters(node)
    value = (
        parameters.get("open_side")
        if operator in {"courtyard", "carve_void"}
        else parameters.get("side")
        if operator == "notch"
        else parameters.get("access_side")
    )
    side = str(value or "closed").strip().lower()
    return side if side in {"east", "west", "north", "south"} else "closed"


def is_usable_public_space_controller(node: Any) -> bool:
    return bool(
        is_materialized_program_controller(node)
        and str(_value(node, "operator", "") or "") in USABLE_PUBLIC_SPACE_OPERATORS
    )


__all__ = [
    "ACCESS_BOUND_PROGRAM_OPERATORS",
    "BOOK_PROJECTION_SOURCE",
    "PROGRAM_PROJECTION_SOURCE",
    "USABLE_PUBLIC_SPACE_OPERATORS",
    "is_book_language_node",
    "is_materialized_program_controller",
    "is_program_relation_candidate",
    "is_usable_public_space_controller",
    "relation_access_side",
]
