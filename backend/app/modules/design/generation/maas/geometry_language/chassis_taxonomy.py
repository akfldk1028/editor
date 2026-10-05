"""Canonical base-volume and plan-chassis taxonomy for executable geometry.

The taxonomy is intentionally independent of program use, BOOK projection,
roof phenotype and VLM judgement.  It gives every exact AST a stable answer to
two different questions:

* which primitive proportion it starts from (``base_seed``), and
* which plan relation the compiled mass actually forms (``chassis``).

Keeping those axes separate prevents materially different core programs from
collapsing into a synthetic ``unknown`` bucket during portfolio selection.
"""

from __future__ import annotations

from typing import Any, Iterable


_CORE_FAMILY_TAXONOMY: dict[str, tuple[str, str]] = {
    "bent_linear_mass": ("bar", "bent_bar"),
    "radial_fan": ("bar", "radial_wings"),
    "l_mass": ("bar", "l_wings"),
    "u_mass": ("bar", "u_court"),
    "courtyard": ("slab", "courtyard"),
    "attached_volume": ("block", "attached_cluster"),
    "overlapping_mass": ("bar", "overlapping_bars"),
    "setback": ("block", "terraced_monolith"),
    "cross_mass": ("bar", "distributed_cross"),
    "tapered_tower": ("tower", "tapered_tower"),
    "leaning_tower": ("tower", "leaning_tower"),
    "notch": ("block", "carved_monolith"),
    "diagonal_slice": ("block", "sculpted_monolith"),
    "cut_corner": ("block", "sculpted_monolith"),
    "lofted_envelope": ("block", "lofted_monolith"),
    "swept_bar": ("bar", "curved_bar"),
    "split_bridge": ("slab", "split_wing"),
    "twisted_mass": ("tower", "twisted_tower"),
}


def core_chassis_families() -> tuple[str, ...]:
    """Return the program-independent executable chassis alphabet.

    Board feedback uses this only to identify chassis that received no final
    representation.  It does not make any chassis program-suitable or bypass
    compiler, BOOK, legal, parking, or VLM gates.
    """
    return tuple(dict.fromkeys(chassis for _seed, chassis in _CORE_FAMILY_TAXONOMY.values()))


def normalize_base_seed(value: Any) -> str:
    """Return the primitive seed id from either legacy or typed metadata."""
    if isinstance(value, dict):
        value = value.get("seed_id") or value.get("id")
    seed = str(value or "").strip()
    return seed if seed and seed != "unknown" else ""


def classify_geometry_program(
    *,
    family: str,
    source_operators: Iterable[str] = (),
    declared_base_seed: Any = None,
) -> dict[str, str]:
    """Classify an exact AST without consulting program use or visual scores."""
    family = str(family or "").strip()
    operators = {str(item or "").strip() for item in source_operators if item}
    seed = normalize_base_seed(declared_base_seed)

    core = _CORE_FAMILY_TAXONOMY.get(family)
    if core:
        core_seed, chassis = core
        return {
            "base_seed": seed or core_seed,
            "chassis": chassis,
            "authority": "exact_core_family",
        }

    # A shallow entry notch is an access relation, not the building body.
    # Preserve tower-scale deformations before the generic carved-monolith
    # fallback so the terminal threshold cannot erase their chassis identity.
    if "taper" in operators and seed == "tower":
        return {
            "base_seed": seed,
            "chassis": "tapered_tower",
            "authority": "exact_source_operator",
        }
    if "shear" in operators and seed == "tower":
        return {
            "base_seed": seed,
            "chassis": "sheared_tower",
            "authority": "exact_source_operator",
        }

    for operator_set, chassis, fallback_seed in (
        ({"radial_array"}, "radial_wings", "bar"),
        ({"cross_mass", "mirror_array", "linear_array"}, "distributed_cross", "bar"),
        ({"grid_mass"}, "distributed_grid", "bar"),
        ({"split_wing"}, "split_wing", "slab"),
        ({"courtyard"}, "courtyard", "slab"),
        ({"bent_bar", "bend"}, "bent_bar", "bar"),
        ({"cantilever"}, "cantilevered_bar", "bar"),
        ({"puncture"}, "perforated_monolith", "block"),
        ({"sweep"}, "curved_bar", "bar"),
        ({"attach"}, "attached_cluster", "block"),
        ({"setback", "terrace", "stepped_mass"}, "terraced_monolith", "block"),
        ({"lift"}, "lifted_spine", "slab"),
        ({"tapered_tower"}, "tapered_tower", "tower"),
        ({"leaning_tower"}, "leaning_tower", "tower"),
        ({"twist"}, "twisted_tower", "tower"),
        ({"carve_void", "notch", "cut_corner"}, "carved_monolith", "block"),
    ):
        if operators & operator_set:
            return {
                "base_seed": seed or fallback_seed,
                "chassis": chassis,
                "authority": "exact_source_operator",
            }

    # A declared primitive seed remains useful evidence when an executable
    # relation is not yet present.  ``unclassified`` is explicit and auditable;
    # it is not allowed to masquerade as a shared topology family.
    return {
        "base_seed": seed or "unclassified",
        "chassis": f"primitive_{seed}" if seed else "unclassified",
        "authority": "declared_base_seed" if seed else "unclassified",
    }


__all__ = ["classify_geometry_program", "core_chassis_families", "normalize_base_seed"]
