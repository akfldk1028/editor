import json
import time
from dataclasses import replace
from types import SimpleNamespace

from backend.app.modules.generation_loop.operators import (
    layout_fingerprint,
    refine_proposals,
)
from backend.app.modules.generation_loop.service import run_building_generation
from backend.app.modules.generation_loop.selector import (
    canonical_building_topology_signature,
)
from backend.app.modules.layout_generator.service import generate_baseline_layout
from backend.app.modules.mass_analyzer.service import analyze_mass
from backend.app.modules.program_prior.service import generate_program_graph
from backend.app.modules.validator.service import validate_layout
from backend.app.modules.visual_review.service import (
    create_visual_review_artifacts,
    run_visual_review_loop,
)
from backend.app.schemas.loop import CandidateRecord
from backend.app.schemas.layout import LayoutCandidate, RoomPolygon
from backend.app.schemas.mass import FloorFootprint, MassInput


def test_zoning_review_uses_selected_floor_footprint(tmp_path) -> None:
    floor_boundaries = (
        ((0.0, 0.0), (32.0, 0.0), (32.0, 12.0), (0.0, 12.0)),
        ((0.0, 0.0), (30.0, 0.0), (30.0, 12.0), (0.0, 12.0)),
    )
    mass = MassInput(
        project_id="zoning-setback-regression",
        floors=2,
        footprint_polygon=list(floor_boundaries[0]),
        floor_footprints=tuple(
            FloorFootprint(floor_index=index, footprint_polygon=boundary)
            for index, boundary in enumerate(floor_boundaries, start=1)
        ),
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"office": 1.0},
    )

    result = run_visual_review_loop(
        mass,
        floor_index=2,
        use_type="office",
        output_dir=tmp_path,
        max_iterations=1,
        review_level="zoning",
    )

    assert result.artifacts, result.error
    report = json.loads(result.artifacts[0].report_path.read_text(encoding="utf-8"))
    assert report["floor_boundary"]["polygon"] == [
        [0.0, 0.0],
        [30.0, 0.0],
        [30.0, 12.0],
        [0.0, 12.0],
    ]


def test_refinement_generates_candidates_for_non_circulation_hard_failure() -> None:
    boundary = [(0.0, 0.0), (30.0, 0.0), (30.0, 12.0), (0.0, 12.0)]
    mass = MassInput(
        project_id="hard-gate-refinement-regression",
        floors=1,
        footprint_polygon=boundary,
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"office": 1.0},
    )
    analysis = analyze_mass(mass)
    program = generate_program_graph(analysis, floor_index=1, use_type="office")
    layout = generate_baseline_layout(analysis, program)
    report = validate_layout(layout, program, boundary=boundary)
    boundary_only = replace(
        report,
        is_valid=False,
        accepted=False,
        hard_violation_count=1,
        violations=[replace(report.violations[0], code="boundary")],
    )
    parent = CandidateRecord(
        iteration=1,
        layout=layout,
        validation=boundary_only,
        fingerprint=layout_fingerprint(layout),
        parent_id=None,
        operator="baseline",
    )

    proposals = refine_proposals([parent], [boundary_only], analysis, program, 2)

    assert proposals
    assert all(proposal.parent_id == layout.candidate_id for proposal in proposals)


def test_review_render_rejects_unresolved_label_collisions(tmp_path) -> None:
    boundary = [(0.0, 0.0), (30.0, 0.0), (30.0, 12.0), (0.0, 12.0)]
    mass = MassInput(
        project_id="review-label-collision-regression",
        floors=1,
        footprint_polygon=boundary,
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"office": 1.0},
    )
    floor = run_building_generation(mass).floor_results[0]

    artifacts = create_visual_review_artifacts(
        floor,
        boundary=boundary,
        output_dir=tmp_path,
        width=240,
        height=120,
        render_style="review",
    )

    report = json.loads(artifacts.report_path.read_text(encoding="utf-8"))
    assert report["png_text"]["unresolved_collision_count"] > 0
    assert report["render_validation"]["status"] == "fail"
    assert report["accepted"] is False


def test_topology_signature_scales_for_repeated_room_roles() -> None:
    rooms = [
        RoomPolygon(
            room_id=f"office-{index}",
            space_type="open_work",
            polygon=[
                (float(index), 0.0),
                (float(index + 1), 0.0),
                (float(index + 1), 1.0),
                (float(index), 1.0),
            ],
        )
        for index in range(9)
    ]
    floor = SimpleNamespace(
        program=SimpleNamespace(use_type="office"),
        layout=LayoutCandidate(
            candidate_id="repeated-role-topology",
            project_id="repeated-role-topology",
            floor_index=1,
            rooms=rooms,
            circulation=[],
            score=0.0,
        ),
    )

    started = time.perf_counter()
    signature = canonical_building_topology_signature((floor,))
    elapsed = time.perf_counter() - started

    assert signature
    assert elapsed < 0.25
