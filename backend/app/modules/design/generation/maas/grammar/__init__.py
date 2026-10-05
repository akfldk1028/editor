"""ARR MAAS grammar adapter."""

from backend.app.modules.design.generation.maas.grammar.intent import load_term_ontology, resolve_intent_to_sequence
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


def __getattr__(name):
    # The interpreter consumes source_geometry, whose compiler imports the
    # grammar data types. Loading it eagerly makes cold Mass CLI imports cyclic.
    if name in {'generate_grammar_variants', 'interpret_sequence'}:
        from backend.app.modules.design.generation.maas.grammar import legal_interpreter
        value = getattr(legal_interpreter, name)
        globals()[name] = value
        return value
    raise AttributeError(name)
