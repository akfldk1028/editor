from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import replace

from backend.app.modules.generation_loop.operators import (
    generate_initial_proposals,
    layout_fingerprint,
    refine_proposals,
)
from backend.app.modules.generation_loop.selector import rank_candidate, select_frontier
from backend.app.modules.layout_generator.service import (
    generate_baseline_layout,
    generate_core_aligned_layout,
    generate_rear_center_layout,
    generate_side_mid_layout,
)
from backend.app.modules.basic_design.service import (
    generate_basic_design,
    generate_shared_structure,
)
from backend.app.modules.mass_analyzer.service import analyze_mass
from backend.app.modules.program_prior.service import generate_program_graph
from backend.app.modules.validator.service import validate_layout
from backend.app.schemas.llm import SUPPORTED_USE_TYPES, FloorAssignment
from backend.app.schemas.mass import MassAnalysis, MassInput
from backend.app.schemas.loop import (
    CandidateRecord,
    IterationRecord,
    LoopConfig,
    LoopResult,
)
from backend.app.schemas.result import (
    AlternativeGeometryComparison,
    BuildingAlternativeResult,
    BuildingAlternativesResult,
    BuildingGenerationResult,
    GenerationResult,
    PlannerProvenance,
)
from backend.app.schemas.layout import LayoutCandidate, OpeningSegment, RoomPolygon
from backend.app.schemas.program import ProgramAdjustment


def run_generation_loop(
    mass: MassInput,
    floor_index: int,
    use_type: str,
) -> GenerationResult:
    analysis = analyze_mass(mass)
    program = generate_program_graph(analysis, floor_index=floor_index, use_type=use_type)
    layout = generate_baseline_layout(analysis, program)
    validation = validate_layout(
        layout,
        program,
        boundary=mass.footprint_polygon,
        street_segments=_street_segments(mass),
    )
    return GenerationResult(
        mass=analysis,
        program=program,
        layout=layout,
        validation=validation,
    )


def run_building_generation(
    mass: MassInput,
    *,
    floor_assignments: Iterable[FloorAssignment] | None = None,
    planner_provenance: PlannerProvenance | None = None,
) -> BuildingGenerationResult:
    analysis = analyze_mass(mass)
    _require_rectangular_floor_plate(mass, analysis)
    if floor_assignments is None:
        assignments = assign_floors_from_use_mix(mass)
        assignment_source = "use_mix"
        provenance = PlannerProvenance(
            planner_mode="deterministic",
            provider="deterministic",
            model=None,
            response_id=None,
            validated_assignments=assignments,
        )
    else:
        assignments = _validate_floor_assignments(
            floor_assignments,
            floors=mass.floors,
        )
        assignment_source = "structured"
        provenance = planner_provenance or PlannerProvenance(
            planner_mode="structured",
            provider="manual",
            model=None,
            response_id=None,
            validated_assignments=assignments,
        )
        if provenance.validated_assignments != assignments:
            raise ValueError(
                "planner provenance assignments must match validated floor assignments"
            )
    min_x, min_y, max_x, max_y = analysis.bounds
    width = max_x - min_x
    depth = max_y - min_y
    if width < 20.0 or depth < 10.0:
        raise ValueError(
            "concept-basic footprint requires width >= 20.0 m and depth >= 10.0 m"
        )

    programs = [
        generate_program_graph(
            analysis,
            floor_index=assignment.floor_index,
            use_type=assignment.use_type,
        )
        for assignment in assignments
    ]
    shared_core_target = max(
        float(next(node.target_area for node in program.nodes if node.space_type == "core"))
        for program in programs
    )

    room_scale = 0.9
    min_x, min_y, max_x, max_y = analysis.bounds
    height = max_y - min_y
    use_role_layout = all(
        program.use_type in {"office", "neighborhood_commercial"}
        and any(node.space_type in {"sales", "open_work"} for node in program.nodes)
        for program in programs
    )
    if use_role_layout:
        streets = _street_segments(mass)
        if any(program.use_type == "neighborhood_commercial" for program in programs) and len(streets) != 1:
            raise ValueError("neighborhood commercial generation requires exactly one street edge")
        if any(program.use_type == "neighborhood_commercial" for program in programs):
            street_start, street_end = streets[0]
            if {street_start, street_end} != {(min_x, min_y), (max_x, min_y)}:
                raise ValueError(
                    "neighborhood commercial street edge must be the y=min_y floor boundary"
                )
        preferred_core_height = min(
            height * (0.47333333333333333 if height >= 12 else 0.46),
            height - 1.2,
        )
        service_band_width = max(
            shared_core_target / preferred_core_height,
            7.6,
        )
        service_x = float(_clean_area(max_x - service_band_width))
        service_band_width = max_x - service_x
        core_height = max(5.4, shared_core_target / service_band_width)
        shared_core_target = service_band_width * core_height
    else:
        service_band_width = max(
            room_scale
            * sum(
                float(node.target_area)
                for node in program.nodes
                if node.space_type not in {"shop_unit", "office_area"}
            )
            / height
            for program in programs
        )
        service_x = float(_clean_area(max_x - service_band_width))
        service_band_width = max_x - service_x
        core_height = room_scale * shared_core_target / service_band_width
    programs = [
        _normalize_program_core(program, shared_core_target)
        for program in programs
    ]
    if width <= 24.0 or depth <= 10.0:
        shallow_compact = width <= 24.0 and depth <= 12.0
        programs = [
            _compress_compact_program(
                program,
                primary_factor=0.8,
                service_factor=0.6,
                upper_service_factor=(
                    (0.5 if program.use_type == "neighborhood_commercial" else 0.5)
                    if shallow_compact
                    else None
                ),
            )
            for program in programs
        ]
    programs = [
        _fit_rear_primary_program(program, analysis)
        for program in programs
    ]
    core_top = float(_clean_area(min_y + core_height))
    shared_core = [
        (service_x, min_y),
        (max_x, min_y),
        (max_x, core_top),
        (service_x, core_top),
    ]

    layouts = []
    for program in programs:
        if use_role_layout:
            layout = generate_rear_center_layout(
                analysis,
                program,
                core_position="rear_right",
            )
        else:
            layout = generate_core_aligned_layout(
                analysis,
                program,
                core_polygon=shared_core,
                service_band_width=service_band_width,
                room_scale=room_scale,
            )
        layouts.append(layout)

    shared_structure = generate_shared_structure(
        mass.footprint_polygon,
        tuple(layouts),
    )
    floor_results = []
    for program, layout in zip(programs, layouts):
        layout = replace(
            layout,
            basic_design=generate_basic_design(
                layout,
                boundary=mass.footprint_polygon,
                street_segments=_street_segments(mass),
                shared_structure=shared_structure,
            ),
        )
        validation = validate_layout(
            layout,
            program,
            boundary=mass.footprint_polygon,
            street_segments=_street_segments(mass),
            require_openings=True,
            min_door_width=0.8,
            min_circulation_width=1.2,
            require_basic_design=True,
        )
        floor_results.append(
            GenerationResult(
                mass=analysis,
                program=program,
                layout=layout,
                validation=validation,
            )
        )

    use_type_areas: dict[str, float] = {}
    for assignment in assignments:
        use_type_areas[assignment.use_type] = (
            use_type_areas.get(assignment.use_type, 0.0) + float(analysis.area)
        )
    core_polygons = [
        next(room.polygon for room in floor.layout.rooms if room.space_type == "core")
        for floor in floor_results
    ]
    vertical_core_aligned = all(
        polygon == core_polygons[0]
        for polygon in core_polygons[1:]
    )
    vertical_basic_design_aligned, vertical_structure_aligned = (
        _vertical_basic_design_alignment(tuple(floor_results))
    )
    return BuildingGenerationResult(
        mass=analysis,
        floor_assignments=assignments,
        floor_results=tuple(floor_results),
        total_area=float(analysis.floor_area),
        use_type_areas={
            use_type: _clean_area(area)
            for use_type, area in sorted(use_type_areas.items())
        },
        assignment_source=assignment_source,
        vertical_core_aligned=vertical_core_aligned,
        vertical_basic_design_aligned=vertical_basic_design_aligned,
        vertical_structure_aligned=vertical_structure_aligned,
        planner_provenance=provenance,
    )


_ALTERNATIVE_STRATEGIES = (
    ("alternative-a", "rear-right-core-single-spine", "rear-right"),
    ("alternative-b", "rear-center-core-dual-bay", "rear-center"),
    ("alternative-c", "side-mid-core-longitudinal-spine", "side-mid"),
)


def run_building_alternatives(mass: MassInput) -> BuildingAlternativesResult:
    """Generate ranked, geometrically distinct concept-basic building options."""
    baseline = run_building_generation(mass)
    alternatives = []
    for alternative_id, strategy, transform in _ALTERNATIVE_STRATEGIES:
        if transform == "identity":
            building = baseline
        elif transform == "rear-right":
            building = _generate_positioned_building(
                baseline,
                mass=mass,
                generator=lambda analysis, program: generate_rear_center_layout(
                    analysis,
                    program,
                    core_position="rear_right",
                ),
            )
        elif transform == "rear-center":
            building = _generate_rear_center_building(baseline, mass=mass)
        elif transform == "side-mid":
            building = _generate_side_mid_building(baseline, mass=mass)
        else:
            building = _transform_building_alternative(
                baseline,
                mass=mass,
                transform=transform,
                alternative_id=alternative_id,
            )
        fingerprints = tuple(
            layout_fingerprint(floor.layout)
            for floor in building.floor_results
        )
        mean_score = sum(
            floor.validation.total_score for floor in building.floor_results
        ) / len(building.floor_results)
        geometry = _alternative_geometry_evidence(building)
        alternatives.append(
            BuildingAlternativeResult(
                alternative_id=alternative_id,
                strategy=strategy,
                building=building,
                score=round(mean_score, 6),
                rank=0,
                fingerprints=fingerprints,
                **geometry,
            )
        )
    alternatives.sort(
        key=lambda alternative: (
            not alternative.accepted,
            -alternative.score,
            alternative.alternative_id,
        )
    )
    ranked = tuple(
        replace(alternative, rank=rank)
        for rank, alternative in enumerate(alternatives, start=1)
    )
    diagonal = math.hypot(
        baseline.mass.bounds[2] - baseline.mass.bounds[0],
        baseline.mass.bounds[3] - baseline.mass.bounds[1],
    )
    comparisons = []
    for index, first in enumerate(ranked):
        for second in ranked[index + 1:]:
            core_distance = math.dist(first.core_centroid, second.core_centroid)
            normalized_distance = core_distance / diagonal
            circulation_different = (
                first.circulation_graph_signature
                != second.circulation_graph_signature
                or first.circulation_bounds != second.circulation_bounds
            )
            tenant_different = (
                first.tenant_assignment_signature
                != second.tenant_assignment_signature
            )
            comparisons.append(
                AlternativeGeometryComparison(
                    first_alternative_id=first.alternative_id,
                    second_alternative_id=second.alternative_id,
                    normalized_core_centroid_distance=round(normalized_distance, 6),
                    circulation_graph_different=circulation_different,
                    tenant_assignment_different=tenant_different,
                    semantic_distinct=(
                        normalized_distance >= 0.15
                        or circulation_different
                        or tenant_different
                    ),
                )
            )
    return BuildingAlternativesResult(
        mass=baseline.mass,
        alternatives=ranked,
        comparisons=tuple(comparisons),
    )


def _alternative_geometry_evidence(building: BuildingGenerationResult) -> dict:
    layout = building.floor_results[0].layout
    core = next(room for room in layout.rooms if room.space_type == "core")
    core_x = [point[0] for point in core.polygon]
    core_y = [point[1] for point in core.polygon]
    core_centroid = (
        round((min(core_x) + max(core_x)) / 2, 6),
        round((min(core_y) + max(core_y)) / 2, 6),
    )
    circulation_points = [
        point
        for path in layout.circulation
        for point in path.polygon
    ]
    circulation_bounds = (
        round(min(point[0] for point in circulation_points), 6),
        round(min(point[1] for point in circulation_points), 6),
        round(max(point[0] for point in circulation_points), 6),
        round(max(point[1] for point in circulation_points), 6),
    )
    width = circulation_bounds[2] - circulation_bounds[0]
    depth = circulation_bounds[3] - circulation_bounds[1]
    orientation = "longitudinal-x" if width >= depth else "longitudinal-y"
    graph = tuple(
        sorted(
            f"{opening.connects[0]}->{opening.connects[1]}"
            for opening in layout.openings
        )
    )
    basic_design = layout.basic_design
    entrance_lines = (
        [
            line
            for line in basic_design.lines
            if line.category == "envelope" and line.kind == "entrance"
        ]
        if basic_design is not None
        else []
    )
    tenant_room_ids = {
        room.room_id
        for room in layout.rooms
        if room.room_id.startswith("sales_")
    }
    tenant_entrances = tuple(
        sorted(
            f"{line.host_id}:{line.line_id}"
            for line in entrance_lines
            if line.host_id in tenant_room_ids
        )
    )
    core_public_entrance = any(
        line.line_id == "core-public-entrance"
        for line in entrance_lines
    )
    commercial_floor = next(
        (
            floor
            for floor in building.floor_results
            if floor.program.use_type == "neighborhood_commercial"
        ),
        None,
    )
    tenant_nodes = (
        sorted(
            (
                node
                for node in commercial_floor.program.nodes
                if node.space_type == "sales"
            ),
            key=lambda node: (str(node.tenant_id), node.node_id),
        )
        if commercial_floor is not None
        else []
    )
    entrance_by_host = {
        line.host_id: line.line_id
        for line in entrance_lines
        if line.host_id in {node.node_id for node in tenant_nodes}
    }
    common_core_policy_passed = bool(
        commercial_floor is not None
        and commercial_floor.validation.basic_design is not None
        and commercial_floor.validation.basic_design.policy_checks.get(
            "common_core_access",
            {},
        ).get("pass")
    )
    tenants = tuple(
        [
            (
                f"{node.tenant_id}->{node.node_id}->"
                f"{entrance_by_host.get(node.node_id, 'missing')}"
            )
            for node in tenant_nodes
        ]
        + [f"common-core-access:{common_core_policy_passed}"]
    )
    family_payload = (
        core_centroid,
        orientation,
        circulation_bounds,
        graph,
        tenants,
    )
    return {
        "core_centroid": core_centroid,
        "circulation_orientation": orientation,
        "circulation_bounds": circulation_bounds,
        "circulation_graph_signature": graph,
        "tenant_assignment_signature": tenants,
        "tenant_count": len(tenant_room_ids),
        "tenant_entrance_assignments": tenant_entrances,
        "core_public_entrance": core_public_entrance,
        "design_family_signature": repr(family_payload),
    }


def _transform_building_alternative(
    baseline: BuildingGenerationResult,
    *,
    mass: MassInput,
    transform: str,
    alternative_id: str,
) -> BuildingGenerationResult:
    bounds = baseline.mass.bounds
    transformed_layouts = tuple(
        _transform_layout(
            floor.layout,
            bounds=bounds,
            transform=transform,
            candidate_id=f"{floor.layout.candidate_id}-{alternative_id}",
        )
        for floor in baseline.floor_results
    )
    shared_structure = generate_shared_structure(
        mass.footprint_polygon,
        transformed_layouts,
    )
    floor_results = []
    streets = _street_segments(mass)
    for floor, layout in zip(baseline.floor_results, transformed_layouts):
        layout = replace(
            layout,
            basic_design=generate_basic_design(
                layout,
                boundary=mass.footprint_polygon,
                street_segments=streets,
                shared_structure=shared_structure,
            ),
        )
        validation = validate_layout(
            layout,
            floor.program,
            boundary=mass.footprint_polygon,
            street_segments=streets,
            require_openings=True,
            min_door_width=0.8,
            min_circulation_width=1.2,
            require_basic_design=True,
        )
        floor_results.append(
            replace(floor, layout=layout, validation=validation)
        )
    values = tuple(floor_results)
    cores = [
        next(room.polygon for room in floor.layout.rooms if room.space_type == "core")
        for floor in values
    ]
    vertical_basic, vertical_structure = _vertical_basic_design_alignment(values)
    return replace(
        baseline,
        floor_results=values,
        vertical_core_aligned=all(core == cores[0] for core in cores[1:]),
        vertical_basic_design_aligned=vertical_basic,
        vertical_structure_aligned=vertical_structure,
    )


def _generate_rear_center_building(
    baseline: BuildingGenerationResult,
    *,
    mass: MassInput,
) -> BuildingGenerationResult:
    adjusted_floors = []
    for floor in baseline.floor_results:
        if floor.program.use_type != "office":
            adjusted_floors.append(floor)
            continue
        nodes = [
            (
                replace(
                    node,
                    target_area=_clean_area(float(node.target_area) * 0.95),
                    min_area=_clean_area(float(node.target_area) * 0.95 * 0.85),
                    max_area=_clean_area(float(node.target_area) * 0.95 * 1.15),
                    min_width=(
                        _clean_area(float(node.min_width) * 0.95)
                        if node.min_width is not None
                        else None
                    ),
                )
                if node.space_type not in {"core", "open_work"}
                else node
            )
            for node in floor.program.nodes
        ]
        program = _with_program_adjustment(
            floor.program,
            nodes,
            reason="rear_center_service_fit",
            source=f"{floor.program.source}:rear_center_service_fit",
        )
        adjusted_floors.append(replace(floor, program=program))
    return _generate_positioned_building(
        replace(baseline, floor_results=tuple(adjusted_floors)),
        mass=mass,
        generator=generate_rear_center_layout,
    )


def _generate_side_mid_building(
    baseline: BuildingGenerationResult,
    *,
    mass: MassInput,
) -> BuildingGenerationResult:
    min_x, min_y, max_x, max_y = baseline.mass.bounds
    depth = max_y - min_y
    cross_bottoms = []
    required_service_heights = []
    for floor in baseline.floor_results:
        core = next(
            node for node in floor.program.nodes if node.space_type == "core"
        )
        core_height = max(7.2, depth * 0.6)
        core_width = float(core.target_area) * 0.855 / core_height
        branch_left = max_x - core_width - 1.2
        primary = next(
            node
            for node in floor.program.nodes
            if node.space_type in {"sales", "open_work"}
        )
        primary_width = (
            (branch_left - min_x) / 2
            if floor.program.use_type == "neighborhood_commercial"
            else branch_left - min_x
        )
        cross_bottoms.append(
            min_y + float(primary.target_area) * 0.855 / primary_width
        )
        service_nodes = [
            node
            for node in floor.program.nodes
            if node.space_type not in {"core", "sales", "open_work"}
        ]
        available_width = max(branch_left - min_x - 4.8, 1.0)
        service_height = max(
            2.4,
            sum(float(node.target_area) * 0.855 for node in service_nodes)
            / available_width,
        )
        while (
            sum(
                max(
                    float(node.target_area) * 0.855 / service_height,
                    float(node.min_width or 0),
                    1.1,
                )
                for node in service_nodes
            )
            > available_width
            and service_height < depth - 3.2
        ):
            service_height += 0.1
        required_service_heights.append(service_height)
    shared_cross_bottom = min(
        max(cross_bottoms),
        max_y - 1.2 - max(required_service_heights),
    )
    return _generate_positioned_building(
        baseline,
        mass=mass,
        generator=lambda analysis, program: generate_side_mid_layout(
            analysis,
            program,
            cross_bottom_override=shared_cross_bottom,
        ),
    )


def _generate_positioned_building(
    baseline: BuildingGenerationResult,
    *,
    mass: MassInput,
    generator,
) -> BuildingGenerationResult:
    layouts = tuple(
        generator(baseline.mass, floor.program)
        for floor in baseline.floor_results
    )
    shared_structure = generate_shared_structure(mass.footprint_polygon, layouts)
    streets = _street_segments(mass)
    floors = []
    for floor, layout in zip(baseline.floor_results, layouts):
        layout = replace(
            layout,
            basic_design=generate_basic_design(
                layout,
                boundary=mass.footprint_polygon,
                street_segments=streets,
                shared_structure=shared_structure,
            ),
        )
        floors.append(
            replace(
                floor,
                layout=layout,
                validation=validate_layout(
                    layout,
                    floor.program,
                    boundary=mass.footprint_polygon,
                    street_segments=streets,
                    require_openings=True,
                    min_door_width=0.8,
                    min_circulation_width=1.2,
                    require_basic_design=True,
                ),
            )
        )
    values = tuple(floors)
    vertical_basic, vertical_structure = _vertical_basic_design_alignment(values)
    return replace(
        baseline,
        floor_results=values,
        vertical_core_aligned=True,
        vertical_basic_design_aligned=vertical_basic,
        vertical_structure_aligned=vertical_structure,
    )


def _transform_layout(
    layout: LayoutCandidate,
    *,
    bounds: tuple[float, float, float, float],
    transform: str,
    candidate_id: str,
) -> LayoutCandidate:
    min_x, min_y, max_x, max_y = bounds

    def point(value):
        x, y = value
        if transform == "mirror-x":
            return (min_x + max_x - x, y)
        if transform == "mirror-y":
            return (x, min_y + max_y - y)
        if transform == "mirror-xy":
            return (min_x + max_x - x, min_y + max_y - y)
        raise ValueError(f"unsupported alternative transform: {transform}")

    def polygon(points):
        transformed = [point(value) for value in points]
        transformed.reverse()
        return transformed

    def room(value):
        return RoomPolygon(
            room_id=value.room_id,
            space_type=value.space_type,
            polygon=polygon(value.polygon),
        )

    def opening(value):
        endpoints = sorted((point(value.start), point(value.end)))
        return OpeningSegment(
            opening_id=value.opening_id,
            kind=value.kind,
            connects=value.connects,
            start=endpoints[0],
            end=endpoints[1],
            clear_width=value.clear_width,
        )

    return LayoutCandidate(
        candidate_id=candidate_id,
        project_id=layout.project_id,
        floor_index=layout.floor_index,
        rooms=[room(value) for value in layout.rooms],
        circulation=[room(value) for value in layout.circulation],
        score=layout.score,
        openings=[opening(value) for value in layout.openings],
    )


def _vertical_basic_design_alignment(
    floor_results: tuple[GenerationResult, ...],
) -> tuple[bool, bool]:
    if not floor_results:
        return False, False

    vertical_signatures = []
    structure_signatures = []
    for floor in floor_results:
        basic_design = floor.layout.basic_design
        if basic_design is None:
            return False, False
        vertical_signatures.append(
            tuple(
                sorted(
                    (
                        element.element_id,
                        element.kind,
                        element.footprint,
                    )
                    for element in basic_design.elements
                    if element.category == "vertical"
                )
            )
        )
        structure_signatures.append(
            (
                tuple(
                    sorted(
                        (
                            element.element_id,
                            element.kind,
                            element.footprint,
                        )
                        for element in basic_design.elements
                        if element.category == "structure"
                    )
                ),
                tuple(
                    sorted(
                        (
                            line.line_id,
                            line.kind,
                            line.points,
                        )
                        for line in basic_design.lines
                        if line.category == "structure"
                    )
                ),
            )
        )
    return (
        all(signature == vertical_signatures[0] for signature in vertical_signatures[1:]),
        all(signature == structure_signatures[0] for signature in structure_signatures[1:]),
    )


def assign_floors_from_use_mix(mass: MassInput) -> tuple[FloorAssignment, ...]:
    if not mass.use_mix:
        raise ValueError("use_mix must contain at least one supported use type")
    unsupported = sorted(set(mass.use_mix) - SUPPORTED_USE_TYPES)
    if unsupported:
        raise ValueError(f"unsupported use_mix types: {', '.join(unsupported)}")
    if any(
        not math.isfinite(float(weight)) or float(weight) < 0
        for weight in mass.use_mix.values()
    ):
        raise ValueError("use_mix weights must be finite and non-negative")
    positive = {
        use_type: float(weight)
        for use_type, weight in mass.use_mix.items()
        if float(weight) > 0
    }
    total_weight = sum(positive.values())
    if total_weight <= 0:
        raise ValueError("use_mix must contain a positive weight")

    use_order = sorted(
        positive,
        key=lambda use_type: (
            use_type != "neighborhood_commercial",
            use_type,
        ),
    )
    raw_counts = {
        use_type: mass.floors * positive[use_type] / total_weight
        for use_type in use_order
    }
    counts = {
        use_type: math.floor(raw_counts[use_type])
        for use_type in use_order
    }
    remaining = mass.floors - sum(counts.values())
    remainder_order = sorted(
        use_order,
        key=lambda use_type: (
            -(raw_counts[use_type] - counts[use_type]),
            use_type != "neighborhood_commercial",
            use_type,
        ),
    )
    for use_type in remainder_order[:remaining]:
        counts[use_type] += 1

    assignments = []
    floor_index = 1
    for use_type in use_order:
        for _ in range(counts[use_type]):
            assignments.append(FloorAssignment(floor_index, use_type))
            floor_index += 1
    return tuple(assignments)


def _validate_floor_assignments(
    assignments: Iterable[FloorAssignment],
    *,
    floors: int,
) -> tuple[FloorAssignment, ...]:
    values = tuple(assignments)
    if not all(isinstance(item, FloorAssignment) for item in values):
        raise ValueError("floor assignments must use FloorAssignment records")
    if any(item.use_type not in SUPPORTED_USE_TYPES for item in values):
        raise ValueError("floor assignments contain an unsupported use type")
    indices = [item.floor_index for item in values]
    if sorted(indices) != list(range(1, floors + 1)):
        raise ValueError(
            "floor assignments must contain every floor exactly once"
        )
    return tuple(sorted(values, key=lambda item: item.floor_index))


def _normalize_program_core(program, shared_core_target: float):
    core_nodes = [node for node in program.nodes if node.space_type == "core"]
    if len(core_nodes) != 1:
        raise ValueError("program must contain exactly one core role")
    core = core_nodes[0]
    primary_roles = {
        "neighborhood_commercial": "sales",
        "office": "open_work",
    }
    primary_role = primary_roles.get(program.use_type)
    if primary_role is None:
        primary_candidates = [
            node
            for node in program.nodes
            if node.space_type in {"shop_unit", "office_area"}
        ]
    else:
        primary_candidates = [
            node for node in program.nodes if node.space_type == primary_role
        ]
    if not primary_candidates:
        raise ValueError(
            f"program must contain a residual primary role for {program.use_type}"
        )
    delta = shared_core_target - float(core.target_area)
    primary_total = sum(float(node.target_area) for node in primary_candidates)
    if primary_total - delta <= 0:
        raise ValueError("shared core leaves no primary usable area")
    nodes = []
    for node in program.nodes:
        if node.node_id == core.node_id:
            target = shared_core_target
            nodes.append(
                replace(
                    node,
                    target_area=_clean_area(target),
                    min_area=_clean_area(target * 0.85),
                    max_area=_clean_area(target * 1.15),
                )
            )
        elif node in primary_candidates:
            share = float(node.target_area) / primary_total
            primary_target = float(node.target_area) - delta * share
            nodes.append(
                replace(
                    node,
                    target_area=_clean_area(primary_target),
                    min_area=_clean_area(primary_target * 0.85),
                    max_area=_clean_area(primary_target * 1.15),
                )
            )
        else:
            nodes.append(node)
    return _with_program_adjustment(
        program,
        nodes,
        reason="shared_core_normalization",
        source="building_aligned_prior",
    )


def _compress_compact_program(
    program,
    *,
    primary_factor: float,
    service_factor: float,
    upper_service_factor: float | None = None,
):
    primary_roles = {"sales", "open_work", "shop_unit", "office_area"}
    upper_service_roles = {
        "stock",
        "meeting",
        "reception",
        "restroom",
        "utility",
        "it_storage",
    }
    nodes = []
    for node in program.nodes:
        if node.space_type == "core":
            nodes.append(node)
            continue
        if node.space_type in primary_roles:
            factor = primary_factor
        elif (
            upper_service_factor is not None
            and node.space_type in upper_service_roles
        ):
            factor = upper_service_factor
        else:
            factor = service_factor
        target = max(
            float(node.target_area) * factor,
            (float(node.min_width or 0) ** 2) / 0.855 * 1.01,
        )
        nodes.append(
            replace(
                node,
                target_area=_clean_area(target),
                min_area=_clean_area(target * 0.85),
                max_area=_clean_area(target * 1.15),
                min_width=(
                    max(1.1, float(node.min_width) * 0.5)
                    if node.min_width is not None
                    and node.space_type != "core"
                    else node.min_width
                ),
                max_aspect_ratio=(
                    max(8.5, float(node.max_aspect_ratio or 1.0))
                    if node.space_type != "core"
                    else node.max_aspect_ratio
                ),
            )
        )
    return _with_program_adjustment(
        program,
        nodes,
        reason="compact_mass_fit",
        source="compact_building_aligned_prior",
    )


def _fit_rear_primary_program(program, analysis: MassAnalysis):
    min_x, min_y, max_x, max_y = analysis.bounds
    depth = max_y - min_y
    rear_height = max(5.2, depth * 0.5)
    front_depth = depth - rear_height - 1.2
    capacity = (max_x - min_x - 1.2) * front_depth
    core = next(node for node in program.nodes if node.space_type == "core")
    actual_core_area = max(
        7.0,
        float(core.target_area) * 0.855 / rear_height,
    ) * rear_height
    fitted_core_target = (
        actual_core_area / 0.855
        if (
            actual_core_area < float(core.min_area or 0)
            or actual_core_area > float(core.max_area or math.inf)
        )
        else float(core.target_area)
    )
    if program.use_type == "neighborhood_commercial":
        tenant_actual = ((max_x - min_x - 1.2) / 2) * front_depth
        tenant_target = tenant_actual / 0.855
        nodes = [
            (
                replace(
                    node,
                    target_area=_clean_area(tenant_target),
                    min_area=_clean_area(tenant_target * 0.85),
                    max_area=_clean_area(tenant_target * 1.15),
                    max_aspect_ratio=max(
                        6.5, float(node.max_aspect_ratio or 1.0)
                    ),
                )
                if node.space_type == "sales"
                else replace(
                    node,
                    max_aspect_ratio=max(
                        6.5, float(node.max_aspect_ratio or 1.0)
                    ),
                )
                if node.space_type != "core"
                else replace(
                    node,
                    target_area=_clean_area(fitted_core_target),
                    min_area=_clean_area(fitted_core_target * 0.85),
                    max_area=_clean_area(fitted_core_target * 1.15),
                )
                if node.space_type == "core"
                else node
            )
            for node in program.nodes
        ]
        return _with_program_adjustment(
            program,
            nodes,
            reason="rear_tenant_fit",
            source=f"{program.source}:rear_tenant_fit",
        )
    if program.use_type != "office":
        return program
    primary = next(node for node in program.nodes if node.space_type == "open_work")
    fitted_target = min(float(primary.target_area), capacity / 0.855 * 0.999)
    nodes = [
        (
            replace(
                node,
                target_area=_clean_area(fitted_target),
                min_area=_clean_area(fitted_target * 0.85),
                max_area=_clean_area(fitted_target * 1.15),
                min_width=min(float(node.min_width or front_depth), front_depth),
                max_aspect_ratio=max(
                    6.5, float(node.max_aspect_ratio or 1.0)
                ),
            )
            if node.node_id == primary.node_id
            else replace(
                node,
                max_aspect_ratio=max(
                    6.5, float(node.max_aspect_ratio or 1.0)
                ),
            )
            if node.space_type != "core"
            else replace(
                node,
                target_area=_clean_area(fitted_core_target),
                min_area=_clean_area(fitted_core_target * 0.85),
                max_area=_clean_area(fitted_core_target * 1.15),
            )
            if node.space_type == "core"
            else node
        )
        for node in program.nodes
    ]
    return _with_program_adjustment(
        program,
        nodes,
        reason="rear_primary_fit",
        source=f"{program.source}:rear_primary_fit",
    )


def _program_adjustment(reason, original_nodes, adjusted_nodes):
    return ProgramAdjustment(
        reason=reason,
        original_nodes=tuple(original_nodes),
        adjusted_nodes=tuple(adjusted_nodes),
        original_targets=tuple(
            (node.node_id, float(node.target_area))
            for node in original_nodes
        ),
        adjusted_targets=tuple(
            (node.node_id, float(node.target_area))
            for node in adjusted_nodes
        ),
    )


def _with_program_adjustment(
    program,
    nodes,
    *,
    reason: str,
    source: str,
):
    if list(program.nodes) == list(nodes):
        return program
    return replace(
        program,
        nodes=nodes,
        source=source,
        adjustments=(
            *program.adjustments,
            _program_adjustment(reason, program.nodes, nodes),
        ),
    )


def _require_rectangular_floor_plate(
    mass: MassInput,
    analysis: MassAnalysis,
) -> None:
    min_x, min_y, max_x, max_y = analysis.bounds
    expected = {
        (float(min_x), float(min_y)),
        (float(max_x), float(min_y)),
        (float(max_x), float(max_y)),
        (float(min_x), float(max_y)),
    }
    actual = {(float(x), float(y)) for x, y in mass.footprint_polygon}
    if len(mass.footprint_polygon) != 4 or actual != expected:
        raise ValueError(
            "building generation currently requires an axis-aligned rectangular floor plate"
        )


def _clean_area(value: float) -> float | int:
    return int(value) if float(value).is_integer() else round(value, 6)


def run_candidate_search(
    mass: MassInput,
    floor_index: int,
    use_type: str,
    config: LoopConfig | None = None,
) -> LoopResult:
    config = config or LoopConfig()
    analysis = analyze_mass(mass)
    program = generate_program_graph(
        analysis,
        floor_index=floor_index,
        use_type=use_type,
    )
    streets = _street_segments(mass)
    try:
        pending = generate_initial_proposals(analysis, program)
    except Exception as error:
        return _failed_loop_result(analysis, program, error)
    seen: set[str] = set()
    iterations: list[IterationRecord] = []
    history: list[CandidateRecord] = []
    best: CandidateRecord | None = None
    evaluation_count = 0
    stagnant_iterations = 0

    for iteration in range(1, config.max_iterations + 1):
        records: list[CandidateRecord] = []
        skipped_for_budget = False
        for proposal in pending:
            layout = proposal.layout
            fingerprint = layout_fingerprint(layout)
            if fingerprint in seen:
                continue
            if evaluation_count >= config.evaluation_budget:
                skipped_for_budget = True
                break
            seen.add(fingerprint)
            try:
                validation = validate_layout(
                    layout,
                    program,
                    boundary=mass.footprint_polygon,
                    street_segments=streets,
                )
            except Exception as error:
                return _failed_loop_result(
                    analysis,
                    program,
                    error,
                    best=best,
                    iterations=iterations,
                    history=history,
                    evaluation_count=evaluation_count,
                )
            records.append(
                CandidateRecord(
                    iteration=iteration,
                    layout=layout,
                    validation=validation,
                    fingerprint=fingerprint,
                    parent_id=proposal.parent_id,
                    operator=proposal.operator,
                    operator_params=proposal.operator_params,
                )
            )
            evaluation_count += 1

        if not records:
            if best is None:
                raise RuntimeError("candidate search produced no evaluable candidates")
            return _loop_result(
                analysis,
                program,
                best,
                iterations,
                history,
                "evaluation_budget_exhausted" if skipped_for_budget else "search_exhausted",
                evaluation_count,
            )

        iteration_best = min(records, key=rank_candidate)
        improved = best is None or rank_candidate(iteration_best) < rank_candidate(best)
        if improved:
            best = iteration_best
            history.append(best)
            stagnant_iterations = 0
        else:
            stagnant_iterations += 1
        assert best is not None
        iterations.append(
            IterationRecord(
                iteration=iteration,
                candidates=records,
                best=iteration_best,
                best_so_far=best,
            )
        )

        if best.validation.accepted:
            reason = "accepted"
        elif skipped_for_budget or evaluation_count >= config.evaluation_budget:
            reason = "evaluation_budget_exhausted"
        elif iteration >= config.max_iterations:
            reason = "iteration_budget_exhausted"
        elif stagnant_iterations >= config.stagnation_iterations:
            reason = "stagnated"
        else:
            frontier = select_frontier(records, config.beam_width)
            try:
                pending = refine_proposals(
                    frontier,
                    [record.validation for record in frontier],
                    analysis,
                    program,
                    iteration + 1,
                )
            except Exception as error:
                return _failed_loop_result(
                    analysis,
                    program,
                    error,
                    best=best,
                    iterations=iterations,
                    history=history,
                    evaluation_count=evaluation_count,
                )
            pending = [
                candidate
                for candidate in pending
                if layout_fingerprint(candidate.layout) not in seen
            ]
            if not pending:
                reason = "search_exhausted"
            else:
                continue

        return _loop_result(
            analysis,
            program,
            best,
            iterations,
            history,
            reason,
            evaluation_count,
        )

    raise AssertionError("search loop did not terminate")


def _street_segments(
    mass: MassInput,
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    points = mass.footprint_polygon
    segments = []
    for edge in mass.site_edges:
        if edge.get("kind") != "street" or "edge_index" not in edge:
            continue
        index = int(edge["edge_index"])
        if index < 0 or index >= len(points):
            raise ValueError(f"street edge index {index} is outside footprint edges")
        segment = []
        for point in (points[index], points[(index + 1) % len(points)]):
            if len(point) != 2:
                raise ValueError("street edge points must contain two coordinates")
            normalized = (float(point[0]), float(point[1]))
            if not all(math.isfinite(value) for value in normalized):
                raise ValueError("street edge points must be finite")
            segment.append(normalized)
        segments.append((segment[0], segment[1]))
    return segments


def _loop_result(
    analysis,
    program,
    best,
    iterations,
    history,
    reason,
    evaluation_count,
) -> LoopResult:
    return LoopResult(
        mass=analysis,
        program=program,
        best=best,
        iterations=iterations,
        history=history,
        termination_reason=reason,
        evaluation_count=evaluation_count,
    )


def _failed_loop_result(
    analysis,
    program,
    error: Exception,
    *,
    best=None,
    iterations=None,
    history=None,
    evaluation_count: int = 0,
) -> LoopResult:
    return LoopResult(
        mass=analysis,
        program=program,
        best=best,
        iterations=iterations or [],
        history=history or [],
        termination_reason="failed",
        evaluation_count=evaluation_count,
        error=f"{type(error).__name__}: {error}",
    )
