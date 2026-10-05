"""Program-neutral architectural operation-graph composition.

This module composes reusable MassDSL operations.  It intentionally contains
no site coordinates, component bounds, or building-use templates.
"""

from __future__ import annotations

from backend.app.modules.design.generation.maas.grammar.sequence_library import SEQUENCES
from backend.app.modules.design.generation.maas.grammar.verb_sequence import VerbCall, VerbSequence


def composed_creative_graphs() -> tuple[VerbSequence, ...]:
    """Compose compatible plan gestures, organizers and sectional gestures."""
    bank = _operation_bank()
    base = VerbCall("base", {"proportion": "site"})
    # Compatibility is expressed at verb level.  Each row is expanded through
    # three section strategies, so new parameter priors can enter through the
    # data-backed sequence library without adding fixed geometry here.
    circuits = {
        "bend_field": ("bend", ("courtyard", "diagonal_connect", "terrace_link")),
        "branch_field": ("branch", ("courtyard", "diagonal_connect", "terrace_link")),
        "interlock_field": ("interlock", ("courtyard", "diagonal_connect", "shift")),
        "folded_field": ("sloped_roof_mass", ("courtyard", "shift", "terrace_link")),
        "terrace_field": ("terrace_link", ("bend", "branch", "diagonal_connect")),
    }
    section_strategies = (
        ("lift", "taper"),
        ("shift", "taper"),
        ("lift", "grade"),
    )
    result: list[VerbSequence] = []
    for field_name, (primary, organizers) in circuits.items():
        for index, organizer in enumerate(organizers):
            section = section_strategies[index % len(section_strategies)]
            verbs = (primary, organizer, *section)
            calls = [base]
            for verb in verbs:
                operation = bank.get(verb)
                if operation is not None and operation.verb not in {item.verb for item in calls[-1:]}:
                    calls.append(VerbCall(operation.verb, dict(operation.params)))
            if len(calls) < 3:
                continue
            result.append(VerbSequence(
                name=f"creative_composed_{field_name}_{index + 1}",
                label=f"composed {field_name.replace('_', ' ')}",
                calls=tuple(calls),
                notes=(
                    "stage=creative_form_exploration",
                    "generator=formal_operation_graph_composer",
                    "coordinate_template=false",
                    "program_projection=pending",
                ),
            ))
    return tuple(result)


def _operation_bank() -> dict[str, VerbCall]:
    bank: dict[str, VerbCall] = {}
    for sequence in SEQUENCES:
        for operation in sequence.calls[1:]:
            bank.setdefault(operation.verb, operation)
    return bank


__all__ = ["composed_creative_graphs"]
