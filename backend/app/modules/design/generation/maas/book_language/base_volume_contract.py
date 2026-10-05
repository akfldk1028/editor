"""Exact normalized cell grammar transcribed from BOOK p.3.

The six records are starting *volumes*, not six scalar clipping lengths.  In
particular, 3/8 is the connected L made by three cells in a 2 x 2 x 2 grid.
Keeping the cell grammar explicit prevents later compilers from flattening all
six choices into the same thin strip.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import prod


@dataclass(frozen=True)
class NormalizedCell:
    minimum: tuple[float, float, float]
    maximum: tuple[float, float, float]

    @property
    def volume(self) -> float:
        return prod(high - low for low, high in zip(self.minimum, self.maximum))


@dataclass(frozen=True)
class BookBaseVolumeSpec:
    label: str
    fraction: float
    topology: str
    cells: tuple[NormalizedCell, ...]


def _cell(
    minimum: tuple[float, float, float],
    maximum: tuple[float, float, float],
) -> NormalizedCell:
    return NormalizedCell(minimum, maximum)


BOOK_BASE_VOLUME_SPECS: tuple[BookBaseVolumeSpec, ...] = (
    BookBaseVolumeSpec("1/1", 1.0, "whole_cube", (
        _cell((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
    )),
    BookBaseVolumeSpec("3/8", 3.0 / 8.0, "connected_three_octant_l", (
        _cell((0.0, 0.5, 0.5), (0.5, 1.0, 1.0)),
        _cell((0.5, 0.0, 0.5), (1.0, 0.5, 1.0)),
        _cell((0.5, 0.5, 0.5), (1.0, 1.0, 1.0)),
    )),
    BookBaseVolumeSpec("1/2", 1.0 / 2.0, "half_cube", (
        _cell((0.0, 0.0, 0.5), (1.0, 1.0, 1.0)),
    )),
    BookBaseVolumeSpec("1/4", 1.0 / 4.0, "half_section_bar", (
        _cell((0.0, 0.5, 0.5), (1.0, 1.0, 1.0)),
    )),
    BookBaseVolumeSpec("1/8", 1.0 / 8.0, "single_octant", (
        _cell((0.5, 0.5, 0.5), (1.0, 1.0, 1.0)),
    )),
    BookBaseVolumeSpec("1/16", 1.0 / 16.0, "quarter_section_bar", (
        _cell((0.0, 0.75, 0.75), (1.0, 1.0, 1.0)),
    )),
)


def book_base_volume_spec(label: str) -> BookBaseVolumeSpec:
    spec = next((item for item in BOOK_BASE_VOLUME_SPECS if item.label == label), None)
    if spec is None:
        raise KeyError(f"unknown BOOK p.3 base volume: {label}")
    return spec


def oriented_book_base_volume_cells(
    label: str,
    orientation: str,
) -> tuple[NormalizedCell, ...]:
    """Map the canonical long bar to long, short or vertical host axes."""

    if orientation not in {"long_axis", "short_axis", "vertical"}:
        raise KeyError(f"unknown BOOK base-volume orientation: {orientation}")
    permutation = {
        "long_axis": (0, 1, 2),
        "short_axis": (1, 0, 2),
        "vertical": (2, 1, 0),
    }[orientation]
    return tuple(NormalizedCell(
        tuple(cell.minimum[index] for index in permutation),
        tuple(cell.maximum[index] for index in permutation),
    ) for cell in book_base_volume_spec(label).cells)


def book_base_volume_outward_sign(label: str, orientation: str, axis: str) -> float:
    """Return the exterior direction implied by the selected p.3 cells."""

    axis_index = {"x": 0, "y": 1, "z": 2}.get(str(axis).lower())
    if axis_index is None:
        raise KeyError(f"unknown BOOK base-volume axis: {axis}")
    cells = oriented_book_base_volume_cells(label, orientation)
    weighted_center = sum(
        ((cell.minimum[axis_index] + cell.maximum[axis_index]) / 2.0) * cell.volume
        for cell in cells
    ) / sum(cell.volume for cell in cells)
    # A whole-axis selection is neutral; choose one exterior deterministically
    # so a signed variation changes intensity instead of entering the remainder.
    return -1.0 if weighted_center < 0.5 - 1e-9 else 1.0


for _spec in BOOK_BASE_VOLUME_SPECS:
    if abs(sum(cell.volume for cell in _spec.cells) - _spec.fraction) > 1e-9:
        raise ValueError(f"BOOK base-volume cell contract is not {_spec.label}")


__all__ = [
    "BOOK_BASE_VOLUME_SPECS", "BookBaseVolumeSpec", "NormalizedCell",
    "book_base_volume_outward_sign", "book_base_volume_spec",
    "oriented_book_base_volume_cells",
]
