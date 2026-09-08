from __future__ import annotations

from dataclasses import replace
import json
import math

import pytest

import backend.app.modules.visual_review.service as visual_review_service
from backend.app.modules.generation_loop.service import (
    build_floor_design_evidence,
    run_building_generation,
)
from backend.app.modules.validator.service import screen_egress_requirements
from backend.app.modules.validator.service import validate_layout
from backend.app.modules.visual_review.service import (
    create_building_visual_review_artifacts,
    create_visual_review_artifacts,
    run_visual_review_loop,
)
from backend.app.schemas.area import BuildingAreaLedger, FloorAreaLedger
from backend.app.schemas.egress import (
    FloorEgressGraphResult,
    RoomTravelEvidence,
    RouteEdge,
    RouteNode,
)
from backend.app.schemas.mass import (
    BuildingCodeContext,
    FloorCodeContext,
    MassInput,
)
from backend.app.schemas.loop import CandidateRecord, IterationRecord, LoopResult


def _mass(*, floors: int = 3) -> MassInput:
    return MassInput(
        project_id="floor-evidence",
        floors=floors,
        footprint_polygon=[(0, 0), (30, 0), (30, 12), (0, 12)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"neighborhood_commercial": 1 / floors, "office": 1 - 1 / floors},
        building_code_context=BuildingCodeContext(
            jurisdiction="KR",
            effective_date="2026-07-28",
            qualifying_sprinkler_protection=False,
            travel_limit_classification="general_30",
            floor_facts=tuple(
                FloorCodeContext(
                    floor_index=index,
                    above_grade=True,
                    occupancy_category="other_supported",
                    story_number=index,
                    habitable_area_m2=360.0,
                    is_evacuation_floor=index == 1,
                )
                for index in range(1, floors + 1)
            ),
        ),
    )


def _checked_egress(distance_m: float) -> FloorEgressGraphResult:
    origin = RouteNode(
        node_id="room:work:farthest",
        kind="room_farthest_candidate",
        point=(0.0, 0.0),
        host_id="work",
    )
    exit_node = RouteNode(
        node_id="exit:west",
        kind="protected_exit_portal",
        point=(distance_m, 0.0),
        host_id="west",
    )
    edge = RouteEdge(
        source_id=origin.node_id,
        target_id=exit_node.node_id,
        kind="inside_room",
        length_m=distance_m,
        polyline=(origin.point, exit_node.point),
        source_geometry_ids=("work",),
    )
    room = RoomTravelEvidence(
        floor_index=1,
        room_id="work",
        farthest_point=origin.point,
        nearest_exit_id=exit_node.node_id,
        distance_m=distance_m,
        route_node_ids=(origin.node_id, exit_node.node_id),
        route_polyline=edge.polyline,
        status="checked",
        unresolved_facts=(),
    )
    return FloorEgressGraphResult(
        floor_index=1,
        status="checked",
        nodes=(origin, exit_node),
        edges=(edge,),
        room_results=(room,),
        governing_room_id=room.room_id,
        governing_distance_m=distance_m,
        governing_exit_id=exit_node.node_id,
        common_path_distance_m=None,
        common_path_status="not_checked",
        dead_end_distance_m=None,
        dead_end_status="not_checked",
        unresolved_facts=(),
    )


def _travel_screening(distance_m: float):
    return screen_egress_requirements(
        context=BuildingCodeContext(
            jurisdiction="KR",
            effective_date="2026-07-28",
            qualifying_sprinkler_protection=False,
            travel_limit_classification="general_30",
            floor_facts=(
                FloorCodeContext(
                    floor_index=1,
                    above_grade=True,
                    occupancy_category="other_supported",
                    story_number=1,
                    habitable_area_m2=100.0,
                    is_evacuation_floor=False,
                ),
            ),
        ),
        floor_index=1,
        generated_direct_stair_count=1,
        floor_diagonal=32.0,
        egress_graph=_checked_egress(distance_m),
    )


def _two_exit_graph(*, connected: bool) -> FloorEgressGraphResult:
    base = _checked_egress(5.0)
    second_exit = RouteNode(
        node_id="exit:east",
        kind="protected_exit_portal",
        point=(15.0, 0.0),
        host_id="east",
    )
    connector = RouteEdge(
        source_id=base.nodes[-1].node_id,
        target_id=second_exit.node_id,
        kind="inside_circulation",
        length_m=10.0,
        polyline=(base.nodes[-1].point, second_exit.point),
        source_geometry_ids=("corridor",),
    )
    return replace(
        base,
        nodes=(*base.nodes, second_exit),
        edges=(*base.edges, *((connector,) if connected else ())),
    )


def test_building_generation_exposes_per_floor_area_and_egress_evidence() -> None:
    building = run_building_generation(_mass())

    assert isinstance(building.area_ledger, BuildingAreaLedger)
    assert tuple(
        floor.area_ledger.floor_index for floor in building.floor_results
    ) == (1, 2, 3)
    assert all(
        isinstance(floor.area_ledger, FloorAreaLedger)
        and isinstance(floor.egress_graph, FloorEgressGraphResult)
        for floor in building.floor_results
    )
    assert building.area_ledger.floors == tuple(
        floor.area_ledger for floor in building.floor_results
    )
    assert len({id(floor.area_ledger) for floor in building.floor_results}) == 3
    assert len({id(floor.egress_graph) for floor in building.floor_results}) == 3


def test_30x12_upper_office_route_recomputes_to_general_30_pass() -> None:
    building = run_building_generation(_mass())

    for floor in building.floor_results[1:]:
        assert floor.egress_graph is not None
        assert floor.egress_graph.governing_distance_m == pytest.approx(26.85)
        governing = next(
            room
            for room in floor.egress_graph.room_results
            if room.room_id == floor.egress_graph.governing_room_id
        )
        assert sum(
            math.dist(start, end)
            for start, end in zip(
                governing.route_polyline,
                governing.route_polyline[1:],
            )
        ) == pytest.approx(26.85)
        travel = next(
            check
            for check in floor.validation.regulatory_screening.checks
            if check.rule_id == "KR-EGRESS-TRAVEL-DISTANCE-ART34"
        )
        assert travel.status == "pass"
        assert travel.measured_value == pytest.approx(26.85)


@pytest.mark.parametrize(
    ("width", "depth", "travel_status"),
    [
        (20.0, 12.0, "pass"),
        (20.0, 20.0, "pass"),
        (30.0, 12.0, "pass"),
        (30.0, 20.0, "fail"),
    ],
)
def test_egress_alignment_preserves_concept_basic_matrix(
    width: float,
    depth: float,
    travel_status: str,
) -> None:
    mass = MassInput(
        project_id=f"egress-matrix-{width:g}x{depth:g}",
        floors=1,
        footprint_polygon=[
            (0, 0),
            (width, 0),
            (width, depth),
            (0, depth),
        ],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"office": 1.0},
        building_code_context=BuildingCodeContext(
            jurisdiction="KR",
            effective_date="2026-07-28",
            qualifying_sprinkler_protection=False,
            travel_limit_classification="general_30",
            floor_facts=(
                FloorCodeContext(
                    floor_index=1,
                    above_grade=True,
                    occupancy_category=(
                        "assembly_religious_bar_funeral_200"
                    ),
                    story_number=1,
                    habitable_area_m2=width * depth,
                    is_evacuation_floor=False,
                ),
            ),
        ),
    )

    floor = run_building_generation(mass).floor_results[0]
    screening = floor.validation.regulatory_screening
    assert screening is not None
    travel = next(
        check
        for check in screening.checks
        if check.rule_id == "KR-EGRESS-TRAVEL-DISTANCE-ART34"
    )
    separation = next(
        check
        for check in screening.checks
        if check.rule_id == "KR-EGRESS-STAIR-SEPARATION-ART8"
    )

    assert floor.validation.accepted
    assert floor.validation.hard_violation_count == 0
    assert floor.area_ledger is not None
    assert floor.area_ledger.status == "pass"
    assert floor.validation.basic_design is not None
    assert floor.validation.basic_design.stair_count == 2
    assert separation.status == "pass"
    assert travel.status == travel_status
    if (width, depth) == (20.0, 20.0):
        assert screening.exit_separation_evidence is not None
        assert (
            screening.exit_separation_evidence
            .nearest_doorway_segment_distance_m
        ) == pytest.approx(math.hypot(width, depth) / 2.0)


def test_floor_area_classification_uses_actual_room_and_layout_sources() -> None:
    floor = run_building_generation(_mass(floors=1)).floor_results[0]
    assert floor.area_ledger is not None
    entries = {entry.bucket: entry for entry in floor.area_ledger.entries}
    room_types = {room.room_id: room.space_type for room in floor.layout.rooms}

    assert entries["core"].provenance.source_ids == tuple(
        sorted(room_id for room_id, kind in room_types.items() if kind == "core")
    )
    assert set(entries["circulation"].provenance.source_ids) == {
        path.room_id for path in floor.layout.circulation
    }
    assert entries["remote_stair"].provenance.source_ids == (
        "remote-stair-footprint",
    )
    assert set(entries["service"].provenance.source_ids) == {
        room_id
        for room_id, kind in room_types.items()
        if kind in {"pantry", "restroom", "it_storage", "stock", "utility"}
    }


def test_unknown_layout_room_is_unclassified_and_not_checked() -> None:
    floor = run_building_generation(_mass(floors=1)).floor_results[0]
    unknown = replace(
        floor.layout.rooms[0],
        room_id="unexpected-room",
        space_type="mystery",
    )
    layout = replace(
        floor.layout,
        rooms=[unknown, *floor.layout.rooms[1:]],
    )

    area, egress = build_floor_design_evidence(
        layout=layout,
        program=floor.program,
        boundary=_mass(floors=1).footprint_polygon,
    )

    assert area.status == "not_checked"
    assert all(entry.area_m2 is None for entry in area.entries)
    assert "unclassified_room:unexpected-room" in area.unresolved_facts
    assert egress.status == "not_checked"
    assert "unclassified_room:unexpected-room" in egress.unresolved_facts


def test_missing_program_room_is_stable_not_checked_evidence() -> None:
    floor = run_building_generation(_mass(floors=1)).floor_results[0]
    missing_id = floor.layout.rooms[0].room_id
    layout = replace(
        floor.layout,
        rooms=[
            room for room in floor.layout.rooms if room.room_id != missing_id
        ],
    )

    area, egress = build_floor_design_evidence(
        layout=layout,
        program=floor.program,
        boundary=_mass(floors=1).footprint_polygon,
    )

    reason = f"missing_program_room:{missing_id}"
    assert area.status == "not_checked"
    assert all(entry.area_m2 is None for entry in area.entries)
    assert reason in area.unresolved_facts
    assert egress.status == "not_checked"
    assert reason in egress.unresolved_facts


@pytest.mark.parametrize(
    ("distance_m", "expected_status"),
    [(30.0, "pass"), (30.001, "fail")],
)
def test_article_34_uses_checked_governing_route(
    distance_m: float,
    expected_status: str,
) -> None:
    screening = _travel_screening(distance_m)
    travel = next(
        check
        for check in screening.checks
        if check.rule_id == "KR-EGRESS-TRAVEL-DISTANCE-ART34"
    )

    assert travel.status == expected_status
    assert travel.measured_value == pytest.approx(distance_m)
    assert travel.threshold == 30.0
    assert "measured_travel_distance" not in screening.unresolved_facts


@pytest.mark.parametrize(
    ("connected", "expected"),
    [(True, True), (False, False)],
)
def test_article_8_connection_requires_circulation_graph_proof(
    connected: bool,
    expected: bool | None,
) -> None:
    mass = _mass(floors=1)
    floor = run_building_generation(mass).floor_results[0]
    context = replace(
        mass.building_code_context,
        floor_facts=(
            FloorCodeContext(
                floor_index=1,
                above_grade=True,
                occupancy_category="other_supported",
                story_number=3,
                habitable_area_m2=400.0,
                is_evacuation_floor=False,
            ),
        ),
    )

    validation = validate_layout(
        floor.layout,
        floor.program,
        boundary=mass.footprint_polygon,
        street_segments=[((0, 0), (30, 0))],
        require_openings=True,
        min_circulation_width=1.2,
        require_basic_design=True,
        building_code_context=context,
        egress_graph=_two_exit_graph(connected=connected),
    )

    screening = validation.regulatory_screening
    assert screening is not None
    assert screening.exit_separation_evidence is not None
    assert (
        screening.exit_separation_evidence.connected_passage_verified
        is expected
    )
    separation = next(
        check
        for check in screening.checks
        if check.rule_id == "KR-EGRESS-STAIR-SEPARATION-ART8"
    )
    if connected:
        assert "connected_exit_passage" not in screening.unresolved_facts
    else:
        assert separation.status == "fail"
        assert "connected_exit_passage" not in screening.unresolved_facts


def test_result_schema_rejects_tampered_floor_evidence() -> None:
    floor = run_building_generation(_mass(floors=1)).floor_results[0]
    assert floor.area_ledger is not None

    with pytest.raises(ValueError, match="floor indexes must match"):
        replace(
            floor,
            area_ledger=replace(floor.area_ledger, floor_index=2),
        )

    legacy = replace(floor, area_ledger=None, egress_graph=None)
    assert legacy.area_ledger is None
    assert legacy.egress_graph is None


def test_building_schema_rejects_tampered_floor_contracts() -> None:
    building = run_building_generation(_mass())
    assert building.area_ledger is not None

    with pytest.raises(ValueError, match="area ledger floor indexes"):
        replace(
            building,
            area_ledger=replace(
                building.area_ledger,
                floors=building.area_ledger.floors[:2],
            ),
        )
    with pytest.raises(ValueError, match="mass floor count"):
        replace(
            building,
            mass=replace(building.mass, floors=4),
        )
    with pytest.raises(ValueError, match="floor assignments"):
        replace(
            building,
            floor_assignments=building.floor_assignments[:2],
        )


def test_generation_schema_rejects_swapped_validation_screening() -> None:
    building = run_building_generation(_mass())

    with pytest.raises(ValueError, match="validation screening floor index"):
        replace(
            building.floor_results[0],
            validation=building.floor_results[1].validation,
        )


def test_building_schema_rejects_missing_floor_egress_evidence() -> None:
    building = run_building_generation(_mass())
    missing_egress = replace(
        building.floor_results[1],
        egress_graph=None,
    )

    with pytest.raises(ValueError, match="every floor requires area and egress"):
        replace(
            building,
            floor_results=(
                building.floor_results[0],
                missing_egress,
                building.floor_results[2],
            ),
        )


def test_building_schema_rejects_same_index_divergent_floor_ledger() -> None:
    building = run_building_generation(_mass())
    floor = building.floor_results[1]
    assert floor.area_ledger is not None
    divergent_floor = replace(
        floor,
        area_ledger=replace(
            floor.area_ledger,
            unresolved_facts=("tampered-floor-ledger",),
        ),
    )

    with pytest.raises(ValueError, match="exactly match floor result ledgers"):
        replace(
            building,
            floor_results=(
                building.floor_results[0],
                divergent_floor,
                building.floor_results[2],
            ),
        )


def test_zoning_loop_revalidates_candidate_with_same_egress_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    mass = _mass()
    floor = run_building_generation(mass).floor_results[1]
    stale_validation = validate_layout(
        floor.layout,
        floor.program,
        boundary=mass.footprint_polygon,
        street_segments=[((0, 0), (30, 0))],
        building_code_context=mass.building_code_context,
    )
    stale_travel = next(
        check
        for check in stale_validation.regulatory_screening.checks
        if check.rule_id == "KR-EGRESS-TRAVEL-DISTANCE-ART34"
    )
    assert stale_travel.status == "not_checked"
    candidate = CandidateRecord(
        iteration=1,
        layout=floor.layout,
        validation=stale_validation,
        fingerprint="stale-candidate",
        parent_id=None,
        operator="test",
    )
    search = LoopResult(
        mass=floor.mass,
        program=floor.program,
        best=candidate,
        iterations=[
            IterationRecord(
                iteration=1,
                candidates=[candidate],
                best=candidate,
                best_so_far=candidate,
            )
        ],
        history=[candidate],
        termination_reason="accepted",
        evaluation_count=1,
    )
    monkeypatch.setattr(
        visual_review_service,
        "run_candidate_search",
        lambda *args, **kwargs: search,
    )

    loop = run_visual_review_loop(
        mass,
        floor_index=2,
        use_type="office",
        output_dir=tmp_path,
        review_level="zoning",
    )

    payload = json.loads(
        loop.artifacts[0].report_path.read_text(encoding="utf-8")
    )
    travel = next(
        check
        for check in payload["regulatory_screening"]["checks"]
        if check["rule_id"] == "KR-EGRESS-TRAVEL-DISTANCE-ART34"
    )
    assert payload["egress_graph"]["status"] == "checked"
    assert travel["status"] == "pass"
    assert travel["measured_value"] == pytest.approx(
        payload["egress_graph"]["governing_distance_m"]
    )
    assert travel["measured_value"] == pytest.approx(26.85)
    assert loop.accepted is True
    assert loop.final_needs_iteration is False


def test_building_review_json_retains_floor_area_and_egress_evidence(
    tmp_path,
) -> None:
    mass = _mass(floors=1)
    building = run_building_generation(mass)
    artifacts = create_building_visual_review_artifacts(
        building,
        boundary=mass.footprint_polygon,
        output_dir=tmp_path,
    )

    payload = json.loads(artifacts.report_path.read_text(encoding="utf-8"))
    floor = payload["floors"][0]
    assert payload["area_ledger"]["floors"][0]["floor_index"] == 1
    assert floor["area_ledger"]["floor_index"] == 1
    assert floor["egress_graph"]["floor_index"] == 1
    assert "unresolved_facts" in floor["egress_graph"]


def test_explicit_regulatory_failure_forces_review_iteration(tmp_path) -> None:
    mass = _mass(floors=1)
    building = run_building_generation(mass)
    floor = building.floor_results[0]
    failed_egress = _checked_egress(30.001)
    failed_validation = validate_layout(
        floor.layout,
        floor.program,
        boundary=mass.footprint_polygon,
        street_segments=[((0, 0), (30, 0))],
        require_openings=True,
        min_door_width=0.8,
        min_circulation_width=1.2,
        require_basic_design=True,
        building_code_context=mass.building_code_context,
        egress_graph=failed_egress,
    )
    failed_floor = replace(
        floor,
        validation=failed_validation,
        egress_graph=failed_egress,
    )
    failed_building = replace(
        building,
        floor_results=(failed_floor,),
    )
    screening = failed_floor.validation.regulatory_screening
    assert screening is not None
    assert screening.status == "fail"

    floor_artifacts = create_visual_review_artifacts(
        failed_floor,
        boundary=mass.footprint_polygon,
        output_dir=tmp_path / "floor",
    )
    building_artifacts = create_building_visual_review_artifacts(
        failed_building,
        boundary=mass.footprint_polygon,
        output_dir=tmp_path / "building",
    )

    floor_payload = json.loads(
        floor_artifacts.report_path.read_text(encoding="utf-8")
    )
    floor_html = floor_artifacts.html_path.read_text(encoding="utf-8")
    building_payload = json.loads(
        building_artifacts.report_path.read_text(encoding="utf-8")
    )
    assert floor_payload["internal_validation"]["status"] == "pass"
    assert floor_payload["regulatory_screening"]["status"] == "fail"
    assert floor_payload["accepted"] is False
    assert floor_payload["needs_iteration"] is True
    assert "Area Ledger" in floor_html
    assert "Travel Distance" in floor_html
    assert "30.001" in floor_html
    assert "Unresolved Evidence" in floor_html
    assert building_payload["regulatory_screening"]["status"] == "fail"
    assert building_payload["render_validation"]["status"] == "pass"
    assert building_payload["accepted"] is False
    assert building_payload["floors"][0]["accepted"] is False
