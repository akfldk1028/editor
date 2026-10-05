"""Diagram-derived semantics for the architect-supplied BOOK.

The BOOK is not a flat list of attractive labels.  Each base operative is a
three-part grammar: choose a relative base volume and orientation, perform one
spatial action, then explore bounded variations of the action.  This module
keeps that evidence separate from parcel coordinates and compiler geometry.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.modules.design.generation.maas.book_language.corpus_contract import BASE_VOLUME_FRACTIONS


@dataclass(frozen=True)
class BookOperationSemantics:
    action: str
    input_topology: str
    output_topology: str
    variation_parameters: tuple[str, ...]
    orientation_modes: tuple[str, ...] = ("long_axis", "short_axis", "vertical")

    def to_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "input_topology": self.input_topology,
            "output_topology": self.output_topology,
            "procedure": [
                "select_relative_base_volume_and_orientation",
                self.action,
                "evaluate_bounded_variations_without_changing_the_operative_identity",
            ],
            "variation_parameters": list(self.variation_parameters),
            "orientation_modes": list(self.orientation_modes),
            "base_volume_fractions": [label for label, _fraction in BASE_VOLUME_FRACTIONS],
            "evidence_kind": "diagram_derived",
        }


# These records transcribe the operation shown on BOOK pp.6-37.  They describe
# intent and legal mutation axes; they deliberately contain no site coordinate
# or named-precedent footprint.
OPERATION_SEMANTICS: dict[str, BookOperationSemantics] = {
    "expand": BookOperationSemantics("extend one boundary or sectional face outward", "single_volume", "single_enlarged_volume", ("factor", "axis", "upper_ratio")),
    "extrude": BookOperationSemantics("project a selected face or region along an axis", "single_volume", "single_extended_volume", ("axis", "length", "size")),
    "inflate": BookOperationSemantics("displace the envelope outward to form a swollen crown", "single_volume", "single_profiled_volume", ("factor", "upper_ratio")),
    "branch": BookOperationSemantics("grow secondary arms from a primary trunk", "single_volume", "connected_multi_arm_volume", ("trunk_ratio", "arm_ratio", "angle")),
    "merge": BookOperationSemantics("fuse separate volumes into one continuous body", "multiple_volumes", "single_fused_volume", ("axis", "gap_ratio", "unit_scale")),
    "nest": BookOperationSemantics("place a smaller volume concentrically within a host", "multiple_volumes", "nested_volumes", ("inner_scale", "upper_ratio")),
    "offset": BookOperationSemantics("duplicate and translate a related volume", "multiple_volumes", "offset_related_volumes", ("axis", "distance_ratio", "other_scale")),
    "bend": BookOperationSemantics("deflect a continuous longitudinal axis into a bend", "single_volume", "single_bent_volume", ("axis", "angle", "curvature", "width_gradient")),
    "skew": BookOperationSemantics("obliquely displace faces while preserving continuity", "single_volume", "single_skewed_volume", ("axis", "angle", "upper_ratio")),
    "split": BookOperationSemantics("divide a terminal region and hinge-displace one child while retaining the opposite trunk", "single_volume", "connected_split_descendants", ("axis", "gap_ratio", "bridge_ratio")),
    "twist": BookOperationSemantics("rotate successive sections around the selected base-volume orientation", "single_volume", "single_twisted_volume", ("angle", "upper_ratio")),
    "interlock": BookOperationSemantics("engage paired notched L volumes through a shared zone", "multiple_volumes", "interlocked_volumes", ("axis", "angle", "bar_ratio", "distance_ratio")),
    "intersect": BookOperationSemantics("retain the spatial crossing of multiple volumes", "multiple_volumes", "intersecting_volume", ("angle", "factor")),
    "lift": BookOperationSemantics("displace a smaller related guest from a larger host while retaining overlap", "multiple_volumes", "host_and_lifted_guest", ("distance_ratio", "guest_scale")),
    "lodge": BookOperationSemantics("lodge a smaller guest in the interval between two related hosts", "multiple_volumes", "two_hosts_with_lodged_guest", ("axis", "distance_ratio", "guest_scale")),
    "overlap": BookOperationSemantics("partially superpose related volumes in plan or section", "multiple_volumes", "overlapping_volumes", ("axis", "slab_ratio", "shift_ratio", "vertical_overlap")),
    "rotate": BookOperationSemantics("rotate one partitioned child about its shared terminal hinge edge", "multiple_volumes", "hinged_rotated_children", ("axis", "angle", "factor")),
    "shift": BookOperationSemantics("translate a related volume without rotating it", "multiple_volumes", "shifted_related_volumes", ("axis", "distance_ratio")),
    "carve": BookOperationSemantics("remove a bounded recess from an exposed side", "single_volume", "single_recessed_volume", ("side", "width_ratio", "depth_ratio")),
    "compress": BookOperationSemantics("contract the volume along the selected base-volume orientation", "single_volume", "single_compressed_volume", ("factor",)),
    "fracture": BookOperationSemantics("subtract a directional bent fissure from the selected base-volume face", "single_volume", "single_fractured_volume", ("gap_ratio", "angle")),
    "grade": BookOperationSemantics("subtract successive bands from the selected base-volume face to form a grade", "single_volume", "single_graded_volume", ("side", "width_ratio", "depth_ratio")),
    "notch": BookOperationSemantics("subtract a triangular wedge from the selected base-volume face", "single_volume", "single_notched_volume", ("corner", "ratio")),
    "pinch": BookOperationSemantics("contract an intermediate waist along the selected base-volume orientation while retaining both ends", "single_volume", "single_pinched_volume", ("waist_ratio", "depth_ratio")),
    "shear": BookOperationSemantics("subtract an oblique half-space normal to the selected base-volume orientation", "single_volume", "single_sheared_volume", ("angle",)),
    "taper": BookOperationSemantics("reduce successive plan sections toward one end or top", "single_volume", "single_tapered_volume", ("x_ratio", "y_ratio", "top_shift_x_ratio", "top_shift_y_ratio")),
    "embed": BookOperationSemantics("subtract the overlap made by a guest embedded in a host", "multiple_volumes", "host_with_embedded_void", ("guest_scale", "position", "distance_ratio")),
    "extract": BookOperationSemantics("subtract the overlapping path of a guest moving from an internal position through an exterior mouth", "multiple_volumes", "host_with_extraction_channel", ("side", "ratio", "distance_ratio")),
    "inscribe": BookOperationSemantics("subtract a geometrically related inner volume", "multiple_volumes", "inscribed_shell_or_court", ("ratio", "open_side")),
    "puncture": BookOperationSemantics("subtract repeated compact openings through the mass", "multiple_volumes", "perforated_volume", ("axis", "n", "spacing_ratio", "ratio")),
}


def semantics_for(verb: str) -> BookOperationSemantics:
    try:
        return OPERATION_SEMANTICS[verb]
    except KeyError as exc:
        raise ValueError(f"BOOK semantics missing for {verb!r}") from exc


__all__ = ["BASE_VOLUME_FRACTIONS", "BookOperationSemantics", "OPERATION_SEMANTICS", "semantics_for"]
