"""ARR MAAS grammar adapter."""

from backend.app.modules.design.generation.maas.grammar.intent import load_term_ontology, resolve_intent_to_sequence
from backend.app.modules.design.generation.maas.grammar.legal_interpreter import generate_grammar_variants, interpret_sequence
from backend.app.modules.design.generation.maas.grammar.sequence_library import SEQUENCES, get_sequence_label
from backend.app.modules.design.generation.maas.grammar.verb_sequence import VerbCall, VerbSequence

__all__ = [
    "SEQUENCES",
    "VerbCall",
    "VerbSequence",
    "generate_grammar_variants",
    "get_sequence_label",
    "interpret_sequence",
    "load_term_ontology",
    "resolve_intent_to_sequence",
]
