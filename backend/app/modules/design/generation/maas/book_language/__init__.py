"""Architect-supplied operative-design language evidence."""
"""Architect-supplied BOOK corpus and executable-language registry."""

from backend.app.modules.design.generation.maas.book_language.registry import BASE_OPERATIVES, book_base_verbs, build_book_language_registry, principles_for_verbs
from backend.app.modules.design.generation.maas.book_language.semantics import BASE_VOLUME_FRACTIONS, OPERATION_SEMANTICS, semantics_for


def audited_book_language_registry():
    """Build the registry with live compiler evidence without import cycles."""
    from backend.app.modules.design.generation.maas.book_language.compile_audit import audit_book_principles

    return build_book_language_registry(audit_book_principles())

__all__ = [
    "BASE_OPERATIVES",
    "BASE_VOLUME_FRACTIONS",
    "OPERATION_SEMANTICS",
    "audited_book_language_registry",
    "book_base_verbs",
    "build_book_language_registry",
    "principles_for_verbs",
    "semantics_for",
]
