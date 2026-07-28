from __future__ import annotations

import math

from engine.geometry.polygon import validate_polygon

from backend.app.schemas.area import (
    AREA_BUCKETS,
    MAX_AREA_TOLERANCE_M2,
    MIN_AREA_TOLERANCE_M2,
    AreaGeometry,
    AreaLedgerEntry,
    AreaProvenance,
    BuildingAreaLedger,
    FloorAreaLedger,
)

_CATEGORY_BUCKETS = (
    "core",
    "circulation",
    "remote_stair",
    "service",
    "primary",
)
_DEFAULT_TOLERANCE_M2 = 1e-6
_BOUNDARY_ROUNDOFF_M2 = 1e-12


def compute_floor_area_ledger(
    *,
    floor_index: int,
    gross: AreaGeometry,
    core: tuple[AreaGeometry, ...] = (),
    circulation: tuple[AreaGeometry, ...] = (),
    remote_stair: tuple[AreaGeometry, ...] = (),
    service: tuple[AreaGeometry, ...] = (),
    primary: tuple[AreaGeometry, ...] = (),
    unclassified: tuple[AreaGeometry, ...] = (),
    classification_rule: str = "closed-program-classification-v1",
    tolerance_m2: float = _DEFAULT_TOLERANCE_M2,
) -> FloorAreaLedger:
    _validate_call(
        floor_index,
        gross,
        (core, circulation, remote_stair, service, primary, unclassified),
        classification_rule,
        tolerance_m2,
    )
    categories = {
        "core": core,
        "circulation": circulation,
        "remote_stair": remote_stair,
        "service": service,
        "primary": primary,
    }
    all_geometry = (gross,) + tuple(
        shape
        for collection in (*categories.values(), unclassified)
        for shape in collection
    )
    unresolved = _geometry_reasons(all_geometry)
    duplicate_ids = _duplicate_source_ids(all_geometry)
    if duplicate_ids:
        unresolved.append("duplicate_area_source_id")
    unresolved.extend(
        f"unclassified_room:{shape.source_id}" for shape in unclassified
    )
    unresolved = list(dict.fromkeys(unresolved))
    if any(
        reason
        in {
            "polygon_holes_unsupported",
            "polygon_too_few_vertices",
            "non_finite_polygon",
            "non_axis_aligned_polygon",
            "self_intersecting_polygon",
            "invalid_polygon",
            "repeated_consecutive_vertex",
            "duplicate_area_source_id",
        }
        for reason in unresolved
    ):
        return _not_checked_floor(
            floor_index,
            gross,
            categories,
            unclassified,
            classification_rule,
            tolerance_m2,
            tuple(unresolved),
        )

    xs = sorted({x for shape in all_geometry for x, _ in _vertices(shape)})
    ys = sorted({y for shape in all_geometry for _, y in _vertices(shape)})
    category_areas = {bucket: 0.0 for bucket in _CATEGORY_BUCKETS}
    gross_area = 0.0
    overlap_area = 0.0
    outside_area = 0.0
    uncovered_area = 0.0
    overlap_source_ids: set[str] = set()
    outside_source_ids: set[str] = set()
    non_gross_shapes = tuple(
        shape
        for collection in (*categories.values(), unclassified)
        for shape in collection
    )
    for x1, x2 in zip(xs, xs[1:]):
        for y1, y2 in zip(ys, ys[1:]):
            cell_area = (x2 - x1) * (y2 - y1)
            if cell_area <= 0:
                continue
            midpoint = ((x1 + x2) / 2, (y1 + y2) / 2)
            inside_gross = _point_in_polygon(midpoint, _vertices(gross))
            active_by_bucket = {
                bucket: tuple(
                    shape.source_id
                    for shape in shapes
                    if _point_in_polygon(midpoint, _vertices(shape))
                )
                for bucket, shapes in categories.items()
            }
            occupied_buckets = tuple(
                bucket
                for bucket, source_ids in active_by_bucket.items()
                if source_ids
            )
            active_source_ids = tuple(
                shape.source_id
                for shape in non_gross_shapes
                if _point_in_polygon(midpoint, _vertices(shape))
            )
            if inside_gross:
                gross_area += cell_area
                if not occupied_buckets:
                    uncovered_area += cell_area
            elif active_source_ids:
                outside_area += cell_area
                outside_source_ids.update(active_source_ids)
            for bucket in occupied_buckets:
                category_areas[bucket] += cell_area
            if len(occupied_buckets) > 1:
                overlap_area += cell_area
                for bucket in occupied_buckets:
                    overlap_source_ids.update(active_by_bucket[bucket])

    overlap_area = _normalize_zero(overlap_area, tolerance_m2)
    outside_area = _normalize_zero(outside_area, tolerance_m2)
    uncovered_area = _normalize_zero(uncovered_area, tolerance_m2)
    if overlap_area > tolerance_m2:
        unresolved.append("cross_category_overlap")
        unresolved.append(
            "cross_category_overlap_sources:"
            + ",".join(sorted(overlap_source_ids))
        )
    if outside_area > tolerance_m2:
        unresolved.append("geometry_out_of_boundary")
        unresolved.append(
            "geometry_out_of_boundary_sources:"
            + ",".join(sorted(outside_source_ids))
        )
    status = "fail" if overlap_area > tolerance_m2 or outside_area > tolerance_m2 else "pass"
    values = {
        "gross": gross_area,
        **category_areas,
        "net": category_areas["service"] + category_areas["primary"],
        "unassigned": uncovered_area,
    }
    entries = _entries(
        values,
        gross,
        categories,
        unclassified,
        classification_rule,
    )
    return FloorAreaLedger(
        floor_index=floor_index,
        status=status,
        entries=entries,
        overlap_area_m2=overlap_area,
        out_of_boundary_area_m2=outside_area,
        tolerance_m2=tolerance_m2,
        unresolved_facts=tuple(dict.fromkeys(unresolved)),
    )


def build_building_area_ledger(
    floors: tuple[FloorAreaLedger, ...],
) -> BuildingAreaLedger:
    if not isinstance(floors, tuple) or not floors:
        raise ValueError("building ledger requires an immutable non-empty floor tuple")
    ordered = tuple(sorted(floors, key=lambda floor: floor.floor_index))
    indexes = tuple(floor.floor_index for floor in ordered)
    if indexes != tuple(range(1, indexes[-1] + 1)):
        raise ValueError(
            "building floor indexes must be consecutive from floor 1"
        )
    if any(floor.status == "not_checked" for floor in ordered):
        status = "not_checked"
        values = {bucket: None for bucket in AREA_BUCKETS}
    else:
        status = "fail" if any(floor.status == "fail" for floor in ordered) else "pass"
        values = {
            bucket: sum(
                _entry(floor, bucket).area_m2 or 0.0 for floor in ordered
            )
            for bucket in AREA_BUCKETS
        }
    totals = tuple(
        AreaLedgerEntry(
            bucket=bucket,
            area_m2=values[bucket],
            provenance=AreaProvenance(
                method="derived_sum",
                source_ids=tuple(
                    f"floor:{floor.floor_index}:{bucket}" for floor in ordered
                ),
                classification_rule="building-floor-sum-v1",
                formula=f"sum floor {bucket} entries",
            ),
        )
        for bucket in AREA_BUCKETS
    )
    return BuildingAreaLedger(floors=ordered, totals=totals, status=status)


def _validate_call(
    floor_index: int,
    gross: AreaGeometry,
    collections: tuple[tuple[AreaGeometry, ...], ...],
    classification_rule: str,
    tolerance_m2: float,
) -> None:
    if (
        not isinstance(floor_index, int)
        or isinstance(floor_index, bool)
        or floor_index < 1
    ):
        raise ValueError("floor_index must be a positive integer")
    if not isinstance(gross, AreaGeometry):
        raise TypeError("gross must be AreaGeometry")
    for collection in collections:
        if not isinstance(collection, tuple) or not all(
            isinstance(shape, AreaGeometry) for shape in collection
        ):
            raise TypeError("area geometry collections must be immutable typed tuples")
    if not isinstance(classification_rule, str) or not classification_rule.strip():
        raise ValueError("classification_rule must be non-empty")
    if (
        not isinstance(tolerance_m2, (int, float))
        or isinstance(tolerance_m2, bool)
        or not math.isfinite(tolerance_m2)
        or not (
            MIN_AREA_TOLERANCE_M2
            <= tolerance_m2
            <= MAX_AREA_TOLERANCE_M2
        )
    ):
        raise ValueError(
            "tolerance_m2 must be within the supported architectural "
            f"range [{MIN_AREA_TOLERANCE_M2}, {MAX_AREA_TOLERANCE_M2}]"
        )


def _geometry_reasons(geometry: tuple[AreaGeometry, ...]) -> list[str]:
    reasons: list[str] = []
    for shape in geometry:
        if shape.holes:
            reasons.append("polygon_holes_unsupported")
            continue
        vertices = _vertices(shape)
        if any(
            not isinstance(point, tuple) or len(point) != 2
            for point in vertices
        ):
            reasons.append("invalid_polygon")
            continue
        if len(set(vertices)) < 4:
            reasons.append("polygon_too_few_vertices")
            continue
        if any(
            current == following
            for current, following in zip(vertices, vertices[1:])
        ):
            reasons.append("repeated_consecutive_vertex")
            continue
        if not all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            for point in vertices
            for value in point
        ):
            reasons.append("non_finite_polygon")
            continue
        if any(
            end[0] != start[0] and end[1] != start[1]
            for start, end in _edges(vertices)
        ):
            reasons.append("non_axis_aligned_polygon")
            continue
        try:
            validate_polygon(vertices, label=shape.source_id)
        except ValueError as error:
            if "self-intersecting" in str(error):
                reasons.append("self_intersecting_polygon")
            else:
                reasons.append("invalid_polygon")
    return list(dict.fromkeys(reasons))


def _entries(
    values: dict[str, float],
    gross: AreaGeometry,
    categories: dict[str, tuple[AreaGeometry, ...]],
    unclassified: tuple[AreaGeometry, ...],
    classification_rule: str,
) -> tuple[AreaLedgerEntry, ...]:
    entries: list[AreaLedgerEntry] = []
    for bucket in AREA_BUCKETS:
        if bucket == "gross":
            method = "polygon_union"
            source_ids = (gross.source_id,)
            rule = "supplied-floor-boundary"
            formula = "union(gross boundary)"
        elif bucket in _CATEGORY_BUCKETS:
            method = "polygon_union"
            source_ids = tuple(shape.source_id for shape in categories[bucket])
            rule = classification_rule
            formula = f"union({bucket} geometry)"
        elif bucket == "net":
            method = "derived_sum"
            source_ids = ("service", "primary")
            rule = classification_rule
            formula = "service + primary"
        else:
            method = "residual"
            source_ids = (
                gross.source_id,
                *(
                    shape.source_id
                    for category in categories.values()
                    for shape in category
                ),
                *(shape.source_id for shape in unclassified),
            )
            rule = "unclassified geometry remains unassigned"
            formula = (
                "area(gross boundary minus union(classified geometry "
                "intersect gross))"
            )
        entries.append(
            AreaLedgerEntry(
                bucket=bucket,
                area_m2=values[bucket],
                provenance=AreaProvenance(
                    method=method,
                    source_ids=tuple(dict.fromkeys(source_ids)),
                    classification_rule=rule,
                    formula=formula,
                ),
            )
        )
    return tuple(entries)


def _not_checked_floor(
    floor_index: int,
    gross: AreaGeometry,
    categories: dict[str, tuple[AreaGeometry, ...]],
    unclassified: tuple[AreaGeometry, ...],
    classification_rule: str,
    tolerance_m2: float,
    unresolved: tuple[str, ...],
) -> FloorAreaLedger:
    empty_values = {bucket: None for bucket in AREA_BUCKETS}
    entries = _entries(
        empty_values,
        gross,
        categories,
        unclassified,
        classification_rule,
    )
    return FloorAreaLedger(
        floor_index=floor_index,
        status="not_checked",
        entries=entries,
        overlap_area_m2=0.0,
        out_of_boundary_area_m2=0.0,
        tolerance_m2=tolerance_m2,
        unresolved_facts=unresolved,
    )


def _vertices(shape: AreaGeometry) -> tuple[tuple[float, float], ...]:
    vertices = shape.polygon
    if len(vertices) > 1 and vertices[0] == vertices[-1]:
        return vertices[:-1]
    return vertices


def _edges(points):
    return zip(points, points[1:] + points[:1])


def _point_in_polygon(point, polygon) -> bool:
    x, y = point
    inside = False
    for start, end in _edges(polygon):
        if (start[1] > y) != (end[1] > y):
            intersection_x = start[0] + (y - start[1]) * (
                end[0] - start[0]
            ) / (end[1] - start[1])
            if x < intersection_x:
                inside = not inside
    return inside


def _duplicate_source_ids(
    geometry: tuple[AreaGeometry, ...],
) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for shape in geometry:
        if shape.source_id in seen:
            duplicates.append(shape.source_id)
        seen.add(shape.source_id)
    return tuple(dict.fromkeys(duplicates))


def _normalize_zero(value: float, tolerance: float) -> float:
    comparison_epsilon = 4 * max(
        math.ulp(tolerance),
        math.ulp(abs(value)) if abs(value) <= tolerance else 0.0,
    )
    boundary_epsilon = max(
        comparison_epsilon,
        _BOUNDARY_ROUNDOFF_M2,
    )
    within_tolerance = abs(value) <= tolerance + boundary_epsilon
    return 0.0 if within_tolerance else value


def _entry(floor: FloorAreaLedger, bucket: str) -> AreaLedgerEntry:
    return next(entry for entry in floor.entries if entry.bucket == bucket)
