"""Normalized architectural base seeds, separate from parcel scope fractions.

A p.3 scope answers *how much of the site is available*. A base seed answers
*what normalized starting proportion enters the recursive solid program*.
Most seeds deliberately expand from the exact same unit Box; they are semantic
priors for agents, not completed-building templates or extra kernel types.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.modules.design.generation.maas.geometry_language.affine_matrix import matrix4_to_lists, scale_matrix4
from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryNode, GeometryProgram


@dataclass(frozen=True)
class BaseSeedSpec:
    seed_id: str
    label: str
    primitive_operator: str
    normalized_scale: tuple[float, float, float]
    architectural_use: str
    core_expansion: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed_id": self.seed_id,
            "label": self.label,
            "primitive_operator": self.primitive_operator,
            "normalized_scale": list(self.normalized_scale),
            "architectural_use": self.architectural_use,
            "core_expansion": self.core_expansion,
        }


@dataclass(frozen=True)
class BaseFormSpec:
    form_id: str
    label: str
    operator: str
    normalized_volume_relation: str


BASE_FORM_SPECS: tuple[BaseFormSpec, ...] = (
    BaseFormSpec("cube", "CUBE", "", "1/1 unit host"),
    BaseFormSpec("elliptical", "ELLIPSOID", "ellipsoidize", "less than cube"),
    BaseFormSpec("tetrahedral", "TETRAHEDRON", "tetrahedralize", "one third of cube"),
)


BASE_SEED_SPECS: tuple[BaseSeedSpec, ...] = (
    BaseSeedSpec("block", "BLOCK", "box", (1.0, 1.0, 1.0), "neutral compact host", "Scale(UnitBox, [1, 1, 1])"),
    BaseSeedSpec("slab", "SLAB", "box", (2.2, 1.45, 0.28), "wide low plate or hall datum", "Scale(UnitBox, [2.2, 1.45, 0.28])"),
    BaseSeedSpec("bar", "BAR", "box", (2.8, 0.62, 0.48), "linear wing or bent ribbon seed", "Scale(UnitBox, [2.8, 0.62, 0.48])"),
    BaseSeedSpec("tower", "TOWER", "box", (0.68, 0.68, 2.5), "vertical tapered or leaning seed", "Scale(UnitBox, [0.68, 0.68, 2.5])"),
    BaseSeedSpec("profiled_prism", "PROFILED PRISM", "extruded_polygon", (1.6, 1.2, 0.75), "non-rectangular footprint seed", "Extrude(PolygonProfile, height)"),
)


# One kernel primitive can carry several plan languages.  These are normalized
# profiles, not completed building templates: synthesis chooses a profile and
# every later BOOK/site/program operation still receives the same SolidNode.
# Keeping this alphabet here prevents triangular/chamfered plans from being
# scattered as one-off coordinate recipes across candidate generators.
PROFILED_PRISM_FAMILIES: tuple[tuple[str, tuple[tuple[float, float], ...]], ...] = (
    (
        "faceted",
        ((0.0, 0.0), (1.6, 0.0), (1.35, 1.15), (0.35, 1.2), (-0.15, 0.55)),
    ),
    (
        "triangular",
        ((0.0, 0.0), (1.6, 0.0), (0.72, 1.2)),
    ),
    (
        "trapezoidal",
        ((0.0, 0.0), (1.6, 0.0), (1.28, 1.2), (0.24, 1.2)),
    ),
    (
        "chamfered",
        ((0.0, 0.0), (1.28, 0.0), (1.6, 0.32), (1.6, 1.2), (0.0, 1.2)),
    ),
    (
        "kite",
        ((0.0, 0.46), (0.62, 0.0), (1.6, 0.5), (0.68, 1.2)),
    ),
    (
        "oval",
        (
            (0.03, 0.62), (0.10, 0.34), (0.30, 0.18), (0.56, 0.05),
            (0.86, 0.0), (1.18, 0.08), (1.44, 0.22), (1.58, 0.47),
            (1.54, 0.72), (1.40, 1.03), (1.12, 1.15), (0.78, 1.20),
            (0.44, 1.12), (0.18, 0.94),
        ),
    ),
    (
        "stadium",
        ((0.1, 0.0), (1.5, 0.0), (1.6, 0.2), (1.6, 1.0), (1.5, 1.2), (0.1, 1.2), (0.0, 1.0), (0.0, 0.2)),
    ),
    (
        "concave_l",
        ((0.0, 0.0), (1.45, 0.0), (1.45, 0.32), (1.18, 0.32), (1.18, 1.0), (1.0, 1.0), (1.0, 0.48), (0.0, 0.48)),
    ),
    (
        "hexagon",
        ((0.0, 0.35), (0.32, 0.03), (0.8, 0.0), (1.28, 0.26), (1.6, 0.6), (1.3, 1.2), (0.6, 1.2)),
    ),
    (
        "circle",
        (
            (1.0, 0.5), (0.9904, 0.5975), (0.9619, 0.6913), (0.9157, 0.7778),
            (0.8536, 0.8536), (0.7778, 0.9157), (0.6913, 0.9619), (0.5975, 0.9904),
            (0.5, 1.0), (0.4025, 0.9904), (0.3087, 0.9619), (0.2222, 0.9157),
            (0.1464, 0.8536), (0.0843, 0.7778), (0.0381, 0.6913), (0.0096, 0.5975),
            (0.0, 0.5), (0.0096, 0.4025), (0.0381, 0.3087), (0.0843, 0.2222),
            (0.1464, 0.1464), (0.2222, 0.0843), (0.3087, 0.0381), (0.4025, 0.0096),
            (0.5, 0.0), (0.5975, 0.0096), (0.6913, 0.0381), (0.7778, 0.0843),
            (0.8536, 0.1464), (0.9157, 0.2222), (0.9619, 0.3087), (0.9904, 0.4025),
        ),
    ),
)


def profiled_prism_parameters(variation_index: int = 0) -> dict[str, Any]:
    """Return one deterministic normalized polygon-profile parameter set."""

    index = max(0, int(variation_index)) % len(PROFILED_PRISM_FAMILIES)
    family, points = PROFILED_PRISM_FAMILIES[index]
    return {
        "points": [list(point) for point in points],
        "height": 0.75,
        "profile_family": family,
        "profile_variant_index": index,
    }


def base_seed_catalog() -> tuple[dict[str, Any], ...]:
    return tuple(spec.to_dict() for spec in BASE_SEED_SPECS)


def base_form_program(form_id: str) -> GeometryProgram:
    """Lower one normalized form capability before one global Matrix4."""

    spec = next((item for item in BASE_FORM_SPECS if item.form_id == form_id), None)
    if spec is None:
        raise KeyError(f"unknown base form: {form_id}")
    provenance = {
        "source": "normalized_base_form_catalog",
        "base_form_id": spec.form_id,
        "not_a_building_template": True,
    }
    unit = GeometryNode(
        "unit_box", "primitive", "box",
        parameters={"width": 1.0, "depth": 1.0, "height": 1.0},
        semantic_role="unitbox", provenance=provenance,
    )
    nodes: list[GeometryNode] = [unit]
    carrier_id = unit.id
    if spec.operator:
        form = GeometryNode(
            "base_form", "modifier", spec.operator, inputs=(unit.id,),
            parameters={"segments": 24} if spec.operator == "ellipsoidize" else {},
            semantic_role="base_form", provenance=provenance,
        )
        nodes.append(form)
        carrier_id = form.id
    matrix = GeometryNode(
        "global_matrix4", "transform", "matrix4", inputs=(carrier_id,),
        parameters={"matrix4": matrix4_to_lists(scale_matrix4((1.0, 1.0, 1.0)))},
        semantic_role="base_volume",
        provenance={**provenance, "global_matrix4": True},
    )
    nodes.append(matrix)
    return GeometryProgram(
        tuple(nodes), matrix.id, name=f"base_form_{spec.form_id}",
        metadata={
            "language_layer": "architectural_base_form",
            "base_form_id": spec.form_id,
            "base_seed": "block",
            "canonical_root": "1/1 UnitBox",
            "basevolume_affine_authority": "explicit_matrix4",
            "not_a_building_template": True,
        },
    )


def base_seed_program(
    seed_id: str,
    *,
    variation_index: int = 0,
    site_extent: tuple[float, float, float] | None = None,
) -> GeometryProgram:
    """One base seed, optionally authored in the parcel's own metres.

    Without `site_extent` a seed is a proportion and nothing more - block is
    1:1:1, slab is 2.20:1.45:0.28, a bar is 4.5 times as long as it is deep -
    and the size arrives later, when the compiled solid is fitted to a host.
    That is the difference between this executor and massv2, and it is where
    the size goes: massv2's seed IS the parcel's own rectangle, so it carries
    metres from its first word and the legal line only ever CUTS it. A seed
    that arrives dimensionless has to be scaled to the site, and every scaling
    step is a chance to come back small - fitted INSIDE the buildable polygon,
    a BOOK mass delivered 664 m2 against a 1,497.9 m2 building-area cap on
    의정부 4115011300106840001.

    `site_extent` is that parcel's own box - the seed rectangle's width and
    depth and the storey budget the law allows - and the seed is scaled to
    fill it on its limiting axis, so the proportion that IS the seed's
    identity survives and the metres are there from the first node. A bar is
    still 4.5 times as long as it is deep; it is now as long as this site can
    hold.
    """

    spec = next((item for item in BASE_SEED_SPECS if item.seed_id == seed_id), None)
    if spec is None:
        raise KeyError(f"unknown base seed: {seed_id}")
    site_scale = (1.0, 1.0, 1.0)
    if site_extent is not None:
        wanted = tuple(max(0.0, float(value)) for value in site_extent)
        if len(wanted) != 3 or min(wanted) <= 1e-9:
            raise ValueError("site_extent must be three positive metre lengths")
        # The plan fills the parcel's rectangle and the height IS the storey
        # budget - the two are separate quantities and massv2 has always
        # treated them so. Taking one scale off all three axes lets the budget
        # govern the plan: a 1:1:1 block on a 19 m budget came out 19 m wide,
        # 24% of the building-area cap, and a 1:1:3.68 tower came out 5.2 m
        # wide, 2%. Both are arithmetic and neither is a building.
        #
        # What survives is the seed's PLAN proportion, which is its identity in
        # plan - slab 2.20:1.45, bar 2.80:0.62, block and tower both square.
        # And that is an honest reading rather than a lossy one: on a parcel
        # this law allows five storeys of, a tower and a block ARE the same
        # figure, because the thing that separated them was a height this site
        # does not grant.
        plan_scale = min(
            wanted[0] / max(spec.normalized_scale[0], 1e-9),
            wanted[1] / max(spec.normalized_scale[1], 1e-9),
        )
        site_scale = (
            plan_scale,
            plan_scale,
            wanted[2] / max(spec.normalized_scale[2], 1e-9),
        )
    provenance = {
        "source": "normalized_base_seed_catalog",
        "seed_id": spec.seed_id,
        "architectural_use": spec.architectural_use,
        "not_a_building_template": True,
    }
    if spec.primitive_operator == "box":
        unit = GeometryNode(
            "unit_box", "primitive", "box",
            parameters={"width": 1.0, "depth": 1.0, "height": 1.0},
            semantic_role="base_seed", provenance=provenance,
        )
        scaled = GeometryNode(
            f"seed_{spec.seed_id}", "transform", "matrix4", inputs=(unit.id,),
            parameters={
                "matrix4": matrix4_to_lists(
                    scale_matrix4(tuple(
                        value * factor
                        for value, factor in zip(spec.normalized_scale, site_scale)
                    )),
                ),
            },
            semantic_role="base_seed",
            provenance={**provenance, "core_expansion": spec.core_expansion},
        )
        nodes = (unit, scaled)
        root = scaled.id
    else:
        prism_parameters = profiled_prism_parameters(variation_index)
        prism = GeometryNode(
            f"seed_{spec.seed_id}", "primitive", "extruded_polygon",
            parameters=prism_parameters,
            semantic_role="base_seed",
            provenance={**provenance, "core_expansion": spec.core_expansion},
        )
        nodes = (prism,)
        root = prism.id
        if any(abs(factor - 1.0) > 1e-9 for factor in site_scale):
            # The profiled prism is authored by its own parameters rather than
            # by a scale on a unit box, so the parcel's metres are composed on
            # afterwards. Uniform, because the profile is a plan family and
            # stretching it unevenly would be a different figure.
            posed = GeometryNode(
                f"seed_{spec.seed_id}_site", "transform", "matrix4",
                inputs=(prism.id,),
                parameters={
                    "matrix4": matrix4_to_lists(scale_matrix4(site_scale)),
                },
                semantic_role="base_seed",
                provenance={**provenance, "core_expansion": spec.core_expansion},
            )
            nodes = (prism, posed)
            root = posed.id
    return GeometryProgram(
        nodes, root, name=f"base_seed_{spec.seed_id}",
        metadata={
            "language_layer": "architectural_base_seed",
            "base_seed": spec.to_dict(),
            "plan_profile_family": (
                prism_parameters["profile_family"]
                if spec.primitive_operator == "extruded_polygon"
                else "rectangular"
            ),
            "site_scope_is_separate": True,
            "canonical_root": "1/1 UnitBox",
            "basevolume_affine_authority": (
                "explicit_matrix4"
                if spec.primitive_operator == "box"
                else "derived_topology"
            ),
        },
    )


def base_seed_programs() -> tuple[GeometryProgram, ...]:
    return tuple(base_seed_program(spec.seed_id) for spec in BASE_SEED_SPECS)


def box_derived_base_seed_programs() -> tuple[GeometryProgram, ...]:
    """Return the four seeds that provably share one identical UnitBox core."""
    return tuple(base_seed_program(spec.seed_id) for spec in BASE_SEED_SPECS if spec.primitive_operator == "box")


__all__ = [
    "BASE_FORM_SPECS", "BASE_SEED_SPECS", "PROFILED_PRISM_FAMILIES",
    "BaseFormSpec", "BaseSeedSpec", "base_form_program", "base_seed_catalog",
    "base_seed_program", "base_seed_programs", "box_derived_base_seed_programs",
    "profiled_prism_parameters",
]
