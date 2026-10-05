"""One table, read from the one file per word that MassAgent owns.

MassAgent is what generates a mass, so the language it generates in belongs to
it: `agents/MassAgent/book-language/verbs/<verb>.json` is the word - the BOOK's
own definition of it, the operator that executes it, and whether anyone has
read the rival implementation massv2 carries. Nothing here restates any of
that; it loads it. Adding a word means adding a file.

The table used to be `_BOOK_VERB_CANONICAL_EFFECT`, private inside
`geometry_language.book_adapter`, where the half of the system that needed it
most could not see it. massv2 wrote its own `carve`, its own `stack`, its own
`taper` - thirty-one words in all - and the two halves drifted until they
contradicted each other outright:

    BOOK: shear -> slice        massv2: shear pushes a volume sideways
    BOOK: skew  -> shear        massv2: skew leans it over
    BOOK: stack -> step         massv2: stack appends tiers beside the body

A sentence that says `shear` does not say which of those it meant, and neither
does the jury sheet that marks it down.
"""

from __future__ import annotations

from backend.app.modules.design.generation import paths as _design_paths

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.app.modules.design.generation.maas.book_language.registry import book_base_verbs


class BookLanguageUnavailable(RuntimeError):
    """The word files are missing, so no BOOK word can be resolved.

    Loudly, rather than falling back to a copy kept here: a second copy is how
    the two halves came to disagree in the first place.
    """


def _language_dir() -> Path:
    """`agents/MassAgent/book-language`, or MASSAGENT_ROOT if it is set."""

    root = os.environ.get("MASSAGENT_ROOT")
    if root:
        return Path(root) / "book-language"
    # backend/design/maas/book_language/execution -> 25_ACE
    return _design_paths.package_root("design/maas/book_language/data")


def _verbs_dir() -> Path:
    return _language_dir() / "verbs"


@lru_cache(maxsize=1)
def _words() -> dict[str, dict[str, Any]]:
    directory = _verbs_dir()
    if not directory.is_dir():
        raise BookLanguageUnavailable(
            f"BOOK word files not found at {directory}. MassAgent owns the "
            "language; set MASSAGENT_ROOT or check out the submodule.")
    found: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        found[str(record.get("verb") or path.stem)] = record
    if not found:
        raise BookLanguageUnavailable(f"no BOOK word files in {directory}")
    return found


def book_verbs() -> frozenset[str]:
    """Every word the BOOK can execute."""

    return frozenset(_words()) | book_base_verbs()


def operator_for(verb: str) -> str | None:
    """The geometry-language operator that realizes this BOOK word."""

    record = _words().get(str(verb))
    return str(record["executed_by"]) if record else None


def semantics_of(verb: str) -> dict[str, Any]:
    """The BOOK's own reading of the word, as its file records it."""

    record = _words().get(str(verb))
    if record is None:
        return {}
    return {
        "action": record.get("action", ""),
        "topology": record.get("topology", ""),
        "variation_parameters": tuple(record.get("variation_parameters") or ()),
        "orientation_modes": tuple(record.get("orientation_modes") or ()),
    }


@lru_cache(maxsize=1)
def base_volumes() -> dict[str, dict[str, Any]]:
    """The first third of the BOOK's grammar: which relative solid to act on.

    The BOOK does not begin with a parcel-sized box. It begins by choosing a
    fraction of the whole - 1/1, 3/8, 1/2, 1/4, 1/8, 1/16 - and an orientation
    for it, and only then performs one action and explores its bounded
    variations. A word file carries the action; these carry what it acts on.
    """

    directory = _language_dir() / "base-volumes"
    if not directory.is_dir():
        raise BookLanguageUnavailable(f"BOOK base volumes not found at {directory}")
    found = {}
    for path in sorted(directory.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        found[str(record["label"])] = record
    return found


@lru_cache(maxsize=1)
def massv2_only_verbs() -> dict[str, dict[str, Any]]:
    """Words massv2 has that the BOOK does not carry.

    `crown`, `fold`, `gable`, `mansard`, `butterfly`, `vault`, `loop`,
    `aggregate`, `align`, `approach` and the rest: fifteen words that say things
    about roofs, rings, fields and regulating lines the BOOK's thirty-five
    cannot. They cannot be reconciled with anything - only kept or retired -
    and they are recorded so the language an agent reads is the whole language
    rather than the BOOK half of it.
    """

    directory = _language_dir() / "massv2-verbs"
    if not directory.is_dir():
        return {}
    found = {}
    for path in sorted(directory.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        found[str(record["verb"])] = record
    return found


def grammar_of(verb: str) -> dict[str, Any]:
    """All three parts of the BOOK sentence this word can stand in."""

    record = _words().get(str(verb)) or {}
    return {
        "layer": record.get("book_layer", ""),
        "base_volume_labels": tuple((record.get("book_grammar") or {}).get(
            "base_volume_labels") or ()),
        "orientations": tuple((record.get("book_grammar") or {}).get("orientations") or ()),
        "bounded_variations": (record.get("book_grammar") or {}).get("bounded_variations"),
        "evidence": tuple(record.get("book_evidence") or ()),
        "aggregation_evidence": tuple(record.get("book_aggregation_evidence") or ()),
    }


def divergence_of(verb: str) -> tuple[bool, str]:
    """(has a rival implementation in massv2, the recorded reading)."""

    record = _words().get(str(verb)) or {}
    return bool(record.get("massv2_implements_it_too")), str(record.get("divergence") or "")


class _Table(dict):
    """Reads the word files on first use, so import order cannot matter."""

    def __missing__(self, key):  # pragma: no cover - dict protocol
        raise KeyError(key)


def _table() -> dict[str, str]:
    return {verb: str(record["executed_by"]) for verb, record in sorted(_words().items())}


def _declared() -> dict[str, str]:
    return {verb: str(record.get("divergence") or "")
            for verb, record in sorted(_words().items())
            if record.get("reviewed") and record.get("divergence")}


BOOK_VERB_OPERATOR: dict[str, str] = _table()
DECLARED_DIVERGENCES: dict[str, str] = _declared()
