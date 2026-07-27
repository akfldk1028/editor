from __future__ import annotations

from backend.app.modules.generation_loop.operators import (
    generate_initial_candidates,
    layout_fingerprint,
    refine_candidates,
)
from backend.app.modules.generation_loop.selector import rank_candidate, select_frontier
from backend.app.modules.layout_generator.service import generate_baseline_layout
from backend.app.modules.mass_analyzer.service import analyze_mass
from backend.app.modules.program_prior.service import generate_program_graph
from backend.app.modules.validator.service import validate_layout
from backend.app.schemas.mass import MassInput
from backend.app.schemas.loop import (
    CandidateRecord,
    IterationRecord,
    LoopConfig,
    LoopResult,
)
from backend.app.schemas.result import GenerationResult


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
        pending = generate_initial_candidates(analysis, program)
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
        for layout in pending:
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
            parent_id, operator, operator_params = _lineage(layout, iteration)
            records.append(
                CandidateRecord(
                    iteration=iteration,
                    layout=layout,
                    validation=validation,
                    fingerprint=fingerprint,
                    parent_id=parent_id,
                    operator=operator,
                    operator_params=operator_params,
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
                pending = refine_candidates(
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
                if layout_fingerprint(candidate) not in seen
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


def _lineage(layout, iteration: int):
    if "::" not in layout.candidate_id:
        marker = f"-f{layout.floor_index}-"
        operator = layout.candidate_id.split(marker, 1)[-1]
        return None, operator, {}
    parent_id, suffix = layout.candidate_id.split("::", 1)
    _, operator, order = suffix.split(":", 2)
    return parent_id, operator, {"order": order}


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
