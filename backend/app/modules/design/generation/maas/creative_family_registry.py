"""Stable registry and balanced scheduling for creative MASS families."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from backend.app.modules.design.generation.maas.creative_family_contract import CreativeFamilySpec, CreativeRecipeContext, CreativeRecipeResult
from backend.app.modules.design.generation.maas.creative_book_supply import creative_book_schedule


CAPACITY_BANDS = (
    "spatial_reserve",
    "balanced_yield",
    "brief_target",
    "maximum_target",
)
BOOK_SCOPE_LABELS = ("1/1", "1/2", "3/8", "1/4", "1/8", "1/16")


@dataclass(frozen=True)
class CreativeFamilyScheduleItem:
    spec: CreativeFamilySpec
    context: CreativeRecipeContext

    @property
    def family_id(self) -> str:
        return self.spec.family_id

    @property
    def recipe_id(self) -> str:
        return self.spec.recipe_id


@dataclass(frozen=True)
class RegisteredCreativeRecipe:
    family_id: str
    recipe_id: str
    form_class: str
    contact_type: str
    builder: Callable[[CreativeRecipeContext], CreativeRecipeResult]


_FAMILY_METADATA = (
    ("bent", "creative_bent_v1", "non_stepped", "spine"),
    (
        "carved_void",
        "creative_carved_void_v1",
        "non_stepped",
        "core",
    ),
    ("courtyard", "creative_courtyard_v1", "non_stepped", "core"),
    ("cross", "creative_cross_v1", "non_stepped", "spine"),
    ("grid", "creative_grid_v1", "non_stepped", "shared_edge"),
    ("inflated", "creative_inflated_v1", "non_stepped", "core"),
    ("notch", "creative_notch_v1", "non_stepped", "core"),
    ("radial", "creative_radial_v1", "non_stepped", "hub"),
    (
        "split_wing",
        "creative_split_wing_v1",
        "non_stepped",
        "bridge",
    ),
    ("stepped", "creative_stepped_v1", "stepped", "core"),
    (
        "triangular_shard",
        "creative_triangular_shard_v1",
        "non_stepped",
        "core",
    ),
    (
        "oblique_crystal",
        "creative_oblique_crystal_v1",
        "non_stepped",
        "core",
    ),
    (
        "thin_disc_cluster",
        "creative_thin_disc_cluster_v1",
        "non_stepped",
        "hub",
    ),
    (
        "interlocking_tilted_discs",
        "creative_interlocking_tilted_discs_v1",
        "non_stepped",
        "shared_edge",
    ),
    (
        "long_span_bridge",
        "creative_long_span_bridge_v1",
        "non_stepped",
        "bridge",
    ),
)

_REGISTERED_FAMILIES = tuple(
    CreativeFamilySpec(
        family_id=family_id,
        recipe_id=recipe_id,
        form_class=form_class,
        contact_type=contact_type,
    )
    for family_id, recipe_id, form_class, contact_type in _FAMILY_METADATA
)


def registered_creative_families() -> tuple[CreativeFamilySpec, ...]:
    return _REGISTERED_FAMILIES


def registered_creative_recipes() -> tuple[RegisteredCreativeRecipe, ...]:
    from backend.app.modules.design.generation.maas.creative_family_recipes import RECIPE_BUILDERS

    return tuple(
        RegisteredCreativeRecipe(
            family_id=spec.family_id,
            recipe_id=spec.recipe_id,
            form_class=spec.form_class,
            contact_type=spec.contact_type,
            builder=RECIPE_BUILDERS[spec.recipe_id],
        )
        for spec in _REGISTERED_FAMILIES
    )


def balanced_family_schedule(
    count: int,
) -> tuple[CreativeFamilyScheduleItem, ...]:
    requested_count = int(count)
    if requested_count < 0:
        raise ValueError("count must be non-negative")

    specs = registered_creative_families()
    base, remainder = divmod(requested_count, len(specs))
    quotas = tuple(
        base + (1 if family_index < remainder else 0)
        for family_index in range(len(specs))
    )
    schedule: list[CreativeFamilyScheduleItem] = []
    book_schedule = creative_book_schedule(requested_count)
    for variation_index in range(max(quotas, default=0)):
        for family_index, spec in enumerate(specs):
            if variation_index >= quotas[family_index]:
                continue
            schedule_index = len(schedule)
            book_assignment = book_schedule[schedule_index]
            # The BOOK schedule labels its assignments by position, and this
            # loop walks families in registry order, so taking the scope from
            # position pins family i to scope i mod 6 - permanently. With 15
            # families against 6 scopes that left every family seeing only two
            # scopes and every scope seeing five of fifteen families: two
            # thirds of the family x scope grid was never generated at all.
            # Offsetting by the variation index walks the whole grid instead,
            # and stays fully deterministic.
            scope_label = BOOK_SCOPE_LABELS[
                (family_index + variation_index) % len(BOOK_SCOPE_LABELS)
            ]
            schedule.append(
                CreativeFamilyScheduleItem(
                    spec=spec,
                    context=CreativeRecipeContext(
                        variation_index=variation_index,
                        book_scope_label=scope_label,
                        capacity_band=CAPACITY_BANDS[
                            schedule_index % len(CAPACITY_BANDS)
                        ],
                        book_principle_id=(
                            book_assignment.principle_id
                        ),
                        book_principle_kind=(
                            book_assignment.principle_kind
                        ),
                        book_execution_verbs=(
                            book_assignment.execution_verbs
                        ),
                        book_aggregation_methods=(
                            book_assignment.aggregation_methods
                        ),
                    ),
                )
            )
    return tuple(schedule)


__all__ = [
    "BOOK_SCOPE_LABELS",
    "CAPACITY_BANDS",
    "CreativeFamilyScheduleItem",
    "RegisteredCreativeRecipe",
    "balanced_family_schedule",
    "registered_creative_families",
    "registered_creative_recipes",
]
