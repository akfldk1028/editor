from dataclasses import replace
import subprocess
import sys

from backend.app.modules.generation_loop.operators import (
    deduplicate_candidates,
    generate_initial_candidates,
    generate_initial_proposals,
    layout_fingerprint,
    refine_candidates,
    refine_proposals,
)
from backend.app.modules.generation_loop.selector import rank_candidate
from backend.app.modules.mass_analyzer.service import analyze_mass
from backend.app.modules.program_prior.service import generate_program_graph
from backend.app.modules.validator.service import validate_layout
from backend.app.schemas.layout import LayoutCandidate, OpeningSegment, RoomPolygon
from backend.app.schemas.loop import CandidateRecord
from backend.app.schemas.mass import MassInput
from backend.app.schemas.metrics import ValidationReport, ValidationViolation
from backend.app.schemas.program import ProgramGraph, ProgramNode


def _mass() -> MassInput:
    return MassInput(
        project_id="operators",
        floors=2,
        footprint_polygon=[(0, 0), (30, 0), (30, 12), (0, 12)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"neighborhood_commercial": 1.0},
    )


def _layout(candidate_id: str, *, split: float = 5) -> LayoutCandidate:
    return LayoutCandidate(
        candidate_id=candidate_id,
        project_id="operators",
        floor_index=1,
        rooms=[
            RoomPolygon("a", "office", [(0, 0), (split, 0), (split, 10), (0, 10)]),
            RoomPolygon("b", "core", [(split, 0), (10, 0), (10, 10), (split, 10)]),
        ],
        circulation=[],
        score=0,
    )


def _report(
    *,
    accepted: bool,
    hard_violation_count: int,
    violation_score: float,
    total_score: float,
) -> ValidationReport:
    return ValidationReport(
        is_valid=accepted,
        accepted=accepted,
        hard_violation_count=hard_violation_count,
        violation_score=violation_score,
        violations=[],
        room_areas=[],
        area_score=1,
        overlap_score=1,
        boundary_score=1,
        circulation_score=1,
        efficiency_score=1,
        adjacency_score=1,
        frontage_score=1,
        coverage_score=1,
        compactness_score=1,
        total_score=total_score,
        messages=[],
        policy_version="test",
    )


def _record(
    candidate_id: str,
    report: ValidationReport,
    *,
    split: float = 5,
) -> CandidateRecord:
    layout = _layout(candidate_id, split=split)
    return CandidateRecord(
        iteration=1,
        layout=layout,
        validation=report,
        fingerprint=layout_fingerprint(layout),
        parent_id=None,
        operator="test",
        operator_params={},
    )


def test_layout_fingerprint_is_canonical_and_geometry_sensitive():
    original = _layout("one")
    reordered = replace(
        original,
        candidate_id="another-id",
        project_id="another-project",
        floor_index=9,
        rooms=list(reversed(original.rooms)),
    )
    changed = _layout("changed", split=6)
    negative_zero = replace(
        original,
        rooms=[
            replace(
                original.rooms[0],
                polygon=[
                    (-0.0, -0.0),
                    (5, 0),
                    (5, 10),
                    (0, 10),
                ],
            ),
            original.rooms[1],
        ],
    )

    assert layout_fingerprint(original) == layout_fingerprint(reordered)
    assert layout_fingerprint(original) == layout_fingerprint(negative_zero)
    assert len(layout_fingerprint(original)) == 64
    assert layout_fingerprint(original) != layout_fingerprint(changed)


def test_layout_fingerprint_canonicalizes_opening_order_and_endpoint_direction():
    first = OpeningSegment(
        "door-a",
        "door",
        ("a", "corridor"),
        (1, 10),
        (1.9, 10),
        0.9,
    )
    second = OpeningSegment(
        "door-b",
        "door",
        ("b", "corridor"),
        (8.1, 10),
        (9, 10),
        0.9,
    )
    original = replace(_layout("original"), openings=[first, second])
    reordered = replace(
        original,
        openings=[
            replace(second, start=second.end, end=second.start),
            replace(first, start=first.end, end=first.start),
        ],
    )
    changed = replace(
        original,
        openings=[replace(first, clear_width=0.8), second],
    )

    assert layout_fingerprint(original) == layout_fingerprint(reordered)
    assert layout_fingerprint(original) != layout_fingerprint(changed)


def test_layout_fingerprint_is_stable_across_python_processes():
    source = """
from backend.app.modules.generation_loop.operators import layout_fingerprint
from backend.app.schemas.layout import LayoutCandidate, RoomPolygon
layout = LayoutCandidate(
    candidate_id="process",
    project_id="operators",
    floor_index=1,
    rooms=[
        RoomPolygon("b", "core", [(5, 0), (10, 0), (10, 10), (5, 10)]),
        RoomPolygon("a", "office", [(0, 0), (5, 0), (5, 10), (0, 10)]),
    ],
    circulation=[],
    score=0,
)
print(layout_fingerprint(layout))
"""
    fingerprints = [
        subprocess.check_output([sys.executable, "-c", source], text=True).strip()
        for _ in range(2)
    ]

    assert fingerprints[0] == fingerprints[1] == layout_fingerprint(_layout("local"))


def test_layout_fingerprint_handles_invalid_geometry_for_validator_rejection():
    invalid = replace(
        _layout("invalid"),
        rooms=[RoomPolygon("a", "office", [])],
    )

    assert len(layout_fingerprint(invalid)) == 64

    non_finite = replace(
        _layout("non-finite"),
        rooms=[
            RoomPolygon(
                "a",
                "office",
                [(0, 0), (float("inf"), 0), (1, 1)],
            )
        ],
    )
    assert len(layout_fingerprint(non_finite)) == 64


def test_rank_is_lexicographic_with_stable_fingerprint_tie_break():
    rejected = _record("rejected", _report(
        accepted=False,
        hard_violation_count=0,
        violation_score=0,
        total_score=1,
    ))
    accepted = _record("accepted", _report(
        accepted=True,
        hard_violation_count=2,
        violation_score=1,
        total_score=0,
    ), split=6)

    assert rank_candidate(accepted) < rank_candidate(rejected)

    tied_a = _record("tie-a", _report(
        accepted=False,
        hard_violation_count=1,
        violation_score=0.25,
        total_score=0.75,
    ), split=4)
    tied_b = _record("tie-b", tied_a.validation, split=7)
    assert sorted([tied_b, tied_a], key=rank_candidate) == sorted(
        [tied_b, tied_a],
        key=lambda record: record.fingerprint,
    )


def test_initial_candidates_are_distinct_and_deduplicate_by_fingerprint():
    analysis = analyze_mass(_mass())
    program = generate_program_graph(analysis, 1, "neighborhood_commercial")

    candidates = generate_initial_candidates(analysis, program)
    fingerprints = [layout_fingerprint(candidate) for candidate in candidates]

    assert candidates[0].candidate_id.endswith("-baseline")
    assert any("stripe-x-reversed" in candidate.candidate_id for candidate in candidates)
    assert any("stripe-y" in candidate.candidate_id for candidate in candidates)
    assert any("guillotine" in candidate.candidate_id for candidate in candidates)
    assert len(fingerprints) == len(set(fingerprints))
    assert deduplicate_candidates([*candidates, candidates[0]]) == candidates


def test_refinement_fingerprint_does_not_depend_on_iteration_metadata():
    analysis = analyze_mass(_mass())
    program = generate_program_graph(analysis, 1, "neighborhood_commercial")
    parent = generate_initial_candidates(analysis, program)[0]
    report = replace(
        _report(
            accepted=False,
            hard_violation_count=1,
            violation_score=0.125,
            total_score=0.5,
        ),
        violations=[
            ValidationViolation(
                code="circulation_missing",
                subject="circulation",
                message="missing",
            )
        ],
    )

    generation_two = refine_candidates([parent], [report], analysis, program, 2)
    generation_three = refine_candidates([parent], [report], analysis, program, 3)

    assert [layout_fingerprint(item) for item in generation_two] == [
        layout_fingerprint(item) for item in generation_three
    ]


def test_fingerprint_does_not_deduplicate_rejected_gap_and_accepted_touch():
    program = ProgramGraph(
        project_id="precision",
        floor_index=1,
        use_type="office",
        nodes=[
            ProgramNode(
                node_id="office",
                space_type="office_area",
                target_area=50,
                min_area=49,
                max_area=51,
            )
        ],
        edges=[],
        source="test",
    )
    boundary = [(0, 0), (10, 0), (10, 10), (0, 10)]

    def candidate(candidate_id, room_end):
        return LayoutCandidate(
            candidate_id=candidate_id,
            project_id="precision",
            floor_index=1,
            rooms=[
                RoomPolygon(
                    "office",
                    "office_area",
                    [(0, 0), (room_end, 0), (room_end, 10), (0, 10)],
                )
            ],
            circulation=[
                RoomPolygon(
                    "corridor",
                    "circulation",
                    [(5, 0), (6, 0), (6, 10), (5, 10)],
                )
            ],
            score=0,
        )

    rejected = candidate("gap", 4.9999996)
    accepted = candidate("touch", 5.0)

    assert not validate_layout(rejected, program, boundary).accepted
    assert validate_layout(accepted, program, boundary).accepted
    assert layout_fingerprint(rejected) != layout_fingerprint(accepted)
    assert deduplicate_candidates([rejected, accepted]) == [rejected, accepted]


def test_corridor_scaling_never_undershoots_declared_minimum():
    mass = MassInput(
        project_id="numeric",
        floors=1,
        footprint_polygon=[(0, 0), (10, 0), (10, 10), (0, 10)],
        site_edges=[],
        access_candidates=[],
        use_mix={"office": 1.0},
    )
    analysis = analyze_mass(mass)
    program = ProgramGraph(
        project_id="numeric",
        floor_index=1,
        use_type="office",
        nodes=[
            ProgramNode("a", "office_area", 50, 45.0000245, 55),
            ProgramNode("b", "core", 50, 45, 55),
        ],
        edges=[],
        source="test",
    )
    parent = LayoutCandidate(
        candidate_id="numeric-parent",
        project_id="numeric",
        floor_index=1,
        rooms=[
            RoomPolygon("a", "office_area", [(0, 0), (5, 0), (5, 10), (0, 10)]),
            RoomPolygon("b", "core", [(5, 0), (10, 0), (10, 10), (5, 10)]),
        ],
        circulation=[],
        score=0,
    )
    missing = replace(
        _report(
            accepted=False,
            hard_violation_count=1,
            violation_score=0.125,
            total_score=0.5,
        ),
        violations=[
            ValidationViolation("circulation_missing", "circulation", "missing")
        ],
    )

    candidates = refine_candidates([parent], [missing], analysis, program, 2)
    reports = [
        validate_layout(candidate, program, mass.footprint_polygon)
        for candidate in candidates
    ]

    assert candidates
    assert all(
        all(metric.within_range for metric in report.room_areas)
        for report in reports
    )


def test_structured_proposals_preserve_direct_parent_across_generations():
    analysis = analyze_mass(replace(_mass(), project_id="tenant::phase"))
    program = generate_program_graph(analysis, 1, "neighborhood_commercial")
    initial = generate_initial_proposals(analysis, program)[0]
    missing = replace(
        _report(
            accepted=False,
            hard_violation_count=1,
            violation_score=0.125,
            total_score=0.5,
        ),
        violations=[
            ValidationViolation("circulation_missing", "circulation", "missing")
        ],
    )
    first_record = _record_from_proposal(initial, missing, 1)
    second = refine_proposals([first_record], [missing], analysis, program, 2)[0]
    second_record = _record_from_proposal(second, missing, 2)
    third = refine_proposals([second_record], [missing], analysis, program, 3)[0]

    assert first_record.parent_id is None
    assert second.parent_id == first_record.layout.candidate_id
    assert third.parent_id == second_record.layout.candidate_id
    assert third.operator.startswith("corridor-")
    assert third.operator_params["order"]


def _record_from_proposal(proposal, report, iteration):
    return CandidateRecord(
        iteration=iteration,
        layout=proposal.layout,
        validation=report,
        fingerprint=layout_fingerprint(proposal.layout),
        parent_id=proposal.parent_id,
        operator=proposal.operator,
        operator_params=proposal.operator_params,
    )
