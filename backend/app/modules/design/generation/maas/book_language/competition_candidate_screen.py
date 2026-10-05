"""Competition breadth policy and deterministic cheap candidate screen."""

from __future__ import annotations

from copy import deepcopy
import json
from itertools import product
from math import isfinite, radians, sqrt
from types import SimpleNamespace
from typing import Any

from shapely.geometry import Polygon

from backend.app.modules.design.generation.maas.geometry_language import GeometryProgram, apply_book_projection_to_geometry_program
from backend.app.modules.design.generation.maas.geometry_language.affine_matrix import matrix4_for_transform
from backend.app.modules.design.generation.maas.grammar.verb_sequence import VerbSequence
from backend.app.modules.design.generation.maas.program_massing import book_sentence_variants, compose_program_with_book_operations
from backend.app.modules.design.generation.maas.book_language.capacity_alternatives import build_capacity_alternative, capacity_alternative_for_host, capacity_contract_for_alternative
from backend.app.modules.design.generation.maas.book_language.competition_breadth_scheduler import CHEAP_EVALUATION_LIMIT, EXACT_SHORTLIST_MAXIMUM, EXACT_SHORTLIST_MINIMUM
from backend.app.modules.design.generation.maas.book_language.competition_portfolio_contract import BASE_SCOPES, CAPACITY_BANDS
from backend.app.modules.design.generation.maas.book_language.lineage import staged_principle_schedule
from backend.app.modules.design.generation.maas.book_language.variation_lattice import book_variation_indices

def competition_breadth_generation_budget(
    target_count: int,
) -> dict[str, Any]:
    """Return the cheap/exact breadth contract for a publishable target."""

    if int(target_count) != 20:
        return {}
    return {
        "scope_labels": BASE_SCOPES,
        "cheap_evaluation_limit": CHEAP_EVALUATION_LIMIT,
        "exact_shortlist_minimum": EXACT_SHORTLIST_MINIMUM,
        "exact_shortlist_maximum": EXACT_SHORTLIST_MAXIMUM,
        "book_probe_count": 3,
    }


def resolve_competition_breadth_generation_budget(
    *,
    target_count: int,
    recursive_only: bool,
    explicit_diagnostic_budget: bool,
    smoke_mode: bool,
) -> dict[str, Any]:
    """Activate target-20 breadth only on the full recursive product path."""

    if (
        not recursive_only
        or int(target_count) != 20
        or smoke_mode
    ):
        return {}
    _ = explicit_diagnostic_budget
    return competition_breadth_generation_budget(20)


def _competition_pre_exact_shortlist(
    records: list[Any] | tuple[Any, ...],
    *,
    page_index: int,
    target_count: int,
) -> tuple[frozenset[str], Any]:
    """Choose quota witnesses before any exact authored/legal operation."""

    from backend.app.modules.design.generation.maas.book_language.competition_breadth_scheduler import CompetitionBreadthScheduler

    schedule = CompetitionBreadthScheduler(
        target_count=int(target_count),
    ).schedule_page(
        records,
        page_index=int(page_index),
    )
    selected_keys = frozenset(
        str(
            record.get("key")
            if isinstance(record, dict)
            else getattr(record, "key", "")
        )
        for record in schedule.exact_shortlist
    )
    return selected_keys, schedule


def _balanced_principle_window(
    schedule: tuple[tuple[int, dict[str, Any]], ...],
    *,
    seed_index: int,
    count: int,
) -> tuple[tuple[int, dict[str, Any]], ...]:
    """Rotate bounded per-parent probes through base and descendant stages."""

    if not schedule or int(count) <= 0:
        return ()
    take = min(len(schedule), max(1, int(count)))
    start = (max(0, int(seed_index)) * take) % len(schedule)
    return tuple(
        schedule[(start + offset) % len(schedule)]
        for offset in range(take)
    )


def _balanced_principle_window_with_lineage_bases(
    schedule: tuple[tuple[int, dict[str, Any]], ...],
    *,
    seed_index: int,
    count: int,
) -> tuple[tuple[int, dict[str, Any]], ...]:
    """Prepend every rotated descendant's canonical base dependency."""

    selected = _balanced_principle_window(
        schedule,
        seed_index=seed_index,
        count=count,
    )
    by_id = {
        str(principle.get("principle_id") or ""): item
        for item in schedule
        for principle in (item[1],)
    }
    result: list[tuple[int, dict[str, Any]]] = []
    seen: set[str] = set()
    for item in selected:
        principle = item[1]
        principle_id = str(principle.get("principle_id") or "")
        base_id = str(
            principle.get("lineage_base_operative_id")
            or principle_id
        )
        for dependency in (by_id.get(base_id), item):
            if dependency is None:
                continue
            dependency_id = str(
                dependency[1].get("principle_id") or ""
            )
            if dependency_id and dependency_id not in seen:
                result.append(dependency)
                seen.add(dependency_id)
    return tuple(result)


def _lineage_stable_scope_label(
    scope_labels: tuple[str, ...],
    *,
    seed_index: int,
    lineage_base_index: int,
    variant_index: int,
) -> str:
    """Rotate scopes without separating a descendant from its exact base."""

    if not scope_labels:
        return ""
    # `variant_index` has to stay out: a descendant is a variant of its base,
    # and letting it move the scope is exactly what separates the two.
    #
    # `lineage_base_index` is the opposite case and was discarded with it by
    # mistake. A descendant carries its base's `lineage_base_operative_id`, so
    # it carries the same index, and the invariant above holds either way.
    # Leaving it out made the scope a function of the seed alone, which pinned
    # every seed - and so every language it authors - to `seed_index % 6`
    # permanently. Measured on PNU 4115011300106840001: the scopes received
    # disjoint sets of languages, 1/2 and 1/4 drew only single-body ones, and
    # both failed the program gate's hierarchy range en masse (dominant
    # component ratio 0.83 against cultural's 0.32-0.75) while 1/1 and 3/8
    # passed 59 of 60 between them.
    _ = variant_index
    stable_index = max(0, int(seed_index)) + max(0, int(lineage_base_index))
    return str(scope_labels[stable_index % len(scope_labels)])


def _cheap_morphology_preclassification(
    program: GeometryProgram,
    execution_verbs: tuple[str, ...],
) -> tuple[str, str, str, str]:
    """Classify solver cells from typed operators without exact geometry."""

    operators = {
        str(node.operator) for node in program.nodes
    } | {str(verb) for verb in execution_verbs}
    if operators & {"setback", "stepped_mass", "terrace", "book_grade"}:
        body = "preclass_stepped"
    elif operators & {"courtyard", "carve_void", "puncture", "notch"}:
        body = "preclass_voided"
    elif operators & {"split_wing", "branch", "cross_mass", "grid_mass"}:
        body = "preclass_winged"
    elif operators & {"bent_bar", "bend", "sweep", "curve"}:
        body = "preclass_curved"
    elif operators & {"taper", "loft", "profiled_hall"}:
        body = "preclass_profiled"
    else:
        body = "preclass_prismatic"

    if operators & {"setback", "terrace", "stepped_mass"}:
        roof = "preclass_terraced_roof"
    elif operators & {"profiled_hall", "loft", "taper"}:
        roof = "preclass_profiled_roof"
    elif operators & {"rotate", "twist", "shear", "skew"}:
        roof = "preclass_oblique_roof"
    elif operators & {"bend", "bent_bar", "sweep"}:
        roof = "preclass_curved_roof"
    elif operators & {"split_wing", "branch", "cross_mass"}:
        roof = "preclass_split_roof"
    elif operators & {"courtyard", "carve_void", "puncture"}:
        roof = "preclass_voided_roof"
    else:
        roof = "preclass_flat_roof"

    chassis = str(
        program.metadata.get("chassis")
        or program.metadata.get("family")
        or "preclass_chassis_unclassified"
    )
    if operators & {"courtyard", "carve_void", "puncture"}:
        plan = "preclass_courtyard"
    elif operators & {"split_wing", "branch", "cross_mass", "grid_mass"}:
        plan = "preclass_winged"
    elif operators & {"rotate", "radial_fan"}:
        plan = "preclass_radial"
    elif operators & {"bar", "bent_bar", "sweep"}:
        plan = "preclass_linear"
    else:
        plan = "preclass_compact"
    return body, roof, chassis, plan


def _cheap_ast_bounds(
    program: GeometryProgram,
) -> tuple[float, float, float, float] | None:
    """Return a proved-conservative XY envelope, or fail closed."""

    Bounds3 = tuple[float, float, float, float, float, float]
    by_id: dict[str, Bounds3] = {}
    center_known_by_id: dict[str, bool] = {}
    aabb_authoritative_by_id: dict[str, bool] = {}

    def corners(value: Bounds3) -> tuple[tuple[float, float, float], ...]:
        return tuple(product(
            (value[0], value[3]),
            (value[1], value[4]),
            (value[2], value[5]),
        ))

    def enclose(points: Any) -> Bounds3:
        values = tuple(points)
        return (
            min(point[0] for point in values),
            min(point[1] for point in values),
            min(point[2] for point in values),
            max(point[0] for point in values),
            max(point[1] for point in values),
            max(point[2] for point in values),
        )

    def union(values: list[Bounds3]) -> Bounds3:
        return (
            min(value[0] for value in values),
            min(value[1] for value in values),
            min(value[2] for value in values),
            max(value[3] for value in values),
            max(value[4] for value in values),
            max(value[5] for value in values),
        )

    def transform(value: Bounds3, raw_matrix: Any) -> Bounds3:
        matrix = tuple(
            tuple(float(component) for component in row)
            for row in raw_matrix
        )
        if len(matrix) != 4 or any(len(row) != 4 for row in matrix):
            raise ValueError("invalid matrix4")
        return enclose(
            tuple(
                tuple(
                    sum(
                        matrix[row][column] * (*point, 1.0)[column]
                        for column in range(4)
                    )
                    for row in range(3)
                )
                for point in corners(value)
            )
        )

    def scale_about(
        value: Bounds3,
        pivot: tuple[float, float, float],
        scales: tuple[float, float, float],
    ) -> Bounds3:
        return transform(value, (
            (scales[0], 0.0, 0.0, pivot[0] * (1.0 - scales[0])),
            (0.0, scales[1], 0.0, pivot[1] * (1.0 - scales[1])),
            (0.0, 0.0, scales[2], pivot[2] * (1.0 - scales[2])),
            (0.0, 0.0, 0.0, 1.0),
        ))

    def scale_about_unknown_center(
        value: Bounds3,
        scales: tuple[float, float, float],
    ) -> Bounds3:
        expanded = list(value)
        for index, scale in enumerate(scales):
            span = value[index + 3] - value[index]
            margin = max(0.0, float(scale) - 1.0) * span
            expanded[index] = value[index] - margin
            expanded[index + 3] = value[index + 3] + margin
        return tuple(expanded)

    def rotational_envelope(
        value: Bounds3,
        *,
        axis_index: int,
        pivot: tuple[float, float, float] | None,
    ) -> Bounds3:
        transverse = [index for index in range(3) if index != axis_index]
        expanded = list(value)
        if pivot is None:
            diameter = sqrt(sum(
                (value[index + 3] - value[index]) ** 2
                for index in transverse
            ))
            for index in transverse:
                expanded[index] = value[index] - diameter
                expanded[index + 3] = value[index + 3] + diameter
            return tuple(expanded)
        radius = max(
            sqrt(sum(
                (point[index] - pivot[index]) ** 2
                for index in transverse
            ))
            for point in corners(value)
        )
        for index in transverse:
            expanded[index] = pivot[index] - radius
            expanded[index + 3] = pivot[index] + radius
        return tuple(expanded)

    def scale_pair(raw: Any) -> tuple[float, float]:
        if isinstance(raw, (int, float)):
            result = (float(raw), float(raw))
        elif isinstance(raw, (list, tuple)) and len(raw) >= 2:
            result = (float(raw[0]), float(raw[1]))
        else:
            raise ValueError("invalid taper scale")
        if min(result) <= 0.02 or max(result) > 4.0:
            raise ValueError("taper scale outside compiler bounds")
        return result

    try:
        for node in program.nodes:
            if any(input_id not in by_id for input_id in node.inputs):
                return None
            inputs = [by_id[input_id] for input_id in node.inputs]
            input_centers_known = [
                center_known_by_id[input_id] for input_id in node.inputs
            ]
            input_aabbs_authoritative = [
                aabb_authoritative_by_id[input_id]
                for input_id in node.inputs
            ]
            p = node.parameters
            center_known = False
            aabb_authoritative = False
            if node.kind == "primitive":
                if node.operator == "box":
                    width = float(p.get("width", 1.0))
                    depth = float(p.get("depth", 1.0))
                    height = float(p.get("height", 1.0))
                    value = (
                        (-width / 2, -depth / 2, -height / 2,
                         width / 2, depth / 2, height / 2)
                        if bool(p.get("center", False))
                        else (0.0, 0.0, 0.0, width, depth, height)
                    )
                    center_known = True
                    aabb_authoritative = True
                elif node.operator == "cylinder":
                    radii = (
                        float(p.get("radius", 1.0)),
                        float(p.get("radius_low", p.get("radius", 1.0))),
                        float(p.get("radius_high", p.get("radius", 1.0))),
                    )
                    radius = max(abs(item) for item in radii)
                    height = float(p.get("height", 1.0))
                    low_z = -height / 2 if bool(p.get("center", False)) else 0.0
                    value = (-radius, -radius, low_z, radius, radius, low_z + height)
                    segments = max(8, min(96, int(p.get("segments", 24))))
                    center_known = segments % 2 == 0
                    aabb_authoritative = segments % 4 == 0
                elif node.operator == "wedge":
                    heights = (
                        0.0,
                        float(p["start_height"]),
                        float(p["end_height"]),
                    )
                    value = (
                        0.0, 0.0, min(heights),
                        float(p["width"]), float(p["depth"]), max(heights),
                    )
                    center_known = True
                    aabb_authoritative = True
                elif node.operator == "extruded_polygon":
                    points = tuple(p.get("points") or ())
                    value = enclose(tuple(
                        (float(point[0]), float(point[1]), z)
                        for point in points
                        for z in (0.0, float(p.get("height", 1.0)))
                    ))
                    center_known = True
                    aabb_authoritative = True
                elif node.operator == "sweep":
                    path = tuple(p.get("path") or ())
                    if len(path) < 2:
                        return None
                    path3 = tuple((
                        float(point[0]),
                        float(point[1]),
                        float(point[2]) if len(point) > 2 else 0.0,
                    ) for point in path)
                    width = abs(float(p.get(
                        "profile_width", p.get("width", 2.0)
                    )))
                    height = abs(float(p.get(
                        "profile_height", p.get("height", 3.0)
                    )))
                    value = (
                        min(point[0] for point in path3) - width,
                        min(point[1] for point in path3) - width,
                        min(point[2] for point in path3),
                        max(point[0] for point in path3) + width,
                        max(point[1] for point in path3) + width,
                        max(point[2] for point in path3) + height,
                    )
                elif node.operator == "loft":
                    profiles = p.get("profiles")
                    if not isinstance(profiles, list) or len(profiles) < 2:
                        return None
                    points3 = []
                    for index, profile in enumerate(profiles):
                        if isinstance(profile, dict):
                            z = float(profile.get("z", index))
                            points = profile.get("points") or ()
                        else:
                            z, points = float(index), profile
                        points3.extend(
                            (float(point[0]), float(point[1]), z)
                            for point in points
                        )
                    value = enclose(tuple(points3))
                    center_known = True
                    aabb_authoritative = True
                else:
                    return None
            elif not inputs:
                return None
            elif node.kind == "boolean":
                if node.operator in {"difference", "intersection"}:
                    value = inputs[0]
                elif node.operator == "union":
                    if (
                        str((node.provenance or {}).get("book_verb") or "")
                        == "recompose_book_scope"
                    ):
                        return None
                    value = union(inputs)
                    aabb_authoritative = all(
                        input_aabbs_authoritative
                    )
                    center_known = aabb_authoritative
                else:
                    return None
            elif node.kind == "transform":
                resolved = dict(p)
                if str(p.get("pivot", "")).lower() in {"center", "centroid"}:
                    if not input_centers_known[0]:
                        return None
                    source = inputs[0]
                    resolved["pivot"] = tuple(
                        (source[index] + source[index + 3]) / 2.0
                        for index in range(3)
                    )
                matrix = matrix4_for_transform(node.operator, resolved)
                value = transform(inputs[0], matrix)
                # A row-separable affine maps every output coordinate from at
                # most one input coordinate, so exact input AABB extrema stay
                # exact through diagonal scale/translation, axis permutation,
                # and equivalent Matrix4 forms. Rotation/shear/mixing clears
                # authority even though its enclosing box remains safe.
                row_separable = all(
                    sum(
                        abs(float(matrix[row][column])) > 1e-12
                        for column in range(3)
                    ) <= 1
                    for row in range(3)
                )
                aabb_authoritative = bool(
                    input_aabbs_authoritative[0]
                    and row_separable
                )
                center_known = aabb_authoritative
            elif node.kind == "modifier":
                value = inputs[0]
                center = tuple(
                    (value[index] + value[index + 3]) / 2.0
                    for index in range(3)
                )
                axis = str(p.get("axis") or (
                    "z" if node.operator in {"taper", "twist"} else "x"
                )).lower()
                axis_index = {"x": 0, "y": 1, "z": 2}.get(axis)
                if node.operator in {
                    "slice", "clip", "clip_fraction", "book_base_volume",
                    "cut_corner", "legal_section_clip",
                }:
                    pass
                elif node.operator in {"pinch", "inflate"}:
                    if axis_index is None:
                        return None
                    factor = (
                        1.0 if node.operator == "pinch" else
                        max(1.04, min(1.45, float(p.get(
                            "middle_scale", p.get("factor", 1.18)
                        ))))
                    )
                    scales = tuple(
                        1.0 if index == axis_index else factor
                        for index in range(3)
                    )
                    value = scale_about_unknown_center(value, scales)
                elif node.operator == "taper":
                    if axis_index is None:
                        return None
                    start = scale_pair(p.get("start_scale", (1.0, 1.0)))
                    end = scale_pair(p.get(
                        "end_scale", p.get("scale_top", (0.6, 0.6))
                    ))
                    other = [index for index in range(3) if index != axis_index]
                    start_scales = [1.0, 1.0, 1.0]
                    end_scales = [1.0, 1.0, 1.0]
                    start_scales[other[0]], start_scales[other[1]] = start
                    end_scales[other[0]], end_scales[other[1]] = end
                    raw_pivot = p.get("pivot")
                    if raw_pivot is None:
                        value = scale_about_unknown_center(
                            value,
                            tuple(max(left, right) for left, right in zip(
                                start_scales, end_scales
                            )),
                        )
                    else:
                        pivot = tuple(float(component) for component in raw_pivot)
                        if len(pivot) != 3:
                            return None
                        value = union([
                            scale_about(value, pivot, tuple(start_scales)),
                            scale_about(value, pivot, tuple(end_scales)),
                        ])
                elif node.operator == "twist":
                    if axis_index is None:
                        return None
                    raw_pivot = p.get("pivot")
                    pivot = (
                        tuple(float(component) for component in raw_pivot)
                        if raw_pivot is not None else None
                    )
                    if pivot is not None and len(pivot) != 3:
                        return None
                    value = rotational_envelope(
                        value,
                        axis_index=axis_index,
                        pivot=pivot,
                    )
                elif node.operator == "bend":
                    if axis_index is None:
                        return None
                    # The compiler derives bend length, radius and center from
                    # the live solid AABB. A retained conservative envelope
                    # from a clip/selection cannot substitute for that AABB.
                    if not input_aabbs_authoritative[0]:
                        return None
                    angle = radians(float(p.get(
                        "angle_degrees", p.get("angle", 35.0)
                    )))
                    if abs(angle) >= 1e-5:
                        length = value[axis_index + 3] - value[axis_index]
                        radius = abs(length / angle)
                        if axis_index == 0:
                            local = (value[4] - value[1]) / 2.0
                            value = (
                                value[0] - radius - local,
                                center[1] - 2 * radius - local,
                                value[2],
                                value[0] + radius + local,
                                center[1] + 2 * radius + local,
                                value[5],
                            )
                        elif axis_index == 1:
                            local = (value[3] - value[0]) / 2.0
                            value = (
                                center[0] - 2 * radius - local,
                                value[1] - radius - local,
                                value[2],
                                center[0] + 2 * radius + local,
                                value[1] + radius + local,
                                value[5],
                            )
                        else:
                            local = (value[3] - value[0]) / 2.0
                            value = (
                                center[0] - 2 * radius - local,
                                value[1],
                                value[2] - radius - local,
                                center[0] + 2 * radius + local,
                                value[4],
                                value[2] + radius + local,
                            )
                else:
                    return None
            elif node.kind == "pattern":
                source = inputs[0]
                count = max(1, min(24, int(p.get("count", 2))))
                if node.operator in {"duplicate", "linear_array", "stack"}:
                    if node.operator == "stack":
                        if (
                            "spacing" not in p
                            and not input_aabbs_authoritative[0]
                        ):
                            # Default spacing is the compiler's exact live
                            # z-span. A loose source envelope can reverse or
                            # enlarge the copy step once a z shift is added.
                            return None
                        shift = p.get("shift_per_level", (0.0, 0.0, 0.0))
                        vector = (
                            float(shift[0]),
                            float(shift[1]),
                            float(p.get("spacing", source[5] - source[2]))
                            + float(shift[2]),
                        )
                    else:
                        raw = p.get(
                            "vector", (p.get("spacing", 2.0), 0.0, 0.0)
                        )
                        vector = tuple(float(component) for component in raw)
                    value = union([
                        transform(source, (
                            (1.0, 0.0, 0.0, vector[0] * index),
                            (0.0, 1.0, 0.0, vector[1] * index),
                            (0.0, 0.0, 1.0, vector[2] * index),
                            (0.0, 0.0, 0.0, 1.0),
                        ))
                        for index in range(count)
                    ])
                    center_known = all(input_centers_known)
                    aabb_authoritative = all(
                        input_aabbs_authoritative
                    )
                else:
                    return None
            elif node.kind == "composition":
                return None
            elif node.kind == "macro":
                if node.operator == "intersect_related":
                    axis_name = str(p.get("axis") or "x").lower()
                    if axis_name not in {"x", "y"}:
                        return None
                    float(p.get("bar_ratio", 0.32))
                    float(p.get("unit_scale", 0.92))
                    float(p.get("angle_degrees", 0.0))
                    value = rotational_envelope(
                        inputs[0],
                        axis_index=2,
                        pivot=None,
                    )
                elif node.operator in {
                    "courtyard", "carve_void", "notch", "book_carve",
                    "book_notch", "book_extract", "puncture", "cut_corner",
                    "embed_void",
                }:
                    value = inputs[0]
                else:
                    return None
            else:
                return None
            if (
                not all(isfinite(component) for component in value)
                or any(value[index + 3] < value[index] for index in range(3))
            ):
                return None
            by_id[node.id] = value
            center_known_by_id[node.id] = center_known
            aabb_authoritative_by_id[node.id] = aabb_authoritative
    except (KeyError, TypeError, ValueError, IndexError, ZeroDivisionError):
        return None
    result = by_id.get(program.root_id)
    return (
        (result[0], result[1], result[3], result[4])
        if result is not None else None
    )


def _legal_section_dimensions(section: Polygon) -> tuple[float, float]:
    rectangle = section.minimum_rotated_rectangle
    coordinates = tuple(rectangle.exterior.coords)
    lengths = sorted(
        sqrt(
            (float(right[0]) - float(left[0])) ** 2
            + (float(right[1]) - float(left[1])) ** 2
        )
        for left, right in zip(coordinates, coordinates[1:])
        if left != right
    )
    if len(lengths) < 2:
        return 0.0, 0.0
    return float(lengths[-1]), float(lengths[0])


def _cheap_typed_ast_candidate_evidence(
    program: GeometryProgram,
    *,
    legal_sections: tuple[Polygon | None, ...],
    target_floor_areas_m2: tuple[float, ...],
) -> dict[str, Any]:
    """Build candidate-specific 2D fit/capacity evidence without exact CSG."""

    issues = tuple(
        issue for issue in program.validate()
        if issue.severity == "error"
    )
    bounds = _cheap_ast_bounds(program) if not issues else None
    bounds_status = (
        "proved_conservative"
        if bounds is not None
        else "invalid_ast" if issues
        else "unknown_bounds"
    )
    authored_compile_pass = bool(bounds is not None)
    exact_required = bool(
        not issues
        and bounds_status == "unknown_bounds"
    )
    if bounds is None:
        width = depth = 0.0
    else:
        width = max(0.0, float(bounds[2]) - float(bounds[0]))
        depth = max(0.0, float(bounds[3]) - float(bounds[1]))
    section_count_matches = bool(
        legal_sections
        and len(legal_sections) == len(target_floor_areas_m2)
    )
    valid_sections = bool(
        section_count_matches
        and all(
            isinstance(section, Polygon)
            and not section.is_empty
            and section.is_valid
            and float(section.area) > 1e-9
            for section in legal_sections
        )
    )
    anisotropies = (0.67, 0.78, 1.0, 1.28)
    maximum_floor_areas: list[float] = []
    required_fit_passes: list[bool] = []
    affine_fit_passes: list[bool] = []
    if authored_compile_pass and valid_sections and width > 1e-9 and depth > 1e-9:
        for section, target_area in zip(
            legal_sections,
            target_floor_areas_m2,
        ):
            legal_long, legal_short = _legal_section_dimensions(section)
            best_area = 0.0
            required_fit = False
            affine_fit = False
            for anisotropy in anisotropies:
                candidate_long = max(
                    width * anisotropy,
                    depth / anisotropy,
                )
                candidate_short = min(
                    width * anisotropy,
                    depth / anisotropy,
                )
                for host_long, host_short in (
                    (legal_long, legal_short),
                    (legal_short, legal_long),
                ):
                    fit_scale = min(
                        host_long / max(candidate_long, 1e-9),
                        host_short / max(candidate_short, 1e-9),
                    )
                    fitted_area = width * depth * fit_scale * fit_scale
                    best_area = max(best_area, fitted_area)
                    required_scale = sqrt(
                        max(0.0, float(target_area))
                        / max(width * depth, 1e-9)
                    )
                    if required_scale <= fit_scale + 1e-9:
                        required_fit = True
                    if (
                        fit_scale > 1e-9
                        and max(candidate_long, candidate_short)
                        / max(min(candidate_long, candidate_short), 1e-9)
                        <= max(
                            host_long / max(host_short, 1e-9),
                            1.0,
                        ) * 4.0
                    ):
                        affine_fit = True
            maximum_floor_areas.append(
                min(float(section.area), best_area)
            )
            required_fit_passes.append(required_fit)
            affine_fit_passes.append(affine_fit and required_fit)
    target_area_total = sum(
        max(0.0, float(value))
        for value in target_floor_areas_m2
    )
    achieved_area_total = sum(maximum_floor_areas)
    capacity_ratio = (
        achieved_area_total / target_area_total
        if target_area_total > 1e-9
        else 0.0
    )
    legal_pass = bool(
        authored_compile_pass
        and valid_sections
        and required_fit_passes
        and all(required_fit_passes)
    )
    affine_pass = bool(
        legal_pass
        and affine_fit_passes
        and all(affine_fit_passes)
    )
    capacity_pass = bool(
        affine_pass
        and target_area_total > 1e-9
        and achieved_area_total + 1e-7
        >= target_area_total * 0.995
    )
    return {
        "authored_compile_pass": authored_compile_pass,
        "typed_ast_valid": not issues,
        "exact_required": exact_required,
        "exact_required_reason": (
            "cheap_bounds_unknown_operator"
            if exact_required else ""
        ),
        "legal_section_screen_pass": legal_pass,
        "affine_screen_pass": affine_pass,
        "approximate_capacity_pass": capacity_pass,
        "approximate_capacity_ratio": round(capacity_ratio, 8),
        "conservative_footprint_bounds": (
            tuple(round(float(value), 8) for value in bounds)
            if bounds is not None else ()
        ),
        "approximate_floor_capacity_m2": tuple(
            round(value, 6) for value in maximum_floor_areas
        ),
        "cheap_geometry_authority": (
            "typed_ast_conservative_3d_to_2d_bounds_no_exact_csg"
        ),
        "cheap_bounds_status": bounds_status,
        "authored_validation_issue_codes": tuple(
            issue.code for issue in issues
        ) + (
            ("cheap_bounds_unknown_operator",)
            if bounds_status == "unknown_bounds"
            else ()
        ),
    }


def _competition_cheap_candidate_records(
    parent_seeds: tuple[VerbSequence, ...],
    principles: tuple[dict[str, Any], ...],
    *,
    book_probe_count: int,
    evaluation_limit: int,
    scope_labels: tuple[str, ...],
    page_index: int,
    legal_sections: tuple[Polygon | None, ...],
    capacity_contract: dict[str, Any] | None,
) -> tuple[Any, ...]:
    """Enumerate the full cheap page before admitting any exact candidate."""

    records: list[Any] = []
    principle_by_id = {
        str(principle["principle_id"]): (index, principle)
        for index, principle in enumerate(principles)
    }
    default_target_floor_areas_m2 = tuple(
        float(value)
        for value in (
            (capacity_contract or {}).get("target_floor_areas_m2")
            or ()
        )
    )
    principles_per_parent = (
        max(
            1,
            min(
                12,
                int(evaluation_limit) // max(1, len(parent_seeds)),
            ),
        )
        if int(evaluation_limit) > 0
        else 12
    )
    for seed_index, seed in enumerate(parent_seeds):
        preservation_control = any(
            note.startswith(
                "geometry_program_preservation_control="
            )
            for note in seed.notes
        )
        payload = next((
            note.split("=", 1)[1]
            for note in seed.notes
            if note.startswith("geometry_program_payload=")
        ), "")
        try:
            program = GeometryProgram.from_dict(json.loads(payload))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        causal_path = None
        execution_contract = program.execution_contract
        if isinstance(execution_contract, dict):
            from backend.app.modules.design.generation.maas.book_language.composition_lattice import book_composition_path_by_id

            causal_path = book_composition_path_by_id(str(
                execution_contract.get("book_composition_path_id") or ""
            ))
        # Divide the bounded page evenly across UnitBox/BaseVolume parents:
        # every form is visited before any one form receives excess probes.
        scheduled_principles = _balanced_principle_window(
            staged_principle_schedule(
                principles,
                seed_index,
                count=max(6, principles_per_parent),
            ),
            seed_index=seed_index,
            count=principles_per_parent,
        )
        if causal_path is not None:
            selected_principle = principle_by_id.get(
                causal_path.principle_id
            )
            scheduled_principles = (
                (selected_principle,) if selected_principle else ()
            )
        if preservation_control:
            scheduled_principles = (
                principle_by_id["book:operative:skew"],
            )
        for principle_index, principle in scheduled_principles:
            execution_verbs = tuple(principle["execution_verbs"])
            lineage_base_id = str(
                principle.get("lineage_base_operative_id")
                or principle["principle_id"]
            )
            lineage_base_index = principle_by_id.get(
                lineage_base_id,
                (principle_index, principle),
            )[0]
            if causal_path is not None:
                variant_index = int(causal_path.variation_index)
                operations = book_sentence_variants(
                    execution_verbs,
                    count=11,
                )[variant_index]
            else:
                variation_indices = (
                    (5,)
                    if preservation_control
                    else book_variation_indices(book_probe_count)
                )
                indexed_variants = tuple(zip(
                    variation_indices,
                    book_sentence_variants(
                        execution_verbs,
                        count=(
                            1
                            if preservation_control
                            else book_probe_count
                        ),
                    ),
                ))
                (variant_index, operations) = indexed_variants[
                    (seed_index + lineage_base_index)
                    % len(indexed_variants)
                ]
            evaluation_index = len(records)
            if evaluation_index >= int(evaluation_limit):
                return tuple(records)
            capacity_schedule_index = (
                _capacity_alternative_schedule_index(
                    evaluation_index=evaluation_index,
                    diagnostic_evaluation_cap=0,
                    genotype_schedule_index=evaluation_index,
                    competition_target_count=20,
                    page_index=page_index,
                )
            )
            cheap_target_utilization = float(
                (capacity_contract or {}).get(
                    "target_utilization"
                )
                or 0.0
            )
            cheap_target_floor_areas_m2 = (
                default_target_floor_areas_m2
            )
            cheap_legal_sections = legal_sections
            capacity_band = CAPACITY_BANDS[
                capacity_schedule_index % len(CAPACITY_BANDS)
            ]
            if capacity_contract:
                host_area = next(
                    (
                        float(section.area)
                        for section in legal_sections
                        if isinstance(section, Polygon)
                        and not section.is_empty
                    ),
                    float(
                        capacity_contract.get(
                            "generation_site_area_m2"
                        )
                        or 0.0
                    ),
                )
                alternative = build_capacity_alternative(
                    capacity_contract,
                    capacity_alternative_for_host(
                        capacity_schedule_index,
                        capacity_contract,
                        host_area_m2=host_area,
                        floor_count=int(
                            capacity_contract.get(
                                "requested_floors"
                            )
                            or len(legal_sections)
                            or 1
                        ),
                    ),
                )
                alternative_contract = (
                    capacity_contract_for_alternative(
                        capacity_contract,
                        alternative,
                    )
                )
                cheap_target_utilization = float(
                    alternative.get("target_utilization")
                    or 0.0
                )
                cheap_target_floor_areas_m2 = tuple(
                    float(value)
                    for value in (
                        alternative_contract.get(
                            "target_floor_areas_m2"
                        )
                        or ()
                    )
                )
                cheap_legal_sections = legal_sections[
                    :len(cheap_target_floor_areas_m2)
                ]
                capacity_band = str(
                    alternative.get("alternative_id")
                    or capacity_band
                )
            scope_label = scope_labels[
                evaluation_index % len(scope_labels)
            ]
            orientation = "vertical"
            if causal_path is not None:
                scope_label = causal_path.base_volume_label
                orientation = causal_path.orientation
            if preservation_control:
                scope_label = "1/1"
            suffix = (
                str(principle["principle_id"])
                .split("book:", 1)[-1]
                .replace(":", "_")
            )
            composed = compose_program_with_book_operations(
                seed,
                operations,
                name_suffix=suffix,
                base_volume_label=scope_label,
                orientation=orientation,
            )
            sequence = VerbSequence(
                name=f"{composed.name}__search_v{variant_index}",
                label=composed.label,
                calls=composed.calls,
                notes=composed.notes,
            )
            book_bind_pass = True
            book_projection_failure_evidence: dict[str, Any] = {}
            projected_program = program
            try:
                projected_program = (
                    apply_book_projection_to_geometry_program(
                        program,
                        sequence,
                    )
                )
            except (TypeError, ValueError) as exc:
                book_bind_pass = False
                typed_evidence = getattr(exc, "evidence", None)
                book_projection_failure_evidence = (
                    deepcopy(typed_evidence)
                    if isinstance(typed_evidence, dict)
                    else {
                        "schema_version": "arr.maas.book_projection_failure.v1",
                        "code": "book_projection_application_failed",
                        "failure_type": type(exc).__name__,
                        "failure_detail": str(exc)[:240],
                        "pre_identity": {
                            "program_hash": program.program_hash(),
                            "root_id": str(program.root_id),
                        },
                        "post_identity": {"status": "not_materialized"},
                    }
                )
            body, roof, chassis, plan = (
                _cheap_morphology_preclassification(
                    projected_program,
                    execution_verbs,
                )
            )
            cheap_geometry = _cheap_typed_ast_candidate_evidence(
                projected_program,
                legal_sections=cheap_legal_sections,
                target_floor_areas_m2=(
                    cheap_target_floor_areas_m2
                ),
            )
            key = (
                f"{seed_index}:"
                f"{principle['principle_id']}:"
                f"{variant_index}"
            )
            records.append(SimpleNamespace(
                key=key,
                book_projection_failure_evidence=(
                    book_projection_failure_evidence
                ),
                page_index=int(page_index),
                base_scope=scope_label,
                genotype_family=str(
                    program.metadata.get("family")
                    or "preclass_genotype_unclassified"
                ),
                book_principle_kind=str(
                    principle.get("kind") or "unclassified"
                ),
                book_principle_id=str(principle["principle_id"]),
                body_family=body,
                roof_family=roof,
                chassis_family=chassis,
                plan_family=plan,
                capacity_band=capacity_band,
                cheap_target_utilization=round(
                    cheap_target_utilization,
                    4,
                ),
                cheap_target_floor_areas_m2=tuple(
                    round(float(value), 6)
                    for value in cheap_target_floor_areas_m2
                ),
                score=0.0,
                typed_ast=projected_program,
                book_bind_pass=book_bind_pass,
                **cheap_geometry,
            ))
    return tuple(records)


def _recursive_principle_schedule_limit(
    *,
    evaluation_cap: int,
    explicit_diagnostic_budget: bool,
) -> int | None:
    """Limit BOOK probes only for explicitly requested diagnostics."""

    if explicit_diagnostic_budget and int(evaluation_cap) > 0:
        return 1
    return None


def _diagnostic_generation_cap_reached(
    *,
    evaluated: int,
    program_passed: int,
    evaluation_cap: int,
    candidate_cap: int,
) -> bool:
    """Use the exact evaluation budget when one is active.

    The candidate cap remains an output slice in diagnostic runs.  Letting a
    run stop on early successful candidates would make the genotype breadth
    depend on gate luck and could terminate before the required first round.
    """

    if int(evaluation_cap) > 0:
        return int(evaluated) >= int(evaluation_cap)
    return bool(
        int(candidate_cap) > 0
        and int(program_passed) >= int(candidate_cap)
    )


def _capacity_alternative_schedule_index(
    *,
    evaluation_index: int,
    diagnostic_evaluation_cap: int,
    genotype_schedule_index: int,
    competition_target_count: int = 0,
    page_index: int = 0,
) -> int:
    """Decouple bounded diagnostic capacity supply from genotype ordering."""

    if int(competition_target_count) == 20:
        return max(0, int(evaluation_index)) + max(0, int(page_index))
    if int(diagnostic_evaluation_cap) > 0:
        return max(0, int(evaluation_index))
    return int(genotype_schedule_index)
