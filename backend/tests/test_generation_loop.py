from dataclasses import replace

import backend.app.modules.generation_loop.service as search_service
from backend.app.modules.generation_loop.selector import rank_candidate
from backend.app.modules.generation_loop.service import (
    run_candidate_search,
    run_generation_loop,
)
from backend.app.schemas.mass import MassInput
from backend.app.schemas.loop import LoopConfig
from backend.app.schemas.layout import RoomPolygon
from engine.geometry.polygon import shared_boundary_length


def test_generation_loop_returns_program_layout_and_validation_report():
    mass = MassInput(
        project_id="loop",
        floors=3,
        footprint_polygon=[(0, 0), (30, 0), (30, 10), (0, 10)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"neighborhood_commercial": 0.34, "office": 0.66},
    )

    result = run_generation_loop(mass, floor_index=1, use_type="neighborhood_commercial")

    assert result.mass.project_id == "loop"
    assert result.program.use_type == "neighborhood_commercial"
    assert result.layout.project_id == "loop"
    assert result.validation.total_score >= 0


def test_office_generation_loop_reaches_structured_validation():
    mass = MassInput(
        project_id="office-loop",
        floors=3,
        footprint_polygon=[(0, 0), (30, 0), (30, 10), (0, 10)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"office": 1.0},
    )

    result = run_generation_loop(mass, floor_index=2, use_type="office")

    assert result.program.use_type == "office"
    assert not result.validation.accepted
    assert "circulation_missing" in {
        violation.code for violation in result.validation.violations
    }


def _sample_mass() -> MassInput:
    return MassInput(
        project_id="sample-search",
        floors=5,
        footprint_polygon=[(0, 0), (30, 0), (30, 12), (0, 12)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"neighborhood_commercial": 0.2, "office": 0.8},
    )


def test_candidate_search_uses_structured_feedback_and_improves_sample():
    result = run_candidate_search(
        _sample_mass(),
        floor_index=1,
        use_type="neighborhood_commercial",
        config=LoopConfig(max_iterations=5, evaluation_budget=32, beam_width=4),
    )

    baseline = result.iterations[0].candidates[0]
    assert baseline.operator == "baseline"
    assert not baseline.validation.accepted
    assert "circulation_missing" in {
        violation.code for violation in baseline.validation.violations
    }

    assert result.termination_reason == "accepted"
    assert len(result.iterations) == 2
    assert result.best.iteration == 2
    assert result.best.parent_id is not None
    assert result.best.fingerprint != baseline.fingerprint
    assert result.best.validation.frontage_score == 1

    fingerprints = [record.fingerprint for record in result.history]
    assert len(fingerprints) == len(set(fingerprints))
    evaluated_fingerprints = [
        candidate.fingerprint
        for iteration in result.iterations
        for candidate in iteration.candidates
    ]
    assert len(evaluated_fingerprints) == len(set(evaluated_fingerprints))
    ranks = [rank_candidate(record) for record in result.history]
    assert ranks == sorted(ranks, reverse=True)
    assert all(metric.within_range for metric in result.best.validation.room_areas)

    corridor = result.best.layout.circulation
    assert corridor
    assert all(
        any(shared_boundary_length(room.polygon, path.polygon) > 0 for path in corridor)
        for room in result.best.layout.rooms
    )
    corridor_min_x = min(point[0] for point in corridor[0].polygon)
    corridor_max_x = max(point[0] for point in corridor[0].polygon)
    corridor_min_y = min(point[1] for point in corridor[0].polygon)
    corridor_max_y = max(point[1] for point in corridor[0].polygon)
    rooms = result.best.layout.rooms
    has_rooms_on_both_sides = (
        any(max(point[1] for point in room.polygon) == corridor_min_y for room in rooms)
        and any(min(point[1] for point in room.polygon) == corridor_max_y for room in rooms)
    ) or (
        any(max(point[0] for point in room.polygon) == corridor_min_x for room in rooms)
        and any(min(point[0] for point in room.polygon) == corridor_max_x for room in rooms)
    )
    assert has_rooms_on_both_sides


def test_search_reports_evaluation_budget_exhaustion_without_accepting():
    result = run_candidate_search(
        _sample_mass(),
        floor_index=1,
        use_type="neighborhood_commercial",
        config=LoopConfig(max_iterations=5, evaluation_budget=1),
    )

    assert result.termination_reason == "evaluation_budget_exhausted"
    assert result.evaluation_count == 1
    assert not result.accepted


def test_search_reports_iteration_budget_exhaustion_without_accepting():
    result = run_candidate_search(
        _sample_mass(),
        floor_index=1,
        use_type="neighborhood_commercial",
        config=LoopConfig(max_iterations=1, evaluation_budget=32),
    )

    assert result.termination_reason == "iteration_budget_exhausted"
    assert len(result.iterations) == 1
    assert not result.accepted


def test_search_exhausts_feedback_operators_for_rejected_concave_layouts():
    mass = replace(
        _sample_mass(),
        project_id="concave-search",
        footprint_polygon=[
            (0, 0),
            (30, 0),
            (30, 4),
            (10, 4),
            (10, 12),
            (0, 12),
        ],
    )

    result = run_candidate_search(
        mass,
        floor_index=1,
        use_type="neighborhood_commercial",
        config=LoopConfig(max_iterations=5, evaluation_budget=32),
    )

    assert result.termination_reason == "search_exhausted"
    assert not result.accepted


def test_search_stagnates_when_novel_refinement_does_not_improve(monkeypatch):
    calls = 0

    def refine_once(frontier, reports, analysis, program, iteration):
        nonlocal calls
        calls += 1
        if calls > 1:
            return []
        parent = frontier[0].layout
        shifted_rooms = [
            RoomPolygon(
                room.room_id,
                room.space_type,
                [(x + 100, y) for x, y in room.polygon],
            )
            for room in parent.rooms
        ]
        return [
            replace(
                parent,
                candidate_id=f"{parent.candidate_id}::i{iteration}:shifted:test",
                rooms=shifted_rooms,
            )
        ]

    monkeypatch.setattr(search_service, "refine_candidates", refine_once)

    result = run_candidate_search(
        _sample_mass(),
        floor_index=1,
        use_type="neighborhood_commercial",
        config=LoopConfig(
            max_iterations=5,
            evaluation_budget=32,
            stagnation_iterations=1,
        ),
    )

    assert result.termination_reason == "stagnated"
    assert not result.accepted


def test_unexpected_evaluation_error_returns_failed_result(monkeypatch):
    def fail_validation(*args, **kwargs):
        raise RuntimeError("evaluator failed")

    monkeypatch.setattr(search_service, "validate_layout", fail_validation)

    result = run_candidate_search(
        _sample_mass(),
        floor_index=1,
        use_type="neighborhood_commercial",
    )

    assert result.termination_reason == "failed"
    assert result.best is None
    assert result.evaluation_count == 0
