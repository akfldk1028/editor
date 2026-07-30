import json
from dataclasses import replace
from pathlib import Path

import pytest
from shapely.geometry import Polygon

import backend.app.modules.generation_loop.service as generation_service
from backend.app.modules.basic_design.stair import (
    required_stair_enclosure,
    resolve_floor_height,
)
from backend.app.modules.circulation_planner.service import (
    generate_circulation_candidate,
)
from backend.app.modules.core_planner.service import generate_shared_core_candidates
from backend.app.modules.generation_loop.contracts import ExteriorAllocationRequest
from backend.app.modules.generation_loop.selector import rank_candidate
from backend.app.modules.generation_loop.service import (
    run_building_generation,
    run_candidate_search,
    run_generation_loop,
)
from backend.app.modules.mass_analyzer.service import analyze_mass
from backend.app.modules.program_prior.service import generate_program_graph
from backend.app.schemas.llm import FloorAssignment
from backend.app.schemas.mass import FloorFootprint, MassInput
from backend.app.schemas.loop import CandidateProposal, LoopConfig
from backend.app.schemas.layout import RoomPolygon
from engine.geometry.polygon import shared_boundary_length


def _exterior_routing_mass() -> MassInput:
    return MassInput(
        project_id="exterior-routing",
        floors=1,
        footprint_polygon=[
            (0.0, 0.0),
            (30.0, 0.0),
            (30.0, 20.0),
            (20.0, 20.0),
            (20.0, 12.0),
            (0.0, 12.0),
        ],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"office": 1.0},
    )


def test_building_generation_routes_exterior_allocation_to_requested_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = []
    original = generation_service.generate_orthogonal_office_layout

    def capture(*args, **kwargs):
        observed.append(tuple(kwargs["exterior_priority_room_ids"]))
        return original(*args, **kwargs)

    monkeypatch.setattr(
        generation_service,
        "generate_orthogonal_office_layout",
        capture,
    )
    mass = _exterior_routing_mass()
    run_building_generation(
        mass,
        exterior_allocation_requests=(
            ExteriorAllocationRequest(1, ("focus", "meeting")),
        ),
    )

    assert observed == [("focus", "meeting")]


def test_long_edge_floor_three_splits_exterior_seeds_for_each_request_set() -> None:
    mass, assignments, programs, core, circulation = _long_edge_fixture_inputs()
    generation_kwargs = {
        "floor_assignments": assignments,
        "program_overrides": programs,
        "core_override": core,
        "circulation_overrides": circulation,
    }
    baseline = run_building_generation(mass, **generation_kwargs)
    explicit_empty = run_building_generation(
        mass,
        **generation_kwargs,
        exterior_allocation_requests=(),
    )

    assert explicit_empty == baseline
    for room_ids in (("focus",), ("meeting",), ("focus", "meeting")):
        building = run_building_generation(
            mass,
            **generation_kwargs,
            exterior_allocation_requests=(
                ExteriorAllocationRequest(3, room_ids),
            ),
        )
        floor = building.floor_results[2]
        exterior = Polygon(floor.floor_boundary).boundary
        rooms = {
            room.room_id: Polygon(room.polygon)
            for room in floor.layout.rooms
        }

        assert building.accepted
        assert all(
            rooms[room_id].boundary.intersection(exterior).length >= 0.6
            for room_id in room_ids
        )


def test_building_generation_rejects_duplicate_or_unknown_exterior_requests() -> None:
    mass = _exterior_routing_mass()
    request = ExteriorAllocationRequest(1, ("focus",))

    with pytest.raises(ValueError, match="one exterior allocation request per floor"):
        run_building_generation(
            mass,
            exterior_allocation_requests=(request, request),
        )
    with pytest.raises(ValueError, match="absent from floor program"):
        run_building_generation(
            mass,
            exterior_allocation_requests=(
                ExteriorAllocationRequest(1, ("fixture-only-room",)),
            ),
        )
    with pytest.raises(ValueError, match="floor is outside building"):
        run_building_generation(
            mass,
            exterior_allocation_requests=(ExteriorAllocationRequest(2, ("focus",)),),
        )


def _long_edge_fixture_inputs():
    manifest_path = (
        Path(__file__).resolve().parents[2]
        / "datasets"
        / "manifests"
        / "sample_mass_irregular_12v_setback_office.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mass = MassInput(
        project_id=manifest["project_id"],
        floors=manifest["floors"],
        footprint_polygon=manifest["footprint_polygon"],
        floor_footprints=tuple(
            FloorFootprint(
                floor_index=floor["floor_index"],
                footprint_polygon=tuple(
                    (float(x), float(y)) for x, y in floor["footprint_polygon"]
                ),
            )
            for floor in manifest["floor_footprints"]
        ),
        site_edges=manifest["site_edges"],
        access_candidates=manifest["access_candidates"],
        use_mix=manifest["use_mix"],
    )
    analysis = analyze_mass(mass)
    boundaries = tuple(
        mass.footprint_for_floor(index)
        for index in range(1, mass.floors + 1)
    )
    assignments = tuple(
        FloorAssignment(index, "office")
        for index in range(1, mass.floors + 1)
    )
    programs = {
        index: generate_program_graph(
            analysis,
            floor_index=index,
            use_type="office",
        )
        for index in range(1, mass.floors + 1)
    }
    requested_core_area = min(
        72.0,
        max(
            float(
                next(
                    node.target_area
                    for node in program.nodes
                    if node.space_type == "core"
                )
            )
            for program in programs.values()
        ),
    )
    core = next(
        candidate
        for candidate in generate_shared_core_candidates(
            boundaries,
            required_area=requested_core_area,
            minimum_width=7.6,
            minimum_depth=5.2,
        )
        if candidate.strategy == "long_edge_adjacent"
    )
    circulation_boundary = min(
        boundaries,
        key=lambda boundary: (Polygon(boundary).area, boundary),
    )
    stair_short_side, stair_long_side = required_stair_enclosure(
        resolve_floor_height(None)[0]
    )
    shared_circulation = generate_circulation_candidate(
        floor_boundary=circulation_boundary,
        core=core,
        street_segments=((circulation_boundary[0], circulation_boundary[1]),),
        minimum_width=1.2,
        stair_dimensions=(
            (stair_short_side, stair_long_side),
            (stair_long_side, stair_short_side),
        ),
        minimum_exit_separation=None,
    )
    circulation = {
        index: shared_circulation
        for index in range(1, mass.floors + 1)
    }
    return mass, assignments, programs, core, circulation


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


def test_candidate_search_accepts_project_ids_with_lineage_delimiters():
    result = run_candidate_search(
        replace(_sample_mass(), project_id="tenant::phase"),
        floor_index=1,
        use_type="neighborhood_commercial",
    )

    assert result.termination_reason == "accepted"
    assert result.best is not None
    assert result.best.parent_id is not None


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


def test_candidate_search_reports_compact_commercial_infeasibility():
    mass = MassInput(
        project_id="compact-commercial",
        floors=1,
        footprint_polygon=[(0, 0), (20, 0), (20, 10), (0, 10)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[],
        use_mix={"neighborhood_commercial": 1.0},
    )

    result = run_candidate_search(mass, 1, "neighborhood_commercial")

    assert not result.accepted
    assert result.termination_reason == "search_exhausted"
    corridor = next(
        record
        for record in result.history
        if record.operator == "corridor-horizontal"
    )
    violations = {
        (item.code, item.subject)
        for item in corridor.validation.violations
    }
    assert {
        ("room_min_width", "checkout"),
        ("room_min_width", "staff"),
    } <= violations


def test_candidate_search_accepts_an_injected_program():
    mass = _sample_mass()
    baseline = generate_program_graph(
        analyze_mass(mass),
        floor_index=2,
        use_type="office",
    )
    injected = replace(
        baseline,
        nodes=list(reversed(baseline.nodes)),
        source="local_qwen_topology:topology-1",
    )

    result = run_candidate_search(
        mass,
        floor_index=2,
        use_type="office",
        config=LoopConfig(max_iterations=1, evaluation_budget=8),
        program=injected,
    )

    assert result.program is injected
    assert result.program.source == "local_qwen_topology:topology-1"


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
            CandidateProposal(
                layout=replace(
                    parent,
                    candidate_id=f"{parent.candidate_id}-shifted-{iteration}",
                    rooms=shifted_rooms,
                ),
                parent_id=parent.candidate_id,
                operator="shifted",
                operator_params={"case": "test"},
            )
        ]

    monkeypatch.setattr(generation_service, "refine_proposals", refine_once)

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

    monkeypatch.setattr(generation_service, "validate_layout", fail_validation)

    result = run_candidate_search(
        _sample_mass(),
        floor_index=1,
        use_type="neighborhood_commercial",
    )

    assert result.termination_reason == "failed"
    assert result.best is None
    assert result.evaluation_count == 0
    assert result.error == "RuntimeError: evaluator failed"
