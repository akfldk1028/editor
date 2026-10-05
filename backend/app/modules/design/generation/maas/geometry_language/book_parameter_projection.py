"""Typed bridge from BOOK semantic parameters to solid-kernel parameters.

BOOK parameters describe variation in a normalized language domain.  Kernel
macros consume narrower structural ratios and finally multiply those ratios by
the bounds of the selected live solid.  Keeping that bridge here makes the
implementation bounds explicit and prevents private remap formulae from being
scattered through the BOOK adapter.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.modules.design.generation.maas.grammar.parameter_schema import PARAMETER_BOUNDS, PARAMETERS_BY_VERB


BOOK_PARAMETER_PROJECTION_SCHEMA_VERSION = "arr.maas.book_kernel_parameter_projection.v1"


@dataclass(frozen=True)
class BookKernelParameterProjection:
    verb: str
    source_parameter: str
    kernel_operator: str
    kernel_parameter: str
    kernel_bounds: tuple[float, float]
    measurement_basis: str
    rationale: str

    @property
    def source_bounds(self) -> tuple[float, float]:
        return PARAMETER_BOUNDS[self.source_parameter]


@dataclass(frozen=True)
class BookRelationInvariant:
    verb: str
    kernel_operator: str
    kernel_parameter: str
    value: float
    measurement_basis: str
    rationale: str


def _projection(
    verb: str,
    source_parameter: str,
    kernel_operator: str,
    kernel_parameter: str,
    kernel_bounds: tuple[float, float],
    measurement_basis: str,
    rationale: str,
) -> BookKernelParameterProjection:
    if source_parameter not in PARAMETERS_BY_VERB[verb]:
        raise ValueError(f"{verb}.{source_parameter} is not a BOOK parameter")
    if source_parameter not in PARAMETER_BOUNDS:
        raise ValueError(f"{source_parameter} has no BOOK parameter bounds")
    return BookKernelParameterProjection(
        verb=verb,
        source_parameter=source_parameter,
        kernel_operator=kernel_operator,
        kernel_parameter=kernel_parameter,
        kernel_bounds=kernel_bounds,
        measurement_basis=measurement_basis,
        rationale=rationale,
    )


# These are implementation transfer contracts, not page evidence from BOOK.
# The source ranges remain authoritative in grammar.parameter_schema; the
# target ranges retain material and connectivity in the manifold kernel.
BOOK_KERNEL_PARAMETER_PROJECTIONS: dict[
    tuple[str, str], BookKernelParameterProjection
] = {
    ("carve", "width_ratio"): _projection(
        "carve", "width_ratio", "book_carve", "width_ratio", (0.18, 0.62),
        "selected_live_solid_face_transverse_spans",
        "keep the p.26 face recess legible without consuming the host edges",
    ),
    ("carve", "depth_ratio"): _projection(
        "carve", "depth_ratio", "book_carve", "depth_ratio", (0.12, 0.52),
        "selected_live_solid_face_normal_span",
        "retain a bounded recess instead of turning CARVE into a through cut",
    ),
    ("lift", "guest_scale"): _projection(
        "lift", "guest_scale", "book_lift", "guest_scale", (0.30, 0.76),
        "selected_live_solid_transverse_spans",
        "preserve the p.20 hierarchy between the larger host and smaller guest",
    ),
    ("lift", "distance_ratio"): _projection(
        "lift", "distance_ratio", "book_lift", "distance_ratio", (0.08, 0.30),
        "selected_live_solid_axis_span",
        "vary the guest displacement while retaining measurable host overlap",
    ),
    ("fracture", "gap_ratio"): _projection(
        "fracture", "gap_ratio", "book_fracture", "gap_ratio", (0.04, 0.14),
        "selected_live_solid_face_transverse_span",
        "make the p.28 fissure visible without turning it into separated wings",
    ),
    ("grade", "width_ratio"): _projection(
        "grade", "width_ratio", "book_grade", "width_ratio", (0.38, 0.90),
        "selected_live_solid_face_transverse_span",
        "preserve side shoulders around the p.29 graded recess",
    ),
    ("notch", "ratio"): _projection(
        "notch", "ratio", "book_notch", "ratio", (0.12, 0.42),
        "selected_live_solid_face_spans",
        "keep the p.30 triangular wedge visible without severing the host",
    ),
    ("extract", "ratio"): _projection(
        "extract", "ratio", "book_extract", "guest_scale", (0.24, 0.56),
        "selected_live_solid_face_spans",
        "retain host shoulders around the p.35 extraction channel",
    ),
    ("extract", "distance_ratio"): _projection(
        "extract", "distance_ratio", "book_extract", "distance_ratio", (0.18, 0.34),
        "selected_live_solid_face_normal_span",
        "carry the guest path through the host face while keeping consecutive cutters overlapped",
    ),
    ("puncture", "ratio"): _projection(
        "puncture", "ratio", "puncture", "ratio", (0.06, 0.24),
        "selected_live_solid_cross_section",
        "keep structure between repeated openings without collapsing variations",
    ),
    ("shift", "distance_ratio"): _projection(
        "shift", "distance_ratio", "shift_related", "distance_ratio", (0.12, 0.32),
        "selected_live_solid_axis_span",
        "keep every shifted upper body outward, connected, and visually distinct",
    ),
    ("interlock", "bar_ratio"): _projection(
        "interlock", "bar_ratio", "interlock_related", "bar_ratio", (0.42, 0.78),
        "selected_live_solid_cross_axis_span",
        "retain a legible locking bar without reducing it to a fragment",
    ),
    ("interlock", "distance_ratio"): _projection(
        "interlock", "distance_ratio", "interlock_related", "distance_ratio", (0.08, 0.30),
        "selected_live_solid_axis_span",
        "expose the locking bar at the terminal boundary while retaining overlap",
    ),
    ("intersect", "factor"): _projection(
        "intersect", "factor", "intersect_related", "unit_scale", (0.86, 1.0),
        "selected_live_solid_plan_span",
        "retain two legible crossing volumes instead of only their Boolean overlap",
    ),
    ("grade", "depth_ratio"): _projection(
        "grade", "depth_ratio", "book_grade", "depth_ratio", (0.18, 0.62),
        "selected_live_solid_face_normal_span",
        "keep a connected back layer behind the p.29 graded recess",
    ),
    ("pinch", "depth_ratio"): _projection(
        "pinch", "depth_ratio", "pinch", "profile_power", (1.2, 3.8),
        "selected_live_solid_axis_span",
        "vary how tightly the p.31 waist is concentrated around the middle",
    ),
    ("embed", "distance_ratio"): _projection(
        "embed", "distance_ratio", "embed_void", "embedded_ratio", (0.46, 0.76),
        "selected_live_solid_face_normal_span",
        "vary the p.34 guest insertion while retaining material behind the overlap",
    ),
    ("shear", "angle"): _projection(
        "shear", "angle", "slice", "offset_ratio", (0.08, 0.32),
        "selected_live_solid_projected_span",
        "retain a bounded diagonal remainder after the p.32 subtractive cut",
    ),
}


BOOK_RELATION_INVARIANTS: dict[tuple[str, str], BookRelationInvariant] = {
    ("fracture", "retained_back_ratio"): BookRelationInvariant(
        verb="fracture",
        kernel_operator="book_fracture",
        kernel_parameter="retained_back_ratio",
        value=0.32,
        measurement_basis="selected_live_solid_face_normal_span",
        rationale=(
            "p.28 defines a subtractive fissure but no through-depth variation; "
            "retain a continuous back layer so the single volume does not become fragments"
        ),
    ),
    ("shift", "split_ratio"): BookRelationInvariant(
        verb="shift",
        kernel_operator="shift_related",
        kernel_parameter="split_ratio",
        value=0.50,
        measurement_basis="selected_live_solid_height",
        rationale=(
            "SHIFT supplies axis and distance but no section plane; use the neutral "
            "mid-height relation instead of pretending it is a BOOK variation"
        ),
    ),
}


def project_book_parameter(verb: str, source_parameter: str, value: float) -> float:
    """Linearly project one bounded BOOK value into its kernel-safe range."""

    contract = BOOK_KERNEL_PARAMETER_PROJECTIONS[(verb, source_parameter)]
    source_low, source_high = contract.source_bounds
    target_low, target_high = contract.kernel_bounds
    bounded = max(source_low, min(source_high, float(value)))
    unit = (bounded - source_low) / (source_high - source_low)
    return round(target_low + (target_high - target_low) * unit, 6)


def book_relation_invariant(verb: str, kernel_parameter: str) -> float:
    return BOOK_RELATION_INVARIANTS[(verb, kernel_parameter)].value


def book_parameter_projection_evidence(verbs: tuple[str, ...]) -> dict[str, object]:
    """Return serializable evidence for the parameter bridge used by a graph."""

    selected_verbs = set(verbs)
    projections = [
        {
            "verb": item.verb,
            "source_parameter": item.source_parameter,
            "source_bounds": list(item.source_bounds),
            "kernel_operator": item.kernel_operator,
            "kernel_parameter": item.kernel_parameter,
            "kernel_bounds": list(item.kernel_bounds),
            "measurement_basis": item.measurement_basis,
        }
        for item in BOOK_KERNEL_PARAMETER_PROJECTIONS.values()
        if item.verb in selected_verbs
    ]
    invariants = [
        {
            "verb": item.verb,
            "kernel_operator": item.kernel_operator,
            "kernel_parameter": item.kernel_parameter,
            "value": item.value,
            "measurement_basis": item.measurement_basis,
        }
        for item in BOOK_RELATION_INVARIANTS.values()
        if item.verb in selected_verbs
    ]
    return {
        "schema_version": BOOK_PARAMETER_PROJECTION_SCHEMA_VERSION,
        "coordinate_system": "selected_live_solid_normalized_bounds",
        "projections": projections,
        "relation_invariants": invariants,
    }


__all__ = [
    "BOOK_KERNEL_PARAMETER_PROJECTIONS",
    "BOOK_PARAMETER_PROJECTION_SCHEMA_VERSION",
    "BOOK_RELATION_INVARIANTS",
    "BookKernelParameterProjection",
    "BookRelationInvariant",
    "book_parameter_projection_evidence",
    "book_relation_invariant",
    "project_book_parameter",
]
