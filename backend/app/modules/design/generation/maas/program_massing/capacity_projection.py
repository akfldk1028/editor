"""Capacity feedback for executable continuous-field mass graphs.

The language author owns the path and topology. This module only projects an
under-capacity ``bend`` genotype toward a measured FAR target by changing its
bounded occupiable width/section parameters. It contains no parcel coordinates
or named-building templates and may be replaced by a learned optimizer later.
"""

from __future__ import annotations

from dataclasses import replace

from backend.app.modules.design.generation.maas.grammar.component_graph import MassComponentGraph, graph_from_sequence
from backend.app.modules.design.generation.maas.grammar.parameter_schema import bounded_parameter
from backend.app.modules.design.generation.maas.grammar.verb_sequence import VerbCall, VerbSequence


def project_bend_capacity(
    sequence: VerbSequence,
    *,
    observed_utilization: float,
    target_utilization: float,
) -> VerbSequence | None:
    """Return one provenance-marked capacity projection for an authored bend.

    Floor area is approximately linear in lane count and lane width. The
    feedback ratio is therefore allocated to a third lane first (when useful),
    then to bounded lane width and vertical overlap. Curve control points,
    topology and every non-capacity parameter remain authored and unchanged.
    """
    observed = float(observed_utilization)
    target = float(target_utilization)
    if observed <= 0.0 or target <= observed:
        return None
    graph = graph_from_sequence(sequence)
    bend_index = next(
        (index for index, node in enumerate(graph.nodes) if node.role == "primary" and node.operation.verb == "bend"),
        None,
    )
    if bend_index is None:
        bend_index = next(
            (index for index, node in enumerate(graph.nodes) if node.operation.verb == "bend"),
            None,
        )
    if bend_index is None:
        return None

    node = graph.nodes[bend_index]
    params = dict(node.operation.params)
    required_factor = max(1.0, min(2.6, target / max(observed, 1e-9)))
    original_lane_count = int(round(float(params.get("lane_count") or 3)))
    lane_count = original_lane_count
    residual_factor = required_factor
    if lane_count == 2 and required_factor >= 1.22:
        lane_count = 3
        residual_factor /= 1.5
    current_width = float(params.get("lane_width_ratio") or params.get("width_ratio") or 0.10)
    projected_width = bounded_parameter(
        "lane_width_ratio",
        current_width * max(1.0, residual_factor) * 1.03,
    )
    current_overlap = float(params.get("vertical_overlap") or 0.22)
    projected_overlap = bounded_parameter(
        "vertical_overlap",
        current_overlap + min(0.12, max(0.0, required_factor - 1.0) * 0.10),
    )
    if (
        lane_count == original_lane_count
        and projected_width == current_width
        and projected_overlap == current_overlap
    ):
        return None

    params.update({
        "lane_count": lane_count,
        "lane_width_ratio": projected_width,
        "vertical_overlap": projected_overlap,
    })
    nodes = list(graph.nodes)
    nodes[bend_index] = replace(
        node,
        operation=VerbCall("bend", params),
        constraints={
            **node.constraints,
            "capacity_projected": True,
            "capacity_projection_source": "observed_far_feedback",
        },
    )
    projected = MassComponentGraph(
        f"{graph.name}__capacity_projected",
        graph.label,
        tuple(nodes),
        graph.notes + (
            "capacity_projection=observed_far_feedback;"
            f"observed={observed:.4f};target={target:.4f}",
        ),
    )
    return projected.to_sequence()


__all__ = ["project_bend_capacity"]
