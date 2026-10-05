"""Where the BOOK's words meet the code that executes them.

The BOOK is the language. `registry` says which words it has, `semantics` says
what each one does to a solid, and `geometry_language` executes them. massv2's
`_VERBS` grew up beside all of that with its own implementations of thirty-one
of the same words, and nothing connected the two: `shear` means a push in one
half and a slice in the other, `skew` means a lean in one and a shear in the
other, and a sentence never says which half it meant.

This package is the join. `canonical` is the single table of BOOK word to the
operator that realizes it - one owner, everything else derived - and
`conformance` measures every rival definition so a disagreement has to be
written down rather than discovered in a jury sheet.
"""

from backend.app.modules.design.generation.maas.book_language.execution.canonical import BOOK_VERB_OPERATOR, DECLARED_DIVERGENCES, base_volumes, book_verbs, grammar_of, massv2_only_verbs, operator_for, semantics_of
from backend.app.modules.design.generation.maas.book_language.execution.conformance import conformance_report, undeclared_divergences

__all__ = [
    "BOOK_VERB_OPERATOR",
    "DECLARED_DIVERGENCES",
    "base_volumes",
    "book_verbs",
    "grammar_of",
    "massv2_only_verbs",
    "semantics_of",
    "conformance_report",
    "operator_for",
    "undeclared_divergences",
]
