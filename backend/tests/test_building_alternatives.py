import pytest
import math

from backend.app.modules.generation_loop.operators import layout_fingerprint
from backend.app.modules.generation_loop.service import run_building_alternatives
from backend.app.schemas.mass import BuildingCodeContext, MassInput
from backend.app.schemas.program import ProgramAdjustment, ProgramNode
from engine.geometry.polygon import polygon_area


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

    assert len(result.alternatives) == 3
    assert sum(alternative.accepted for alternative in result.alternatives) >= 2
    assert [alternative.rank for alternative in result.alternatives] == [1, 2, 3]
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
    assert len(
        {
            tuple(layout_fingerprint(floor.layout) for floor in alternative.floor_results)
            for alternative in result.alternatives
        }
    ) == 3
    assert len({alternative.strategy for alternative in result.alternatives}) == 3
    assert len(result.comparisons) == 3
    assert all(comparison.semantic_distinct for comparison in result.comparisons)
    assert len({alternative.core_centroid for alternative in result.alternatives}) == 3
    assert all(alternative.circulation_graph_signature for alternative in result.alternatives)
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

    assert result.accepted_count < 2
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
        alternative.alternative_id: alternative
        for alternative in result.alternatives
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
    assert 0.35 < normalized["alternative-b"][0] < 0.65
    assert normalized["alternative-b"][1] > 0.65
    assert normalized["alternative-c"][0] > 0.65
    assert 0.35 < normalized["alternative-c"][1] < 0.65
    assert all("front" not in alternative.strategy for alternative in result.alternatives)
    assert all(
        alternative.tenant_count == 2
        and len(alternative.tenant_entrance_assignments) == 2
        and alternative.core_public_entrance
        for alternative in result.alternatives
    )
    for alternative in result.alternatives:
        footprints = {
            floor.layout.remote_stair_footprint
            for floor in alternative.floor_results
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
            room
            for room in commercial.layout.rooms
            if room.space_type == "sales"
        ):
            actual = sum(
                element.kind == "sales_shelf"
                and element.host_id == room.room_id
                for element in features.elements
            )
            assert actual >= math.ceil(polygon_area(room.polygon) / 30.0)
        for floor in alternative.floor_results:
            for adjustment in floor.program.adjustments:
                assert adjustment.original_nodes != adjustment.adjusted_nodes
                assert {
                    node.node_id for node in adjustment.original_nodes
                } == {
                    node.node_id for node in adjustment.adjusted_nodes
                }
    assert "shared_core_normalization" in {
        adjustment.reason
        for alternative in result.alternatives
        for floor in alternative.floor_results
        for adjustment in floor.program.adjustments
    }
    assert all(
        assignment.startswith("tenant_")
        or assignment in {"common-core-access:True"}
        for alternative in result.alternatives
        for assignment in alternative.tenant_assignment_signature
    )
