from dataclasses import replace
import pytest
import math

import backend.app.modules.generation_loop.service as generation_service
from backend.app.modules.generation_loop.operators import layout_fingerprint
from backend.app.modules.generation_loop.selector import (
    canonical_building_topology_signature,
)
from backend.app.modules.generation_loop.service import run_building_alternatives
from backend.app.schemas.llm import FloorAssignment
from backend.app.schemas.mass import (
    BuildingCodeContext,
    FloorCodeContext,
    MassInput,
)
from backend.app.schemas.program import ProgramAdjustment, ProgramNode
from backend.app.schemas.result import PlannerProvenance
from backend.engine.geometry.polygon import (
    polygon_area,
    polygon_overlap_area,
    shared_boundary_with_segments_length,
    validate_boundary_segments,
)


def _adjustment_kwargs():
    original = ProgramNode(
        "sales",
        "sales",
        10.0,
        min_area=8.5,
        max_area=11.5,
        min_width=4.0,
        max_aspect_ratio=3.0,
    )
    adjusted = ProgramNode(
        "sales",
        "sales",
        9.0,
        min_area=7.65,
        max_area=10.35,
        min_width=3.0,
        max_aspect_ratio=6.5,
    )
    return {
        "reason": "fit",
        "original_nodes": (original,),
        "adjusted_nodes": (adjusted,),
        "original_targets": (("sales", 10.0),),
        "adjusted_targets": (("sales", 9.0),),
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            **_adjustment_kwargs(),
            "reason": "",
        },
        {
            **_adjustment_kwargs(),
            "original_targets": (("sales", float("nan")),),
        },
        {
            **_adjustment_kwargs(),
            "adjusted_targets": (("office", 9.0),),
        },
        {
            **_adjustment_kwargs(),
            "original_targets": (("sales", 10.0), ("sales", 9.0)),
        },
        {
            **_adjustment_kwargs(),
            "adjusted_nodes": _adjustment_kwargs()["original_nodes"],
            "adjusted_targets": (("sales", 10.0),),
        },
    ],
)
def test_program_adjustment_rejects_invalid_audit_evidence(kwargs):
    with pytest.raises(ValueError):
        ProgramAdjustment(**kwargs)


def test_program_adjustment_captures_all_changed_node_fields():
    adjustment = ProgramAdjustment(**_adjustment_kwargs())

    before = adjustment.original_nodes[0]
    after = adjustment.adjusted_nodes[0]
    assert before.target_area != after.target_area
    assert before.min_area != after.min_area
    assert before.max_area != after.max_area
    assert before.min_width != after.min_width
    assert before.max_aspect_ratio != after.max_aspect_ratio


def test_building_alternatives_preserve_explicit_assignments_and_provenance():
    mass = MassInput(
        project_id="alternatives-explicit-commercial",
        floors=1,
        footprint_polygon=[(0, 0), (30, 0), (30, 12), (0, 12)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[],
        use_mix={"office": 1.0},
    )
    assignments = (FloorAssignment(1, "neighborhood_commercial"),)
    provenance = PlannerProvenance(
        planner_mode="structured",
        provider="openai",
        model="gpt-test",
        response_id="resp-explicit",
        validated_assignments=assignments,
    )

    result = run_building_alternatives(
        mass,
        floor_assignments=assignments,
        planner_provenance=provenance,
    )

    assert result.alternatives
    for alternative in result.alternatives:
        assert alternative.building.floor_assignments == assignments
        assert alternative.building.planner_provenance == provenance
        assert {
            floor.program.use_type for floor in alternative.building.floor_results
        } == {"neighborhood_commercial"}


@pytest.mark.parametrize("width,depth", [(20, 12), (30, 12), (30, 20)])
def test_building_alternatives_are_distinct_ranked_and_mostly_accepted(width, depth):
    mass = MassInput(
        project_id=f"alternatives-{width}x{depth}",
        floors=3,
        footprint_polygon=[(0, 0), (width, 0), (width, depth), (0, depth)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"neighborhood_commercial": 1 / 3, "office": 2 / 3},
        building_code_context=BuildingCodeContext(
            jurisdiction="KR",
            effective_date="2026-07-28",
            sprinklered=True,
            qualifying_sprinkler_protection=True,
        ),
    )

    result = run_building_alternatives(mass)

    assert len(result.alternatives) == 2
    assert sum(alternative.accepted for alternative in result.alternatives) == 2
    assert [alternative.rank for alternative in result.alternatives] == [1, 2]
    assert [alternative.accepted for alternative in result.alternatives] == sorted(
        (alternative.accepted for alternative in result.alternatives),
        reverse=True,
    )
    for accepted in (True, False):
        scores = [
            alternative.score
            for alternative in result.alternatives
            if alternative.accepted is accepted
        ]
        assert scores == sorted(scores, reverse=True)
    assert (
        len(
            {
                tuple(
                    layout_fingerprint(floor.layout)
                    for floor in alternative.floor_results
                )
                for alternative in result.alternatives
            }
        )
        == 2
    )
    assert len({alternative.strategy for alternative in result.alternatives}) == 2
    assert len(result.comparisons) == 1
    assert all(comparison.semantic_distinct for comparison in result.comparisons)
    assert len({alternative.core_centroid for alternative in result.alternatives}) == 2
    assert all(
        alternative.circulation_graph_signature for alternative in result.alternatives
    )
    assert all(
        alternative.building.vertical_core_aligned
        and alternative.building.vertical_basic_design_aligned
        and alternative.building.vertical_structure_aligned
        for alternative in result.alternatives
    )


def test_legacy_unknown_sprinkler_uses_conservative_target_for_alternatives():
    mass = MassInput(
        project_id="legacy-unknown-sprinkler",
        floors=3,
        footprint_polygon=[(0, 0), (30, 0), (30, 12), (0, 12)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"neighborhood_commercial": 1 / 3, "office": 2 / 3},
    )

    result = run_building_alternatives(mass)

    assert result.accepted_count == 2
    for alternative in result.alternatives:
        for floor in alternative.floor_results:
            screening = floor.validation.regulatory_screening
            assert screening is not None
            assert screening.status == "not_checked"
            assert "floor_code_context" in screening.unresolved_facts
            assert floor.validation.basic_design is not None
            assert floor.validation.basic_design.policy_checks[
                "remote_exit_separation"
            ]["threshold"] == pytest.approx(math.hypot(30, 12) / 2)
    by_id = {
        alternative.alternative_id: alternative for alternative in result.alternatives
    }
    min_x, min_y, max_x, max_y = result.mass.bounds
    normalized = {
        alternative_id: (
            (alternative.core_centroid[0] - min_x) / (max_x - min_x),
            (alternative.core_centroid[1] - min_y) / (max_y - min_y),
        )
        for alternative_id, alternative in by_id.items()
    }
    assert normalized["alternative-a"][0] > 0.65
    assert normalized["alternative-a"][1] > 0.65
    assert normalized["alternative-c"][0] > 0.65
    assert 0.35 < normalized["alternative-c"][1] < 0.65
    assert all(
        "front" not in alternative.strategy for alternative in result.alternatives
    )
    assert all(
        alternative.tenant_count == 2
        and len(alternative.tenant_entrance_assignments) == 2
        and alternative.core_public_entrance
        for alternative in result.alternatives
    )
    for alternative in result.alternatives:
        footprints = {
            floor.layout.remote_stair_footprint for floor in alternative.floor_results
        }
        assert len(footprints) == 1
        assert None not in footprints
        assert all(floor.program.adjustments for floor in alternative.floor_results)
        commercial = next(
            floor
            for floor in alternative.floor_results
            if floor.program.use_type == "neighborhood_commercial"
        )
        features = commercial.layout.basic_design
        assert features is not None
        for room in (
            room for room in commercial.layout.rooms if room.space_type == "sales"
        ):
            actual = sum(
                element.kind == "sales_shelf" and element.host_id == room.room_id
                for element in features.elements
            )
            assert actual >= math.ceil(polygon_area(room.polygon) / 30.0)
        for floor in alternative.floor_results:
            for adjustment in floor.program.adjustments:
                assert adjustment.original_nodes != adjustment.adjusted_nodes
                assert {node.node_id for node in adjustment.original_nodes} == {
                    node.node_id for node in adjustment.adjusted_nodes
                }
    assert "shared_core_normalization" in {
        adjustment.reason
        for alternative in result.alternatives
        for floor in alternative.floor_results
        for adjustment in floor.program.adjustments
    }
    assert "side_mid_primary_fit" in {
        adjustment.reason
        for alternative in result.alternatives
        if alternative.alternative_id == "alternative-c"
        for floor in alternative.floor_results
        for adjustment in floor.program.adjustments
    }
    assert all(
        assignment.startswith("tenant_") or assignment in {"common-core-access:True"}
        for alternative in result.alternatives
        for assignment in alternative.tenant_assignment_signature
    )


def _explicit_one_stair_mass() -> MassInput:
    return MassInput(
        project_id="explicit-one-stair-family",
        floors=2,
        footprint_polygon=[(0, 0), (30, 0), (30, 12), (0, 12)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"office": 1.0},
        building_code_context=BuildingCodeContext(
            jurisdiction="KR",
            effective_date="2026-07-28",
            floor_facts=(
                FloorCodeContext(
                    floor_index=1,
                    above_grade=True,
                    story_number=1,
                    habitable_area_m2=100.0,
                    is_evacuation_floor=False,
                    occupancy_category="other_supported",
                ),
                FloorCodeContext(
                    floor_index=2,
                    above_grade=True,
                    story_number=2,
                    habitable_area_m2=100.0,
                    is_evacuation_floor=False,
                    occupancy_category="other_supported",
                ),
            ),
        ),
    )


def _explicit_mixed_one_stair_mass() -> MassInput:
    mass = _explicit_one_stair_mass()
    return replace(
        mass,
        floors=3,
        use_mix={
            "neighborhood_commercial": 1 / 3,
            "office": 2 / 3,
        },
        building_code_context=replace(
            mass.building_code_context,
            floor_facts=tuple(
                FloorCodeContext(
                    floor_index=index,
                    above_grade=True,
                    story_number=index,
                    habitable_area_m2=100.0,
                    is_evacuation_floor=False,
                    occupancy_category="other_supported",
                )
                for index in range(1, 4)
            ),
        ),
    )


def test_explicit_all_floor_one_stair_screen_emits_both_stair_families():
    result = run_building_alternatives(_explicit_one_stair_mass())

    families = {
        alternative.strategy.split("/", 1)[0] for alternative in result.alternatives
    }
    assert families == {
        "screened_minimum_one_stair",
        "conservative_redundant_two_stair",
    }
    for alternative in result.alternatives:
        expected_count = (
            1 if alternative.strategy.startswith("screened_minimum_one_stair/") else 2
        )
        assert all(
            sum(
                element.kind == "stair"
                for element in floor.layout.basic_design.elements
            )
            == expected_count
            for floor in alternative.floor_results
        )
        assert len({id(floor.layout) for floor in alternative.floor_results}) == 2
        assert len({id(floor.validation) for floor in alternative.floor_results}) == 2
        stair_ids_by_floor = {
            tuple(
                sorted(
                    element.element_id
                    for element in floor.layout.basic_design.elements
                    if element.kind == "stair"
                )
            )
            for floor in alternative.floor_results
        }
        assert len(stair_ids_by_floor) == 1
        assert {
            next(
                room.room_id for room in floor.layout.rooms if room.space_type == "core"
            )
            for floor in alternative.floor_results
        } == {"core"}
        assert all(
            floor.validation.regulatory_screening.screened_required_direct_stair_count
            == 1
            for floor in alternative.floor_results
        )
    accepted_one_stair = [
        alternative
        for alternative in result.alternatives
        if (
            alternative.strategy.startswith("screened_minimum_one_stair/")
            and alternative.accepted
        )
    ]
    assert accepted_one_stair
    assert not {
        violation.code
        for alternative in accepted_one_stair
        for floor in alternative.floor_results
        for violation in floor.validation.violations
    } & {
        "vertical_missing",
        "protected_exit_count",
        "egress_route_missing",
    }


def test_one_stair_family_reclaims_remote_stair_reserve_into_program_space():
    result = run_building_alternatives(_explicit_one_stair_mass())
    by_id = {
        alternative.alternative_id: alternative for alternative in result.alternatives
    }
    one_stair_alternatives = [
        alternative
        for alternative in result.alternatives
        if alternative.strategy.startswith("screened_minimum_one_stair/")
    ]

    assert result.accepted_count >= 2
    assert one_stair_alternatives
    for one_stair in one_stair_alternatives:
        conservative_id = one_stair.alternative_id.removeprefix("one-stair-")
        conservative = by_id[conservative_id]
        assert len(one_stair.floor_results) == len(conservative.floor_results)
        for one_floor, conservative_floor in zip(
            one_stair.floor_results,
            conservative.floor_results,
            strict=True,
        ):
            assert one_floor.layout.remote_stair_footprint is None
            assert all(
                not (element.kind == "stair" and element.host_id == "floor")
                for element in one_floor.layout.basic_design.elements
            )
            assert all(
                not (
                    line.kind == "protected_exit" and line.target_id == "remote-stair-2"
                )
                for line in one_floor.layout.basic_design.lines
            )
            assert one_floor.area_ledger is not None
            assert conservative_floor.area_ledger is not None
            assert one_floor.area_ledger.status == "pass"
            one_values = {
                entry.bucket: entry.area_m2 for entry in one_floor.area_ledger.entries
            }
            conservative_values = {
                entry.bucket: entry.area_m2
                for entry in conservative_floor.area_ledger.entries
            }
            assert one_values["remote_stair"] == pytest.approx(0.0)
            assert one_values["circulation"] == pytest.approx(
                conservative_values["circulation"]
            )
            assert one_values["net"] + 1e-7 >= (
                conservative_values["net"] + conservative_values["remote_stair"]
            )
            assert one_values["unassigned"] < conservative_values["unassigned"]
            assert one_floor.program.adjustments[-1].reason.startswith(
                "one_stair_remote_reserve_reclaimed:"
            )
            assert (
                one_floor.program.adjustments[-1].original_nodes
                != one_floor.program.adjustments[-1].adjusted_nodes
            )


def test_mixed_one_stair_reclaimed_rooms_have_truthful_exterior_windows():
    mass = _explicit_mixed_one_stair_mass()
    result = run_building_alternatives(mass)
    one_stair = next(
        alternative
        for alternative in result.alternatives
        if alternative.alternative_id == "one-stair-alternative-a"
    )

    assert result.accepted_count >= 2
    assert one_stair.accepted
    assert [floor.program.use_type for floor in one_stair.floor_results] == [
        "neighborhood_commercial",
        "office",
        "office",
    ]
    for floor in one_stair.floor_results:
        adjustment = floor.program.adjustments[-1]
        reclaimed_room_id = adjustment.reason.split(":", 1)[1]
        reclaimed_room = next(
            room for room in floor.layout.rooms if room.room_id == reclaimed_room_id
        )
        windows = [
            line
            for line in floor.layout.basic_design.lines
            if line.kind == "window" and line.host_id == reclaimed_room_id
        ]
        assert len(windows) == 1
        segment = (windows[0].points[0], windows[0].points[-1])
        validate_boundary_segments(
            mass.footprint_polygon,
            [segment],
            label="reclaimed room window",
        )
        assert shared_boundary_with_segments_length(
            reclaimed_room.polygon,
            [segment],
        ) == pytest.approx(math.dist(*segment))
        assert "window_missing" not in {
            violation.code for violation in floor.validation.violations
        }
        assert all(
            polygon_overlap_area(reclaimed_room.polygon, obstacle) == 0.0
            for obstacle in (
                *(
                    room.polygon
                    for room in floor.layout.rooms
                    if room.room_id != reclaimed_room_id
                ),
                *(path.polygon for path in floor.layout.circulation),
            )
        )


def test_unknown_floor_applicability_only_emits_conservative_family():
    mass = MassInput(
        project_id="unknown-stair-family",
        floors=2,
        footprint_polygon=[(0, 0), (30, 0), (30, 12), (0, 12)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[],
        use_mix={"office": 1.0},
    )

    result = run_building_alternatives(mass)

    assert result.alternatives
    assert all(
        alternative.strategy.startswith("conservative_redundant_two_stair/")
        for alternative in result.alternatives
    )
    signatures = [
        alternative.design_family_signature for alternative in result.alternatives
    ]
    assert len(signatures) == len(set(signatures))
    assert all(
        floor.validation.regulatory_screening.status == "not_checked"
        for alternative in result.alternatives
        for floor in alternative.floor_results
    )


def test_any_floor_requiring_two_stairs_suppresses_one_stair_family():
    mass = _explicit_one_stair_mass()
    first, second = mass.building_code_context.floor_facts
    mass = MassInput(
        project_id="mixed-stair-family",
        floors=mass.floors,
        footprint_polygon=mass.footprint_polygon,
        site_edges=mass.site_edges,
        access_candidates=mass.access_candidates,
        use_mix=mass.use_mix,
        building_code_context=BuildingCodeContext(
            jurisdiction="KR",
            effective_date="2026-07-28",
            floor_facts=(
                first,
                FloorCodeContext(
                    floor_index=second.floor_index,
                    above_grade=True,
                    story_number=5,
                    habitable_area_m2=500.0,
                    is_evacuation_floor=False,
                    occupancy_category="other_supported",
                ),
            ),
        ),
    )

    result = run_building_alternatives(mass)

    assert result.alternatives
    assert all(
        alternative.strategy.startswith("conservative_redundant_two_stair/")
        for alternative in result.alternatives
    )
    assert {
        floor.validation.regulatory_screening.screened_required_direct_stair_count
        for floor in result.alternatives[0].floor_results
    } == {1, 2}


@pytest.mark.parametrize(
    ("polygon", "reason"),
    [
        (
            [(0, 0), (18, 0), (18, 12), (0, 12)],
            "width >= 20.0",
        ),
        (
            [(0, 0), (30, 0), (30, 12), (20, 12), (20, 8), (0, 8)],
            "concept workstation arrangement",
        ),
    ],
)
def test_infeasible_mass_reports_conservative_family_rejection(
    polygon,
    reason,
):
    mass = MassInput(
        project_id="infeasible-family",
        floors=2,
        footprint_polygon=polygon,
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[],
        use_mix={"office": 1.0},
    )

    result = run_building_alternatives(mass)

    assert result.alternatives == ()
    assert len(result.rejected_families) == 1
    rejected = result.rejected_families[0]
    assert rejected.family == "conservative_redundant_two_stair"
    assert any(reason in item for item in rejected.reasons)


def test_conservative_family_does_not_swallow_unrelated_strategy_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mass = MassInput(
        project_id="unrelated-family-error",
        floors=1,
        footprint_polygon=[(0, 0), (30, 0), (30, 12), (0, 12)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[],
        use_mix={"office": 1.0},
    )

    def fail_unrelated(*args, **kwargs):
        raise ValueError("unrelated strategy failure")

    monkeypatch.setattr(
        generation_service,
        "_generate_side_mid_building",
        fail_unrelated,
    )

    with pytest.raises(ValueError, match="unrelated strategy failure"):
        run_building_alternatives(mass)


def test_topology_signature_ignores_connects_order_and_tracks_circulation_edges():
    mass = MassInput(
        project_id="topology-canonical",
        floors=1,
        footprint_polygon=[(0, 0), (30, 0), (30, 12), (0, 12)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[],
        use_mix={"office": 1.0},
    )
    result = run_building_alternatives(mass)
    alternative = next(
        item for item in result.alternatives if item.alternative_id == "alternative-c"
    )
    floor = alternative.floor_results[0]
    reversed_connects = replace(
        floor,
        layout=replace(
            floor.layout,
            openings=[
                replace(opening, connects=tuple(reversed(opening.connects)))
                for opening in floor.layout.openings
            ],
        ),
    )
    assert canonical_building_topology_signature((floor,)) == (
        canonical_building_topology_signature((reversed_connects,))
    )

    assert len(floor.layout.circulation) == 2
    first, second = floor.layout.circulation
    disconnected = replace(
        floor,
        layout=replace(
            floor.layout,
            circulation=[
                first,
                replace(
                    second,
                    polygon=[(x + 100.0, y) for x, y in second.polygon],
                ),
            ],
        ),
    )
    assert canonical_building_topology_signature((floor,)) != (
        canonical_building_topology_signature((disconnected,))
    )
