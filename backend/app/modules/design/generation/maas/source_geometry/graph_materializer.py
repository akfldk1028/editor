"""Materialize an executable component graph into semantic early-massing solids.

The compiler state stored for a child is cumulative.  Emitting every terminal
state therefore duplicates its ancestors and produces the familiar pile of
overlapping boxes.  This module interprets graph *relations* instead:

* the primary lineage owns the main solid;
* subtractive descendants reshape that solid, but never become solids;
* support descendants may replace the upper plate or contribute a true delta;
* connector descendants only materialize geometry that bridges distinct parts.

No named typology template or parcel coordinate recipe is used here.
"""

from __future__ import annotations

from collections import Counter
from math import cos, radians, sin
from typing import Any

from shapely.affinity import affine_transform, rotate
from shapely.geometry import LineString, MultiPolygon, Polygon, box
from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.grammar.component_graph import MassComponentGraph, MassComponentNode

from backend.app.modules.design.generation.maas.source_geometry.ir import SourceVolume


def is_graph_native(graph: MassComponentGraph) -> bool:
    return any(
        bool(node.constraints.get("author_graph_native") or node.constraints.get("critic_authored"))
        for node in graph.nodes
    )


def materialize_graph_states(
    graph: MassComponentGraph,
    states: dict[str, dict[str, Any]],
) -> tuple[tuple[SourceVolume, ...], dict[str, Any]]:
    """Project graph roles and relations without re-emitting cumulative states."""
    child_counts = Counter(node.parent_id for node in graph.nodes if node.parent_id is not None)
    terminals = [node for node in graph.nodes[1:] if child_counts.get(node.node_id, 0) == 0]
    primary = next((node for node in graph.nodes[1:] if node.role == "primary"), None)
    if primary is None or not isinstance(states.get(primary.node_id), dict):
        return (), _evidence(terminals, child_counts, (), (), "missing_primary")

    # LLM-authored graphs commonly attach the primary, void and sectional
    # support as siblings of the root.  Relation semantics still make those
    # nodes operate on the single primary mass. Restricting mutations to
    # descendants silently discarded correctly authored courtyard/subtract
    # nodes and turned them into metadata-only generic boxes.
    subtractive = [
        node for node in graph.nodes[1:]
        if node.role == "void" or node.relation == "subtract"
    ]
    supports = [node for node in graph.nodes[1:] if node.role == "support" and node not in subtractive]
    connectors = [node for node in graph.nodes[1:] if node.role == "connector" or node.relation == "connect"]

    primary_state = states[primary.node_id]
    materialization_states = dict(states)
    for node in supports:
        if _is_descendant(graph, node, primary.node_id):
            continue
        rebased = _rebase_state_to_primary(node, primary_state, graph, states)
        if rebased is not None:
            materialization_states[node.node_id] = rebased
    main = _polygon(primary_state.get("footprint"))
    if main is None:
        return (), _evidence(terminals, child_counts, (), (), "missing_primary_footprint")

    split_bodies = _split_primary_bodies(primary, graph, states)
    interlock_bodies = _interlock_primary_bodies(primary, states)
    relational_bodies = split_bodies or interlock_bodies
    if relational_bodies:
        parent_state = states.get(str(primary.parent_id))
        parent_footprint = _polygon(parent_state.get("footprint")) if isinstance(parent_state, dict) else None
        if parent_footprint is not None:
            main = parent_footprint

    authored_layout_units = tuple(
        polygon
        for value in (primary_state.get("layout_units") or ())
        if (polygon := _polygon(value)) is not None
    )
    if len(authored_layout_units) >= 2 or relational_bodies:
        # In a field graph, separation between authored cells is already the
        # void. Re-cutting every cell with a cumulative courtyard state turns
        # clean bars into notched/tortuous fragments and can delete a member.
        # Preserve the cells and consume the void relation as figure-ground
        # intent instead of extruding or subtracting it a second time.
        applied_subtractive = []
        encoded_field_voids = list(subtractive)
    else:
        main, applied_subtractive = _apply_subtractive_relations(main, subtractive, graph, states)
        encoded_field_voids = []
    if main is None:
        return (), _evidence(terminals, child_counts, (), (), "subtraction_removed_primary")
    shape_node = applied_subtractive[-1] if applied_subtractive else primary
    shape_state = states.get(shape_node.node_id) if isinstance(states.get(shape_node.node_id), dict) else primary_state

    consumed = [
        primary.node_id,
        *(node.node_id for node in applied_subtractive),
        *(node.node_id for node in encoded_field_voids),
    ]
    volumes: list[SourceVolume] = []
    layout_units = _partition_layout_units(primary_state.get("layout_units"), main)
    connector_layout_units = layout_units or relational_bodies
    if relational_bodies:
        for index, body in enumerate(relational_bodies):
            if interlock_bodies:
                bottom, top = ((0.0, 0.56), (0.44, 1.0))[index]
            else:
                bottom, top = 0.0, min(1.0, 0.76 + index * 0.08)
            volumes.append(SourceVolume(
                role=f"primary_graph_{_token(primary)}_body_{index}",
                footprint=body,
                bottom_fraction=bottom,
                top_fraction=top,
                verb=primary.operation.verb,
            ))
    elif layout_units:
        # Array/offset is one graph operator, not several inherited terminals.
        # Cell partitioning removes planar overlap before any z assignment.
        for index, unit in enumerate(layout_units[:4]):
            volumes.append(SourceVolume(
                role=f"primary_graph_{_token(primary)}_unit_{index}",
                footprint=unit,
                bottom_fraction=0.0,
                top_fraction=min(1.0, 0.72 + index * 0.08),
                verb=primary.operation.verb,
            ))
    else:
        layers, profile_node = _sectional_layers(main, shape_state, supports, materialization_states)
        if len(layers) >= 2:
            bands = _section_bands(len(layers), shape_state)
            for index, ((layer, node), (bottom, top)) in enumerate(zip(layers, bands)):
                volumes.append(SourceVolume(
                    role=(
                        f"primary_graph_{_token(primary)}_ground"
                        if index == 0
                        else f"support_graph_{_token(node or primary)}_section_{index}"
                    ),
                    footprint=layer,
                    bottom_fraction=bottom,
                    top_fraction=top,
                    verb=(node or primary).operation.verb,
                ))
                if node is not None:
                    consumed.append(node.node_id)
        else:
            # A support may change the section/roof without changing the plan.
            # Preserve that authored verb so the surface compiler can loft the
            # primary envelope instead of displaying another flat box.
            effective_node = profile_node or primary
            volumes.append(SourceVolume(
                role=f"primary_graph_{_token(primary)}_solid",
                footprint=main,
                bottom_fraction=0.0,
                top_fraction=1.0,
                verb=effective_node.operation.verb,
            ))
            if profile_node is not None:
                consumed.append(profile_node.node_id)

    # A support is emitted only when it contributes plan area not already
    # represented by the primary lineage.  Cumulative support states otherwise
    # remain metadata/mutations rather than duplicate solids.
    occupied_plan = unary_union([volume.footprint for volume in volumes])
    for node in supports:
        if node.node_id in consumed:
            continue
        if connector_layout_units:
            # Array cells already carry staggered height bands. A cumulative
            # lift/shift/taper support does not contribute a fifth plan mass;
            # emitting its delta fills the intended courts between cells.
            consumed.append(node.node_id)
            continue
        state = materialization_states.get(node.node_id)
        contribution = _state_delta(state, occupied_plan, minimum_area=max(1.0, main.area * 0.035))
        if contribution is None:
            continue
        volumes.append(SourceVolume(
            role=f"support_graph_{_token(node)}_delta",
            footprint=contribution,
            bottom_fraction=0.44,
            top_fraction=0.78,
            verb=node.operation.verb,
        ))
        occupied_plan = unary_union((occupied_plan, contribution))
        consumed.append(node.node_id)
        if len(volumes) >= 4:
            break

    for node in connectors:
        if len(volumes) >= 4:
            break
        if node.operation.verb not in {"diagonal_connect", "interlock", "terrace_link"}:
            # A graph relation called `connect` is not automatically a
            # skybridge. Offset/overlap are mutations and must not fill every
            # open slot in a clustered field with an invented corridor.
            consumed.append(node.node_id)
            continue
        connector = _connector_delta(node, main, connector_layout_units, occupied_plan, materialization_states)
        if connector is None:
            continue
        volumes.append(SourceVolume(
            role=f"connector_graph_{_token(node)}_bridge",
            footprint=connector,
            bottom_fraction=0.56,
            top_fraction=0.72,
            verb=node.operation.verb,
        ))
        occupied_plan = unary_union((occupied_plan, connector))
        consumed.append(node.node_id)

    emitted = tuple(volume.role for volume in volumes)
    evidence = _evidence(terminals, child_counts, consumed, emitted, "relation_semantics")
    evidence.update({
        "primary_node_id": primary.node_id,
        "subtractive_node_ids": [node.node_id for node in applied_subtractive],
        "layout_unit_count": len(connector_layout_units),
        "split_body_count": len(split_bodies),
        "interlock_body_count": len(interlock_bodies),
        "cumulative_terminal_states_emitted": False,
    })
    return tuple(volumes), evidence


def _split_primary_bodies(
    primary: MassComponentNode,
    graph: MassComponentGraph,
    states: dict[str, dict[str, Any]],
) -> tuple[Polygon, ...]:
    """Resolve a split relation as two clean bodies before adding a bridge."""
    if primary.operation.verb != "split":
        return ()
    parent_state = states.get(str(primary.parent_id))
    parent = _polygon(parent_state.get("footprint")) if isinstance(parent_state, dict) else None
    if parent is None:
        return ()
    minx, miny, maxx, maxy = parent.bounds
    params = primary.operation.params
    try:
        gap_ratio = float(params.get("gap_ratio", 0.18))
    except (TypeError, ValueError):
        gap_ratio = 0.18
    gap_ratio = max(0.08, min(0.32, gap_ratio))
    axis = str(params.get("axis") or "x").lower()
    if axis == "y":
        gap = (maxy - miny) * gap_ratio
        center = parent.centroid.y
        cutter = box(minx - 1.0, center - gap / 2.0, maxx + 1.0, center + gap / 2.0)
    else:
        gap = (maxx - minx) * gap_ratio
        center = parent.centroid.x
        cutter = box(center - gap / 2.0, miny - 1.0, center + gap / 2.0, maxy + 1.0)
    separated = parent.difference(cutter)
    parts = list(separated.geoms) if isinstance(separated, MultiPolygon) else [separated]
    bodies = [part for part in parts if isinstance(part, Polygon) and part.area >= max(1.0, parent.area * 0.12)]
    if len(bodies) != 2:
        return ()
    bodies.sort(key=lambda item: item.centroid.y if axis == "y" else item.centroid.x)
    return tuple(bodies)


def _interlock_primary_bodies(
    primary: MassComponentNode,
    states: dict[str, dict[str, Any]],
) -> tuple[Polygon, ...]:
    """Resolve an interlock verb as two crossing occupiable bars."""
    if primary.operation.verb != "interlock":
        return ()
    parent_state = states.get(str(primary.parent_id))
    parent = _polygon(parent_state.get("footprint")) if isinstance(parent_state, dict) else None
    if parent is None:
        return ()
    minx, miny, maxx, maxy = parent.bounds
    width, depth = maxx - minx, maxy - miny
    cx, cy = parent.centroid.x, parent.centroid.y
    params = primary.operation.params
    try:
        angle = float(params.get("angle", 28.0))
    except (TypeError, ValueError):
        angle = 28.0
    # Some structured responses express radians even though the DSL uses
    # degrees. Normalize that representation without imposing a form preset.
    if abs(angle) <= 1.2:
        angle *= 57.29577951308232
    angle = max(-48.0, min(48.0, angle))
    try:
        bar_ratio = float(params.get("bar_ratio", 0.34))
    except (TypeError, ValueError):
        bar_ratio = 0.34
    bar_width = min(width, depth) * max(0.18, min(0.42, bar_ratio * 0.55))
    length = max(width, depth) * 1.25
    horizontal = rotate(
        box(cx - length / 2.0, cy - bar_width / 2.0, cx + length / 2.0, cy + bar_width / 2.0),
        angle,
        origin=(cx, cy),
    ).intersection(parent)
    vertical = rotate(
        box(cx - bar_width / 2.0, cy - length / 2.0, cx + bar_width / 2.0, cy + length / 2.0),
        angle,
        origin=(cx, cy),
    ).intersection(parent)
    bodies = tuple(
        body
        for value in (horizontal, vertical)
        if (body := _polygon(value)) is not None and body.area >= max(1.0, parent.area * 0.12)
    )
    return bodies if len(bodies) == 2 else ()


def _is_descendant(graph: MassComponentGraph, node: MassComponentNode, ancestor_id: str) -> bool:
    parents = {item.node_id: item.parent_id for item in graph.nodes}
    parent_id = node.parent_id
    while parent_id is not None:
        if parent_id == ancestor_id:
            return True
        parent_id = parents.get(parent_id)
    return False


def _rebase_state_to_primary(
    node: MassComponentNode,
    primary_state: dict[str, Any],
    graph: MassComponentGraph,
    states: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Move a root-sibling mutation from its parent frame to the primary.

    The compiler evaluates each branch in its actual parent frame.  For a
    support attached beside the primary, its normalized shift/taper/lift is
    still meaningful, but the resulting coordinates live in the root parcel
    frame.  A bounds-to-bounds affine transform preserves that authored rule
    while applying it to the primary mass.  This is graph interpretation, not
    a named-form template or parcel-coordinate recipe.
    """
    parent_id = next((item.parent_id for item in graph.nodes if item.node_id == node.node_id), None)
    parent_state = states.get(str(parent_id))
    state = states.get(node.node_id)
    target = _polygon(primary_state.get("footprint"))
    parent = _polygon(parent_state.get("footprint")) if isinstance(parent_state, dict) else None
    if not isinstance(state, dict) or target is None or parent is None:
        return None
    pminx, pminy, pmaxx, pmaxy = parent.bounds
    tminx, tminy, tmaxx, tmaxy = target.bounds
    pwidth, pdepth = pmaxx - pminx, pmaxy - pminy
    if min(pwidth, pdepth) <= 1e-9:
        return None
    sx = (tmaxx - tminx) / pwidth
    sy = (tmaxy - tminy) / pdepth
    matrix = (sx, 0.0, 0.0, sy, tminx - pminx * sx, tminy - pminy * sy)
    rebased = dict(state)
    for key in ("footprint", "upper"):
        polygon = _polygon(state.get(key))
        rebased[key] = _polygon(affine_transform(polygon, matrix)) if polygon is not None else None
    rebased["layout_units"] = [
        transformed
        for item in state.get("layout_units") or []
        if (polygon := _polygon(item)) is not None
        and (transformed := _polygon(affine_transform(polygon, matrix))) is not None
    ]
    return rebased


def _apply_subtractive_relations(
    main: Polygon,
    nodes: list[MassComponentNode],
    graph: MassComponentGraph,
    states: dict[str, dict[str, Any]],
) -> tuple[Polygon | None, list[MassComponentNode]]:
    """Apply each node's *delta* to the primary, including root siblings.

    A node state is cumulative relative to its own parent.  The cutter is
    therefore ``parent footprint - node footprint``. Applying that cutter to
    the primary preserves the primary bar/array shape while honoring a void
    authored on the root branch; replacing the primary with the sibling state
    would incorrectly restore the full parcel envelope.
    """
    parents = {node.node_id: node.parent_id for node in graph.nodes}
    result: Polygon | None = main
    applied: list[MassComponentNode] = []
    for node in nodes:
        if result is None:
            break
        state = states.get(node.node_id)
        parent_state = states.get(str(parents.get(node.node_id)))
        if not isinstance(state, dict) or not isinstance(parent_state, dict):
            continue
        before = _polygon(parent_state.get("footprint"))
        after = _polygon(state.get("footprint"))
        if before is None or after is None:
            continue
        cutter = before.difference(after)
        if cutter.is_empty or cutter.intersection(result).area < max(0.5, result.area * 0.006):
            continue
        result = _polygon(result.difference(cutter))
        if result is not None:
            applied.append(node)
    return result, applied


def _polygon(value: Any) -> Polygon | None:
    if isinstance(value, Polygon) and not value.is_empty:
        return value
    if isinstance(value, MultiPolygon) and not value.is_empty:
        return max(value.geoms, key=lambda item: item.area)
    return None


def _partition_layout_units(value: Any, clip: Polygon) -> tuple[Polygon, ...]:
    units = [_polygon(item) for item in (value or ())]
    units = [item.intersection(clip) for item in units if item is not None and not item.is_empty]
    units = [_polygon(item) for item in units]
    units = [item for item in units if item is not None and item.area >= max(1.0, clip.area * 0.025)]
    if len(units) < 2:
        return ()

    x_spread = max(item.centroid.x for item in units) - min(item.centroid.x for item in units)
    y_spread = max(item.centroid.y for item in units) - min(item.centroid.y for item in units)
    use_x = x_spread >= y_spread
    units.sort(key=lambda item: item.centroid.x if use_x else item.centroid.y)
    centers = [item.centroid.x if use_x else item.centroid.y for item in units]
    boundaries = [(left + right) / 2.0 for left, right in zip(centers, centers[1:])]
    minx, miny, maxx, maxy = clip.bounds
    result: list[Polygon] = []
    for index, unit in enumerate(units):
        low = boundaries[index - 1] if index else (minx if use_x else miny)
        high = boundaries[index] if index < len(boundaries) else (maxx if use_x else maxy)
        cell = box(low, miny, high, maxy) if use_x else box(minx, low, maxx, high)
        shaped = _polygon(unit.intersection(cell).intersection(clip))
        if shaped is not None and shaped.area >= max(1.0, clip.area * 0.025):
            result.append(shaped)
    return tuple(result) if len(result) >= 2 else ()


def _upper_plate(
    main: Polygon,
    shape_state: dict[str, Any],
    supports: list[MassComponentNode],
    states: dict[str, dict[str, Any]],
) -> tuple[Polygon | None, MassComponentNode | None]:
    # Prefer the deepest support because it expresses the graph's sectional
    # mutation.  Fall back to the subtractive/primary lineage upper plate.
    for node in reversed(supports):
        state = states.get(node.node_id)
        if not isinstance(state, dict):
            continue
        candidate = _polygon(state.get("upper"))
        if candidate is not None:
            return _polygon(candidate.intersection(main)), node
    return _polygon(shape_state.get("upper")), None


_SECTIONAL_SUPPORT_VERBS = {
    "bar", "branch", "extrude", "grade", "inset", "interlock", "lift",
    "offset", "overlap", "pinch", "shift", "sloped_roof_mass", "stack",
    "taper", "terrace_link", "inflate", "lodge", "merge", "rotate", "shear",
    "skew", "twist",
}
_PROFILE_SUPPORT_VERBS = {
    "branch", "grade", "inflate", "pinch", "rotate", "shear",
    "skew", "sloped_roof_mass", "terrace_link", "twist",
}


def _sectional_layers(
    main: Polygon,
    shape_state: dict[str, Any],
    supports: list[MassComponentNode],
    states: dict[str, dict[str, Any]],
) -> tuple[list[tuple[Polygon, MassComponentNode | None]], MassComponentNode | None]:
    """Turn cumulative support states into at most three non-duplicate bands.

    The graph may branch, so every support state contains its ancestor again.
    We keep only distinct clipped profiles and assign them to separate height
    bands later. Same-plan profile verbs are retained as a surface mutation.
    """
    layers: list[tuple[Polygon, MassComponentNode | None]] = [(main, None)]
    profile_node: MassComponentNode | None = None
    for node in supports:
        if node.operation.verb not in _SECTIONAL_SUPPORT_VERBS:
            continue
        state = states.get(node.node_id)
        if not isinstance(state, dict):
            continue
        candidate = _polygon(state.get("upper"))
        if candidate is None:
            candidate = _polygon(state.get("footprint"))
        if candidate is None:
            continue
        candidate = _polygon(candidate.intersection(main))
        if candidate is None or candidate.area < max(1.0, main.area * 0.16):
            continue
        if _meaningfully_different(layers[-1][0], candidate):
            layers.append((candidate, node))
            if len(layers) >= 3:
                break
        elif node.operation.verb in _PROFILE_SUPPORT_VERBS:
            profile_node = node
    if len(layers) == 1:
        # Preserve the former primary/void-lineage upper plate whenever no
        # support contributes a distinct section. Omitting this fallback
        # collapsed carved and nested graphs into one full-height box.
        lineage_upper = _polygon(shape_state.get("upper"))
        if lineage_upper is not None:
            lineage_upper = _polygon(lineage_upper.intersection(main))
        if lineage_upper is not None and _meaningfully_different(main, lineage_upper):
            layers.append((lineage_upper, profile_node))
    return layers, profile_node


def _section_bands(
    count: int,
    shape_state: dict[str, Any],
) -> tuple[tuple[float, float], ...]:
    if count <= 1:
        return ((0.0, 1.0),)
    if count == 2:
        split = _fraction(shape_state.get("lower_fraction"), default=0.54)
        return ((0.0, split), (max(0.0, split - 0.04), 1.0))
    # Three bands express a stepped/shifted section while the slight overlaps
    # keep the building connected without re-emitting full cumulative solids.
    return ((0.0, 0.42), (0.38, 0.72), (0.68, 1.0))


def _meaningfully_different(main: Polygon, upper: Polygon) -> bool:
    delta = float(main.symmetric_difference(upper).area) / max(float(main.area), 1e-9)
    area_ratio = float(upper.area) / max(float(main.area), 1e-9)
    return delta >= 0.055 and 0.18 <= area_ratio <= 0.94


def _state_delta(state: Any, occupied, *, minimum_area: float) -> Polygon | None:
    if not isinstance(state, dict):
        return None
    candidates = (_polygon(state.get("upper")), _polygon(state.get("footprint")))
    for candidate in candidates:
        if candidate is None:
            continue
        delta = _polygon(candidate.difference(occupied))
        if delta is not None and delta.area >= minimum_area:
            return delta
    return None


def _connector_delta(
    node: MassComponentNode,
    main: Polygon,
    layout_units: tuple[Polygon, ...],
    occupied,
    states: dict[str, dict[str, Any]],
) -> Polygon | None:
    minx, miny, maxx, maxy = main.bounds
    width, depth = maxx - minx, maxy - miny
    if min(width, depth) <= 0:
        return None
    if len(layout_units) >= 2:
        left, right = max(
            ((a, b) for index, a in enumerate(layout_units) for b in layout_units[index + 1:]),
            key=lambda pair: pair[0].centroid.distance(pair[1].centroid),
        )
        points = ((left.centroid.x, left.centroid.y), (right.centroid.x, right.centroid.y))
    else:
        params = node.operation.params
        angle = radians(float(params.get("angle", 32.0)))
        if str(params.get("axis") or "x") == "y":
            angle += radians(90.0)
        radius = max(width, depth) * 0.58
        cx, cy = main.centroid.x, main.centroid.y
        points = (
            (cx - cos(angle) * radius, cy - sin(angle) * radius),
            (cx + cos(angle) * radius, cy + sin(angle) * radius),
        )
    bridge_width = min(width, depth) * 0.075
    root_state = states.get(next(iter(states), ""), {})
    root = _polygon(root_state.get("footprint")) if isinstance(root_state, dict) else None
    corridor = LineString(points).buffer(bridge_width, cap_style=2, join_style=2)
    if root is not None:
        corridor = corridor.intersection(root)
    # Only a span outside the occupied plan is a new connector.  A line buried
    # inside one solid is annotation, not another overlapping volume.
    delta = _polygon(corridor.difference(occupied.buffer(-bridge_width * 0.18)))
    if delta is None or delta.area < max(1.0, main.area * 0.018):
        return None
    return delta


def _evidence(
    terminals: list[MassComponentNode],
    child_counts: Counter,
    consumed: Any,
    emitted: Any,
    status: str,
) -> dict[str, Any]:
    return {
        "schema_version": "arr.maas.graph_materialization.v2",
        "mode": status,
        "terminal_node_count": len(terminals),
        "terminal_node_ids": [node.node_id for node in terminals],
        "consumed_node_ids": list(consumed),
        "emitted_volume_roles": list(emitted),
        "emitted_volume_count": len(emitted),
        "branching_parent_count": sum(1 for count in child_counts.values() if count >= 2),
        "template_name_used": False,
    }


def _token(node: MassComponentNode) -> str:
    return "".join(character if character.isalnum() else "_" for character in node.node_id.lower()).strip("_") or node.operation.verb


def _fraction(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0.38, min(0.72, parsed))


__all__ = ["is_graph_native", "materialize_graph_states"]
