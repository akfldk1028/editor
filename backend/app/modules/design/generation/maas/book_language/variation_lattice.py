"""Deterministic 11-state variation lattice transcribed from BOOK page layout.

Every operative page presents eleven variation diagrams in three orientations.
The diagrams do not prescribe parcel dimensions, so this module maps their
ordered diversity into the existing bounded parameter schema without making
all parameters rise and fall together.
"""

from __future__ import annotations

from backend.app.modules.design.generation.maas.book_language.corpus_contract import BASE_VOLUME_FRACTIONS, BOOK_ORIENTATIONS, BOOK_VARIATION_COUNT


# Ordered from restrained to emphatic.  Parameter-specific phase offsets turn
# the one-dimensional page row into a decorrelated typed probe, while staying
# deterministic and fully inside the shared compiler bounds.
_INTENSITY_FRACTIONS = (0.18, 0.24, 0.30, 0.36, 0.43, 0.50, 0.57, 0.64, 0.70, 0.76, 0.82)


def book_variation_indices(count: int) -> tuple[int, ...]:
    """Choose evenly distributed states from the complete eleven-state row."""
    wanted = max(1, min(BOOK_VARIATION_COUNT, int(count)))
    if wanted == 1:
        return (BOOK_VARIATION_COUNT // 2,)
    return tuple(
        round(index * (BOOK_VARIATION_COUNT - 1) / (wanted - 1))
        for index in range(wanted)
    )


def _parameter_phase(parameter_name: str) -> int:
    return sum((index + 1) * ord(character) for index, character in enumerate(parameter_name)) % BOOK_VARIATION_COUNT


def variation_fraction(parameter_name: str, variation_index: int) -> float:
    """Return a stable, parameter-decorrelated fraction for a BOOK state."""
    index = int(variation_index) % BOOK_VARIATION_COUNT
    phase = _parameter_phase(parameter_name)
    return _INTENSITY_FRACTIONS[(index + phase) % BOOK_VARIATION_COUNT]


def categorical_variation_index(parameter_name: str, variation_index: int, value_count: int) -> int:
    if value_count <= 0:
        raise ValueError("categorical BOOK parameter requires at least one value")
    return (int(variation_index) + _parameter_phase(parameter_name)) % value_count


def book_probe_scope(
    seed_index: int,
    lineage_base_index: int,
    variation_index: int,
    *,
    force_vertical: bool = False,
    couple_variation: bool = True,
) -> tuple[str, str]:
    """Cross a variation state with the six volumes and three orientations."""
    origin = int(seed_index) + int(lineage_base_index)
    variation = int(variation_index)
    scope_cursor = origin + variation if couple_variation else origin
    label = BASE_VOLUME_FRACTIONS[scope_cursor % len(BASE_VOLUME_FRACTIONS)][0]
    orientation = (
        "vertical"
        if force_vertical
        else BOOK_ORIENTATIONS[
            (origin + round(variation / 5)) % len(BOOK_ORIENTATIONS)
            if couple_variation
            else (origin // len(BASE_VOLUME_FRACTIONS)) % len(BOOK_ORIENTATIONS)
        ]
    )
    return label, orientation


__all__ = [
    "book_probe_scope", "book_variation_indices", "categorical_variation_index", "variation_fraction",
]
