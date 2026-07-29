from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import replace

from shapely import union_all
from shapely.geometry import LineString, MultiLineString, Polygon, box
from shapely.prepared import prep
from backend.app.modules.generation_loop.operators import (
    generate_initial_proposals,
    layout_fingerprint,
    refine_proposals,
)
from backend.app.modules.generation_loop.selector import (
    canonical_building_topology_signature,
    rank_candidate,
    select_frontier,
)
from backend.app.modules.layout_generator.service import (
    generate_baseline_layout,
    generate_core_aligned_layout,
    generate_rear_center_layout,
    generate_side_mid_layout,
)
from backend.app.modules.layout_generator.orthogonal import (
    generate_orthogonal_office_layout,
)
from backend.app.modules.circulation_planner.contracts import CirculationCandidate
from backend.app.modules.circulation_planner.service import (
    circulation_geometry_fingerprint,
)
from backend.app.modules.core_planner.contracts import CoreCandidate
from backend.app.modules.core_planner.service import core_geometry_fingerprint
from backend.app.modules.basic_design import (
    generate_basic_design,
    generate_room_window,
    generate_shared_structure,
)
from backend.app.modules.basic_design.stair import (
    required_stair_enclosure,
    resolve_floor_height,
)
from backend.app.modules.mass_analyzer.service import analyze_mass
from backend.app.modules.program_prior.service import generate_program_graph
from backend.app.modules.validator.service import validate_layout
from backend.app.modules.area_ledger.service import (
    build_building_area_ledger,
    compute_floor_area_ledger,
)
from backend.app.modules.egress_graph.service import measure_traversable_egress
from backend.app.schemas.area import AreaGeometry, FloorAreaLedger
from backend.app.schemas.egress import (
    FloorEgressGraphResult,
    RoomTravelEvidence,
)
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
    RejectedAlternativeFamilyResult,
)
from backend.app.schemas.layout import LayoutCandidate, OpeningSegment, RoomPolygon
from backend.app.schemas.program import ProgramAdjustment, ProgramGraph
from engine.geometry import (
    bounding_box_aspect_ratio,
    orthogonal_min_width,
    shared_boundary_segments,
)
from engine.geometry.polygon import (
    bounds as polygon_bounds,
    contains_polygon,
    polygon_area,
    polygon_overlap_area,
    union_polygon,
)
from engine.geometry.orthogonal import (
    common_floor_region,
    shared_core_candidates,
)
from engine.geometry.polygonal import (
    common_polygon_region,
    fixed_rectangle_candidates,
    largest_inscribed_axis_aligned_rectangle,
)


_SERVICE_SPACE_TYPES = {
    "pantry",
    "restroom",
    "it_storage",
    "stock",
    "utility",
}
_OCCUPIED_SERVICE_SPACE_TYPES = {"pantry", "restroom"}
_AREA_CLASSIFICATION_RULE = "actual-program-room-classification-v1"


def build_floor_design_evidence(
    *,
    layout: LayoutCandidate,
    program: ProgramGraph,
    boundary: list[tuple[float, float]],
) -> tuple[FloorAreaLedger, FloorEgressGraphResult]:
    """Build conservative area and traversable-egress evidence for one floor."""
    floor_boundary = tuple((float(x), float(y)) for x, y in boundary)
    program_types = {node.node_id: node.space_type for node in program.nodes}
    layout_room_ids = {room.room_id for room in layout.rooms}
    missing_program_reasons = tuple(
        f"missing_program_room:{node_id}"
        for node_id in sorted(program_types.keys() - layout_room_ids)
    )
    classified: dict[str, list[AreaGeometry]] = {
        "core": [],
        "service": [],
        "primary": [],
    }
    unclassified: list[AreaGeometry] = []
    occupied_room_ids: list[str] = []
    for room in sorted(layout.rooms, key=lambda item: item.room_id):
        geometry = AreaGeometry(
            source_id=room.room_id,
            polygon=tuple(room.polygon),
        )
        expected_type = program_types.get(room.room_id)
        if expected_type is None or expected_type != room.space_type:
            unclassified.append(geometry)
            continue
        if room.space_type == "core":
            classified["core"].append(geometry)
        elif room.space_type in _SERVICE_SPACE_TYPES:
            classified["service"].append(geometry)
            if room.space_type in _OCCUPIED_SERVICE_SPACE_TYPES:
                occupied_room_ids.append(room.room_id)
        else:
            classified["primary"].append(geometry)
            occupied_room_ids.append(room.room_id)

    circulation = tuple(
        AreaGeometry(path.room_id, tuple(path.polygon))
        for path in sorted(layout.circulation, key=lambda item: item.room_id)
    )
    remote_stair = (
        (
            AreaGeometry(
                "remote-stair-footprint",
                tuple(layout.remote_stair_footprint),
            ),
        )
        if layout.remote_stair_footprint is not None
        else ()
    )
    area = compute_floor_area_ledger(
        floor_index=layout.floor_index,
        gross=AreaGeometry("floor-boundary", floor_boundary),
        core=tuple(classified["core"]),
        circulation=circulation,
        remote_stair=remote_stair,
        service=tuple(classified["service"]),
        primary=tuple(classified["primary"]),
        unclassified=tuple(unclassified),
        classification_rule=_AREA_CLASSIFICATION_RULE,
    )
    unresolved = (
        *missing_program_reasons,
        *tuple(f"unclassified_room:{geometry.source_id}" for geometry in unclassified),
    )
    if unresolved:
        area = replace(
            area,
            status="not_checked",
            entries=tuple(replace(entry, area_m2=None) for entry in area.entries),
            unresolved_facts=tuple(
                dict.fromkeys((*area.unresolved_facts, *unresolved))
            ),
        )
    if unresolved:
        egress = _not_checked_egress(
            layout.floor_index,
            tuple(occupied_room_ids),
            unresolved,
        )
    elif not occupied_room_ids:
        egress = _not_checked_egress(
            layout.floor_index,
            (),
            ("occupied_room_policy_empty",),
        )
    else:
        egress = measure_traversable_egress(
            layout=layout,
            floor_boundary=floor_boundary,
            occupied_room_ids=tuple(occupied_room_ids),
        )
    return area, egress


def _not_checked_egress(
    floor_index: int,
    room_ids: tuple[str, ...],
    reasons: tuple[str, ...],
) -> FloorEgressGraphResult:
    return FloorEgressGraphResult(
        floor_index=floor_index,
        status="not_checked",
        nodes=(),
        edges=(),
        room_results=tuple(
            RoomTravelEvidence(
                floor_index=floor_index,
                room_id=room_id,
                farthest_point=None,
                nearest_exit_id=None,
                distance_m=None,
                route_node_ids=(),
                route_polyline=(),
                status="not_checked",
                unresolved_facts=reasons,
            )
            for room_id in room_ids
        ),
        governing_room_id=None,
        governing_distance_m=None,
        governing_exit_id=None,
        common_path_distance_m=None,
        common_path_status="not_checked",
        dead_end_distance_m=None,
        dead_end_status="not_checked",
        unresolved_facts=reasons,
    )


def run_generation_loop(
    mass: MassInput,
    floor_index: int,
    use_type: str,
) -> GenerationResult:
    analysis = analyze_mass(mass)
    program = generate_program_graph(
        analysis, floor_index=floor_index, use_type=use_type
    )
    layout = generate_baseline_layout(analysis, program)
    area_ledger, egress_graph = build_floor_design_evidence(
        layout=layout,
        program=program,
        boundary=mass.footprint_polygon,
    )
    validation = validate_layout(
        layout,
        program,
        boundary=mass.footprint_polygon,
        street_segments=_street_segments(mass),
        building_code_context=mass.building_code_context,
        egress_graph=egress_graph,
    )
    return GenerationResult(
        mass=analysis,
        program=program,
        layout=layout,
        validation=validation,
        area_ledger=area_ledger,
        egress_graph=egress_graph,
    )


def run_building_generation(
    mass: MassInput,
    *,
    floor_assignments: Iterable[FloorAssignment] | None = None,
    planner_provenance: PlannerProvenance | None = None,
    program_overrides: Mapping[int, ProgramGraph] | None = None,
    core_override: CoreCandidate | None = None,
    circulation_overrides: Mapping[int, CirculationCandidate] | None = None,
) -> BuildingGenerationResult:
    analysis = analyze_mass(mass)
    has_nonrectangular_floor = any(
        not _is_axis_aligned_rectangle(plate.footprint_polygon, plate.bounds)
        for plate in analysis.floor_plates
    )
    has_nonorthogonal_floor = any(
        not _is_axis_aligned_polygon(plate.footprint_polygon)
        for plate in analysis.floor_plates
    )
    has_structural_override = (
        core_override is not None or circulation_overrides is not None
    )
    uses_floor_plate_geometry = bool(
        mass.floor_footprints
        or has_nonrectangular_floor
        or has_structural_override
    )
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
    floor_analyses = tuple(
        _analysis_for_floor(analysis, floor_index)
        for floor_index in range(1, mass.floors + 1)
    )
    fixed_circulation = _validate_structural_overrides(
        mass,
        core_override=core_override,
        circulation_overrides=circulation_overrides,
    )
    min_x, min_y, max_x, max_y = analysis.bounds
    width = max_x - min_x
    depth = max_y - min_y
    if width < 20.0 or depth < 10.0:
        raise ValueError(
            "concept-basic footprint requires width >= 20.0 m and depth >= 10.0 m"
        )

    overrides = dict(program_overrides or {})
    if any(
        not isinstance(floor_index, int)
        or floor_index < 1
        or floor_index > mass.floors
        for floor_index in overrides
    ):
        raise ValueError("program override floor indexes must be inside the building")
    for assignment in assignments:
        override = overrides.get(assignment.floor_index)
        if override is not None and (
            not isinstance(override, ProgramGraph)
            or override.project_id != mass.project_id
            or override.floor_index != assignment.floor_index
            or override.use_type != assignment.use_type
        ):
            raise ValueError(
                "program override identity must match project, floor, and use"
            )
    programs = [
        overrides.get(assignment.floor_index)
        or generate_program_graph(
            floor_analysis,
            floor_index=assignment.floor_index,
            use_type=assignment.use_type,
        )
        for assignment, floor_analysis in zip(assignments, floor_analyses)
    ]
    shared_core_target = max(
        float(
            next(
                node.target_area for node in program.nodes if node.space_type == "core"
            )
        )
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
    shared_core: list[tuple[float, float]] | tuple[tuple[float, float], ...]
    shared_remote_stair = None
    polygonal_layout_boundary = None
    if uses_floor_plate_geometry:
        floor_boundaries = tuple(
            plate.footprint_polygon for plate in analysis.floor_plates
        )
        common_boundary = (
            common_polygon_region(floor_boundaries)
            if has_nonorthogonal_floor
            else common_floor_region(floor_boundaries)
        )
        resolved_height, _ = resolve_floor_height(
            (
                mass.building_code_context.floor_to_floor_height_m
                if mass.building_code_context is not None
                else None
            )
        )
        stair_short_side, stair_long_side = required_stair_enclosure(resolved_height)
        minimum_depth = min(
            plate.bounds[3] - plate.bounds[1] for plate in analysis.floor_plates
        )
        core_depth = max(
            stair_long_side + 0.25,
            5.2,
            minimum_depth * 0.55,
        )
        if core_override is not None:
            shared_core = core_override.polygon
        else:
            core_width = max(7.6, shared_core_target / core_depth)
            core_candidates = (
                fixed_rectangle_candidates
                if has_nonorthogonal_floor
                else shared_core_candidates
            )
            candidates = [
                candidate
                for candidate in core_candidates(
                    floor_boundaries,
                    width=core_width,
                    depth=core_depth,
                )
                if (
                    polygon_bounds(candidate)[2] - polygon_bounds(candidate)[0]
                    >= core_width - 1e-7
                    and polygon_bounds(candidate)[3] - polygon_bounds(candidate)[1]
                    >= core_depth - 1e-7
                )
            ]
            if not candidates:
                raise ValueError(
                    "common floor region cannot fit the shared vertical core"
                )
            if has_nonorthogonal_floor:
                shared_core, shared_remote_stair, polygonal_layout_boundary = (
                    _select_polygonal_core_and_stair(
                        candidates,
                        floor_boundaries=floor_boundaries,
                        common_shape=Polygon(common_boundary),
                        stair_dimensions=(
                            (stair_short_side, stair_long_side),
                            (stair_long_side, stair_short_side),
                        ),
                    )
                )
            else:
                shared_core = max(
                    candidates,
                    key=lambda candidate: (
                        polygon_bounds(candidate)[3],
                        polygon_bounds(candidate)[2],
                        polygon_bounds(candidate),
                    ),
                )
        service_x, _, service_max_x, _ = polygon_bounds(shared_core)
        service_band_width = service_max_x - service_x
        core_height = polygon_bounds(shared_core)[3] - polygon_bounds(shared_core)[1]
        shared_core_target = polygon_area(shared_core)
        if (
            core_override is None
            and has_nonrectangular_floor
            and not has_nonorthogonal_floor
        ):
            core_min_x, core_min_y, core_max_x, _ = polygon_bounds(shared_core)
            corridor_bottom = core_min_y - 1.2
            common_shape = Polygon(common_boundary)
            stair_candidates = _aligned_remote_stair_candidates(
                common_shape,
                corridor_bottom=corridor_bottom,
                dimensions=(
                    (stair_short_side, stair_long_side),
                    (stair_long_side, stair_short_side),
                ),
                excluded_polygon=shared_core,
            )
            if has_nonorthogonal_floor:
                feasible_stairs = []
                for candidate in stair_candidates:
                    try:
                        for boundary in floor_boundaries:
                            largest_inscribed_axis_aligned_rectangle(
                                boundary,
                                required_polygons=(
                                    shared_core,
                                    candidate,
                                ),
                            )
                    except ValueError:
                        continue
                    feasible_stairs.append(candidate)
                stair_candidates = feasible_stairs
            if not stair_candidates:
                raise ValueError(
                    "common floor region cannot fit an aligned remote stair"
                )
            core_center = (
                (core_min_x + core_max_x) / 2,
                (core_min_y + polygon_bounds(shared_core)[3]) / 2,
            )
            shared_remote_stair = max(
                stair_candidates,
                key=lambda candidate: (
                    math.dist(
                        Polygon(candidate).centroid.coords[0],
                        core_center,
                    ),
                    polygon_bounds(candidate),
                ),
            )
    elif use_role_layout:
        streets = _street_segments(mass)
        if (
            any(program.use_type == "neighborhood_commercial" for program in programs)
            and len(streets) != 1
        ):
            raise ValueError(
                "neighborhood commercial generation requires exactly one street edge"
            )
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
        _normalize_program_core(program, shared_core_target) for program in programs
    ]
    if has_nonrectangular_floor:
        programs = [
            _zone_orthogonal_office_program(
                program,
                expand_focus=not has_nonorthogonal_floor,
            )
            for program in programs
        ]
    programs = [
        (
            _compress_compact_program(
                program,
                primary_factor=0.8,
                service_factor=0.6,
                upper_service_factor=(
                    0.5
                    if floor_analysis.bounds[2] - floor_analysis.bounds[0] <= 24.0
                    and floor_analysis.bounds[3] - floor_analysis.bounds[1] <= 12.0
                    else None
                ),
            )
            if (
                floor_analysis.bounds[2] - floor_analysis.bounds[0] <= 24.0
                or floor_analysis.bounds[3] - floor_analysis.bounds[1] <= 10.0
            )
            else program
        )
        for program, floor_analysis in zip(programs, floor_analyses)
    ]
    programs = [
        (
            program
            if has_nonrectangular_floor
            else _fit_rear_primary_program(
                program,
                floor_analysis,
                floor_to_floor_height_m=(
                    mass.building_code_context.floor_to_floor_height_m
                    if mass.building_code_context is not None
                    else None
                ),
                core_polygon=(shared_core if uses_floor_plate_geometry else None),
            )
        )
        for program, floor_analysis in zip(programs, floor_analyses)
    ]
    core_top = float(_clean_area(min_y + core_height))
    if not uses_floor_plate_geometry:
        shared_core = [
            (service_x, min_y),
            (max_x, min_y),
            (max_x, core_top),
            (service_x, core_top),
        ]

    layouts = []
    for program, floor_analysis in zip(programs, floor_analyses):
        circulation_candidate = fixed_circulation.get(program.floor_index)
        if has_nonrectangular_floor or has_structural_override:
            layout_boundary = floor_analysis.boundary_for_floor(
                program.floor_index
            )
            if has_nonorthogonal_floor and circulation_candidate is None:
                layout_boundary = polygonal_layout_boundary
            layout = generate_orthogonal_office_layout(
                layout_boundary,
                program,
                core_polygon=shared_core,
                remote_stair_polygon=(
                    None if circulation_candidate is not None else shared_remote_stair
                ),
                circulation_candidate=circulation_candidate,
                frontage_segments=(
                    _street_segments_for_boundary(
                        mass,
                        floor_analysis.boundary_for_floor(
                            program.floor_index
                        ),
                    )
                    if program.use_type == "neighborhood_commercial"
                    else ()
                ),
                respect_program_order=program.source.startswith(
                    "local_qwen_topology:"
                ),
            )
            if core_override is not None:
                layout = replace(
                    layout,
                    rooms=[
                        (
                            replace(room, polygon=core_override.polygon)
                            if room.space_type == "core"
                            else room
                        )
                        for room in layout.rooms
                    ],
                )
        elif use_role_layout:
            layout = generate_rear_center_layout(
                floor_analysis,
                program,
                core_position="rear_right",
                floor_to_floor_height_m=(
                    mass.building_code_context.floor_to_floor_height_m
                    if mass.building_code_context is not None
                    else None
                ),
                core_polygon=(shared_core if uses_floor_plate_geometry else None),
                respect_program_order=program.source.startswith(
                    "local_qwen_topology:"
                ),
            )
        else:
            layout = generate_core_aligned_layout(
                floor_analysis,
                program,
                core_polygon=shared_core,
                service_band_width=service_band_width,
                room_scale=room_scale,
            )
        layouts.append(layout)
    if core_override is not None and any(
        next(room for room in layout.rooms if room.space_type == "core").polygon
        != core_override.polygon
        for layout in layouts
    ):
        raise ValueError("generated floors must preserve shared core override equality")

    if has_nonrectangular_floor or has_structural_override:
        programs = [
            _fit_orthogonal_program_to_layout(program, layout)
            for program, layout in zip(programs, layouts)
        ]

    shared_structure = generate_shared_structure(
        list(
            common_boundary
            if uses_floor_plate_geometry
            else mass.footprint_polygon
        ),
        tuple(layouts),
        floor_to_floor_height_m=(
            mass.building_code_context.floor_to_floor_height_m
            if mass.building_code_context is not None
            else None
        ),
    )
    floor_results = []
    for floor_analysis, program, layout in zip(
        floor_analyses,
        programs,
        layouts,
    ):
        floor_plate = analysis.floor_plate(program.floor_index)
        floor_boundary = floor_plate.footprint_polygon
        floor_streets = _street_segments_for_boundary(
            mass,
            floor_boundary,
        )
        layout = replace(
            layout,
            basic_design=generate_basic_design(
                layout,
                boundary=floor_boundary,
                street_segments=floor_streets,
                shared_structure=shared_structure,
                floor_to_floor_height_m=(
                    mass.building_code_context.floor_to_floor_height_m
                    if mass.building_code_context is not None
                    else None
                ),
            ),
        )
        area_ledger, egress_graph = build_floor_design_evidence(
            layout=layout,
            program=program,
            boundary=floor_boundary,
        )
        validation = validate_layout(
            layout,
            program,
            boundary=floor_boundary,
            street_segments=floor_streets,
            require_openings=True,
            min_door_width=0.8,
            min_circulation_width=1.2,
            require_basic_design=True,
            building_code_context=mass.building_code_context,
            egress_graph=egress_graph,
        )
        floor_results.append(
            GenerationResult(
                mass=floor_analysis,
                program=program,
                layout=layout,
                validation=validation,
                area_ledger=area_ledger,
                egress_graph=egress_graph,
                floor_boundary=floor_boundary,
                floor_boundary_source=floor_plate.source,
            )
        )

    use_type_areas: dict[str, float] = {}
    for assignment in assignments:
        use_type_areas[assignment.use_type] = use_type_areas.get(
            assignment.use_type, 0.0
        ) + float(analysis.area_for_floor(assignment.floor_index))
    core_polygons = [
        next(room.polygon for room in floor.layout.rooms if room.space_type == "core")
        for floor in floor_results
    ]
    vertical_core_aligned = all(
        polygon == core_polygons[0] for polygon in core_polygons[1:]
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
        area_ledger=build_building_area_ledger(
            tuple(
                floor.area_ledger
                for floor in floor_results
                if floor.area_ledger is not None
            )
        ),
    )


def _validate_structural_overrides(
    mass: MassInput,
    *,
    core_override: CoreCandidate | None,
    circulation_overrides: Mapping[int, CirculationCandidate] | None,
) -> dict[int, CirculationCandidate]:
    if core_override is not None and not isinstance(core_override, CoreCandidate):
        raise TypeError("core override must be an immutable CoreCandidate")
    if circulation_overrides is None:
        supplied: dict[int, CirculationCandidate] = {}
    elif not isinstance(circulation_overrides, Mapping):
        raise TypeError("circulation overrides must be a floor mapping")
    else:
        supplied = dict(circulation_overrides)
        if not supplied:
            raise ValueError("circulation overrides must not be empty")
    if supplied and core_override is None:
        raise ValueError("circulation override identity requires a core override")

    expected_floor_keys = set(range(1, mass.floors + 1))
    if supplied and set(supplied) != expected_floor_keys:
        raise ValueError("circulation overrides must cover every floor exactly")
    if any(
        not isinstance(floor_index, int) or isinstance(floor_index, bool)
        for floor_index in supplied
    ):
        raise ValueError("circulation override floor keys must be integers")
    if any(
        not isinstance(candidate, CirculationCandidate)
        for candidate in supplied.values()
    ):
        raise TypeError(
            "circulation overrides must contain immutable CirculationCandidate records"
        )

    if core_override is None:
        return supplied
    expected_contained_indices = tuple(range(mass.floors))
    if (
        core_geometry_fingerprint(core_override.polygon)
        != core_override.fingerprint
    ):
        raise ValueError("core override fingerprint does not match its geometry")
    if core_override.contained_floor_indices != expected_contained_indices:
        raise ValueError("core override contained floor identity must match the building")
    core_shape = Polygon(core_override.polygon)
    if (
        not core_shape.is_valid
        or core_shape.area <= 0
        or any(
            not Polygon(mass.footprint_for_floor(floor_index)).covers(core_shape)
            for floor_index in expected_floor_keys
        )
    ):
        raise ValueError("core override must be contained by every floor")

    for floor_index, candidate in supplied.items():
        if candidate.core_fingerprint is None:
            raise ValueError(
                "circulation override requires a core fingerprint binding"
            )
        if candidate.core_fingerprint != core_override.fingerprint:
            raise ValueError(
                "circulation override core fingerprint must match the core override"
            )
        expected_fingerprint = circulation_geometry_fingerprint(
            strategy=candidate.strategy,
            core_fingerprint=candidate.core_fingerprint,
            polygons=candidate.polygons,
            remote_stair=candidate.remote_stair_polygon,
        )
        if candidate.fingerprint != expected_fingerprint:
            raise ValueError(
                "circulation override fingerprint does not match its geometry"
            )
        if candidate.strategy != core_override.strategy:
            raise ValueError(
                "circulation override strategy must match the core override"
            )
        if not all(
            (
                candidate.entrance_connected,
                candidate.core_connected,
                candidate.stair_connected,
            )
        ):
            raise ValueError("circulation override must record connected topology")
        floor_shape = Polygon(mass.footprint_for_floor(floor_index))
        corridor_shapes = tuple(Polygon(polygon) for polygon in candidate.polygons)
        remote_stair = Polygon(candidate.remote_stair_polygon)
        circulation_shapes = (*corridor_shapes, remote_stair)
        if (
            not candidate.polygons
            or any(
                not shape.is_valid
                or shape.area <= 0
                or not floor_shape.covers(shape)
                for shape in circulation_shapes
            )
        ):
            raise ValueError(
                f"circulation override for floor {floor_index} must be contained"
            )
        corridor = union_all(corridor_shapes)
        access_segments = _structural_access_segments(
            mass,
            mass.footprint_for_floor(floor_index),
        )
        entrance_connected = any(
            corridor.boundary.intersection(LineString(segment)).length + 1e-8
            >= 0.9
            for segment in access_segments
        )
        core_connected = (
            corridor.boundary.intersection(core_shape.boundary).length + 1e-8
            >= 0.9
        )
        stair_connected = (
            corridor.boundary.intersection(remote_stair.boundary).length + 1e-8
            >= 0.9
        )
        if (
            corridor.geom_type != "Polygon"
            or corridor.is_empty
            or not entrance_connected
            or not core_connected
            or not stair_connected
            or corridor.intersection(core_shape).area > 1e-8
            or remote_stair.intersects(core_shape)
            or corridor.intersection(remote_stair).area > 1e-8
        ):
            raise ValueError(
                f"circulation override for floor {floor_index} "
                "must have actual connected topology"
            )
    return supplied


def _structural_access_segments(
    mass: MassInput,
    boundary: tuple[tuple[float, float], ...],
) -> tuple[tuple[tuple[float, float], tuple[float, float]], ...]:
    edge_indices = {
        int(record["edge_index"])
        for record in mass.site_edges
        if "edge_index" in record and record.get("kind") == "street"
    }
    edge_indices.update(
        int(record["edge_index"])
        for record in mass.access_candidates
        if "edge_index" in record
    )
    return tuple(
        (boundary[index], boundary[(index + 1) % len(boundary)])
        for index in sorted(edge_indices)
        if 0 <= index < len(boundary)
    )


_ALTERNATIVE_STRATEGIES = (
    ("alternative-a", "rear-right-core-single-spine", "rear-right"),
    ("alternative-b", "rear-center-core-dual-bay", "rear-center"),
    ("alternative-c", "side-mid-core-longitudinal-spine", "side-mid"),
)


def run_building_alternatives(
    mass: MassInput,
    *,
    floor_assignments: Iterable[FloorAssignment] | None = None,
    planner_provenance: PlannerProvenance | None = None,
) -> BuildingAlternativesResult:
    """Generate ranked, geometrically distinct concept-basic building options."""
    try:
        baseline = run_building_generation(
            mass,
            floor_assignments=floor_assignments,
            planner_provenance=planner_provenance,
        )
    except ValueError as error:
        return BuildingAlternativesResult(
            mass=analyze_mass(mass),
            alternatives=(),
            comparisons=(),
            rejected_families=(
                RejectedAlternativeFamilyResult(
                    family="conservative_redundant_two_stair",
                    reasons=(str(error),),
                ),
            ),
        )
    conservative = []
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
                    floor_to_floor_height_m=(
                        mass.building_code_context.floor_to_floor_height_m
                        if mass.building_code_context is not None
                        else None
                    ),
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
            layout_fingerprint(floor.layout) for floor in building.floor_results
        )
        mean_score = sum(
            floor.validation.total_score for floor in building.floor_results
        ) / len(building.floor_results)
        geometry = _alternative_geometry_evidence(building)
        conservative.append(
            BuildingAlternativeResult(
                alternative_id=alternative_id,
                strategy=f"conservative_redundant_two_stair/{strategy}",
                building=building,
                score=round(mean_score, 6),
                rank=0,
                fingerprints=fingerprints,
                **geometry,
            )
        )
    conservative = _deduplicate_family_topologies(conservative)
    alternatives = list(conservative)
    floor_required_counts = tuple(
        (
            floor.program.floor_index,
            (
                floor.validation.regulatory_screening.screened_required_direct_stair_count
                if floor.validation.regulatory_screening is not None
                else None
            ),
        )
        for floor in baseline.floor_results
    )
    if floor_required_counts and all(count == 1 for _, count in floor_required_counts):
        one_stair = []
        for conservative_alternative in conservative:
            building = _screened_one_stair_building(
                conservative_alternative.building,
                mass=mass,
            )
            geometry = _alternative_geometry_evidence(building)
            one_stair.append(
                BuildingAlternativeResult(
                    alternative_id=(
                        f"one-stair-{conservative_alternative.alternative_id}"
                    ),
                    strategy=(
                        "screened_minimum_one_stair/"
                        + conservative_alternative.strategy.split("/", 1)[1]
                    ),
                    building=building,
                    score=round(
                        sum(
                            floor.validation.total_score
                            for floor in building.floor_results
                        )
                        / len(building.floor_results),
                        6,
                    ),
                    rank=0,
                    fingerprints=tuple(
                        layout_fingerprint(floor.layout)
                        for floor in building.floor_results
                    ),
                    **geometry,
                )
            )
        alternatives.extend(_deduplicate_family_topologies(one_stair))
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
        for second in ranked[index + 1 :]:
            core_distance = math.dist(first.core_centroid, second.core_centroid)
            normalized_distance = core_distance / diagonal
            circulation_different = (
                first.circulation_graph_signature != second.circulation_graph_signature
                or first.circulation_bounds != second.circulation_bounds
            )
            tenant_different = (
                first.tenant_assignment_signature != second.tenant_assignment_signature
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
        point for path in layout.circulation for point in path.polygon
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
        room.room_id for room in layout.rooms if room.room_id.startswith("sales_")
    }
    tenant_entrances = tuple(
        sorted(
            f"{line.host_id}:{line.line_id}"
            for line in entrance_lines
            if line.host_id in tenant_room_ids
        )
    )
    core_public_entrance = any(
        line.line_id == "core-public-entrance" for line in entrance_lines
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
    return {
        "core_centroid": core_centroid,
        "circulation_orientation": orientation,
        "circulation_bounds": circulation_bounds,
        "circulation_graph_signature": graph,
        "tenant_assignment_signature": tenants,
        "tenant_count": len(tenant_room_ids),
        "tenant_entrance_assignments": tenant_entrances,
        "core_public_entrance": core_public_entrance,
        "design_family_signature": canonical_building_topology_signature(
            building.floor_results
        ),
    }


def _deduplicate_family_topologies(
    alternatives: list[BuildingAlternativeResult],
) -> list[BuildingAlternativeResult]:
    distinct = []
    seen: set[str] = set()
    for alternative in alternatives:
        signature = alternative.design_family_signature
        if signature in seen:
            continue
        seen.add(signature)
        distinct.append(alternative)
    return distinct


def _screened_one_stair_building(
    building: BuildingGenerationResult,
    *,
    mass: MassInput,
) -> BuildingGenerationResult:
    floors = []
    streets = _street_segments(mass)
    for floor in building.floor_results:
        layout = floor.layout
        basic_design = layout.basic_design
        if basic_design is None:
            raise ValueError(
                "screened one-stair family requires generated basic design"
            )
        removed_stair_ids = {
            element.element_id
            for element in basic_design.elements
            if element.kind == "stair" and element.host_id == "floor"
        }
        if len(removed_stair_ids) != 1:
            raise ValueError(
                "screened one-stair family requires exactly one removable remote stair"
            )
        removed_exit_ids = {
            line.line_id
            for line in basic_design.lines
            if (line.kind == "protected_exit" and line.target_id in removed_stair_ids)
        }
        features = replace(
            basic_design,
            elements=tuple(
                element
                for element in basic_design.elements
                if element.element_id not in removed_stair_ids
            ),
            lines=tuple(
                line
                for line in basic_design.lines
                if line.target_id not in removed_stair_ids
                and line.line_id not in removed_exit_ids
                and line.target_id not in removed_exit_ids
            ),
        )
        reclaimed_layout, reclaimed_program, reclaimed_room_id = (
            _reclaim_remote_stair_reserve(
                layout,
                floor.program,
                boundary=mass.footprint_polygon,
            )
        )
        if reclaimed_room_id is not None:
            reclaimed_room = next(
                room
                for room in reclaimed_layout.rooms
                if room.room_id == reclaimed_room_id
            )
            reclaimed_window = generate_room_window(
                reclaimed_room,
                boundary=mass.footprint_polygon,
            )
            features = replace(
                features,
                lines=(
                    *tuple(
                        line
                        for line in features.lines
                        if not (
                            line.kind == "window" and line.host_id == reclaimed_room_id
                        )
                    ),
                    *((reclaimed_window,) if reclaimed_window is not None else ()),
                ),
            )
        one_stair_layout = replace(
            reclaimed_layout,
            candidate_id=f"{layout.candidate_id}-screened-one-stair",
            basic_design=features,
            remote_stair_footprint=None,
        )
        area_ledger, egress_graph = build_floor_design_evidence(
            layout=one_stair_layout,
            program=reclaimed_program,
            boundary=mass.footprint_polygon,
        )
        floors.append(
            replace(
                floor,
                program=reclaimed_program,
                layout=one_stair_layout,
                validation=validate_layout(
                    one_stair_layout,
                    reclaimed_program,
                    boundary=mass.footprint_polygon,
                    street_segments=streets,
                    require_openings=True,
                    min_door_width=0.8,
                    min_circulation_width=1.2,
                    require_basic_design=True,
                    required_protected_exit_count=1,
                    building_code_context=mass.building_code_context,
                    egress_graph=egress_graph,
                ),
                area_ledger=area_ledger,
                egress_graph=egress_graph,
            )
        )
    values = tuple(floors)
    vertical_basic, vertical_structure = _vertical_basic_design_alignment(values)
    return replace(
        building,
        floor_results=values,
        vertical_core_aligned=True,
        vertical_basic_design_aligned=vertical_basic,
        vertical_structure_aligned=vertical_structure,
        area_ledger=build_building_area_ledger(
            tuple(
                floor.area_ledger for floor in values if floor.area_ledger is not None
            )
        ),
    )


def _reclaim_remote_stair_reserve(
    layout: LayoutCandidate,
    program: ProgramGraph,
    *,
    boundary: list[tuple[float, float]],
) -> tuple[LayoutCandidate, ProgramGraph, str | None]:
    reserve = layout.remote_stair_footprint
    if reserve is None:
        raise ValueError("one-stair reclamation requires a remote stair reserve")
    room_candidates = []
    program_by_id = {node.node_id: node for node in program.nodes}
    for room in layout.rooms:
        if room.space_type == "core" or room.room_id not in program_by_id:
            continue
        shared_length = sum(
            math.dist(*segment)
            for segment in shared_boundary_segments(
                room.polygon,
                reserve,
            )
        )
        if shared_length > 1e-9:
            room_candidates.append((shared_length, room))
    for _, room in sorted(
        room_candidates,
        key=lambda item: (-item[0], item[1].room_id),
    ):
        node = program_by_id[room.room_id]
        for reclaimed in _room_reclamation_candidates(room, reserve):
            if not _valid_reclaimed_room(
                reclaimed,
                room=room,
                layout=layout,
                boundary=boundary,
                min_width=node.min_width,
                max_aspect_ratio=node.max_aspect_ratio,
            ):
                continue
            reclaimed_area = polygon_area(reclaimed)
            rooms = [
                (
                    replace(candidate, polygon=list(reclaimed))
                    if candidate.room_id == room.room_id
                    else candidate
                )
                for candidate in layout.rooms
            ]
            nodes = [
                (
                    replace(
                        candidate,
                        target_area=_clean_area(reclaimed_area),
                        min_area=_clean_area(reclaimed_area * 0.85),
                        max_area=_clean_area(reclaimed_area * 1.15),
                    )
                    if candidate.node_id == room.room_id
                    else candidate
                )
                for candidate in program.nodes
            ]
            adjusted = _with_program_adjustment(
                program,
                nodes,
                reason=(f"one_stair_remote_reserve_reclaimed:{room.room_id}"),
                source=(f"{program.source}:one_stair_remote_reserve_reclaimed"),
            )
            return replace(layout, rooms=rooms), adjusted, room.room_id

    circulation_candidates = []
    for path in layout.circulation:
        shared_length = sum(
            math.dist(*segment)
            for segment in shared_boundary_segments(
                path.polygon,
                reserve,
            )
        )
        if shared_length > 1e-9:
            circulation_candidates.append((shared_length, path))
    if not circulation_candidates:
        raise ValueError("remote stair reserve has no valid adjacent reclamation space")
    _, target = min(
        circulation_candidates,
        key=lambda item: (-item[0], item[1].room_id),
    )
    merged = union_polygon((target.polygon, reserve))
    if not math.isclose(
        polygon_area(merged),
        polygon_area(target.polygon) + polygon_area(reserve),
        abs_tol=1e-7,
    ):
        raise ValueError("remote stair reserve must not overlap reclaimed circulation")
    return (
        replace(
            layout,
            circulation=[
                (
                    replace(path, polygon=list(merged))
                    if path.room_id == target.room_id
                    else path
                )
                for path in layout.circulation
            ],
        ),
        program,
        None,
    )


def _room_reclamation_candidates(
    room: RoomPolygon,
    reserve: tuple[tuple[float, float], ...],
) -> tuple[tuple[tuple[float, float], ...], ...]:
    min_x, min_y, max_x, max_y = polygon_bounds((*room.polygon, *reserve))
    rectangle = (
        (min_x, min_y),
        (max_x, min_y),
        (max_x, max_y),
        (min_x, max_y),
    )
    exact_union = union_polygon((room.polygon, reserve))
    return tuple(dict.fromkeys((rectangle, exact_union)))


def _valid_reclaimed_room(
    reclaimed: tuple[tuple[float, float], ...],
    *,
    room: RoomPolygon,
    layout: LayoutCandidate,
    boundary: list[tuple[float, float]],
    min_width: float | None,
    max_aspect_ratio: float | None,
) -> bool:
    if not contains_polygon(boundary, reclaimed):
        return False
    if min_width is not None and (
        orthogonal_min_width(reclaimed) + 1e-9 < float(min_width)
    ):
        return False
    if max_aspect_ratio is not None and (
        bounding_box_aspect_ratio(reclaimed) - 1e-9 > float(max_aspect_ratio)
    ):
        return False
    obstacles = [
        candidate.polygon
        for candidate in layout.rooms
        if candidate.room_id != room.room_id
    ] + [path.polygon for path in layout.circulation]
    return all(
        polygon_overlap_area(reclaimed, obstacle) <= 1e-9 for obstacle in obstacles
    )


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
        floor_to_floor_height_m=(
            mass.building_code_context.floor_to_floor_height_m
            if mass.building_code_context is not None
            else None
        ),
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
                floor_to_floor_height_m=(
                    mass.building_code_context.floor_to_floor_height_m
                    if mass.building_code_context is not None
                    else None
                ),
            ),
        )
        area_ledger, egress_graph = build_floor_design_evidence(
            layout=layout,
            program=floor.program,
            boundary=mass.footprint_polygon,
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
            building_code_context=mass.building_code_context,
            egress_graph=egress_graph,
        )
        floor_results.append(
            replace(
                floor,
                layout=layout,
                validation=validation,
                area_ledger=area_ledger,
                egress_graph=egress_graph,
            )
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
        area_ledger=build_building_area_ledger(
            tuple(
                floor.area_ledger for floor in values if floor.area_ledger is not None
            )
        ),
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
                        _clean_area(float(node.min_width) * 0.92)
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
        generator=lambda analysis, program: generate_rear_center_layout(
            analysis,
            program,
            floor_to_floor_height_m=(
                mass.building_code_context.floor_to_floor_height_m
                if mass.building_code_context is not None
                else None
            ),
        ),
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
    stair_height, _ = resolve_floor_height(
        mass.building_code_context.floor_to_floor_height_m
        if mass.building_code_context is not None
        else None
    )
    _, stair_long_side = required_stair_enclosure(stair_height)
    for floor in baseline.floor_results:
        core = next(node for node in floor.program.nodes if node.space_type == "core")
        core_height = max(7.2, depth * 0.6)
        core_width = max(
            float(core.target_area) / core_height,
            stair_long_side + 0.25,
        )
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
        cross_bottoms.append(min_y + float(primary.target_area) / primary_width)
        service_nodes = [
            node
            for node in floor.program.nodes
            if node.space_type not in {"core", "sales", "open_work"}
        ]
        available_width = max(branch_left - min_x - stair_long_side, 1.0)
        service_height = max(
            2.4,
            sum(float(node.target_area) for node in service_nodes) / available_width,
        )
        while (
            sum(
                max(
                    float(node.target_area) / service_height,
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
            floor_to_floor_height_m=(
                mass.building_code_context.floor_to_floor_height_m
                if mass.building_code_context is not None
                else None
            ),
        ),
    )


def _generate_positioned_building(
    baseline: BuildingGenerationResult,
    *,
    mass: MassInput,
    generator,
) -> BuildingGenerationResult:
    layouts = tuple(
        generator(baseline.mass, floor.program) for floor in baseline.floor_results
    )
    shared_structure = generate_shared_structure(
        mass.footprint_polygon,
        layouts,
        floor_to_floor_height_m=(
            mass.building_code_context.floor_to_floor_height_m
            if mass.building_code_context is not None
            else None
        ),
    )
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
                floor_to_floor_height_m=(
                    mass.building_code_context.floor_to_floor_height_m
                    if mass.building_code_context is not None
                    else None
                ),
            ),
        )
        area_ledger, egress_graph = build_floor_design_evidence(
            layout=layout,
            program=floor.program,
            boundary=mass.footprint_polygon,
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
                    building_code_context=mass.building_code_context,
                    egress_graph=egress_graph,
                ),
                area_ledger=area_ledger,
                egress_graph=egress_graph,
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
        area_ledger=build_building_area_ledger(
            tuple(
                floor.area_ledger for floor in values if floor.area_ledger is not None
            )
        ),
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
                        element.stair_geometry,
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
        all(
            signature == vertical_signatures[0] for signature in vertical_signatures[1:]
        ),
        all(
            signature == structure_signatures[0]
            for signature in structure_signatures[1:]
        ),
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
    counts = {use_type: math.floor(raw_counts[use_type]) for use_type in use_order}
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
        raise ValueError("floor assignments must contain every floor exactly once")
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
        source=f"{program.source}:building_aligned_prior",
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
            upper_service_factor is not None and node.space_type in upper_service_roles
        ):
            factor = upper_service_factor
        else:
            factor = service_factor
        target = max(
            float(node.target_area) * factor,
            (float(node.min_width or 0) ** 2) * 1.01,
        )
        nodes.append(
            replace(
                node,
                target_area=_clean_area(target),
                min_area=_clean_area(target * 0.85),
                max_area=_clean_area(target * 1.15),
                min_width=(
                    max(1.1, float(node.min_width) * 0.5)
                    if node.min_width is not None and node.space_type != "core"
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
        source=f"{program.source}:compact_building_aligned_prior",
    )


def _fit_rear_primary_program(
    program,
    analysis: MassAnalysis,
    *,
    floor_to_floor_height_m: float | None,
    core_polygon: tuple[tuple[float, float], ...]
    | list[tuple[float, float]]
    | None = None,
):
    min_x, min_y, max_x, max_y = analysis.bounds
    depth = max_y - min_y
    resolved_height, _ = resolve_floor_height(floor_to_floor_height_m)
    _, stair_long_side = required_stair_enclosure(resolved_height)
    if core_polygon is None:
        rear_height = max(stair_long_side + 0.25, 5.2, depth * 0.5)
        front_depth = depth - rear_height - 1.2
        fixed_core_width = None
    else:
        core_bounds = polygon_bounds(core_polygon)
        rear_height = core_bounds[3] - core_bounds[1]
        front_depth = core_bounds[1] - min_y - 1.2
        fixed_core_width = core_bounds[2] - core_bounds[0]
    capacity = (max_x - min_x - 1.2) * front_depth
    core = next(node for node in program.nodes if node.space_type == "core")
    core_width = (
        fixed_core_width
        if fixed_core_width is not None
        else max(7.0, float(core.target_area) / rear_height)
    )
    service_nodes = [
        node
        for node in program.nodes
        if node.space_type not in {"core", "sales", "open_work"}
    ]
    service_width_capacity = max(
        0.0,
        max_x - min_x - core_width - stair_long_side,
    )
    service_width_demand = sum(
        max(
            float(node.target_area) / rear_height,
            math.sqrt(
                float(node.target_area) / float(node.max_aspect_ratio or math.inf)
            )
            * 1.000001,
            float(node.min_width or 0),
            1.1,
        )
        for node in service_nodes
    )
    if service_width_demand > service_width_capacity and service_width_capacity > 0:
        minimum_width_demand = sum(
            max(float(node.min_width or 0), 1.1) for node in service_nodes
        )
        if minimum_width_demand > service_width_capacity + 1e-7:
            raise ValueError("rear service minimum widths exceed floor plate")
        low, high = 0.0, 1.0
        for _ in range(50):
            scale = (low + high) / 2
            scaled_width = sum(
                max(
                    float(node.target_area) * scale / rear_height,
                    math.sqrt(
                        float(node.target_area)
                        * scale
                        / float(node.max_aspect_ratio or math.inf)
                    )
                    * 1.000001,
                    float(node.min_width or 0),
                    1.1,
                )
                for node in service_nodes
            )
            if scaled_width <= service_width_capacity:
                low = scale
            else:
                high = scale
        scale = low
        adjusted_nodes = [
            (
                replace(
                    node,
                    target_area=_clean_area(float(node.target_area) * scale),
                    min_area=_clean_area(float(node.target_area) * scale * 0.85),
                    max_area=_clean_area(float(node.target_area) * scale * 1.15),
                )
                if node in service_nodes
                else node
            )
            for node in program.nodes
        ]
        program = _with_program_adjustment(
            program,
            adjusted_nodes,
            reason="rear_service_residual_fit",
            source=f"{program.source}:rear_service_residual_fit",
        )
        core = next(node for node in program.nodes if node.space_type == "core")
    actual_core_area = core_width * rear_height
    fitted_core_target = (
        actual_core_area
        if (
            actual_core_area < float(core.min_area or 0)
            or actual_core_area > float(core.max_area or math.inf)
        )
        else float(core.target_area)
    )
    if program.use_type == "neighborhood_commercial":
        tenant_actual = ((max_x - min_x - 1.2) / 2) * front_depth
        tenant_target = tenant_actual
        nodes = [
            (
                replace(
                    node,
                    target_area=_clean_area(tenant_target),
                    min_area=_clean_area(tenant_target * 0.85),
                    max_area=_clean_area(tenant_target * 1.15),
                    max_aspect_ratio=max(6.5, float(node.max_aspect_ratio or 1.0)),
                )
                if node.space_type == "sales"
                else replace(
                    node,
                    max_aspect_ratio=max(6.5, float(node.max_aspect_ratio or 1.0)),
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
    fitted_target = min(float(primary.target_area), capacity * 0.999)
    nodes = [
        (
            replace(
                node,
                target_area=_clean_area(fitted_target),
                min_area=_clean_area(fitted_target * 0.85),
                max_area=_clean_area(fitted_target * 1.15),
                min_width=min(float(node.min_width or front_depth), front_depth),
                max_aspect_ratio=max(6.5, float(node.max_aspect_ratio or 1.0)),
            )
            if node.node_id == primary.node_id
            else replace(
                node,
                max_aspect_ratio=max(6.5, float(node.max_aspect_ratio or 1.0)),
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


def _zone_orthogonal_office_program(
    program: ProgramGraph,
    *,
    expand_focus: bool = True,
) -> ProgramGraph:
    if program.use_type not in {"office", "neighborhood_commercial"}:
        raise ValueError(
            "nonrectangular floor generation requires a supported use"
        )
    if program.use_type != "office":
        return program
    adjusted_nodes = [
        (
            replace(
                node,
                space_type="open_work",
                zone="work",
                frontage_required=True,
                min_width=max(float(node.min_width or 0), 4.8),
                max_aspect_ratio=max(
                    float(node.max_aspect_ratio or 0),
                    6.5,
                ),
            )
            if expand_focus and node.space_type == "focus"
            else node
        )
        for node in program.nodes
    ]
    return _with_program_adjustment(
        program,
        adjusted_nodes,
        reason="orthogonal_open_work_zoning",
        source=f"{program.source}:orthogonal_open_work_zoning",
    )


def _fit_orthogonal_program_to_layout(
    program: ProgramGraph,
    layout: LayoutCandidate,
) -> ProgramGraph:
    room_by_id = {room.room_id: room for room in layout.rooms}
    adjusted_nodes = []
    for node in program.nodes:
        room = room_by_id[node.node_id]
        actual_area = polygon_area(room.polygon)
        actual_width = orthogonal_min_width(room.polygon)
        actual_aspect = bounding_box_aspect_ratio(room.polygon)
        adjusted_nodes.append(
            replace(
                node,
                target_area=_clean_area(actual_area),
                min_area=_clean_area(actual_area * 0.85),
                max_area=_clean_area(actual_area * 1.15),
                min_width=min(
                    float(node.min_width or actual_width),
                    actual_width,
                ),
                max_aspect_ratio=max(
                    float(node.max_aspect_ratio or actual_aspect),
                    actual_aspect,
                ),
            )
        )
    return _with_program_adjustment(
        program,
        adjusted_nodes,
        reason="orthogonal_layout_fit",
        source=f"{program.source}:orthogonal_layout_fit",
    )


def _program_adjustment(reason, original_nodes, adjusted_nodes):
    return ProgramAdjustment(
        reason=reason,
        original_nodes=tuple(original_nodes),
        adjusted_nodes=tuple(adjusted_nodes),
        original_targets=tuple(
            (node.node_id, float(node.target_area)) for node in original_nodes
        ),
        adjusted_targets=tuple(
            (node.node_id, float(node.target_area)) for node in adjusted_nodes
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


def _is_axis_aligned_rectangle(
    polygon: Iterable[tuple[float, float]],
    polygon_bounds_value: tuple[float, float, float, float],
) -> bool:
    points = tuple((float(x), float(y)) for x, y in polygon)
    min_x, min_y, max_x, max_y = polygon_bounds_value
    expected = {
        (float(min_x), float(min_y)),
        (float(max_x), float(min_y)),
        (float(max_x), float(max_y)),
        (float(min_x), float(max_y)),
    }
    return len(points) == 4 and set(points) == expected


def _is_axis_aligned_polygon(
    polygon: Iterable[tuple[float, float]],
) -> bool:
    points = tuple((float(x), float(y)) for x, y in polygon)
    return all(
        math.isclose(start[0], end[0], abs_tol=1e-8)
        or math.isclose(start[1], end[1], abs_tol=1e-8)
        for start, end in zip(points, (*points[1:], points[0]))
    )


def _aligned_remote_stair_candidates(
    common_shape: Polygon,
    *,
    corridor_bottom: float,
    dimensions: Iterable[tuple[float, float]],
    excluded_polygon: Iterable[tuple[float, float]],
    grid_step: float = 0.25,
) -> list[tuple[tuple[float, float], ...]]:
    min_x, _, max_x, _ = common_shape.bounds
    candidates = []
    for stair_width, stair_depth in set(dimensions):
        stair_min_y = corridor_bottom - stair_depth
        maximum_x = max_x - stair_width
        count = max(0, math.ceil((maximum_x - min_x) / grid_step))
        x_origins = {
            min_x,
            maximum_x,
            *(
                min_x + index * grid_step
                for index in range(count + 1)
                if min_x + index * grid_step <= maximum_x + 1e-8
            ),
        }
        for stair_min_x in sorted(x_origins):
            candidate = (
                (stair_min_x, stair_min_y),
                (stair_min_x + stair_width, stair_min_y),
                (stair_min_x + stair_width, corridor_bottom),
                (stair_min_x, corridor_bottom),
            )
            if (
                common_shape.covers(Polygon(candidate))
                and polygon_overlap_area(candidate, excluded_polygon) <= 1e-7
            ):
                candidates.append(candidate)
    return candidates


def _select_polygonal_core_and_stair(
    core_candidates: Iterable[tuple[tuple[float, float], ...]],
    *,
    floor_boundaries: Iterable[Iterable[tuple[float, float]]],
    common_shape: Polygon,
    stair_dimensions: Iterable[tuple[float, float]],
) -> tuple[
    tuple[tuple[float, float], ...],
    tuple[tuple[float, float], ...],
    tuple[tuple[float, float], ...],
]:
    boundaries = tuple(tuple(boundary) for boundary in floor_boundaries)
    cores = _representative_rectangle_candidates(tuple(core_candidates))
    prepared_common = prep(common_shape)
    maximum_floor_diagonal = max(
        math.hypot(
            polygon_bounds(boundary)[2] - polygon_bounds(boundary)[0],
            polygon_bounds(boundary)[3] - polygon_bounds(boundary)[1],
        )
        for boundary in boundaries
    )
    target_separation = maximum_floor_diagonal * 0.5
    pairs = []
    for core in cores:
        core_bounds = polygon_bounds(core)
        core_center = Polygon(core).centroid.coords[0]
        stairs = _aligned_remote_stair_candidates(
            common_shape,
            corridor_bottom=core_bounds[1] - 1.2,
            dimensions=stair_dimensions,
            excluded_polygon=core,
        )
        for stair in sorted(
            stairs,
            key=lambda stair: math.dist(
                Polygon(stair).centroid.coords[0],
                core_center,
            ),
            reverse=True,
        ):
            stair_shape = Polygon(stair)
            pair_bounds = Polygon(core).union(stair_shape).bounds
            minimum_frame = box(*pair_bounds)
            if not prepared_common.covers(minimum_frame):
                continue
            separation = math.dist(
                stair_shape.centroid.coords[0],
                core_center,
            )
            pairs.append(
                (
                    separation >= target_separation - 1e-7,
                    separation,
                    minimum_frame.area,
                    core_bounds[3],
                    core_bounds[2],
                    core,
                    stair,
                )
            )
            break
    if not pairs:
        raise ValueError(
            "common floor region cannot fit an aligned core and remote stair"
        )
    _, _, _, _, _, core, stair = max(pairs)
    planning_boundary = largest_inscribed_axis_aligned_rectangle(
        common_shape.exterior.coords[:-1],
        required_polygons=(core, stair),
    )
    return core, stair, planning_boundary


def _representative_rectangle_candidates(
    candidates: tuple[tuple[tuple[float, float], ...], ...],
) -> tuple[tuple[tuple[float, float], ...], ...]:
    groups: dict[tuple[str, float, float, float], list] = {}
    for candidate in candidates:
        min_x, min_y, max_x, max_y = polygon_bounds(candidate)
        width = round(max_x - min_x, 7)
        height = round(max_y - min_y, 7)
        groups.setdefault(("y", width, height, round(min_y, 7)), []).append(
            candidate
        )
        groups.setdefault(("x", width, height, round(min_x, 7)), []).append(
            candidate
        )
    selected = set()
    for key, group in groups.items():
        axis = 0 if key[0] == "y" else 1
        ordered = sorted(group, key=lambda item: polygon_bounds(item)[axis])
        last = len(ordered) - 1
        selected.update(
            ordered[round(last * fraction)]
            for fraction in (0.0, 0.25, 0.5, 0.75, 1.0)
        )
    return tuple(sorted(selected, key=polygon_bounds))


def _analysis_for_floor(
    analysis: MassAnalysis,
    floor_index: int,
) -> MassAnalysis:
    plate = analysis.floor_plate(floor_index)
    return replace(
        analysis,
        area=plate.area,
        edge_count=plate.edge_count,
        bounds=plate.bounds,
    )


def _clean_area(value: float) -> float | int:
    return int(value) if float(value).is_integer() else round(value, 6)


def run_candidate_search(
    mass: MassInput,
    floor_index: int,
    use_type: str,
    config: LoopConfig | None = None,
    *,
    program: ProgramGraph | None = None,
) -> LoopResult:
    config = config or LoopConfig()
    analysis = analyze_mass(mass)
    if program is None:
        program = generate_program_graph(
            analysis,
            floor_index=floor_index,
            use_type=use_type,
        )
    elif (
        program.project_id != mass.project_id
        or program.floor_index != floor_index
        or program.use_type != use_type
    ):
        raise ValueError("injected program identity does not match search request")
    floor_analysis = _analysis_for_floor(analysis, floor_index)
    boundary = mass.footprint_for_floor(floor_index)
    streets = _street_segments(mass)
    try:
        pending = generate_initial_proposals(floor_analysis, program)
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
                    boundary=boundary,
                    street_segments=streets,
                    building_code_context=mass.building_code_context,
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
                "evaluation_budget_exhausted"
                if skipped_for_budget
                else "search_exhausted",
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


def _street_segments_for_boundary(
    mass: MassInput,
    boundary: Iterable[tuple[float, float]],
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    floor_boundary = Polygon(tuple(boundary))
    segments = []
    for start, end in _street_segments(mass):
        clipped = floor_boundary.boundary.intersection(LineString((start, end)))
        lines = (
            [clipped]
            if isinstance(clipped, LineString)
            else list(clipped.geoms)
            if isinstance(clipped, MultiLineString)
            else []
        )
        for line in lines:
            coordinates = tuple(line.coords)
            if len(coordinates) >= 2 and line.length > 1e-9:
                segments.append(
                    (
                        tuple(float(value) for value in coordinates[0]),
                        tuple(float(value) for value in coordinates[-1]),
                    )
                )
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
