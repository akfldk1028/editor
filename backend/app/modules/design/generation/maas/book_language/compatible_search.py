"""Bounded rollback of BOOK assignments that fail portfolio compatibility."""

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class CompatibleAssignment:
    assignment: dict[int, int]
    evidence: dict[str, Any]


def search_compatible_assignment(
    *, source_count: int, slot_count: int, incumbent: dict[int, int],
    candidate: Callable[[int, int], Any | None],
    compatible: Callable[[Any, list[Any]], bool],
    max_evaluations: int = 64, max_states: int = 2048,
) -> CompatibleAssignment:
    """Keep the incumbent when valid, otherwise retry without relaxing gates.

    Budgets cover additional pair evaluations and search states. Incumbent
    verification is always performed, so a timeout cannot return unchecked work.
    """
    if min(source_count, slot_count, max_evaluations, max_states) < 0:
        raise ValueError('counts and search budgets must be non-negative')
    if any(not 0 <= slot < slot_count or not 0 <= source < source_count
           for slot, source in incumbent.items()):
        raise ValueError('incumbent assignment is outside the source/slot domain')
    cache: dict[tuple[int, int], Any | None] = {}
    best: dict[int, int] = {}
    retained: list[Any] = []
    initial_rejections = []
    for slot, source in sorted(incumbent.items()):
        key = (source, slot)
        cache[key] = value = candidate(source, slot)
        if (source not in best.values() and value is not None
                and compatible(value, retained)):
            best[slot] = source
            retained.append(value)
        else:
            initial_rejections.append({"slot": slot, "source": source})
    initial_count = len(best)
    evaluations = states = 0
    exhausted = False
    conflicts = 0

    def finish(status):
        return CompatibleAssignment(dict(sorted(best.items())), {
            'algorithm': 'bounded_compatible_assignment.v1',
            'status': status,
            'initial_matching_count': len(incumbent),
            'initial_compatible_count': initial_count,
            'retained_count': len(best),
            'additional_evaluations': evaluations,
            'visited_states': states,
            'initial_rejections': initial_rejections,
            'initial_rejection_count': len(initial_rejections),
            'retry_compatibility_rejections': conflicts,
            'compatibility_rejections': len(initial_rejections) + conflicts,
            'max_evaluations': max_evaluations,
            'max_states': max_states,
            'gate_policy': 'unchanged',
            'quality_claim': 'compatible_supply_only',
        })

    if len(best) == slot_count:
        return finish('incumbent_valid')

    def visit(slot, assignment, selected, used):
        nonlocal best, evaluations, states, exhausted, conflicts
        if len(assignment) > len(best):
            best = dict(assignment)
        if len(best) == slot_count:
            return True
        if slot == slot_count or len(assignment) + min(
                slot_count - slot, source_count - len(used)) <= len(best):
            return False
        if states >= max_states:
            exhausted = True
            return False
        states += 1
        preferred = [incumbent[slot]] if slot in incumbent else []
        order = preferred + [i for i in range(source_count) if i not in preferred]
        for source in order:
            if source in used:
                continue
            key = (source, slot)
            if key not in cache:
                if evaluations >= max_evaluations:
                    exhausted = True
                    continue
                cache[key] = candidate(source, slot)
                evaluations += 1
            value = cache[key]
            if value is None:
                continue
            if not compatible(value, selected):
                conflicts += 1
                continue
            assignment[slot] = source
            if visit(slot + 1, assignment, selected + [value], used | {source}):
                return True
            del assignment[slot]
        return visit(slot + 1, assignment, selected, used)

    visit(0, {}, [], set())
    return finish('complete' if len(best) == slot_count else
                  'budget_exhausted' if exhausted else 'search_exhausted')
