"""Executable MAAS vocabulary.

BOOK operations are the architect-supplied language contract. ARR-specific
verbs extend that contract for legal envelopes, roofs and program assembly;
they must never be presented as a replacement for the BOOK principles.
"""

from backend.app.modules.design.generation.maas.book_language import book_base_verbs


BOOK_BASE_VERBS = set(book_base_verbs())
AGGREGATION_VERBS = {"array", "join", "pack", "reflect", "stack"}
ARR_EXTENSION_VERBS = {
    "base", "bar", "cave", "courtyard", "step_envelope",
    "diagonal_connect", "terrace_link", "sloped_roof_mass", "inset",
    "select_book_scope",
}

SUPPORTED_VERBS = BOOK_BASE_VERBS | AGGREGATION_VERBS | ARR_EXTENSION_VERBS

PLAN_VERBS = {
    "notch",
    "cave",
    "courtyard",
    "split",
    "branch",
    "pinch",
    "interlock",
    "overlap",
    "bar",
    "shift",
    "inset",
    "expand",
    "bend",
    "embed",
    "extrude",
    "nest",
    "stack",
    "offset",
    "array",
    "reflect",
    "inflate",
    "merge",
    "skew",
    "twist",
    "intersect",
    "lodge",
    "rotate",
    "carve",
    "compress",
    "fracture",
    "shear",
    "extract",
    "inscribe",
    "puncture",
    "pack",
    "join",
}

SECTION_VERBS = {"lift", "taper", "grade", "step_envelope"}
DESIGN_SECTION_VERBS = {"diagonal_connect", "terrace_link", "sloped_roof_mass"}


__all__ = [
    "AGGREGATION_VERBS", "ARR_EXTENSION_VERBS", "BOOK_BASE_VERBS",
    "DESIGN_SECTION_VERBS", "PLAN_VERBS", "SECTION_VERBS", "SUPPORTED_VERBS",
]
