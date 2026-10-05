"""Executable early-typology priors recovered from the frontend vocabulary.

These are not finished footprint templates.  Each prior names one normalized
topological relation that can be authored from a base seed before BOOK scope,
operation, combination and aggregation layers are applied.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class TypologyPrior:
    typology_id: str
    label: str
    relation_class: str
    primary_operator: str
    preferred_base_seeds: tuple[str, ...]
    program_ids: tuple[str, ...]


_ALL = ("neighborhood_living", "cultural", "gymnasium")
_PUBLIC_MIXED = ("neighborhood_living", "cultural")


TYPOLOGY_PRIORS: tuple[TypologyPrior, ...] = (
    TypologyPrior("additive", "Additive", "addition", "inflate", ("block", "slab", "bar"), _ALL),
    TypologyPrior("subtractive", "Subtractive", "subtraction", "carve_void", ("block", "slab"), _ALL),
    TypologyPrior("grid", "Grid", "field", "grid_mass", ("bar",), _PUBLIC_MIXED),
    TypologyPrior("lshape", "L Shape", "corner", "notch", ("block", "slab"), _ALL),
    TypologyPrior("ushape", "U Shape", "open_court", "courtyard", ("slab", "block"), _PUBLIC_MIXED),
    TypologyPrior("cross", "Cross", "intersecting_wings", "cross_mass", ("bar", "slab"), _PUBLIC_MIXED),
    TypologyPrior("courtyard", "Courtyard", "closed_court", "courtyard", ("block", "slab"), _PUBLIC_MIXED),
    TypologyPrior("tower_podium", "Tower + Podium", "vertical_hierarchy", "stepped_mass", ("tower", "block"), ("neighborhood_living",)),
    TypologyPrior("hshape", "H Shape", "parallel_wings_bridge", "split_wing", ("bar", "slab"), _PUBLIC_MIXED),
    TypologyPrior("radial", "Radial", "radial_wings", "radial_array", ("bar",), ("cultural",)),
    TypologyPrior("freeform", "Freeform", "continuous_deformation", "bend", ("bar", "profiled_prism"), _ALL),
)


def typology_prior(typology_id: str) -> TypologyPrior:
    item = next((prior for prior in TYPOLOGY_PRIORS if prior.typology_id == typology_id), None)
    if item is None:
        raise KeyError(f"unknown early typology prior: {typology_id}")
    return item


def typology_priors_for_program(
    program_id: str,
    *,
    allowed_macro_operators: Iterable[str] = (),
) -> tuple[TypologyPrior, ...]:
    allowed = frozenset(str(value) for value in allowed_macro_operators if str(value))
    macro_operators = frozenset({
        "courtyard", "carve_void", "notch", "cross_mass", "grid_mass", "stepped_mass", "split_wing",
    })
    return tuple(
        prior for prior in TYPOLOGY_PRIORS
        if str(program_id) in prior.program_ids
        and (
            prior.primary_operator not in macro_operators
            or not allowed
            or prior.primary_operator in allowed
        )
    )


__all__ = ["TYPOLOGY_PRIORS", "TypologyPrior", "typology_prior", "typology_priors_for_program"]
