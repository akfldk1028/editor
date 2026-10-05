"""Shared editable MassDSL parameter contract for every authoring agent."""

from __future__ import annotations


PARAMETER_BOUNDS: dict[str, tuple[float, float]] = {
    "factor": (0.18, 0.90),
    "ratio": (0.12, 0.90),
    "upper_ratio": (0.18, 0.95),
    "top_ratio": (0.18, 0.95),
    "width_ratio": (0.05, 0.90),
    "lane_width_ratio": (0.045, 0.22),
    "arm_ratio": (0.10, 0.90),
    "branch_ratio": (0.10, 0.90),
    "bar_ratio": (0.08, 0.48),
    "width_gradient": (-0.30, 0.30),
    "width_start_ratio": (0.45, 1.35),
    "width_mid_ratio": (0.65, 1.55),
    "width_end_ratio": (0.45, 1.35),
    "width_wave": (-0.28, 0.28),
    "branch_point_ratio": (0.22, 0.58),
    "height_start_ratio": (0.40, 1.00),
    "height_mid_ratio": (0.50, 1.00),
    "height_end_ratio": (0.40, 1.00),
    "height_wave": (-0.24, 0.24),
    "longitudinal_wave": (-0.24, 0.24),
    "twist": (-0.30, 0.30),
    "shoulder_fraction": (0.12, 0.68),
    "base_scale_x_ratio": (0.28, 1.0),
    "base_scale_y_ratio": (0.28, 1.0),
    "base_shift_x_ratio": (-0.28, 0.28),
    "base_shift_y_ratio": (-0.28, 0.28),
    "top_scale_x_ratio": (0.08, 1.12),
    "top_scale_y_ratio": (0.08, 1.12),
    "top_shift_x_ratio": (-0.30, 0.30),
    "top_shift_y_ratio": (-0.30, 0.30),
    "depth_ratio": (0.10, 0.90),
    "slab_ratio": (0.12, 0.70),
    "distance_ratio": (-0.34, 0.34),
    "shift_ratio": (-0.34, 0.34),
    "curvature": (-0.18, 0.18),
    "vertical_overlap": (0.0, 0.34),
    "lower_floor_fraction": (0.12, 0.88),
    "gap_ratio": (0.04, 0.48),
    "angle": (-55.0, 55.0),
    "shift": (-0.34, 0.34),
    "x_ratio": (0.18, 1.0),
    "y_ratio": (0.18, 1.0),
    "waist_ratio": (0.18, 0.90),
    "length": (0.10, 1.0),
    "bridge_ratio": (0.04, 0.60),
    "trunk_ratio": (0.10, 0.90),
    "guest_scale": (0.12, 0.80),
    "inner_scale": (0.12, 0.80),
    "other_scale": (0.18, 0.90),
    "spacing_ratio": (0.08, 0.50),
    "unit_scale": (0.12, 0.70),
    "hierarchy_ratio": (0.08, 0.36),
    "stagger_ratio": (0.04, 0.28),
    "size": (0.10, 0.80),
    "levels": (2.0, 4.0),
    "n": (2.0, 4.0),
    "lane_count": (2.0, 3.0),
    "field_samples": (5.0, 9.0),
}


CATEGORICAL_PARAMETER_VALUES: dict[str, tuple[str, ...]] = {
    "axis": ("x", "y"),
    "side": ("north", "south", "east", "west"),
    "corner": ("nw", "ne", "sw", "se"),
    "open_side": ("closed", "north", "south", "east", "west"),
    "field_topology": ("parallel", "branched"),
    "vertical_mode": ("terraced", "grounded"),
    "position": ("center", "north", "south", "east", "west"),
    "orientation": ("long_axis", "short_axis", "vertical"),
    "base_volume_label": ("1/1", "3/8", "1/2", "1/4", "1/8", "1/16"),
}


# Canonical operation contract shared by the LLM author and VLM graph reviser.
# Keeping this in the grammar layer prevents the author prompt from accepting a
# parameter that the mutation layer will silently discard.
PARAMETERS_BY_VERB: dict[str, tuple[str, ...]] = {
    "select_book_scope": ("base_volume_label", "orientation"),
    "expand": ("axis", "factor", "upper_ratio", "lower_floor_fraction"),
    "notch": ("corner", "ratio"),
    "cave": ("side", "width_ratio", "depth_ratio"),
    "courtyard": ("ratio", "open_side", "upper_ratio", "lower_floor_fraction"),
    "split": ("axis", "gap_ratio", "bridge_ratio", "upper_ratio", "lower_floor_fraction"),
    "bar": ("axis", "factor", "shift", "upper_ratio", "lower_floor_fraction"),
    "branch": ("angle", "trunk_ratio", "arm_ratio", "upper_ratio", "lower_floor_fraction"),
    "pinch": ("axis", "waist_ratio", "depth_ratio", "upper_ratio", "lower_floor_fraction"),
    "bend": (
        "axis", "angle", "factor", "upper_ratio", "lower_floor_fraction",
        "lane_count", "lane_width_ratio", "vertical_overlap", "curvature",
        "branch_point_ratio", "width_start_ratio", "width_mid_ratio",
        "width_end_ratio", "width_wave", "height_start_ratio",
        "height_mid_ratio", "height_end_ratio", "height_wave",
        "field_topology", "vertical_mode", "control_points",
    ),
    "embed": ("guest_scale", "position", "upper_ratio", "distance_ratio", "lower_floor_fraction"),
    "extrude": ("axis", "length", "size", "upper_ratio", "lower_floor_fraction"),
    "nest": ("inner_scale", "upper_ratio", "lower_floor_fraction"),
    "stack": ("levels", "upper_ratio", "lower_floor_fraction"),
    "offset": ("axis", "distance_ratio", "other_scale", "upper_ratio", "lower_floor_fraction"),
    "array": (
        "axis", "n", "spacing_ratio", "unit_scale", "hierarchy_ratio",
        "stagger_ratio", "lower_floor_fraction",
    ),
    "reflect": ("axis", "gap_ratio", "unit_scale", "upper_ratio", "lower_floor_fraction"),
    "inflate": ("factor", "upper_ratio", "lower_floor_fraction"),
    "merge": ("axis", "gap_ratio", "unit_scale", "upper_ratio", "lower_floor_fraction"),
    "skew": ("axis", "angle", "upper_ratio", "lower_floor_fraction"),
    "twist": ("angle", "upper_ratio", "lower_floor_fraction"),
    "intersect": ("angle", "factor", "upper_ratio", "lower_floor_fraction"),
    "lodge": ("axis", "distance_ratio", "guest_scale", "upper_ratio", "lower_floor_fraction"),
    "rotate": ("angle", "factor", "upper_ratio", "lower_floor_fraction"),
    "carve": ("side", "width_ratio", "depth_ratio", "upper_ratio", "lower_floor_fraction"),
    "compress": ("axis", "factor", "upper_ratio", "lower_floor_fraction"),
    "fracture": ("axis", "gap_ratio", "angle", "upper_ratio", "lower_floor_fraction"),
    "shear": ("axis", "angle", "upper_ratio", "lower_floor_fraction"),
    "extract": ("side", "ratio", "distance_ratio", "upper_ratio", "lower_floor_fraction"),
    "inscribe": ("ratio", "open_side", "upper_ratio", "lower_floor_fraction"),
    "puncture": ("ratio", "axis", "n", "spacing_ratio", "upper_ratio", "lower_floor_fraction"),
    "pack": ("axis", "n", "spacing_ratio", "unit_scale", "upper_ratio", "lower_floor_fraction"),
    "join": ("axis", "gap_ratio", "unit_scale", "bridge_ratio", "upper_ratio", "lower_floor_fraction"),
    "interlock": ("angle", "bar_ratio", "upper_ratio", "distance_ratio", "lower_floor_fraction"),
    "overlap": ("axis", "slab_ratio", "shift_ratio", "vertical_overlap", "upper_ratio", "distance_ratio", "lower_floor_fraction"),
    "lift": (
        "axis", "guest_scale", "distance_ratio",
        "upper_ratio", "lower_floor_fraction",
    ),
    "taper": (
        "x_ratio", "y_ratio", "lower_floor_fraction",
        "plan_control_points", "top_height_controls", "shoulder_fraction",
        "base_scale_x_ratio", "base_scale_y_ratio",
        "base_shift_x_ratio", "base_shift_y_ratio",
        "top_scale_x_ratio", "top_scale_y_ratio",
        "top_shift_x_ratio", "top_shift_y_ratio",
    ),
    "grade": ("side", "width_ratio", "depth_ratio", "lower_floor_fraction"),
    "shift": ("axis", "distance_ratio"),
    "diagonal_connect": ("axis", "upper_ratio", "distance_ratio", "angle", "lower_floor_fraction"),
    "terrace_link": ("side", "upper_ratio", "width_ratio", "depth_ratio", "lower_floor_fraction"),
    "sloped_roof_mass": (
        "axis", "upper_ratio", "x_ratio", "y_ratio", "lower_floor_fraction",
        "field_samples", "longitudinal_wave", "twist", "control_points",
        "section_interpolation",
    ),
}


def bounded_parameter(name: str, value: float) -> float:
    low, high = PARAMETER_BOUNDS[name]
    bounded = max(low, min(high, float(value)))
    if name in {"n", "lane_count", "field_samples", "levels"}:
        return int(round(bounded))
    return round(bounded, 4)


__all__ = [
    "CATEGORICAL_PARAMETER_VALUES",
    "PARAMETER_BOUNDS",
    "PARAMETERS_BY_VERB",
    "bounded_parameter",
]
