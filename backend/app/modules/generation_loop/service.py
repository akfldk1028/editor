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
from backend.app.schemas.result import BuildingGenerationResult, GenerationResult


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
) -> BuildingGenerationResult:
    analysis = analyze_mass(mass)
    _require_rectangular_floor_plate(mass, analysis)
    if floor_assignments is None:
        assignments = assign_floors_from_use_mix(mass)
        assignment_source = "use_mix"
    else:
        assignments = _validate_floor_assignments(
            floor_assignments,
            floors=mass.floors,
        )
        assignment_source = "structured"

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
    programs = [
        _normalize_program_core(program, shared_core_target)
        for program in programs
    ]

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
        core_height = min(height * (0.47333333333333333 if height >= 12 else 0.46), height - 1.2)
        service_band_width = shared_core_target / core_height
        service_x = float(_clean_area(max_x - service_band_width))
        service_band_width = max_x - service_x
        core_height = shared_core_target / service_band_width
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
    core_top = float(_clean_area(min_y + core_height))
    shared_core = [
        (service_x, min_y),
        (max_x, min_y),
        (max_x, core_top),
        (service_x, core_top),
    ]

    floor_results = []
    for program in programs:
        layout = generate_core_aligned_layout(
            analysis,
            program,
            core_polygon=shared_core,
            service_band_width=service_band_width,
            room_scale=room_scale,
        )
        validation = validate_layout(
            layout,
            program,
            boundary=mass.footprint_polygon,
            street_segments=_street_segments(mass),
            require_openings=True,
            min_door_width=0.8,
            min_circulation_width=1.2,
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
    if len(primary_candidates) != 1:
        raise ValueError(
            f"program must contain exactly one residual primary role for {program.use_type}"
        )
    primary = primary_candidates[0]
    delta = shared_core_target - float(core.target_area)
    primary_target = float(primary.target_area) - delta
    if primary_target <= 0:
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
        elif node.node_id == primary.node_id:
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
    return replace(program, nodes=nodes, source="building_aligned_prior")


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
        segments.append((points[index], points[(index + 1) % len(points)]))
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
