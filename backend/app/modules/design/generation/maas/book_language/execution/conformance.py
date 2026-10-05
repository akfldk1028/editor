"""Which BOOK words massv2 has implemented for itself, and whether anyone said so.

The BOOK is the language; a second implementation of one of its words is a
dialect. A dialect is allowed - `shear` really is used both ways and the
sentences that rely on each are already written - but it has to be written
down, because the cost of an undeclared one is paid downstream by a jury who
sees a building that does not match its sentence and marks the concept down
without being able to say why.

`undeclared_divergences` is the number this package exists to bring to zero.
It does not fall by deleting a verb; it falls by somebody reading the two
implementations of one word and either reconciling them or recording the
reading in `DECLARED_DIVERGENCES`.
"""

from __future__ import annotations

from typing import Any

from backend.app.modules.design.generation.maas.book_language.execution.canonical import BOOK_VERB_OPERATOR, divergence_of


def _massv2_verbs() -> frozenset[str]:
    """Imported here, not at module scope: the BOOK side must not need massv2."""

    from backend.app.modules.design.generation.maas.massv2.execute import _VERBS

    return frozenset(_VERBS)


def conformance_report() -> dict[str, Any]:
    """One row per BOOK word: its operator, and any rival implementation."""

    rivals = _massv2_verbs()
    rows = []
    for verb in sorted(BOOK_VERB_OPERATOR):
        recorded_rival, reading = divergence_of(verb)
        # The word file says whether massv2 carries its own; the live table is
        # the check on that claim, so a verb added to `_VERBS` without touching
        # its word file still shows up here.
        has_rival = verb in rivals or recorded_rival
        rows.append({
            "verb": verb,
            "book_operator": BOOK_VERB_OPERATOR[verb],
            "massv2_implements_it_too": has_rival,
            "divergence_declared": bool(reading.strip()),
            "reading": reading,
        })
    undeclared = [row["verb"] for row in rows
                  if row["massv2_implements_it_too"] and not row["divergence_declared"]]
    return {
        "schema_version": "arr.maas.book_verb_conformance.v1",
        "book_words": len(rows),
        "implemented_twice": sum(1 for row in rows if row["massv2_implements_it_too"]),
        "declared": sum(1 for row in rows if row["divergence_declared"]),
        "undeclared": undeclared,
        "rows": rows,
    }


def undeclared_divergences() -> tuple[str, ...]:
    """BOOK words massv2 also implements, with nobody having said why."""

    return tuple(conformance_report()["undeclared"])
